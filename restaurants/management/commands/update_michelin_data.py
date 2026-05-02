import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from restaurants.michelin import michelin_source
from restaurants.models import Restaurant
from restaurants.sources import Probe, fetch_all

_REQUIRED_CSV_COLUMNS = ("Name", "Location", "Award")


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
        # Refuse to run on a missing/empty/malformed CSV — otherwise every row
        # below would print "no CSV match", indistinguishable from real
        # demotions, which can lead to incorrect manual status removals.
        csv_path = Path(settings.MICHELIN_CSV_PATH)
        if not csv_path.is_file() or csv_path.stat().st_size == 0:
            raise CommandError(
                f"Michelin CSV not found or empty at {csv_path}. "
                "Download michelin_my_maps.csv from Kaggle and place it there "
                "(or set MICHELIN_CSV_PATH) before running this command."
            )
        self._validate_csv_shape(csv_path)

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
                no_match += 1
                continue

            proposed = fv.value
            if proposed == current:
                unchanged += 1
                continue

            proposed_label = Restaurant.MichelinStatus(proposed).label
            verb = "CHANGED" if apply else "WOULD CHANGE"
            self.stdout.write(self.style.SUCCESS(
                f"[{restaurant.name}] {verb}: {current_label} → {proposed_label}"
            ))
            if apply:
                restaurant.michelin_status = proposed
                restaurant.save(update_fields=["michelin_status"])
            would_change += 1

        verb = "changed" if apply else "would change"
        self.stdout.write(self.style.SUCCESS(
            f"\nDone: {would_change} {verb}, {unchanged} unchanged, {no_match} no match"
        ))

    @staticmethod
    def _validate_csv_shape(csv_path: Path) -> None:
        """Ensure the CSV has the columns we read and at least one data row.

        Without this, a header-only or wrong-schema file would silently produce
        zero matches and the diff would look like a mass demotion. Blank lines
        and rows with only empty cells (e.g. ",,") don't count as data.
        """
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader, None) or []
            missing = [c for c in _REQUIRED_CSV_COLUMNS if c not in header]
            if missing:
                raise CommandError(
                    f"Michelin CSV at {csv_path} is missing required columns: "
                    f"{', '.join(missing)}."
                )
            has_data = any(any(cell.strip() for cell in row) for row in reader)
            if not has_data:
                raise CommandError(
                    f"Michelin CSV at {csv_path} has a header but no data rows."
                )
