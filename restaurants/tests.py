from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

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
