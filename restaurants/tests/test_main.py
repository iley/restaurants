import io
import os
import shutil
import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from restaurants.models import City, Photo, Restaurant, Visit
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

    @classmethod
    def setUpTestData(cls):
        from pathlib import Path

        # Pin to the test fixture so the CSV-presence guard in the command
        # passes; the source itself is stubbed in `_run`, so the file is
        # only read by the guard.
        cls.fixture_csv = Path(__file__).parent / "fixtures" / "michelin_test.csv"

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
        with override_settings(MICHELIN_CSV_PATH=self.fixture_csv), patch(
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
        # Only changed rows are printed; unchanged and no-match rows are quiet.
        self.assertIn("Diff Me", out)
        self.assertNotIn("Same", out)
        self.assertNotIn("Lost", out)
        # Summary counts still cover all three rows.
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
        # Restrict the queryset to just "Lost" to isolate the no-match path.
        Restaurant.objects.exclude(pk=self.lost.pk).delete()
        self._run()
        out = self.stdout_buf.getvalue()
        self.assertNotIn("Lost", out)
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
        with override_settings(MICHELIN_CSV_PATH=self.fixture_csv), patch(
            "restaurants.management.commands.update_michelin_data.michelin_source",
            stub,
        ):
            call_command("update_michelin_data", "--city", "dublin", stdout=self.stdout_buf)
        self.assertTrue(seen)
        self.assertTrue(all(name == "Dublin" for name in seen))

    def test_aborts_when_csv_missing(self):
        from django.core.management.base import CommandError

        missing = self.fixture_csv.parent / "does_not_exist.csv"
        with override_settings(MICHELIN_CSV_PATH=missing):
            with self.assertRaises(CommandError) as cm:
                call_command("update_michelin_data", stdout=self.stdout_buf)
        self.assertIn(str(missing), str(cm.exception))

    def test_aborts_when_csv_empty(self):
        import tempfile
        from django.core.management.base import CommandError

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as fh:
            empty_path = fh.name
        try:
            with override_settings(MICHELIN_CSV_PATH=empty_path):
                with self.assertRaises(CommandError) as cm:
                    call_command("update_michelin_data", stdout=self.stdout_buf)
            self.assertIn(empty_path, str(cm.exception))
        finally:
            import os
            os.unlink(empty_path)

    def test_aborts_when_csv_path_is_directory(self):
        # A directory at the configured path used to slip past the missing/empty
        # check (exists() True, st_size non-zero) and crash later in _load_city.
        import tempfile
        from django.core.management.base import CommandError

        with tempfile.TemporaryDirectory() as dir_path:
            with override_settings(MICHELIN_CSV_PATH=dir_path):
                with self.assertRaises(CommandError) as cm:
                    call_command("update_michelin_data", stdout=self.stdout_buf)
            self.assertIn(dir_path, str(cm.exception))

    def test_aborts_when_csv_missing_required_columns(self):
        # A non-empty file with the wrong schema would otherwise yield zero
        # matches and look like a mass demotion.
        import os
        import tempfile
        from django.core.management.base import CommandError

        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        ) as fh:
            fh.write("Foo,Bar,Baz\n1,2,3\n")
            bad_path = fh.name
        try:
            with override_settings(MICHELIN_CSV_PATH=bad_path):
                with self.assertRaises(CommandError) as cm:
                    call_command("update_michelin_data", stdout=self.stdout_buf)
            self.assertIn("missing required columns", str(cm.exception))
        finally:
            os.unlink(bad_path)

    def test_aborts_when_csv_header_only(self):
        # Header-present but no data rows: same failure mode as empty.
        import os
        import tempfile
        from django.core.management.base import CommandError

        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        ) as fh:
            fh.write("Name,Location,Award\n")
            header_only_path = fh.name
        try:
            with override_settings(MICHELIN_CSV_PATH=header_only_path):
                with self.assertRaises(CommandError) as cm:
                    call_command("update_michelin_data", stdout=self.stdout_buf)
            self.assertIn("no data rows", str(cm.exception))
        finally:
            os.unlink(header_only_path)

    def test_aborts_when_csv_has_only_blank_rows(self):
        # csv.reader yields [] for blank lines and ['', '', ''] for rows of
        # only commas — neither is a real data row, so both must be rejected.
        import os
        import tempfile
        from django.core.management.base import CommandError

        for body in ("Name,Location,Award\n\n", "Name,Location,Award\n,,\n"):
            with tempfile.NamedTemporaryFile(
                suffix=".csv", delete=False, mode="w", encoding="utf-8"
            ) as fh:
                fh.write(body)
                blank_path = fh.name
            try:
                with override_settings(MICHELIN_CSV_PATH=blank_path):
                    with self.assertRaises(CommandError) as cm:
                        call_command("update_michelin_data", stdout=self.stdout_buf)
                self.assertIn("no data rows", str(cm.exception))
            finally:
                os.unlink(blank_path)


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


class CheckDuplicateViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.other_city = City.objects.create(name="Cork", slug="cork")
        cls.existing = Restaurant.objects.create(
            city=cls.city, name="Chapter One", cuisine="Modern Irish",
            location="North City",
        )
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True,
        )
        cls.url = reverse("admin:restaurants_restaurant_check_duplicate")

    def setUp(self):
        self.client.force_login(self.staff)

    def test_anonymous_user_redirected(self):
        anon = Client()
        resp = anon.post(self.url, {"name": "X", "city": str(self.city.pk)})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_get_returns_405(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)

    def test_blank_inputs_render_empty(self):
        resp = self.client.post(self.url, {"name": "", "city": str(self.city.pk)})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "duplicate-warning")

    def test_exact_match_renders_warning(self):
        resp = self.client.post(self.url, {
            "name": "Chapter One", "city": str(self.city.pk),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Chapter One")
        self.assertContains(resp, "duplicate-warning")

    def test_match_is_case_insensitive(self):
        resp = self.client.post(self.url, {
            "name": "chapter ONE", "city": str(self.city.pk),
        })
        self.assertContains(resp, "duplicate-warning")

    def test_different_city_does_not_match(self):
        resp = self.client.post(self.url, {
            "name": "Chapter One", "city": str(self.other_city.pk),
        })
        self.assertNotContains(resp, "duplicate-warning")

    def test_excludes_self_when_pk_provided(self):
        # On the change page we pass the current pk; the row itself must not
        # be flagged as its own duplicate.
        resp = self.client.post(self.url, {
            "name": "Chapter One",
            "city": str(self.city.pk),
            "pk": str(self.existing.pk),
        })
        self.assertNotContains(resp, "duplicate-warning")

    def test_no_match_renders_empty(self):
        resp = self.client.post(self.url, {
            "name": "Brand New Place", "city": str(self.city.pk),
        })
        self.assertNotContains(resp, "duplicate-warning")

    def test_malformed_city_returns_empty_not_500(self):
        # A city value of "x" used to crash with ValueError when passed
        # straight into the queryset; guard with int() parse instead.
        resp = self.client.post(self.url, {"name": "Chapter One", "city": "x"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "duplicate-warning")

    def test_malformed_pk_falls_back_to_no_exclude(self):
        resp = self.client.post(self.url, {
            "name": "Chapter One",
            "city": str(self.city.pk),
            "pk": "not-an-int",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "duplicate-warning")


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
        self.assertContains(resp, 'id="duplicate-warning"')
        self.assertContains(resp, "/check-duplicate/")
        self.assertContains(resp, "htmx.min.js")

    def test_change_page_renders_with_fetch_button(self):
        city = City.objects.create(name="Dublin", slug="dublin")
        restaurant = Restaurant.objects.create(city=city, name="Test", cuisine="Italian")
        url = reverse("admin:restaurants_restaurant_change", args=[restaurant.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Fetch attributes")
        self.assertContains(resp, 'id="fetch-results"')


class MichelinFetchAttributesPanelTests(TestCase):
    """End-to-end smoke test: the admin change form's per-field fetch panel
    surfaces a Michelin status row when the restaurant matches the CSV.

    Pins MICHELIN_CSV_PATH to the test fixture and disables Google Places so
    the fetched dict is Michelin-only — proves the registered `michelin_source`
    flows all the way through `fetch_all` into the rendered admin panel.
    """

    @classmethod
    def setUpTestData(cls):
        from pathlib import Path

        cls.fixture_csv = Path(__file__).parent / "fixtures" / "michelin_test.csv"
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.restaurant = Restaurant.objects.create(
            city=cls.city, name="Patrick Guilbaud", cuisine="French",
        )
        User = get_user_model()
        cls.staff = User.objects.create_superuser(
            username="admin", password="pw", email="a@b.c",
        )

    def setUp(self):
        from restaurants import michelin
        michelin._CITY_CACHE.clear()
        self.client.force_login(self.staff)

    @override_settings(GOOGLE_PLACES_API_KEY="")
    def test_change_form_then_fetch_panel_shows_michelin_row(self):
        with override_settings(MICHELIN_CSV_PATH=self.fixture_csv):
            change_url = reverse(
                "admin:restaurants_restaurant_change", args=[self.restaurant.pk],
            )
            change_resp = self.client.get(change_url)
            self.assertEqual(change_resp.status_code, 200)

            fetch_url = reverse("admin:restaurants_restaurant_fetch_attributes")
            fetch_resp = self.client.post(fetch_url, {
                "name": self.restaurant.name,
                "city": str(self.city.pk),
                "michelin_status": self.restaurant.michelin_status,
            })

        self.assertEqual(fetch_resp.status_code, 200)
        # A Michelin row must be rendered: the fixture entry "Patrick Guilbaud"
        # in Dublin maps to "2 Stars" -> MichelinStatus.TWO_STARS ("two_stars").
        self.assertContains(fetch_resp, 'data-target="id_michelin_status"')
        # data-value carries the raw slug (the form select expects it).
        self.assertContains(fetch_resp, 'data-value="two_stars"')
        self.assertContains(fetch_resp, "Michelin Status")
        self.assertContains(fetch_resp, "Michelin Guide")
        # The visible cell shows the human label, not the slug.
        self.assertContains(fetch_resp, "<td class=\"fetch-proposed\">2 Stars</td>")


class MichelinCsvPathSettingTests(TestCase):
    def test_setting_is_configured_under_data_dir(self):
        from pathlib import Path

        from django.conf import settings

        path = Path(settings.MICHELIN_CSV_PATH)
        self.assertEqual(path.name, "michelin_my_maps.csv")
        self.assertEqual(path.parent.name, "data")

    def test_setting_honors_env_var(self):
        import importlib
        import os
        from pathlib import Path

        from config import settings as settings_module

        with patch.dict(os.environ, {"MICHELIN_CSV_PATH": "/custom/michelin.csv"}):
            reloaded = importlib.reload(settings_module)
            try:
                self.assertEqual(reloaded.MICHELIN_CSV_PATH, Path("/custom/michelin.csv"))
            finally:
                importlib.reload(settings_module)


class _AdminActionTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin_user = User.objects.create_superuser(
            username="admin", password="pw", email="a@b.c",
        )
        cls.city = City.objects.create(name="Dublin", slug="dublin")

    def setUp(self):
        from django.contrib import admin as django_admin
        self.model_admin = django_admin.site._registry[Restaurant]

    def _request(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        rf = RequestFactory()
        req = rf.post("/admin/restaurants/restaurant/")
        req.user = self.admin_user
        req.session = self.client.session
        setattr(req, "_messages", FallbackStorage(req))
        return req


class MichelinAdminActionTests(_AdminActionTestBase):
    """Admin actions for Michelin status updates, pinned to [michelin_source]."""

    def test_force_action_overwrites_default_none_status(self):
        # The default `michelin_status="none"` is non-empty, so only the force
        # variant actually writes — that's the documented intent.
        r = Restaurant.objects.create(city=self.city, name="X", cuisine="French")
        fetched = {
            "michelin_status": FetchedValue(
                value=Restaurant.MichelinStatus.ONE_STAR,
                source_name="Michelin Guide",
            ),
        }
        with patch("restaurants.admin.fetch_all", return_value=fetched) as mock_fetch:
            self.model_admin.force_update_michelin_status(
                self._request(), Restaurant.objects.all(),
            )
        from restaurants.michelin import michelin_source
        _, kwargs = mock_fetch.call_args
        self.assertEqual(kwargs["sources"], [michelin_source])
        r.refresh_from_db()
        self.assertEqual(r.michelin_status, Restaurant.MichelinStatus.ONE_STAR)

    def test_non_force_action_skips_when_current_is_default_none(self):
        r = Restaurant.objects.create(city=self.city, name="X", cuisine="French")
        fetched = {
            "michelin_status": FetchedValue(
                value=Restaurant.MichelinStatus.ONE_STAR,
                source_name="Michelin Guide",
            ),
        }
        with patch("restaurants.admin.fetch_all", return_value=fetched):
            self.model_admin.update_michelin_status(
                self._request(), Restaurant.objects.all(),
            )
        r.refresh_from_db()
        self.assertEqual(r.michelin_status, Restaurant.MichelinStatus.NONE)

    def test_force_action_writes_only_michelin_status_field(self):
        Restaurant.objects.create(city=self.city, name="X", cuisine="French")
        fetched = {
            "michelin_status": FetchedValue(
                value=Restaurant.MichelinStatus.BIB_GOURMAND,
                source_name="Michelin Guide",
            ),
        }
        captured: list[list[str]] = []
        original_save = Restaurant.save

        def capturing_save(instance, *args, **kwargs):
            if "update_fields" in kwargs:
                captured.append(list(kwargs["update_fields"]))
            return original_save(instance, *args, **kwargs)

        with patch("restaurants.admin.fetch_all", return_value=fetched), \
             patch.object(Restaurant, "save", capturing_save):
            self.model_admin.force_update_michelin_status(
                self._request(), Restaurant.objects.all(),
            )
        self.assertEqual(captured, [["michelin_status"]])

    def test_action_does_not_call_google_places_source(self):
        r = Restaurant.objects.create(city=self.city, name="X", cuisine="French")
        # If michelin_source is the only source passed, fetch_all must not invoke
        # google_places_source — verify by patching the registry stand-ins.
        google_calls: list[str] = []
        michelin_calls: list[str] = []

        def google_stub(probe):
            google_calls.append(probe.name)
            return {"address": "1 Main St"}

        google_stub.source_name = "Google Places"

        def michelin_stub(probe):
            michelin_calls.append(probe.name)
            return {"michelin_status": Restaurant.MichelinStatus.ONE_STAR}

        michelin_stub.source_name = "Michelin Guide"

        with patch("restaurants.admin.google_places_source", google_stub), \
             patch("restaurants.admin.michelin_source", michelin_stub):
            self.model_admin.force_update_michelin_status(
                self._request(), Restaurant.objects.all(),
            )
        self.assertEqual(michelin_calls, [r.name])
        self.assertEqual(google_calls, [])
        r.refresh_from_db()
        self.assertEqual(r.michelin_status, Restaurant.MichelinStatus.ONE_STAR)

    def test_actions_registered_on_changelist(self):
        # The action dropdown only renders when the changelist has rows.
        Restaurant.objects.create(city=self.city, name="X", cuisine="French")
        self.client.force_login(self.admin_user)
        url = reverse("admin:restaurants_restaurant_changelist")
        resp = self.client.get(url)
        self.assertContains(resp, "update_michelin_status")
        self.assertContains(resp, "force_update_michelin_status")


@override_settings(GOOGLE_PLACES_API_KEY="test-key")
class PlacesAdminActionScopingTests(_AdminActionTestBase):
    """The places admin actions must pin to [google_places_source] so that
    `fetch_all`'s default `SOURCES` list (which now includes Michelin) does
    not silently drag Michelin lookups into the Places-labelled actions."""

    def test_fetch_places_data_pins_to_google_places_source(self):
        Restaurant.objects.create(city=self.city, name="X", cuisine="French")
        with patch("restaurants.admin.fetch_all", return_value={}) as mock_fetch:
            self.model_admin.fetch_places_data(
                self._request(), Restaurant.objects.all(),
            )
        from restaurants.places import google_places_source
        _, kwargs = mock_fetch.call_args
        self.assertEqual(kwargs["sources"], [google_places_source])

    def test_force_fetch_places_data_pins_to_google_places_source(self):
        Restaurant.objects.create(city=self.city, name="X", cuisine="French")
        with patch("restaurants.admin.fetch_all", return_value={}) as mock_fetch:
            self.model_admin.force_fetch_places_data(
                self._request(), Restaurant.objects.all(),
            )
        from restaurants.places import google_places_source
        _, kwargs = mock_fetch.call_args
        self.assertEqual(kwargs["sources"], [google_places_source])

    def test_fetch_places_data_never_writes_michelin_status(self):
        # Even if Michelin would have matched, it isn't in the source list,
        # so michelin_status must never appear in update_fields.
        r = Restaurant.objects.create(city=self.city, name="X", cuisine="French")
        google_payload = {"address": "1 Main St"}
        michelin_payload = {"michelin_status": Restaurant.MichelinStatus.ONE_STAR}

        def google_stub(probe):
            return google_payload

        google_stub.source_name = "Google Places"

        def michelin_stub(probe):
            return michelin_payload

        michelin_stub.source_name = "Michelin Guide"

        captured: list[list[str]] = []
        original_save = Restaurant.save

        def capturing_save(instance, *args, **kwargs):
            if "update_fields" in kwargs:
                captured.append(list(kwargs["update_fields"]))
            return original_save(instance, *args, **kwargs)

        with patch("restaurants.admin.google_places_source", google_stub), \
             patch("restaurants.admin.michelin_source", michelin_stub), \
             patch.object(Restaurant, "save", capturing_save):
            self.model_admin.fetch_places_data(
                self._request(), Restaurant.objects.all(),
            )
        flat = [f for fields in captured for f in fields]
        self.assertIn("address", flat)
        self.assertNotIn("michelin_status", flat)
        r.refresh_from_db()
        self.assertEqual(r.michelin_status, Restaurant.MichelinStatus.NONE)


class PlacesAdminActionMissingApiKeyTests(_AdminActionTestBase):
    @override_settings(GOOGLE_PLACES_API_KEY="")
    def test_fetch_places_data_short_circuits_without_api_key(self):
        Restaurant.objects.create(city=self.city, name="X", cuisine="French")
        with patch("restaurants.admin.fetch_all") as mock_fetch:
            self.model_admin.fetch_places_data(
                self._request(), Restaurant.objects.all(),
            )
        mock_fetch.assert_not_called()


class PinnedFieldTests(TestCase):
    def setUp(self):
        self.city = City.objects.create(name="Dublin", slug="dublin")

    def test_pinned_defaults_to_false(self):
        r = Restaurant.objects.create(city=self.city, name="X", cuisine="Italian")
        self.assertFalse(r.pinned)


class PinnedSortOrderTests(TestCase):
    """Pinned restaurants must precede non-pinned ones regardless of the chosen
    sort column, and ties within each group must respect that sort."""

    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        # Names chosen so alphabetical sort would interleave pinned/unpinned
        # if pinning weren't taking precedence.
        cls.alpha = Restaurant.objects.create(
            city=cls.city, name="Alpha", cuisine="Italian", rating=8, pinned=False,
        )
        cls.bravo = Restaurant.objects.create(
            city=cls.city, name="Bravo", cuisine="Italian", rating=10, pinned=True,
        )
        cls.charlie = Restaurant.objects.create(
            city=cls.city, name="Charlie", cuisine="Italian", rating=6, pinned=False,
        )
        cls.delta = Restaurant.objects.create(
            city=cls.city, name="Delta", cuisine="Italian", rating=7, pinned=True,
        )
        cls.url = reverse("restaurant_list", kwargs={"city_slug": cls.city.slug})

    def _names(self, sort):
        resp = self.client.get(self.url, {"sort": sort})
        self.assertEqual(resp.status_code, 200)
        return [r.name for r in resp.context["restaurants"]]

    def test_pinned_precede_unpinned_when_sorting_by_name_asc(self):
        # Within each group, ties broken alphabetically.
        self.assertEqual(self._names("name"), ["Bravo", "Delta", "Alpha", "Charlie"])

    def test_pinned_precede_unpinned_when_sorting_by_rating_desc(self):
        # Within each group, the higher-rated row comes first.
        # Pinned: Bravo (10) > Delta (7). Unpinned: Alpha (8) > Charlie (6).
        self.assertEqual(self._names("-rating"), ["Bravo", "Delta", "Alpha", "Charlie"])


class PinnedMarkerRenderTests(TestCase):
    """The 📌 marker should render next to pinned restaurant names only."""

    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.pinned = Restaurant.objects.create(
            city=cls.city, name="PinnedPlace", cuisine="Italian", rating=8, pinned=True,
        )
        cls.unpinned = Restaurant.objects.create(
            city=cls.city, name="UnpinnedPlace", cuisine="Italian", rating=7, pinned=False,
        )
        cls.url = reverse("restaurant_list", kwargs={"city_slug": cls.city.slug})

    def test_pin_marker_renders_for_pinned_row(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        # Anchor the marker to the row link so unrelated occurrences elsewhere
        # on the page can't satisfy or break the assertion.
        self.assertContains(resp, ">PinnedPlace</a> 📌")
        self.assertNotContains(resp, ">UnpinnedPlace</a> 📌")


class RestaurantEditPageTests(TestCase):
    """Auth gate + GET on the staff-only edit page."""

    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.restaurant = Restaurant.objects.create(
            city=cls.city, name="Chapter One", cuisine="Modern Irish",
        )
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True,
        )
        cls.regular = User.objects.create_user(
            username="reg", password="pw", is_staff=False,
        )
        cls.edit_url = reverse(
            "restaurant_edit",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )
        cls.detail_url = reverse(
            "restaurant_detail",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )

    def test_anonymous_get_redirects_to_admin_login(self):
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertIn(self.edit_url, resp["Location"])

    def test_non_staff_get_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_staff_get_returns_200_with_restaurant_name(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Chapter One")

    def test_edit_link_shows_on_detail_page_for_staff(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'href="{self.edit_url}"')

    def test_edit_link_hidden_on_detail_page_for_anon(self):
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, f'href="{self.edit_url}"')

    def test_edit_link_hidden_on_detail_page_for_non_staff(self):
        self.client.force_login(self.regular)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, f'href="{self.edit_url}"')


class RestaurantTogglePinnedTests(TestCase):
    """HTMX toggle for Restaurant.pinned on the edit page."""

    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.restaurant = Restaurant.objects.create(
            city=cls.city, name="Chapter One", cuisine="Modern Irish",
        )
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True,
        )
        cls.regular = User.objects.create_user(
            username="reg", password="pw", is_staff=False,
        )
        cls.toggle_url = reverse(
            "restaurant_toggle_pinned",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )
        cls.edit_url = reverse(
            "restaurant_edit",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )

    def setUp(self):
        # Reset pinned state between tests so order doesn't matter.
        self.restaurant.pinned = False
        self.restaurant.save(update_fields=["pinned"])

    def test_anonymous_post_redirects_to_login(self):
        resp = self.client.post(self.toggle_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.restaurant.refresh_from_db()
        self.assertFalse(self.restaurant.pinned)

    def test_non_staff_post_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.post(self.toggle_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.restaurant.refresh_from_db()
        self.assertFalse(self.restaurant.pinned)

    def test_staff_post_pins_an_unpinned_restaurant(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.toggle_url)
        self.assertEqual(resp.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertTrue(self.restaurant.pinned)
        self.assertContains(resp, "Pinned")

    def test_staff_post_unpins_a_pinned_restaurant(self):
        self.restaurant.pinned = True
        self.restaurant.save(update_fields=["pinned"])
        self.client.force_login(self.staff)
        resp = self.client.post(self.toggle_url)
        self.assertEqual(resp.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertFalse(self.restaurant.pinned)
        # Response shows the un-pinned state — neither "Pinned" nor the star.
        self.assertNotContains(resp, "Pinned")
        self.assertNotContains(resp, "★")

    def test_get_returns_405(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.toggle_url)
        self.assertEqual(resp.status_code, 405)

    def test_toggle_partial_rendered_on_edit_page(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="pinned-toggle"')
        self.assertContains(resp, f'hx-post="{self.toggle_url}"')


class HtmxCsrfWiringTests(TestCase):
    """Bare hx-post buttons (pin, delete) live outside any <form>, so they
    rely on a global htmx:configRequest handler in base.html that copies the
    csrftoken cookie into the X-CSRFToken header. Lock that contract in."""

    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.restaurant = Restaurant.objects.create(city=cls.city, name="R")
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True,
        )

    def test_pin_toggle_post_without_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        # Seed the csrftoken cookie via GET of the edit page.
        edit_url = reverse(
            "restaurant_edit",
            kwargs={"city_slug": self.city.slug, "pk": self.restaurant.pk},
        )
        self.assertEqual(client.get(edit_url).status_code, 200)
        toggle_url = reverse(
            "restaurant_toggle_pinned",
            kwargs={"city_slug": self.city.slug, "pk": self.restaurant.pk},
        )
        # No X-CSRFToken header (which is what would happen if base.html's
        # htmx:configRequest handler were removed) — Django rejects the POST.
        self.assertEqual(client.post(toggle_url).status_code, 403)

    def test_pin_toggle_post_with_csrf_header_succeeds(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        edit_url = reverse(
            "restaurant_edit",
            kwargs={"city_slug": self.city.slug, "pk": self.restaurant.pk},
        )
        client.get(edit_url)
        token = client.cookies["csrftoken"].value
        toggle_url = reverse(
            "restaurant_toggle_pinned",
            kwargs={"city_slug": self.city.slug, "pk": self.restaurant.pk},
        )
        resp = client.post(toggle_url, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(resp.status_code, 200)

    def test_base_template_wires_csrf_header_for_htmx(self):
        client = Client()
        client.force_login(self.staff)
        edit_url = reverse(
            "restaurant_edit",
            kwargs={"city_slug": self.city.slug, "pk": self.restaurant.pk},
        )
        resp = client.get(edit_url)
        self.assertEqual(resp.status_code, 200)
        # The handler reads the csrftoken cookie and sets the X-CSRFToken
        # header on every htmx request; without it, the pin/delete buttons
        # (which sit outside any <form>) would 403 in production.
        self.assertContains(resp, "htmx:configRequest")
        self.assertContains(resp, "X-CSRFToken")


class RestaurantEditRatingTests(TestCase):
    """HTMX inline edit for Restaurant.rating on the edit page."""

    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.restaurant = Restaurant.objects.create(
            city=cls.city, name="Chapter One", cuisine="Modern Irish", rating=8,
        )
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True,
        )
        cls.regular = User.objects.create_user(
            username="reg", password="pw", is_staff=False,
        )
        cls.rating_url = reverse(
            "restaurant_edit_rating",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )
        cls.edit_url = reverse(
            "restaurant_edit",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )

    def setUp(self):
        # Reset rating each test so order doesn't matter.
        self.restaurant.rating = 8
        self.restaurant.save(update_fields=["rating"])

    def test_anonymous_get_redirects_to_login(self):
        resp = self.client.get(self.rating_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_anonymous_post_redirects_to_login(self):
        resp = self.client.post(self.rating_url, {"rating": "9"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.rating, 8)

    def test_non_staff_get_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.get(self.rating_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_non_staff_post_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.post(self.rating_url, {"rating": "9"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.rating, 8)

    def test_staff_get_renders_form_with_current_rating(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.rating_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="rating"')
        # Current rating shows in the value attribute.
        self.assertContains(resp, 'value="8"')

    def test_staff_post_valid_rating_updates_db(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.rating_url, {"rating": "10"})
        self.assertEqual(resp.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.rating, 10)
        self.assertContains(resp, 'value="10"')
        self.assertContains(resp, "Saved")

    def test_staff_post_rating_zero_renders_error_db_unchanged(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.rating_url, {"rating": "0"})
        self.assertEqual(resp.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.rating, 8)
        self.assertContains(resp, "is-danger")

    def test_staff_post_rating_eleven_renders_error_db_unchanged(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.rating_url, {"rating": "11"})
        self.assertEqual(resp.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.rating, 8)
        self.assertContains(resp, "is-danger")

    def test_staff_post_empty_rating_clears_to_wishlist(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.rating_url, {"rating": ""})
        self.assertEqual(resp.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertIsNone(self.restaurant.rating)
        self.assertTrue(self.restaurant.is_wishlist)

    def test_rating_form_rendered_on_edit_page(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="rating-form"')
        self.assertContains(resp, f'hx-post="{self.rating_url}"')
        # Pre-filled with the current rating.
        self.assertContains(resp, 'value="8"')


class RestaurantEditCommentsTests(TestCase):
    """HTMX inline edit for Restaurant.comments on the edit page."""

    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.restaurant = Restaurant.objects.create(
            city=cls.city, name="Chapter One", cuisine="Modern Irish",
            comments="Original comment.",
        )
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True,
        )
        cls.regular = User.objects.create_user(
            username="reg", password="pw", is_staff=False,
        )
        cls.comments_url = reverse(
            "restaurant_edit_comments",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )
        cls.edit_url = reverse(
            "restaurant_edit",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )

    def setUp(self):
        # Reset comments each test so order doesn't matter.
        self.restaurant.comments = "Original comment."
        self.restaurant.save(update_fields=["comments"])

    def test_anonymous_get_redirects_to_login(self):
        resp = self.client.get(self.comments_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_anonymous_post_redirects_to_login(self):
        resp = self.client.post(self.comments_url, {"comments": "tampered"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.comments, "Original comment.")

    def test_non_staff_get_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.get(self.comments_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_non_staff_post_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.post(self.comments_url, {"comments": "tampered"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.comments, "Original comment.")

    def test_staff_get_renders_form_with_current_comments(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.comments_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="comments"')
        self.assertContains(resp, "Original comment.")

    def test_staff_post_valid_comments_updates_db(self):
        self.client.force_login(self.staff)
        new_text = "New **bold** comment with a [link](https://example.com)."
        resp = self.client.post(self.comments_url, {"comments": new_text})
        self.assertEqual(resp.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.comments, new_text)
        self.assertContains(resp, "New **bold** comment")
        self.assertContains(resp, "Saved")

    def test_staff_post_empty_comments_allowed(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.comments_url, {"comments": ""})
        self.assertEqual(resp.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.comments, "")

    def test_staff_post_very_long_comments_saved(self):
        self.client.force_login(self.staff)
        long_text = "x" * 10000
        resp = self.client.post(self.comments_url, {"comments": long_text})
        self.assertEqual(resp.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.comments, long_text)
        self.assertEqual(len(self.restaurant.comments), 10000)

    def test_comments_form_rendered_on_edit_page(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="comments-form"')
        self.assertContains(resp, f'hx-post="{self.comments_url}"')
        self.assertContains(resp, "Original comment.")


class RestaurantEditVisitsTests(TestCase):
    """HTMX list + add/edit/delete for Restaurant.visits on the edit page."""

    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.other_city = City.objects.create(name="Cork", slug="cork")
        cls.restaurant = Restaurant.objects.create(
            city=cls.city, name="Chapter One", cuisine="Modern Irish",
        )
        cls.other_restaurant = Restaurant.objects.create(
            city=cls.city, name="Other", cuisine="Italian",
        )
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True,
        )
        cls.regular = User.objects.create_user(
            username="reg", password="pw", is_staff=False,
        )
        cls.section_url = reverse(
            "restaurant_visits_section",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )
        cls.add_url = reverse(
            "visit_create",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )
        cls.edit_url = reverse(
            "restaurant_edit",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )

    def _edit_url(self, visit_pk, restaurant_pk=None):
        return reverse(
            "visit_edit",
            kwargs={
                "city_slug": self.city.slug,
                "pk": restaurant_pk or self.restaurant.pk,
                "visit_pk": visit_pk,
            },
        )

    def _delete_url(self, visit_pk, restaurant_pk=None):
        return reverse(
            "visit_delete",
            kwargs={
                "city_slug": self.city.slug,
                "pk": restaurant_pk or self.restaurant.pk,
                "visit_pk": visit_pk,
            },
        )

    # --- auth gate: section GET ---

    def test_anon_get_section_redirects_to_login(self):
        resp = self.client.get(self.section_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_non_staff_get_section_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.get(self.section_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    # --- auth gate: create ---

    def test_anon_post_create_redirects_to_login(self):
        resp = self.client.post(self.add_url, {"date": "2026-01-01", "notes": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertEqual(self.restaurant.visits.count(), 0)

    def test_non_staff_post_create_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.post(self.add_url, {"date": "2026-01-01", "notes": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertEqual(self.restaurant.visits.count(), 0)

    # --- auth gate: edit ---

    def test_anon_get_edit_redirects_to_login(self):
        visit = Visit.objects.create(restaurant=self.restaurant, date="2026-01-01")
        resp = self.client.get(self._edit_url(visit.pk))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_non_staff_post_edit_redirects_to_login(self):
        visit = Visit.objects.create(restaurant=self.restaurant, date="2026-01-01")
        self.client.force_login(self.regular)
        resp = self.client.post(self._edit_url(visit.pk), {
            "date": "2026-02-02", "notes": "tampered",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        visit.refresh_from_db()
        self.assertEqual(str(visit.date), "2026-01-01")

    # --- auth gate: delete ---

    def test_anon_post_delete_redirects_to_login(self):
        visit = Visit.objects.create(restaurant=self.restaurant, date="2026-01-01")
        resp = self.client.post(self._delete_url(visit.pk))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertTrue(Visit.objects.filter(pk=visit.pk).exists())

    def test_non_staff_post_delete_redirects_to_login(self):
        visit = Visit.objects.create(restaurant=self.restaurant, date="2026-01-01")
        self.client.force_login(self.regular)
        resp = self.client.post(self._delete_url(visit.pk))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertTrue(Visit.objects.filter(pk=visit.pk).exists())

    # --- happy paths ---

    def test_staff_get_section_renders_visits(self):
        Visit.objects.create(restaurant=self.restaurant, date="2026-03-15", notes="Great")
        self.client.force_login(self.staff)
        resp = self.client.get(self.section_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "2026-03-15")
        self.assertContains(resp, "Great")
        # The "Add visit" form must be present too.
        self.assertContains(resp, 'id="visit-add-form"')

    def test_staff_post_create_adds_visit(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.add_url, {
            "date": "2026-04-10", "notes": "Dinner with K.",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.restaurant.visits.count(), 1)
        visit = self.restaurant.visits.get()
        self.assertEqual(str(visit.date), "2026-04-10")
        self.assertEqual(visit.notes, "Dinner with K.")
        # Section partial should show the new row.
        self.assertContains(resp, "2026-04-10")
        self.assertContains(resp, "Dinner with K.")

    def test_staff_post_create_invalid_date_renders_error(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.add_url, {"date": "not-a-date", "notes": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.restaurant.visits.count(), 0)
        self.assertContains(resp, "is-danger")

    def test_staff_post_create_missing_date_renders_error(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.add_url, {"date": "", "notes": "no date"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.restaurant.visits.count(), 0)
        self.assertContains(resp, "is-danger")

    def test_staff_get_edit_renders_form(self):
        visit = Visit.objects.create(
            restaurant=self.restaurant, date="2026-01-01", notes="Original",
        )
        self.client.force_login(self.staff)
        resp = self.client.get(self._edit_url(visit.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="date"')
        self.assertContains(resp, 'value="2026-01-01"')
        self.assertContains(resp, "Original")

    def test_staff_post_edit_updates_visit(self):
        visit = Visit.objects.create(
            restaurant=self.restaurant, date="2026-01-01", notes="Original",
        )
        self.client.force_login(self.staff)
        resp = self.client.post(self._edit_url(visit.pk), {
            "date": "2026-02-02", "notes": "Updated",
        })
        self.assertEqual(resp.status_code, 200)
        visit.refresh_from_db()
        self.assertEqual(str(visit.date), "2026-02-02")
        self.assertEqual(visit.notes, "Updated")
        # Response should be the row partial (read-only mode) with new values.
        self.assertContains(resp, "2026-02-02")
        self.assertContains(resp, "Updated")

    def test_edit_404_when_visit_belongs_to_other_restaurant(self):
        # A visit that belongs to other_restaurant must not be editable under
        # restaurant's URL — guards against cross-restaurant id-guessing.
        visit = Visit.objects.create(
            restaurant=self.other_restaurant, date="2026-01-01",
        )
        self.client.force_login(self.staff)
        resp = self.client.get(self._edit_url(visit.pk))
        self.assertEqual(resp.status_code, 404)

    def test_staff_post_delete_removes_visit(self):
        visit = Visit.objects.create(restaurant=self.restaurant, date="2026-01-01")
        self.client.force_login(self.staff)
        resp = self.client.post(self._delete_url(visit.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Visit.objects.filter(pk=visit.pk).exists())

    def test_delete_404_when_visit_belongs_to_other_restaurant(self):
        visit = Visit.objects.create(
            restaurant=self.other_restaurant, date="2026-01-01",
        )
        self.client.force_login(self.staff)
        resp = self.client.post(self._delete_url(visit.pk))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Visit.objects.filter(pk=visit.pk).exists())

    def test_delete_get_returns_405(self):
        visit = Visit.objects.create(restaurant=self.restaurant, date="2026-01-01")
        self.client.force_login(self.staff)
        resp = self.client.get(self._delete_url(visit.pk))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Visit.objects.filter(pk=visit.pk).exists())

    def test_create_get_returns_405(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.add_url)
        self.assertEqual(resp.status_code, 405)

    def test_visits_section_rendered_on_edit_page(self):
        Visit.objects.create(restaurant=self.restaurant, date="2026-05-01", notes="Lunch")
        self.client.force_login(self.staff)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="visits-section"')
        self.assertContains(resp, "2026-05-01")
        self.assertContains(resp, "Lunch")
        self.assertContains(resp, f'hx-post="{self.add_url}"')


def _make_jpeg(name="test.jpg", color=(255, 0, 0), size=(20, 20)):
    """Return a SimpleUploadedFile with a tiny in-memory JPEG."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")


_PHOTO_MEDIA_ROOT = tempfile.mkdtemp(prefix="restaurants-photo-tests-")


@override_settings(MEDIA_ROOT=_PHOTO_MEDIA_ROOT)
class RestaurantEditPhotosTests(TestCase):
    """HTMX upload + caption + reorder + delete for Restaurant.photos."""

    @classmethod
    def setUpTestData(cls):
        cls.city = City.objects.create(name="Dublin", slug="dublin")
        cls.restaurant = Restaurant.objects.create(
            city=cls.city, name="Chapter One", cuisine="Modern Irish",
        )
        cls.other_restaurant = Restaurant.objects.create(
            city=cls.city, name="Other", cuisine="Italian",
        )
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True,
        )
        cls.regular = User.objects.create_user(
            username="reg", password="pw", is_staff=False,
        )
        cls.section_url = reverse(
            "restaurant_photos_section",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )
        cls.upload_url = reverse(
            "photo_upload",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )
        cls.reorder_url = reverse(
            "photo_reorder",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )
        cls.edit_url = reverse(
            "restaurant_edit",
            kwargs={"city_slug": cls.city.slug, "pk": cls.restaurant.pk},
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_PHOTO_MEDIA_ROOT, ignore_errors=True)

    def _caption_url(self, photo_pk, restaurant_pk=None):
        return reverse(
            "photo_edit_caption",
            kwargs={
                "city_slug": self.city.slug,
                "pk": restaurant_pk or self.restaurant.pk,
                "photo_pk": photo_pk,
            },
        )

    def _delete_url(self, photo_pk, restaurant_pk=None):
        return reverse(
            "photo_delete",
            kwargs={
                "city_slug": self.city.slug,
                "pk": restaurant_pk or self.restaurant.pk,
                "photo_pk": photo_pk,
            },
        )

    # --- auth gate ---

    def test_anon_get_section_redirects_to_login(self):
        resp = self.client.get(self.section_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_non_staff_get_section_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.get(self.section_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_anon_post_upload_redirects_to_login(self):
        resp = self.client.post(self.upload_url, {"image": _make_jpeg(), "caption": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertEqual(self.restaurant.photos.count(), 0)

    def test_non_staff_post_upload_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.post(self.upload_url, {"image": _make_jpeg(), "caption": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertEqual(self.restaurant.photos.count(), 0)

    def test_anon_get_caption_redirects_to_login(self):
        photo = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg())
        resp = self.client.get(self._caption_url(photo.pk))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_non_staff_post_caption_redirects_to_login(self):
        photo = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg())
        self.client.force_login(self.regular)
        resp = self.client.post(self._caption_url(photo.pk), {"caption": "x"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_anon_post_delete_redirects_to_login(self):
        photo = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg())
        resp = self.client.post(self._delete_url(photo.pk))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())

    def test_non_staff_post_delete_redirects_to_login(self):
        photo = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg())
        self.client.force_login(self.regular)
        resp = self.client.post(self._delete_url(photo.pk))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())

    def test_anon_post_reorder_redirects_to_login(self):
        resp = self.client.post(self.reorder_url, {"photo_ids": []})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_non_staff_post_reorder_redirects_to_login(self):
        self.client.force_login(self.regular)
        resp = self.client.post(self.reorder_url, {"photo_ids": []})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    # --- happy paths ---

    def test_staff_get_section_renders_existing_photos(self):
        Photo.objects.create(
            restaurant=self.restaurant, image=_make_jpeg(), caption="Tasty",
        )
        self.client.force_login(self.staff)
        resp = self.client.get(self.section_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Tasty")
        self.assertContains(resp, 'id="photo-upload-form"')

    def test_staff_upload_creates_photo_with_thumbnail(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.upload_url, {
            "image": _make_jpeg(name="lunch.jpg"),
            "caption": "Lunch shot",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.restaurant.photos.count(), 1)
        photo = self.restaurant.photos.get()
        self.assertEqual(photo.caption, "Lunch shot")
        # The model's save() generates a thumbnail; verify the file is present.
        self.assertTrue(photo.thumbnail.name)
        photo.thumbnail.open("rb")
        photo.thumbnail.close()
        self.assertContains(resp, "Lunch shot")

    def test_staff_upload_non_image_renders_validation_error(self):
        self.client.force_login(self.staff)
        bogus = SimpleUploadedFile("notes.txt", b"hello world", content_type="text/plain")
        resp = self.client.post(self.upload_url, {"image": bogus, "caption": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.restaurant.photos.count(), 0)
        self.assertContains(resp, "is-danger")

    def test_staff_upload_assigns_increasing_order(self):
        self.client.force_login(self.staff)
        self.client.post(self.upload_url, {"image": _make_jpeg(name="a.jpg"), "caption": "a"})
        self.client.post(self.upload_url, {"image": _make_jpeg(name="b.jpg"), "caption": "b"})
        orders = list(self.restaurant.photos.values_list("order", flat=True).order_by("order"))
        self.assertEqual(orders, [0, 1])

    def test_staff_get_caption_renders_inline_form(self):
        photo = Photo.objects.create(
            restaurant=self.restaurant, image=_make_jpeg(), caption="Old caption",
        )
        self.client.force_login(self.staff)
        resp = self.client.get(self._caption_url(photo.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="caption"')
        self.assertContains(resp, "Old caption")

    def test_staff_post_caption_updates_db(self):
        photo = Photo.objects.create(
            restaurant=self.restaurant, image=_make_jpeg(), caption="Old caption",
        )
        self.client.force_login(self.staff)
        resp = self.client.post(self._caption_url(photo.pk), {"caption": "New caption"})
        self.assertEqual(resp.status_code, 200)
        photo.refresh_from_db()
        self.assertEqual(photo.caption, "New caption")
        self.assertContains(resp, "New caption")

    def test_caption_404_when_photo_belongs_to_other_restaurant(self):
        photo = Photo.objects.create(restaurant=self.other_restaurant, image=_make_jpeg())
        self.client.force_login(self.staff)
        resp = self.client.get(self._caption_url(photo.pk))
        self.assertEqual(resp.status_code, 404)

    def test_staff_post_delete_removes_photo(self):
        photo = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg())
        image_path = photo.image.path
        thumbnail_path = photo.thumbnail.path
        self.assertTrue(os.path.exists(image_path))
        self.assertTrue(os.path.exists(thumbnail_path))
        self.client.force_login(self.staff)
        resp = self.client.post(self._delete_url(photo.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Photo.objects.filter(pk=photo.pk).exists())
        self.assertFalse(os.path.exists(image_path))
        self.assertFalse(os.path.exists(thumbnail_path))

    def test_delete_404_when_photo_belongs_to_other_restaurant(self):
        photo = Photo.objects.create(restaurant=self.other_restaurant, image=_make_jpeg())
        self.client.force_login(self.staff)
        resp = self.client.post(self._delete_url(photo.pk))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())

    def test_delete_get_returns_405(self):
        photo = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg())
        self.client.force_login(self.staff)
        resp = self.client.get(self._delete_url(photo.pk))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())

    def test_upload_get_returns_405(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.upload_url)
        self.assertEqual(resp.status_code, 405)

    def test_reorder_updates_order_field(self):
        p1 = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg(), order=0)
        p2 = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg(), order=1)
        p3 = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg(), order=2)
        self.client.force_login(self.staff)
        # Submit a new order [p3, p1, p2].
        resp = self.client.post(self.reorder_url, {
            "photo_ids": [str(p3.pk), str(p1.pk), str(p2.pk)],
        })
        self.assertEqual(resp.status_code, 200)
        p1.refresh_from_db()
        p2.refresh_from_db()
        p3.refresh_from_db()
        self.assertEqual(p3.order, 0)
        self.assertEqual(p1.order, 1)
        self.assertEqual(p2.order, 2)

    def test_reorder_ignores_photos_from_other_restaurant(self):
        mine = Photo.objects.create(restaurant=self.restaurant, image=_make_jpeg(), order=0)
        theirs = Photo.objects.create(
            restaurant=self.other_restaurant, image=_make_jpeg(), order=5,
        )
        self.client.force_login(self.staff)
        resp = self.client.post(self.reorder_url, {
            "photo_ids": [str(theirs.pk), str(mine.pk)],
        })
        self.assertEqual(resp.status_code, 200)
        theirs.refresh_from_db()
        mine.refresh_from_db()
        # Stranger photo untouched; mine repositioned according to its own index.
        self.assertEqual(theirs.order, 5)
        self.assertEqual(mine.order, 1)

    def test_photos_section_rendered_on_edit_page(self):
        Photo.objects.create(
            restaurant=self.restaurant, image=_make_jpeg(), caption="On edit page",
        )
        self.client.force_login(self.staff)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="photos-section"')
        self.assertContains(resp, "On edit page")
        self.assertContains(resp, f'hx-post="{self.upload_url}"')
