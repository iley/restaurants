import csv
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from restaurants.models import City, Restaurant, Visit


class Command(BaseCommand):
    help = "Import restaurants from the cleaned Dublin CSV file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default="docs/dublin_food.csv",
            help="Path to the CSV file (relative to project root)",
        )

    def handle(self, **options):
        csv_path = Path(options["csv"])
        if not csv_path.is_absolute():
            csv_path = settings.BASE_DIR / csv_path

        dublin, _ = City.objects.get_or_create(
            name="Dublin", defaults={"slug": "dublin"}
        )

        created = skipped = visits_created = 0

        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                name = row["Name"].strip()

                restaurant, was_created = Restaurant.objects.get_or_create(
                    name=name,
                    city=dublin,
                    defaults={
                        "cuisine": row["Cuisine"].strip(),
                        "venue_category": row["Venue category"].strip(),
                        "location": row["Location"].strip(),
                        "rating": int(row["Rating"].strip()),
                        "michelin_status": row["Michelin status"].strip(),
                        "comments": row["Comments"].strip(),
                    },
                )

                if not was_created:
                    skipped += 1
                    continue

                created += 1
                date_str = row["Date visited"].strip()
                if date_str:
                    Visit.objects.create(
                        restaurant=restaurant,
                        date=datetime.strptime(date_str, "%d/%m/%Y").date(),
                    )
                    visits_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created} created, {skipped} skipped, {visits_created} visits"
            )
        )
