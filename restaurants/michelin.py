"""Michelin guide data source.

Loads restaurant entries from a Kaggle-sourced CSV (`michelin_my_maps.csv`)
and matches probes by fuzzy name comparison with optional geo gating. The
full ~19k-row CSV is streamed and only entries whose city contains the
probe's city substring are retained, keyed by `(path, mtime, city)` so each
city is scanned at most once per process.
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from .models import Restaurant

if TYPE_CHECKING:
    from .sources import Probe

MICHELIN_NAME_THRESHOLD = 88
MICHELIN_AMBIGUITY_GAP = 5
MICHELIN_GEO_BONUS_M = 200
MICHELIN_GEO_PENALTY_M = 5000
_GEO_BONUS_SCORE = 5
_GEO_PENALTY_SCORE = 20

_AWARD_TO_STATUS: dict[str, str] = {
    "3 Stars": Restaurant.MichelinStatus.THREE_STARS,
    "2 Stars": Restaurant.MichelinStatus.TWO_STARS,
    "1 Star": Restaurant.MichelinStatus.ONE_STAR,
    "Bib Gourmand": Restaurant.MichelinStatus.BIB_GOURMAND,
    "Selected Restaurants": Restaurant.MichelinStatus.SELECTED,
}

_NON_ALNUM_SPACE = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    """Strip accents, lowercase, drop punctuation, collapse whitespace."""
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = no_marks.lower()
    cleaned = _NON_ALNUM_SPACE.sub(" ", lowered)
    return _WHITESPACE.sub(" ", cleaned).strip()


@dataclass
class MichelinEntry:
    name: str
    normalized_name: str
    city_normalized: str
    latitude: float | None
    longitude: float | None
    status: str


# Cache key includes mtime so a CSV refresh invalidates without process restart.
_CITY_CACHE: dict[tuple[str, float, str], list[MichelinEntry]] = {}


def _parse_coord(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _load_city(path: Path, city_normalized: str) -> list[MichelinEntry]:
    """Return all CSV entries whose normalized city contains `city_normalized`.

    Streams the file and keeps only matching rows (typically a few dozen),
    avoiding full materialization of the 19k-row CSV.
    """
    path = Path(path)
    if not path.exists() or not city_normalized:
        return []
    mtime = path.stat().st_mtime
    key = (str(path), mtime, city_normalized)
    cached = _CITY_CACHE.get(key)
    if cached is not None:
        return cached

    entries: list[MichelinEntry] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            award = (row.get("Award") or "").strip()
            status = _AWARD_TO_STATUS.get(award)
            if status is None:
                continue
            location = row.get("Location") or ""
            # Location values look like "Dublin City, Ireland"; first piece is the city.
            city_part = location.split(",", 1)[0]
            entry_city_norm = _normalize(city_part)
            if city_normalized not in entry_city_norm:
                continue
            name = (row.get("Name") or "").strip()
            normalized_name = _normalize(name)
            entries.append(MichelinEntry(
                name=name,
                normalized_name=normalized_name,
                city_normalized=entry_city_norm,
                latitude=_parse_coord(row.get("Latitude") or ""),
                longitude=_parse_coord(row.get("Longitude") or ""),
                status=status,
            ))
    _CITY_CACHE[key] = entries
    return entries


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def match(probe: "Probe") -> MichelinEntry | None:
    """Return the best CSV entry matching `probe`, or None if uncertain."""
    from django.conf import settings

    city_norm = _normalize(probe.city_name)
    entries = _load_city(Path(settings.MICHELIN_CSV_PATH), city_norm)
    if not entries:
        return None

    probe_norm = _normalize(probe.name)
    if not probe_norm:
        return None

    probe_lat = float(probe.latitude) if probe.latitude is not None else None
    probe_lon = float(probe.longitude) if probe.longitude is not None else None
    have_probe_geo = probe_lat is not None and probe_lon is not None

    scored: list[tuple[float, MichelinEntry]] = []
    for e in entries:
        score = fuzz.token_set_ratio(probe_norm, e.normalized_name)
        if have_probe_geo and e.latitude is not None and e.longitude is not None:
            d = _haversine_m(probe_lat, probe_lon, e.latitude, e.longitude)
            if d <= MICHELIN_GEO_BONUS_M:
                score += _GEO_BONUS_SCORE
            elif d > MICHELIN_GEO_PENALTY_M:
                score -= _GEO_PENALTY_SCORE
        scored.append((score, e))

    scored.sort(key=lambda x: x[0], reverse=True)
    if scored[0][0] < MICHELIN_NAME_THRESHOLD:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < MICHELIN_AMBIGUITY_GAP:
        return None
    return scored[0][1]


def michelin_source(probe: "Probe") -> dict | None:
    """Adapter exposing Michelin guide CSV matches to the sources registry."""
    entry = match(probe)
    if entry is None:
        return None
    return {"michelin_status": entry.status}


michelin_source.source_name = "Michelin Guide"
