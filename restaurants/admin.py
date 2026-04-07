import logging

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


@admin.register(Restaurant)
class RestaurantAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ["name", "city", "cuisine", "venue_category", "michelin_status", "rating", "hidden", "closed"]
    list_filter = ["city", "venue_category", "michelin_status", "hidden", "closed"]
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
        data = search_place(obj.name, obj.city.name, api_key)
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
            data = search_place(restaurant.name, restaurant.city.name, api_key)
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
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
