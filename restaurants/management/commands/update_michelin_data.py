from django.core.management.base import BaseCommand

from restaurants.michelin import michelin_source
from restaurants.models import Restaurant
from restaurants.sources import Probe, fetch_all


class Command(BaseCommand):
    help = (
        "Diff Michelin status from the local CSV against current values. "
        "Default is dry-run; pass --apply to write the proposed changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--city",
            help="Only process restaurants in this city (slug)",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write proposed changes; without this flag, only the diff is printed",
        )

    def handle(self, **options):
        qs = Restaurant.objects.select_related("city").all()
        if options["city"]:
            qs = qs.filter(city__slug=options["city"])

        restaurants = list(qs)
        if not restaurants:
            self.stdout.write("No restaurants to process.")
            return

        apply = options["apply"]
        would_change = unchanged = no_match = 0

        for restaurant in restaurants:
            fetched = fetch_all(
                Probe.from_restaurant(restaurant),
                sources=[michelin_source],
            )
            current = restaurant.michelin_status
            current_label = restaurant.get_michelin_status_display()

            fv = fetched.get("michelin_status")
            if fv is None:
                self.stdout.write(
                    f"[{restaurant.name}] no CSV match (current: {current_label})"
                )
                no_match += 1
                continue

            proposed = fv.value
            if proposed == current:
                self.stdout.write(
                    f"[{restaurant.name}] no change (current: {current_label})"
                )
                unchanged += 1
                continue

            restaurant.michelin_status = proposed
            proposed_label = restaurant.get_michelin_status_display()
            verb = "CHANGED" if apply else "WOULD CHANGE"
            self.stdout.write(self.style.SUCCESS(
                f"[{restaurant.name}] {verb}: {current_label} → {proposed_label}"
            ))
            if apply:
                restaurant.save(update_fields=["michelin_status"])
            else:
                # Revert in-memory mutation so dry-run does not leak state.
                restaurant.michelin_status = current
            would_change += 1

        verb = "changed" if apply else "would change"
        self.stdout.write(self.style.SUCCESS(
            f"\nDone: {would_change} {verb}, {unchanged} unchanged, {no_match} no match"
        ))
