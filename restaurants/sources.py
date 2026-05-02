"""Pluggable attribute sources for restaurants.

Each source is a callable that takes a `Probe` and returns either a dict of
field values or `None`. `fetch_all` merges values from all registered sources
using a first-non-empty-wins rule, returning a `dict[field_name, FetchedValue]`
that records which source supplied each value.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Optional

from .michelin import michelin_source
from .places import google_places_source

# Fields any source may provide. Single source of truth used by `fetch_all`
# (which fields to merge) and by the admin view (which POST values to read as
# the user's "current" values).
FETCHABLE_FIELDS = [
    "address",
    "website",
    "google_maps_url",
    "google_place_id",
    "google_rating",
    "latitude",
    "longitude",
    "michelin_status",
]


@dataclass
class Probe:
    """Inputs needed to query an attribute source.

    Built from either a saved `Restaurant` or unsaved admin form values, so the
    fetch flow works on the change form before the user clicks Save.
    """
    name: str
    city_name: str
    location: str = ""
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None

    @classmethod
    def from_restaurant(cls, restaurant) -> "Probe":
        return cls(
            name=restaurant.name,
            city_name=restaurant.city.name,
            location=restaurant.location,
            latitude=restaurant.latitude,
            longitude=restaurant.longitude,
        )


@dataclass
class FetchedValue:
    value: Any
    source_name: str


# A Source is just a callable. Using a plain Callable type rather than Protocol
# keeps the registry simple and lets functions be registered without a wrapper.
Source = Callable[[Probe], Optional[dict]]


def _is_empty(value: Any) -> bool:
    return value is None or value == ""


def apply_fetched(
    restaurant,
    fetched: dict[str, "FetchedValue"],
    force: bool = False,
) -> list[str]:
    """Write fetched values onto a restaurant.

    Default mode only fills blank fields with non-empty values. With `force=True`,
    any field whose fetched value differs from the current value is overwritten.
    Returns the list of fields that were actually changed (suitable for
    `update_fields`).
    """
    updated: list[str] = []
    for field, fv in fetched.items():
        current = getattr(restaurant, field)
        value = fv.value
        if force:
            if value != current:
                setattr(restaurant, field, value)
                updated.append(field)
        else:
            if current in (None, "") and not _is_empty(value):
                setattr(restaurant, field, value)
                updated.append(field)
    return updated


def fetch_all(probe: Probe, sources: Optional[list] = None) -> dict[str, FetchedValue]:
    """Query all sources and merge the results.

    For each fetchable field, the first source (in registration order) that
    returns a non-empty value wins. Fields not provided by any source are
    absent from the returned dict.
    """
    if sources is None:
        sources = SOURCES
    merged: dict[str, FetchedValue] = {}
    for source in sources:
        data = source(probe)
        if not data:
            continue
        source_name = getattr(source, "source_name", source.__name__)
        for field in FETCHABLE_FIELDS:
            if field in merged:
                continue
            value = data.get(field)
            if _is_empty(value):
                continue
            merged[field] = FetchedValue(value=value, source_name=source_name)
    return merged


SOURCES: list[Source] = [google_places_source, michelin_source]
