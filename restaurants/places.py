import logging

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


def google_places_source(probe) -> dict | None:
    """Adapter that exposes Google Places to the sources registry.

    Returns a dict keyed by Restaurant field names (`google_place_id`, ...)
    rather than the legacy `place_id` key, so values flow into `fetch_all`
    without re-mapping.
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
        "google_rating": data.get("google_rating"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
    }


google_places_source.source_name = "Google Places"


def apply_place_data(restaurant, data: dict, force: bool = False) -> list[str]:
    """Apply place data to a restaurant.

    By default only fills blank fields. With force=True, overwrites all fields.
    Returns a list of field names that were updated.
    """
    field_map = {
        "google_place_id": "place_id",
        "address": "address",
        "website": "website",
        "google_maps_url": "google_maps_url",
        "google_rating": "google_rating",
        "latitude": "latitude",
        "longitude": "longitude",
    }
    updated = []
    for model_field, data_key in field_map.items():
        current = getattr(restaurant, model_field)
        value = data.get(data_key)
        if force:
            if value != current:
                setattr(restaurant, model_field, value)
                updated.append(model_field)
        else:
            if current in (None, "") and value:
                setattr(restaurant, model_field, value)
                updated.append(model_field)
    return updated
