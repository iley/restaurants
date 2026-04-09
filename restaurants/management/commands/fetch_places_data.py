import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from restaurants.models import Restaurant
from restaurants.places import apply_place_data, search_place


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
        api_key = settings.GOOGLE_PLACES_API_KEY
        if not api_key:
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

            data = search_place(restaurant.name, restaurant.city.name, api_key, restaurant.location)
            if data is None:
                self.stdout.write(self.style.WARNING(f"{prefix} — not found"))
                not_found += 1
                continue

            fields = apply_place_data(restaurant, data, force=options["force"])
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
