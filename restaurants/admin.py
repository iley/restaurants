import logging
import subprocess
import sys

from adminsortable2.admin import SortableAdminBase, SortableTabularInline
from django.conf import settings
from django.contrib import admin

from .models import City, Photo, Restaurant, Tag, Visit
from .places import apply_place_data, search_place

logger = logging.getLogger(__name__)


class VisitInline(admin.TabularInline):
    model = Visit
    extra = 1


class PhotoInline(SortableTabularInline):
    model = Photo
    extra = 0


class WishlistFilter(admin.SimpleListFilter):
    title = "wishlist"
    parameter_name = "wishlist"

    def lookups(self, request, model_admin):
        return [("yes", "Wishlist (no rating)"), ("no", "Visited (has rating)")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(rating__isnull=True)
        if self.value() == "no":
            return queryset.filter(rating__isnull=False)
        return queryset


@admin.register(Restaurant)
class RestaurantAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ["name", "city", "cuisine", "venue_category", "michelin_status", "rating", "hidden", "closed"]
    list_filter = ["city", "venue_category", "michelin_status", WishlistFilter, "hidden", "closed"]
    list_editable = ["hidden", "closed"]
    search_fields = ["name", "cuisine", "location", "comments"]
    filter_horizontal = ["tags"]
    inlines = [VisitInline, PhotoInline]
    actions = ["fetch_places_data", "force_fetch_places_data"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        api_key = settings.GOOGLE_PLACES_API_KEY
        if not api_key or obj.address:
            return
        data = search_place(obj.name, obj.city.name, api_key, obj.location)
        if data:
            fields = apply_place_data(obj, data)
            if fields:
                obj.save(update_fields=fields)

    @admin.action(description="Fetch Google Places data")
    def fetch_places_data(self, request, queryset):
        self._do_fetch_places(request, queryset, force=False)

    @admin.action(description="Re-fetch Google Places data (overwrite)")
    def force_fetch_places_data(self, request, queryset):
        self._do_fetch_places(request, queryset, force=True)

    def _do_fetch_places(self, request, queryset, force):
        api_key = settings.GOOGLE_PLACES_API_KEY
        if not api_key:
            self.message_user(
                request,
                "GOOGLE_PLACES_API_KEY is not configured.",
                level="error",
            )
            return

        updated = not_found = skipped = 0
        for restaurant in queryset.select_related("city"):
            data = search_place(restaurant.name, restaurant.city.name, api_key, restaurant.location)
            if data is None:
                not_found += 1
                continue
            fields = apply_place_data(restaurant, data, force=force)
            if fields:
                restaurant.save(update_fields=fields)
                updated += 1
            else:
                skipped += 1

        self.message_user(
            request,
            f"Places data: {updated} updated, {not_found} not found, {skipped} already complete.",
        )


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "color"]
    search_fields = ["name"]


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = [
        (None, {"fields": ["name", "slug"]}),
        ("Map bounding box", {
            "fields": ["bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat"],
            "description": (
                'Look up values at <a href="http://bboxfinder.com" target="_blank">bboxfinder.com</a>. '
                "Leave blank to disable the map tab for this city."
            ),
        }),
    ]
    actions = ["fetch_tiles"]

    @admin.action(description="Fetch map tiles")
    def fetch_tiles(self, request, queryset):
        cities = [c for c in queryset if c.has_bbox]
        if not cities:
            self.message_user(request, "No selected cities have a bounding box set.", level="warning")
            return
        for city in cities:
            # Run in background so a browser disconnect won't kill it
            subprocess.Popen(
                [sys.executable, "manage.py", "fetch_tiles", "--city", city.slug],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        names = ", ".join(c.name for c in cities)
        self.message_user(request, f"Tile fetch started in the background for: {names}")
