from django.contrib import admin

from .models import City, Photo, Restaurant, Visit


class VisitInline(admin.TabularInline):
    model = Visit
    extra = 1


class PhotoInline(admin.TabularInline):
    model = Photo
    extra = 1


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ["name", "city", "cuisine", "venue_category", "michelin_status", "rating"]
    list_filter = ["city", "venue_category", "michelin_status"]
    search_fields = ["name", "cuisine", "location", "comments"]
    inlines = [VisitInline, PhotoInline]


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
