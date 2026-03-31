from django.core.management.base import BaseCommand

from restaurants.models import Photo


class Command(BaseCommand):
    help = "Strip EXIF metadata (location, timestamps, etc.) from all uploaded photos"

    def handle(self, *args, **options):
        photos = Photo.objects.exclude(image="")
        total = photos.count()
        if not total:
            self.stdout.write("No photos found.")
            return

        for photo in photos:
            photo._strip_exif()
            self.stdout.write(f"  {photo}")

        self.stdout.write(
            self.style.SUCCESS(f"Stripped EXIF data from {total} photo(s).")
        )
