import subprocess
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from restaurants.models import City

MAX_ZOOM = 15


class Command(BaseCommand):
    help = "Extract PMTiles for cities with a bounding box"

    def add_arguments(self, parser):
        parser.add_argument(
            "--city",
            help="Only process this city (slug)",
        )
        parser.add_argument(
            "--date",
            help="Protomaps build date (YYYYMMDD). Default: yesterday's build.",
        )

    def handle(self, **options):
        tiles_dir = Path(settings.TILES_DIR)
        tiles_dir.mkdir(parents=True, exist_ok=True)

        # Use yesterday's build by default (today's may not exist yet)
        build_date = options["date"] or f"{date.today() - timedelta(days=1):%Y%m%d}"
        planet_url = f"https://build.protomaps.com/{build_date}.pmtiles"

        cities = City.objects.all()
        if options["city"]:
            cities = cities.filter(slug=options["city"])

        cities = [c for c in cities if c.has_bbox]
        if not cities:
            raise CommandError("No cities with a bounding box found.")

        for city in cities:
            output = tiles_dir / f"{city.slug}.pmtiles"
            bbox = f"{city.bbox_min_lon},{city.bbox_min_lat},{city.bbox_max_lon},{city.bbox_max_lat}"
            self.stdout.write(f"Extracting tiles for {city.name} (bbox={bbox}) ...")

            result = subprocess.run(
                [
                    "pmtiles", "extract",
                    planet_url, str(output),
                    f"--bbox={bbox}",
                    f"--maxzoom={MAX_ZOOM}",
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                self.stderr.write(self.style.ERROR(
                    f"pmtiles extract failed for {city.name}:\n{result.stderr}"
                ))
                continue

            size_mb = output.stat().st_size / (1024 * 1024)
            self.stdout.write(self.style.SUCCESS(
                f"{city.name}: {output} ({size_mb:.1f} MB)"
            ))
