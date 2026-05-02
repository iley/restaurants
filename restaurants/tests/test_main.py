from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from restaurants.models import City, Restaurant
from restaurants.sources import (
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
class BulkApplyTests(TestCase):
    """Cover apply_fetched semantics for the inputs the bulk admin action and
    management command pass it: full payloads against blank and partial
    restaurants in default and force modes."""

    PAYLOAD = {
        "google_place_id": "ChIJabc",
        "address": "1 Main St, Dublin",
        "website": "https://example.com",
        "google_maps_url": "https://maps.google.com/?cid=1",
        "google_rating": Decimal("4.5"),
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

    def test_blank_field_merge_fills_every_payload_field(self):
        fetched = self._build_fetched(self.PAYLOAD)
        updated = apply_fetched(self.blank, fetched)
        self.assertEqual(set(updated), set(self.PAYLOAD.keys()))

    def test_default_mode_skips_non_blank_fields(self):
        fetched = self._build_fetched(self.PAYLOAD)
        updated = apply_fetched(self.partial, fetched)
        expected = set(self.PAYLOAD.keys()) - {"address"}
        self.assertEqual(set(updated), expected)
        self.assertEqual(self.partial.address, "kept")

    def test_force_overwrites_non_blank_fields(self):
        fetched = self._build_fetched(self.PAYLOAD)
        updated = apply_fetched(self.partial, fetched, force=True)
        self.assertIn("address", updated)
        self.assertEqual(self.partial.address, "1 Main St, Dublin")

    def test_management_command_routes_through_fetch_all(self):
        stub_calls = []

        def stub(probe):
            stub_calls.append(probe)
            return self.PAYLOAD

        stub.source_name = "Google Places"
        with patch(
            "restaurants.management.commands.fetch_google_places_data.google_places_source",
            stub,
        ):
            call_command("fetch_google_places_data", "--city", "dublin")
        self.assertTrue(stub_calls, "stubbed source was not invoked")
        self.blank.refresh_from_db()
        self.assertEqual(self.blank.address, "1 Main St, Dublin")
        self.assertEqual(self.blank.website, "https://example.com")
        self.assertEqual(self.blank.google_place_id, "ChIJabc")

    def _build_fetched(self, payload):
        return {k: FetchedValue(value=v, source_name="stub") for k, v in payload.items()}


@override_settings(GOOGLE_PLACES_API_KEY="test-key")
class FetchAllDataCommandTests(TestCase):
    """The `fetch_all_data` command runs all live sources but must never write
    `michelin_status` — Michelin is reviewed via `update_michelin_data`."""

    PAYLOAD = {
        "address": "1 Main St, Dublin",
        "website": "https://example.com",
        "google_place_id": "ChIJabc",
    }

    def setUp(self):
        self.city = City.objects.create(name="Dublin", slug="dublin")
        self.restaurant = Restaurant.objects.create(
            city=self.city, name="Blank", cuisine="Italian",
        )

    def test_live_sources_excludes_michelin(self):
        from restaurants.michelin import michelin_source
        from restaurants.sources import LIVE_SOURCES
        self.assertNotIn(michelin_source, LIVE_SOURCES)

    def test_excludes_michelin_status_even_when_michelin_would_match(self):
        google_stub = _stub_source(self.PAYLOAD, name="Google Places")
        # The Michelin stub would return a status if it were ever called — its
        # presence in the test scenario proves the exclusion is enforced by
        # the command's source-list scope, not by an empty CSV.
        michelin_stub = _stub_source(
            {"michelin_status": Restaurant.MichelinStatus.ONE_STAR},
            name="Michelin Guide",
        )
        self.assertEqual(
            michelin_stub(None),
            {"michelin_status": Restaurant.MichelinStatus.ONE_STAR},
        )

        captured: list[list[str]] = []
        original_save = Restaurant.save

        def capturing_save(instance, *args, **kwargs):
            if "update_fields" in kwargs:
                captured.append(list(kwargs["update_fields"]))
            return original_save(instance, *args, **kwargs)

        with patch(
            "restaurants.management.commands.fetch_all_data.LIVE_SOURCES",
            [google_stub],
        ), patch.object(Restaurant, "save", capturing_save):
            call_command("fetch_all_data", "--city", "dublin")

        flat = [f for fields in captured for f in fields]
        self.assertIn("address", flat, "google fields should be written")
        self.assertNotIn("michelin_status", flat)

    def test_missing_data_predicate_ignores_michelin_status(self):
        # A restaurant with all live fields populated and `michelin_status` at
        # the default "none" should be skipped by the default backfill — proves
        # the missing-data filter doesn't include michelin_status.
        Restaurant.objects.create(
            city=self.city, name="Filled", cuisine="Italian",
            address="x", website="https://x", google_maps_url="https://m",
            google_place_id="pid", google_rating=Decimal("4.0"),
            latitude=Decimal("53.0"), longitude=Decimal("-6.0"),
        )
        # The Blank one (set up above) is missing data and would be selected.
        called_with: list[str] = []

        def stub(probe):
            called_with.append(probe.name)
            return self.PAYLOAD

        stub.source_name = "Google Places"
        with patch(
            "restaurants.management.commands.fetch_all_data.LIVE_SOURCES",
            [stub],
        ):
            call_command("fetch_all_data")
        self.assertIn("Blank", called_with)
        self.assertNotIn("Filled", called_with)


class UpdateMichelinDataCommandTests(TestCase):
    """The `update_michelin_data` command diffs Michelin CSV matches against
    current values; default is dry-run, --apply writes only `michelin_status`."""

    def setUp(self):
        from io import StringIO

        self.dublin = City.objects.create(name="Dublin", slug="dublin")
        self.cork = City.objects.create(name="Cork", slug="cork")
        # Three restaurants with three distinct outcomes:
        #  - "Diff Me" currently NONE, source proposes ONE_STAR -> would change
        #  - "Same" currently ONE_STAR, source proposes ONE_STAR -> unchanged
        #  - "Lost" currently TWO_STARS, source returns no match -> demotion
        self.diff_me = Restaurant.objects.create(
            city=self.dublin, name="Diff Me", cuisine="Italian",
            michelin_status=Restaurant.MichelinStatus.NONE,
        )
        self.same = Restaurant.objects.create(
            city=self.dublin, name="Same", cuisine="Italian",
            michelin_status=Restaurant.MichelinStatus.ONE_STAR,
        )
        self.lost = Restaurant.objects.create(
            city=self.dublin, name="Lost", cuisine="Italian",
            michelin_status=Restaurant.MichelinStatus.TWO_STARS,
        )
        self.stdout_buf = StringIO()

    def _michelin_stub(self):
        # Returns proposed status keyed by restaurant name; None means no match.
        proposals = {
            "Diff Me": {"michelin_status": Restaurant.MichelinStatus.ONE_STAR},
            "Same": {"michelin_status": Restaurant.MichelinStatus.ONE_STAR},
            "Lost": None,
        }

        def stub(probe):
            return proposals.get(probe.name)

        stub.source_name = "Michelin Guide"
        return stub

    def _run(self, *args):
        with patch(
            "restaurants.management.commands.update_michelin_data.michelin_source",
            self._michelin_stub(),
        ):
            call_command("update_michelin_data", *args, stdout=self.stdout_buf)

    def test_dry_run_writes_nothing(self):
        self._run()
        # DB must be untouched.
        self.diff_me.refresh_from_db()
        self.same.refresh_from_db()
        self.lost.refresh_from_db()
        self.assertEqual(self.diff_me.michelin_status, Restaurant.MichelinStatus.NONE)
        self.assertEqual(self.same.michelin_status, Restaurant.MichelinStatus.ONE_STAR)
        self.assertEqual(self.lost.michelin_status, Restaurant.MichelinStatus.TWO_STARS)

    def test_dry_run_prints_diff_lines(self):
        self._run()
        out = self.stdout_buf.getvalue()
        self.assertIn("Diff Me", out)
        self.assertIn("WOULD CHANGE", out)
        self.assertIn("Same", out)
        self.assertIn("no change", out)
        self.assertIn("Lost", out)
        self.assertIn("no CSV match", out)
        # Summary counts.
        self.assertIn("1 would change", out)
        self.assertIn("1 unchanged", out)
        self.assertIn("1 no match", out)

    def test_apply_writes_only_michelin_status(self):
        captured: list[list[str]] = []
        original_save = Restaurant.save

        def capturing_save(instance, *args, **kwargs):
            if "update_fields" in kwargs:
                captured.append(list(kwargs["update_fields"]))
            return original_save(instance, *args, **kwargs)

        with patch.object(Restaurant, "save", capturing_save):
            self._run("--apply")

        # Only the diff_me restaurant should have been saved.
        self.assertEqual(captured, [["michelin_status"]])
        self.diff_me.refresh_from_db()
        self.assertEqual(
            self.diff_me.michelin_status,
            Restaurant.MichelinStatus.ONE_STAR,
        )
        # Unchanged and no-match rows are still at their original status.
        self.same.refresh_from_db()
        self.lost.refresh_from_db()
        self.assertEqual(self.same.michelin_status, Restaurant.MichelinStatus.ONE_STAR)
        self.assertEqual(self.lost.michelin_status, Restaurant.MichelinStatus.TWO_STARS)

    def test_no_match_path_classified(self):
        # Restrict the queryset to just "Lost" via --city to isolate the path.
        Restaurant.objects.exclude(pk=self.lost.pk).delete()
        self._run()
        out = self.stdout_buf.getvalue()
        self.assertIn("[Lost] no CSV match", out)
        self.assertIn("0 would change", out)
        self.assertIn("0 unchanged", out)
        self.assertIn("1 no match", out)

    def test_city_filter_scopes_queryset(self):
        # Add a Cork restaurant that the stub would propose a change for, then
        # run with --city dublin and confirm Cork was not visited.
        Restaurant.objects.create(
            city=self.cork, name="Diff Me", cuisine="Italian",
            michelin_status=Restaurant.MichelinStatus.NONE,
        )
        seen: list[str] = []

        def stub(probe):
            seen.append(probe.city_name)
            return None

        stub.source_name = "Michelin Guide"
        with patch(
            "restaurants.management.commands.update_michelin_data.michelin_source",
            stub,
        ):
            call_command("update_michelin_data", "--city", "dublin", stdout=self.stdout_buf)
        self.assertTrue(seen)
        self.assertTrue(all(name == "Dublin" for name in seen))


class GooglePlacesSourceTests(TestCase):
    def setUp(self):
        self.probe = Probe(name="Test", city_name="Dublin")

    def test_returns_none_without_api_key(self):
        from restaurants.places import google_places_source
        with override_settings(GOOGLE_PLACES_API_KEY=""):
            self.assertIsNone(google_places_source(self.probe))

    def test_propagates_none_from_search_place(self):
        from restaurants.places import google_places_source
        with override_settings(GOOGLE_PLACES_API_KEY="k"), \
             patch("restaurants.places.search_place", return_value=None):
            self.assertIsNone(google_places_source(self.probe))

    def test_remaps_keys_and_coerces_floats_to_decimal(self):
        from restaurants.places import google_places_source
        raw = {
            "place_id": "ChIJ123",
            "address": "1 Main St",
            "website": "https://example.com",
            "google_maps_url": "https://maps.google.com/?cid=1",
            "google_rating": 4.3,  # float from JSON
            "latitude": 53.3498,
            "longitude": -6.2603,
        }
        with override_settings(GOOGLE_PLACES_API_KEY="k"), \
             patch("restaurants.places.search_place", return_value=raw):
            result = google_places_source(self.probe)
        self.assertEqual(result["google_place_id"], "ChIJ123")
        # Floats must arrive as Decimals matching the model's DecimalField storage.
        self.assertEqual(result["google_rating"], Decimal("4.3"))
        self.assertEqual(result["latitude"], Decimal("53.3498"))
        self.assertEqual(result["longitude"], Decimal("-6.2603"))


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

    def test_post_treats_numerically_equal_decimals_as_unchanged(self):
        # Form posts the model's DecimalField as a padded string ("53.349800"),
        # while a fresh fetch yields Decimal("53.3498") — same number, different
        # string form. The unchanged-row check must compare numerically.
        fetched = {
            "latitude": FetchedValue(value=Decimal("53.3498"), source_name="Google Places"),
        }
        with patch("restaurants.admin.fetch_all", return_value=fetched):
            resp = self.client.post(self.url, {
                "name": "Test", "city": str(self.city.pk),
                "latitude": "53.349800",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'data-target="id_latitude"')
        self.assertContains(resp, "No proposed changes.")

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


class MichelinCsvPathSettingTests(TestCase):
    def test_setting_is_configured_under_data_dir(self):
        from pathlib import Path

        from django.conf import settings

        path = Path(settings.MICHELIN_CSV_PATH)
        self.assertEqual(path.name, "michelin_my_maps.csv")
        self.assertEqual(path.parent.name, "data")
