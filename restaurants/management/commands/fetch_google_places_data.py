from restaurants.places import google_places_source

from .fetch_all_data import Command as FetchAllDataCommand


class Command(FetchAllDataCommand):
    """Same flow as fetch_all_data, restricted to the Google Places source."""

    help = "Fetch Google Places data for restaurants missing any Places field"

    def get_sources(self):
        # Resolved at call time so tests can patch the module-level name.
        return [google_places_source]
