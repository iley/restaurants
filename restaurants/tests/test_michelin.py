import os
import shutil
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from restaurants.models import Restaurant
from restaurants.sources import FETCHABLE_FIELDS, Probe, fetch_all
from restaurants import michelin
from restaurants.michelin import (
    _AWARD_TO_STATUS,
    MichelinEntry,
    _load_city,
    _normalize,
    match,
    michelin_source,
)


FIXTURE_CSV = Path(__file__).parent / "fixtures" / "michelin_test.csv"


def _clear_cache():
    michelin._CITY_CACHE.clear()


@override_settings()  # placeholder for clarity; per-test override below sets MICHELIN_CSV_PATH
class MatchTests(TestCase):
    def setUp(self):
        _clear_cache()
        self.csv = FIXTURE_CSV

    def _probe(self, name, city="Dublin", lat=None, lon=None):
        return Probe(
            name=name,
            city_name=city,
            latitude=Decimal(str(lat)) if lat is not None else None,
            longitude=Decimal(str(lon)) if lon is not None else None,
        )

    def _match(self, probe):
        with override_settings(MICHELIN_CSV_PATH=self.csv):
            return match(probe)

    def test_exact_match(self):
        result = self._match(self._probe("Patrick Guilbaud"))
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Patrick Guilbaud")
        self.assertEqual(result.status, Restaurant.MichelinStatus.TWO_STARS)

    def test_case_insensitive_match(self):
        result = self._match(self._probe("patrick GUILBAUD"))
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Patrick Guilbaud")

    def test_accent_stripped_match(self):
        # Probe is "Foret" (no accent), CSV has "Forêt".
        result = self._match(self._probe("Foret"))
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Forêt")
        self.assertEqual(result.status, Restaurant.MichelinStatus.SELECTED)

    def test_token_subset_match(self):
        # Probe "Bloom" matches "Bloom Brasserie" via token_set_ratio.
        result = self._match(self._probe("Bloom"))
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Bloom Brasserie")
        self.assertEqual(result.status, Restaurant.MichelinStatus.BIB_GOURMAND)

    def test_geo_tiebreaker_resolves_close_name_candidates(self):
        # "Sister Cafe" matches both "Sister Cafe North" and "Sister Cafe South"
        # at score 100. Without geo, gap is 0 -> ambiguous.
        # Probe coords match North very closely, so North gets +5 and South -20.
        result = self._match(self._probe("Sister Cafe", lat=53.355, lon=-6.260))
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Sister Cafe North")

    def test_geo_mismatch_rejects_otherwise_good_name_match(self):
        # Probe "Bloom" with coordinates >5 km from Bloom Brasserie.
        # 100 (name) - 20 (geo penalty) = 80, below the 88 threshold.
        result = self._match(self._probe("Bloom", lat=0.0, lon=0.0))
        self.assertIsNone(result)

    def test_ambiguous_name_with_no_geo_returns_none(self):
        # Same Sister Cafe scenario without lat/lon -> two equal scores, gap 0.
        result = self._match(self._probe("Sister Cafe"))
        self.assertIsNone(result)

    def test_city_scoping_excludes_other_cities(self):
        # Twin Palms exists only in Madrid in the fixture; a Dublin probe
        # for "Twin Palms" must not see it.
        result = self._match(self._probe("Twin Palms", city="Dublin"))
        self.assertIsNone(result)
        # Cross-check: a Cork probe for "DiSotto" finds the Cork entry,
        # and a Dublin probe for "DiSotto" does not.
        cork_match = self._match(self._probe("DiSotto", city="Cork"))
        self.assertIsNotNone(cork_match)
        dublin_disotto = self._match(self._probe("DiSotto", city="Dublin"))
        self.assertIsNone(dublin_disotto)


class AwardMappingTests(TestCase):
    def test_every_michelin_status_value_is_mapped(self):
        statuses = set(_AWARD_TO_STATUS.values())
        all_values = set(Restaurant.MichelinStatus.values)
        # Every non-NONE status must be a target of at least one award.
        self.assertEqual(
            statuses,
            all_values - {Restaurant.MichelinStatus.NONE},
        )

    def test_each_award_string_maps_to_expected_enum(self):
        cases = {
            "3 Stars": Restaurant.MichelinStatus.THREE_STARS,
            "2 Stars": Restaurant.MichelinStatus.TWO_STARS,
            "1 Star": Restaurant.MichelinStatus.ONE_STAR,
            "Bib Gourmand": Restaurant.MichelinStatus.BIB_GOURMAND,
            "Selected Restaurants": Restaurant.MichelinStatus.SELECTED,
        }
        for award, expected in cases.items():
            self.assertEqual(_AWARD_TO_STATUS[award], expected)

    def test_unknown_award_returns_none(self):
        # The fixture contains a row with award "Random Award"; the loader
        # must skip it silently. After loading Dublin, that row's name
        # ("Mystery Spot") must not appear in the entries.
        _clear_cache()
        with override_settings(MICHELIN_CSV_PATH=FIXTURE_CSV):
            entries = _load_city(FIXTURE_CSV, "dublin")
        names = {e.name for e in entries}
        self.assertNotIn("Mystery Spot", names)


class LoadCityCacheTests(TestCase):
    def setUp(self):
        _clear_cache()

    def test_repeat_call_for_same_city_reads_file_once(self):
        real_open = open
        with patch("restaurants.michelin.open", side_effect=real_open) as mocked:
            _load_city(FIXTURE_CSV, "dublin")
            _load_city(FIXTURE_CSV, "dublin")
        self.assertEqual(mocked.call_count, 1)

    def test_distinct_cities_each_read_file(self):
        real_open = open
        with patch("restaurants.michelin.open", side_effect=real_open) as mocked:
            _load_city(FIXTURE_CSV, "dublin")
            _load_city(FIXTURE_CSV, "madrid")
        self.assertEqual(mocked.call_count, 2)

    def test_mtime_change_invalidates_cache(self):
        # Copy the fixture so bumping mtime doesn't pollute the checked-in file.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_csv = Path(tmp) / "michelin.csv"
            shutil.copy(FIXTURE_CSV, tmp_csv)
            real_open = open
            with patch("restaurants.michelin.open", side_effect=real_open) as mocked:
                _load_city(tmp_csv, "dublin")
                new_mtime = time.time() + 1
                os.utime(tmp_csv, (new_mtime, new_mtime))
                _load_city(tmp_csv, "dublin")
        self.assertEqual(mocked.call_count, 2)

    def test_missing_file_returns_empty_list(self):
        result = _load_city(Path("/nonexistent/michelin.csv"), "dublin")
        self.assertEqual(result, [])

    def test_directory_path_returns_empty_list(self):
        # If MICHELIN_CSV_PATH resolves to a directory (e.g. Docker bind-mount
        # misconfig), _load_city must not crash with IsADirectoryError; admin
        # actions invoke michelin_source unconditionally.
        with tempfile.TemporaryDirectory() as dir_path:
            result = _load_city(Path(dir_path), "dublin")
        self.assertEqual(result, [])


class MichelinSourceTests(TestCase):
    def setUp(self):
        _clear_cache()

    def test_source_name_attribute(self):
        self.assertEqual(michelin_source.source_name, "Michelin Guide")

    def test_returns_michelin_status_only_when_matched(self):
        with override_settings(MICHELIN_CSV_PATH=FIXTURE_CSV):
            result = michelin_source(Probe(name="Patrick Guilbaud", city_name="Dublin"))
        self.assertEqual(result, {"michelin_status": Restaurant.MichelinStatus.TWO_STARS})

    def test_returns_none_when_no_match(self):
        with override_settings(MICHELIN_CSV_PATH=FIXTURE_CSV):
            result = michelin_source(Probe(name="Totally Unknown Place", city_name="Dublin"))
        self.assertIsNone(result)

    def test_returns_none_when_csv_missing(self):
        with override_settings(MICHELIN_CSV_PATH=Path("/nonexistent/michelin.csv")):
            result = michelin_source(Probe(name="Patrick Guilbaud", city_name="Dublin"))
        self.assertIsNone(result)


class FetchAllMergesMichelinAndPlacesTests(TestCase):
    def test_merges_michelin_status_with_places_fields(self):
        # Both sources contribute distinct fields; fetch_all should keep both.
        def places_stub(probe):
            return {
                "address": "1 Main St",
                "website": "https://example.com",
            }
        places_stub.source_name = "Google Places"

        def michelin_stub(probe):
            return {"michelin_status": Restaurant.MichelinStatus.ONE_STAR}
        michelin_stub.source_name = "Michelin Guide"

        probe = Probe(name="X", city_name="Dublin")
        result = fetch_all(probe, sources=[places_stub, michelin_stub])

        self.assertEqual(result["michelin_status"].value, Restaurant.MichelinStatus.ONE_STAR)
        self.assertEqual(result["michelin_status"].source_name, "Michelin Guide")
        self.assertEqual(result["address"].value, "1 Main St")
        self.assertEqual(result["address"].source_name, "Google Places")
        self.assertEqual(result["website"].value, "https://example.com")

    def test_michelin_status_in_fetchable_fields(self):
        self.assertIn("michelin_status", FETCHABLE_FIELDS)

    def test_michelin_source_registered_in_default_sources(self):
        from restaurants.sources import SOURCES
        self.assertIn(michelin_source, SOURCES)


class NormalizeTests(TestCase):
    def test_strips_accents(self):
        self.assertEqual(_normalize("Forêt"), "foret")
        self.assertEqual(_normalize("crème brûlée"), "creme brulee")

    def test_lowercases_and_collapses_whitespace(self):
        self.assertEqual(_normalize("  Hello   World  "), "hello world")

    def test_strips_punctuation(self):
        # Punctuation becomes whitespace then collapses, so "Bloom's" -> "bloom s".
        # Token-set matching is unaffected.
        self.assertEqual(_normalize("Bloom's Brasserie!"), "bloom s brasserie")

    def test_empty_input(self):
        self.assertEqual(_normalize(""), "")
