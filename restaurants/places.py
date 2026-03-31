import logging

import requests

logger = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.id,places.formattedAddress,places.websiteUri,places.googleMapsUri,places.rating"


def search_place(name: str, city: str, api_key: str) -> dict | None:
    """Search Google Places for a restaurant and return its details.

    Returns a dict with keys: place_id, address, website, google_maps_url.
    Returns None if no result is found or the request fails.
    """
    query = f"{name}, {city}"
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
    return {
        "place_id": place.get("id", ""),
        "address": place.get("formattedAddress", ""),
        "website": place.get("websiteUri", ""),
        "google_maps_url": place.get("googleMapsUri", ""),
        "google_rating": place.get("rating"),
    }


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
