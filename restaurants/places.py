import logging
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.id,places.formattedAddress,places.websiteUri,places.googleMapsUri,places.rating,places.location"


def search_place(name: str, city: str, api_key: str, location: str = "") -> dict | None:
    """Search Google Places for a restaurant and return its details.

    Returns a dict with keys: place_id, address, website, google_maps_url.
    Returns None if no result is found or the request fails.
    """
    parts = [name]
    if location:
        parts.append(location)
    parts.append(city)
    query = ", ".join(parts)
    try:
        resp = requests.post(
            SEARCH_URL,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            json={"textQuery": query},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException:
        logger.warning("Google Places API request failed for %r", query, exc_info=True)
        return None

    places = resp.json().get("places", [])
    if not places:
        logger.info("No Google Places result for %r", query)
        return None

    place = places[0]
    location = place.get("location", {})
    return {
        "place_id": place.get("id", ""),
        "address": place.get("formattedAddress", ""),
        "website": place.get("websiteUri", ""),
        "google_maps_url": place.get("googleMapsUri", ""),
        "google_rating": place.get("rating"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
    }


def _to_decimal(value):
    # Google Places returns numeric fields as JSON numbers (Python floats).
    # Coerce via str() so the value matches the model's DecimalField storage
    # exactly — direct float->Decimal would carry binary-fp drift, causing
    # spurious "changed" flags on re-fetch.
    if value is None:
        return None
    return Decimal(str(value))


def _to_coord(value):
    # Quantize to the latitude/longitude column precision (decimal_places=6).
    # Without this, fresh fetches carry extra precision that both shows a
    # spurious diff against the stored 6-place value and exceeds max_digits=9
    # on save.
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def google_places_source(probe) -> dict | None:
    """Adapter that exposes Google Places to the sources registry.

    Returns a dict keyed by Restaurant field names so values flow into
    `fetch_all` without re-mapping.
    """
    api_key = settings.GOOGLE_PLACES_API_KEY
    if not api_key:
        return None
    data = search_place(probe.name, probe.city_name, api_key, probe.location)
    if data is None:
        return None
    return {
        "google_place_id": data.get("place_id", ""),
        "address": data.get("address", ""),
        "website": data.get("website", ""),
        "google_maps_url": data.get("google_maps_url", ""),
        "google_rating": _to_decimal(data.get("google_rating")),
        "latitude": _to_coord(data.get("latitude")),
        "longitude": _to_coord(data.get("longitude")),
    }


google_places_source.source_name = "Google Places"
