import io
from pathlib import PurePath

from django.core.files.base import ContentFile
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from PIL import Image, ImageOps

THUMBNAIL_MAX_SIZE = (800, 800)
THUMBNAIL_QUALITY = 80


class City(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)

    # Bounding box for map tile extraction and initial viewport.
    # A city without a bbox simply won't have a map tab.
    bbox_min_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    bbox_min_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    bbox_max_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    bbox_max_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "cities"

    def __str__(self):
        return self.name

    @property
    def has_bbox(self):
        return all(v is not None for v in [
            self.bbox_min_lon, self.bbox_min_lat,
            self.bbox_max_lon, self.bbox_max_lat,
        ])


class Tag(models.Model):
    class Color(models.TextChoices):
        BLUE = "is-info", "Blue"
        GREEN = "is-success", "Green"
        YELLOW = "is-warning", "Yellow"
        RED = "is-danger", "Red"
        PURPLE = "is-link", "Purple"
        TEAL = "is-primary", "Teal"
        DARK = "is-dark", "Dark"

    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=20, choices=Color.choices, default=Color.BLUE)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Restaurant(models.Model):
    class VenueCategory(models.TextChoices):
        RESTAURANT = "restaurant", "Restaurant"
        CAFE = "cafe", "Cafe"
        BAR = "bar", "Bar"
        PUB = "pub", "Pub"
        SANDWICH_PLACE = "sandwich_place", "Sandwich place"
        BAKERY = "bakery", "Bakery"
        FOOD_TRUCK = "food_truck", "Food truck"
        OTHER = "other", "Other"

    class MichelinStatus(models.TextChoices):
        NONE = "none", "None"
        SELECTED = "selected", "Selected"
        BIB_GOURMAND = "bib_gourmand", "Bib Gourmand"
        ONE_STAR = "one_star", "1 Star"
        TWO_STARS = "two_stars", "2 Stars"
        THREE_STARS = "three_stars", "3 Stars"

    RATING_TIERS = {
        "highly_recommend": {"label": "Highly recommend", "range": (9, 10)},
        "recommend": {"label": "Recommend", "range": (7, 8)},
        "ok": {"label": "It's OK", "range": (5, 6)},
        "dont_recommend": {"label": "Don't recommend", "range": (1, 4)},
    }

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="restaurants")
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True, help_text="Neighbourhood or area")
    cuisine = models.CharField(max_length=100, help_text="e.g. Italian, Japanese, Mexican")
    venue_category = models.CharField(
        max_length=20,
        choices=VenueCategory.choices,
        default=VenueCategory.RESTAURANT,
    )
    michelin_status = models.CharField(
        max_length=20,
        choices=MichelinStatus.choices,
        default=MichelinStatus.NONE,
    )
    # Null rating means the restaurant is on the wishlist (not visited yet).
    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Internal rating 1-10. Leave blank for wishlist (not visited yet).",
    )
    comments = models.TextField(blank=True, help_text="Markdown supported")

    # Fields for Google Places integration (M5) — useful for manual entry too
    address = models.CharField(max_length=300, blank=True)
    website = models.URLField(blank=True)
    google_maps_url = models.URLField(blank=True)
    google_place_id = models.CharField(max_length=300, blank=True)
    google_rating = models.DecimalField(
        max_digits=2, decimal_places=1, null=True, blank=True,
    )

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    hidden = models.BooleanField(default=False, help_text="Hide from the public list")
    closed = models.BooleanField(
        default=False, help_text="Restaurant has permanently closed",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="restaurants")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def rating_tier(self):
        if self.rating is None:
            return ""
        for tier in self.RATING_TIERS.values():
            lo, hi = tier["range"]
            if lo <= self.rating <= hi:
                return tier["label"]
        return ""

    @property
    def is_wishlist(self):
        return self.rating is None


class Visit(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="visits")
    date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.restaurant.name} — {self.date}"


class Photo(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="photos/")
    thumbnail = models.ImageField(upload_to="photos/thumbs/", blank=True)
    caption = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0, help_text="Lower numbers appear first")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.restaurant.name} — {self.caption or 'photo'}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track the image name so we can detect changes in save()
        self._original_image_name = self.image.name if self.image else None

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        super().save(*args, **kwargs)
        # Only generate thumbnails on full saves or when image is in update_fields
        if update_fields is not None and "image" not in update_fields:
            return
        image_changed = self.image.name != self._original_image_name
        if self.image and image_changed:
            self._strip_exif()
        if self.image and (image_changed or not self.thumbnail):
            self._generate_thumbnail()
            self._original_image_name = self.image.name

    def _strip_exif(self):
        """Re-save the image without EXIF metadata (location, timestamps, etc.)."""
        img = Image.open(self.image)
        fmt = img.format
        img = ImageOps.exif_transpose(img)
        save_kwargs = {}
        if fmt == "JPEG":
            save_kwargs["quality"] = 95
        buf = io.BytesIO()
        img.save(buf, format=fmt, **save_kwargs)
        buf.seek(0)
        name = self.image.name
        self.image.storage.delete(name)
        self.image.save(name, ContentFile(buf.read()), save=False)
        super().save(update_fields=["image"])

    def _generate_thumbnail(self):
        img = Image.open(self.image)
        img = ImageOps.exif_transpose(img)
        img.thumbnail(THUMBNAIL_MAX_SIZE)
        if img.mode in ("RGBA", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=THUMBNAIL_QUALITY)
        buf.seek(0)

        thumb_name = PurePath(self.image.name).stem + ".jpg"
        self.thumbnail.save(thumb_name, ContentFile(buf.read()), save=False)
        # save only the thumbnail field to avoid recursion
        super().save(update_fields=["thumbnail"])
