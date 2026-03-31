from django.core.management.base import BaseCommand

from restaurants.models import Photo


class Command(BaseCommand):
    help = "Generate thumbnails for photos that don't have one"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenerate thumbnails even if they already exist",
        )

    def handle(self, *args, **options):
        photos = Photo.objects.all()
        if not options["force"]:
            photos = photos.filter(thumbnail="")

        total = photos.count()
        if not total:
            self.stdout.write("All photos already have thumbnails.")
            return

        for photo in photos:
            photo._generate_thumbnail()
            self.stdout.write(f"  {photo}")

        self.stdout.write(self.style.SUCCESS(f"Generated thumbnails for {total} photo(s)."))
