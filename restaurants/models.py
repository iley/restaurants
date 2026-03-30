from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class City(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "cities"

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
        OTHER = "other", "Other"

    class MichelinStatus(models.TextChoices):
        NONE = "none", "None"
        LISTED = "listed", "Michelin listed"
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
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Internal rating 1-10",
    )
    comments = models.TextField(blank=True)

    # Fields for Google Places integration (M5) — useful for manual entry too
    address = models.CharField(max_length=300, blank=True)
    website = models.URLField(blank=True)
    google_maps_url = models.URLField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def rating_tier(self):
        for tier in self.RATING_TIERS.values():
            lo, hi = tier["range"]
            if lo <= self.rating <= hi:
                return tier["label"]
        return ""


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
    caption = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0, help_text="Lower numbers appear first")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.restaurant.name} — {self.caption or 'photo'}"
