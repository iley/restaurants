import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from restaurants.models import Restaurant
from restaurants.places import google_places_source
from restaurants.sources import Probe, apply_fetched, fetch_all


class Command(BaseCommand):
    help = "Fetch Google Places data for restaurants missing any Places field"

    def add_arguments(self, parser):
        parser.add_argument(
            "--city",
            help="Only process restaurants in this city (slug)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="fetch_all",
            help="Include all restaurants, not just those missing data",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing data with fresh API values",
        )

    def handle(self, **options):
        if not settings.GOOGLE_PLACES_API_KEY:
            raise CommandError(
                "GOOGLE_PLACES_API_KEY is not set. "
                "Export it as an environment variable and try again."
            )

        qs = Restaurant.objects.select_related("city").all()
        if options["city"]:
            qs = qs.filter(city__slug=options["city"])
        if not options["fetch_all"] and not options["force"]:
            from django.db.models import Q

            qs = qs.filter(
                Q(address="")
                | Q(website="")
                | Q(google_maps_url="")
                | Q(google_place_id="")
                | Q(google_rating__isnull=True)
                | Q(latitude__isnull=True)
                | Q(longitude__isnull=True)
            )

        restaurants = list(qs)
        if not restaurants:
            self.stdout.write("No restaurants to process.")
            return

        total = len(restaurants)
        updated = not_found = skipped = 0

        for i, restaurant in enumerate(restaurants, 1):
            prefix = f"[{i}/{total}] {restaurant.name}"

            fetched = fetch_all(
                Probe.from_restaurant(restaurant),
                sources=[google_places_source],
            )
            if not fetched:
                self.stdout.write(self.style.WARNING(f"{prefix} — not found"))
                not_found += 1
                continue

            fields = apply_fetched(restaurant, fetched, force=options["force"])
            if fields:
                restaurant.save(update_fields=fields)
                self.stdout.write(
                    self.style.SUCCESS(f"{prefix} — updated ({', '.join(fields)})")
                )
                updated += 1
            else:
                self.stdout.write(f"{prefix} — skipped (all fields already set)")
                skipped += 1

            # Be polite to the API
            if i < total:
                time.sleep(0.1)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {updated} updated, {not_found} not found, {skipped} skipped"
            )
        )
