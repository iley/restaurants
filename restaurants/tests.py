from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import City, Restaurant
from .sources import (
    FETCHABLE_FIELDS,
    FetchedValue,
    Probe,
    apply_fetched,
    fetch_all,
)


def _stub_source(payload, name="stub"):
    """Build a Source callable that returns a fixed payload, ignoring the probe."""
    def _src(probe):
        return payload
    _src.__name__ = name
    _src.source_name = name
    return _src


class FetchAllTests(TestCase):
    def setUp(self):
        self.probe = Probe(name="Test", city_name="Dublin")

    def test_single_source_returns_merged_dict(self):
        src = _stub_source({
            "address": "1 Main St",
            "website": "https://example.com",
            "google_rating": 4.5,
        }, name="stub")
        result = fetch_all(self.probe, sources=[src])
        self.assertEqual(set(result.keys()), {"address", "website", "google_rating"})
        self.assertEqual(result["address"].value, "1 Main St")
        self.assertEqual(result["address"].source_name, "stub")
        self.assertEqual(result["google_rating"].value, 4.5)

    def test_first_non_empty_wins_across_sources(self):
        first = _stub_source({"address": "", "website": "https://first.example"}, name="first")
        second = _stub_source({"address": "1 Main St", "website": "https://second.example"}, name="second")
        result = fetch_all(self.probe, sources=[first, second])
        # first won for website, second won for address (first's address was empty).
        self.assertEqual(result["website"].source_name, "first")
        self.assertEqual(result["website"].value, "https://first.example")
        self.assertEqual(result["address"].source_name, "second")
        self.assertEqual(result["address"].value, "1 Main St")

    def test_handles_source_returning_none(self):
        none_src = _stub_source(None, name="empty")
        good = _stub_source({"address": "1 Main St"}, name="good")
        result = fetch_all(self.probe, sources=[none_src, good])
        self.assertEqual(result["address"].value, "1 Main St")
        self.assertEqual(result["address"].source_name, "good")

    def test_skips_empty_string_and_none_values(self):
        src = _stub_source({
            "address": "",
            "website": None,
            "google_place_id": "abc",
        }, name="stub")
        result = fetch_all(self.probe, sources=[src])
        self.assertEqual(set(result.keys()), {"google_place_id"})

    def test_unknown_keys_ignored(self):
        src = _stub_source({"address": "1 Main St", "extra": "ignored"}, name="stub")
        result = fetch_all(self.probe, sources=[src])
        self.assertNotIn("extra", result)
        self.assertEqual(set(result.keys()) - set(FETCHABLE_FIELDS), set())


class ApplyFetchedTests(TestCase):
    def setUp(self):
        self.city = City.objects.create(name="Dublin", slug="dublin")
        self.restaurant = Restaurant.objects.create(
            city=self.city, name="Test", cuisine="Italian",
        )

    def _fetched(self, **values):
        return {k: FetchedValue(value=v, source_name="stub") for k, v in values.items()}

    def test_default_fills_blank_fields_only(self):
        self.restaurant.address = "existing"
        self.restaurant.save()
        fetched = self._fetched(address="new", website="https://example.com")
        updated = apply_fetched(self.restaurant, fetched)
        self.assertEqual(updated, ["website"])
        self.assertEqual(self.restaurant.address, "existing")
        self.assertEqual(self.restaurant.website, "https://example.com")

    def test_force_overwrites_when_value_differs(self):
        self.restaurant.address = "existing"
        self.restaurant.save()
        fetched = self._fetched(address="new")
        updated = apply_fetched(self.restaurant, fetched, force=True)
        self.assertEqual(updated, ["address"])
        self.assertEqual(self.restaurant.address, "new")

    def test_force_no_change_when_value_equal(self):
        self.restaurant.address = "same"
        self.restaurant.save()
        fetched = self._fetched(address="same")
        updated = apply_fetched(self.restaurant, fetched, force=True)
        self.assertEqual(updated, [])


@override_settings(GOOGLE_PLACES_API_KEY="test-key")
class BulkActionUpdateFieldsParityTests(TestCase):
    """Confirm the bulk admin action and management command produce the same
    update_fields set as the legacy code path for representative inputs.
    """

    PAYLOAD = {
        "google_place_id": "ChIJabc",
        "address": "1 Main St, Dublin",
        "website": "https://example.com",
        "google_maps_url": "https://maps.google.com/?cid=1",
        "google_rating": 4.5,
        "latitude": Decimal("53.3498"),
        "longitude": Decimal("-6.2603"),
    }

    def setUp(self):
        self.city = City.objects.create(name="Dublin", slug="dublin")
        self.blank = Restaurant.objects.create(city=self.city, name="Blank", cuisine="Italian")
        self.partial = Restaurant.objects.create(
            city=self.city, name="Partial", cuisine="Italian",
            address="kept", website="",
        )

    def test_apply_fetched_matches_legacy_blank_field_merge(self):
        # On a wholly-blank restaurant, blank-field merge fills every fetchable field.
        fetched = self._build_fetched(self.PAYLOAD)
        updated = apply_fetched(self.blank, fetched)
        self.assertEqual(set(updated), set(FETCHABLE_FIELDS))

    def test_apply_fetched_skips_non_blank_fields_by_default(self):
        # On a partially-populated restaurant, address is preserved; the rest fills in.
        fetched = self._build_fetched(self.PAYLOAD)
        updated = apply_fetched(self.partial, fetched)
        expected = set(FETCHABLE_FIELDS) - {"address"}
        self.assertEqual(set(updated), expected)
        self.assertEqual(self.partial.address, "kept")

    def test_apply_fetched_force_overwrites_address(self):
        fetched = self._build_fetched(self.PAYLOAD)
        updated = apply_fetched(self.partial, fetched, force=True)
        self.assertIn("address", updated)
        self.assertEqual(self.partial.address, "1 Main St, Dublin")

    def test_management_command_routes_through_fetch_all(self):
        """Smoke test: command runs end-to-end with a stubbed source and saves the expected fields."""
        stub = _stub_source(self.PAYLOAD, name="Google Places")
        with patch("restaurants.sources.SOURCES", [stub]):
            call_command("fetch_places_data", "--city", "dublin")
        self.blank.refresh_from_db()
        self.assertEqual(self.blank.address, "1 Main St, Dublin")
        self.assertEqual(self.blank.website, "https://example.com")
        self.assertEqual(self.blank.google_place_id, "ChIJabc")

    def _build_fetched(self, payload):
        return {k: FetchedValue(value=v, source_name="stub") for k, v in payload.items()}


class FetchAttributesViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True,
        )
        cls.url = reverse("admin:restaurants_restaurant_fetch_attributes")

    def setUp(self):
        self.client.force_login(self.staff)

    def test_anonymous_user_redirected(self):
        anon = Client()
        resp = anon.post(self.url, {"name": "X", "city": self.city.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_get_returns_405(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)

    def test_post_with_results_renders_rows(self):
        fetched = {
            "address": FetchedValue(value="1 Main St", source_name="Google Places"),
            "website": FetchedValue(value="https://example.com", source_name="Google Places"),
        }
        with patch("restaurants.admin.fetch_all", return_value=fetched):
            resp = self.client.post(self.url, {
                "name": "Test", "city": str(self.city.pk), "location": "",
                "address": "", "website": "",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "1 Main St")
        self.assertContains(resp, "https://example.com")
        self.assertContains(resp, "Google Places")
        self.assertContains(resp, 'data-target="id_address"')
        self.assertContains(resp, "fetch-apply-all")

    def test_post_hides_rows_where_current_equals_proposed(self):
        fetched = {
            "address": FetchedValue(value="1 Main St", source_name="Google Places"),
            "website": FetchedValue(value="https://example.com", source_name="Google Places"),
        }
        with patch("restaurants.admin.fetch_all", return_value=fetched):
            resp = self.client.post(self.url, {
                "name": "Test", "city": str(self.city.pk),
                "address": "1 Main St",  # equals proposed -> hidden
                "website": "",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'data-target="id_address"')
        self.assertContains(resp, 'data-target="id_website"')

    def test_post_no_proposals_renders_empty_message(self):
        with patch("restaurants.admin.fetch_all", return_value={}):
            resp = self.client.post(self.url, {
                "name": "Test", "city": str(self.city.pk),
            })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No proposed changes.")
        self.assertNotContains(resp, "fetch-apply-all")

    def test_post_with_blank_inputs_shows_friendly_message(self):
        # No name -> we never call fetch_all; we ask the user to fill the form.
        with patch("restaurants.admin.fetch_all") as mock_fetch:
            resp = self.client.post(self.url, {"name": "", "city": str(self.city.pk)})
            mock_fetch.assert_not_called()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enter a name")

    def test_csrf_protection_enforced(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        resp = csrf_client.post(self.url, {"name": "X", "city": str(self.city.pk)})
        self.assertEqual(resp.status_code, 403)


class ChangeFormFetchButtonTests(TestCase):
    """Smoke test: the admin add page renders with the Fetch attributes button
    and includes HTMX so the button can fire."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_superuser(
            username="admin", password="pw", email="a@b.c",
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_add_page_renders_with_fetch_button(self):
        resp = self.client.get(reverse("admin:restaurants_restaurant_add"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Fetch attributes")
        self.assertContains(resp, 'id="fetch-results"')
        self.assertContains(resp, "htmx.min.js")

    def test_change_page_renders_with_fetch_button(self):
        city = City.objects.create(name="Dublin", slug="dublin")
        restaurant = Restaurant.objects.create(city=city, name="Test", cuisine="Italian")
        url = reverse("admin:restaurants_restaurant_change", args=[restaurant.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Fetch attributes")
        self.assertContains(resp, 'id="fetch-results"')
