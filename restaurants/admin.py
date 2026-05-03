import subprocess
import sys
from decimal import Decimal, InvalidOperation

from adminsortable2.admin import SortableAdminBase, SortableTabularInline
from django.conf import settings
from django.contrib import admin
from django.http import HttpResponseNotAllowed
from django.template.response import TemplateResponse
from django.urls import path

from .michelin import michelin_source
from .models import City, Photo, Restaurant, Tag, Visit
from .places import google_places_source
from .sources import FETCHABLE_FIELDS, Probe, apply_fetched, fetch_all


def _parse_decimal(value):
    if not value:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _choice_label(field, value):
    """Return the human-readable label for a choice value, else the value itself.

    Form-style POST data and TextChoices fields both render as raw slugs
    (e.g. `two_stars`); panels should show the choice's display label.
    """
    if not value:
        return value
    try:
        model_field = Restaurant._meta.get_field(field)
    except Exception:
        return value
    choices = getattr(model_field, "flatchoices", None)
    if not choices:
        return value
    return dict(choices).get(value, value)


def _values_equal(current, proposed):
    """Compare a POSTed string to a fetched value for the unchanged-row check.

    Numeric fields (Decimal/float) need numeric comparison: a form input may
    render `Decimal('53.349800')` as the string `"53.349800"` while a fresh
    fetch produces `Decimal('53.3498')`, which is the same number. Falling back
    to string compare for everything else keeps the simple cases simple.
    """
    if isinstance(proposed, (Decimal, float, int)) and not isinstance(proposed, bool):
        try:
            return Decimal(str(current).strip()) == Decimal(str(proposed))
        except (InvalidOperation, ValueError):
            return False
    return str(current).strip() == str(proposed).strip()


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
    actions = [
        "fetch_places_data",
        "force_fetch_places_data",
        "update_michelin_status",
        "force_update_michelin_status",
    ]

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        last_city_id = (
            Restaurant.objects.order_by("-created_at")
            .values_list("city_id", flat=True)
            .first()
        )
        if last_city_id is not None:
            initial.setdefault("city", last_city_id)
        else:
            default = City.get_default()
            if default is not None:
                initial.setdefault("city", default.pk)
        return initial

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "fetch-attributes/",
                self.admin_site.admin_view(self.fetch_attributes_view),
                name="restaurants_restaurant_fetch_attributes",
            ),
            path(
                "check-duplicate/",
                self.admin_site.admin_view(self.check_duplicate_view),
                name="restaurants_restaurant_check_duplicate",
            ),
        ]
        return custom + urls

    def check_duplicate_view(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        name = request.POST.get("name", "").strip()
        template = "admin/restaurants/restaurant/_duplicate_warning.html"
        empty = TemplateResponse(request, template, {"duplicates": []})
        if not name:
            return empty
        try:
            city_id = int(request.POST.get("city", "").strip())
        except ValueError:
            return empty

        qs = Restaurant.objects.filter(city_id=city_id, name__iexact=name).select_related("city")
        pk_raw = request.POST.get("pk", "").strip()
        if pk_raw:
            try:
                qs = qs.exclude(pk=int(pk_raw))
            except ValueError:
                pass
        return TemplateResponse(request, template, {"duplicates": list(qs[:5])})

    def fetch_attributes_view(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        name = request.POST.get("name", "").strip()
        city_pk = request.POST.get("city", "").strip()
        location = request.POST.get("location", "").strip()

        template = "admin/restaurants/restaurant/_fetch_results.html"
        if not name or not city_pk:
            return TemplateResponse(request, template, {
                "rows": [],
                "message": "Enter a name and select a city before fetching.",
            })

        try:
            city = City.objects.get(pk=city_pk)
        except (City.DoesNotExist, ValueError):
            return TemplateResponse(request, template, {
                "rows": [],
                "message": "Selected city not found.",
            })

        probe = Probe(
            name=name,
            city_name=city.name,
            location=location,
            latitude=_parse_decimal(request.POST.get("latitude")),
            longitude=_parse_decimal(request.POST.get("longitude")),
        )
        fetched = fetch_all(probe)

        current = {f: request.POST.get(f, "") for f in FETCHABLE_FIELDS}
        rows = []
        for field, fv in fetched.items():
            current_val = current.get(field, "")
            proposed_val = fv.value
            if _values_equal(current_val, proposed_val):
                continue
            rows.append({
                "field": field,
                "label": field.replace("_", " ").title(),
                "current_display": _choice_label(field, current_val),
                "proposed": proposed_val,
                "proposed_display": _choice_label(field, proposed_val),
                "source_name": fv.source_name,
                "input_id": f"id_{field}",
            })

        message = "" if rows else "No proposed changes."
        return TemplateResponse(request, template, {"rows": rows, "message": message})

    @admin.action(description="Fetch Google Places data")
    def fetch_places_data(self, request, queryset):
        if not settings.GOOGLE_PLACES_API_KEY:
            self.message_user(request, "GOOGLE_PLACES_API_KEY is not configured.", level="error")
            return
        self._run_sources(request, queryset, [google_places_source], force=False, label="Places data")

    @admin.action(description="Re-fetch Google Places data (overwrite)")
    def force_fetch_places_data(self, request, queryset):
        if not settings.GOOGLE_PLACES_API_KEY:
            self.message_user(request, "GOOGLE_PLACES_API_KEY is not configured.", level="error")
            return
        self._run_sources(request, queryset, [google_places_source], force=True, label="Places data")

    @admin.action(description="Update Michelin status")
    def update_michelin_status(self, request, queryset):
        self._run_sources(request, queryset, [michelin_source], force=False, label="Michelin status")

    @admin.action(description="Re-fetch Michelin status (overwrite)")
    def force_update_michelin_status(self, request, queryset):
        self._run_sources(request, queryset, [michelin_source], force=True, label="Michelin status")

    def _run_sources(self, request, queryset, sources, force, label):
        updated = not_found = skipped = 0
        for restaurant in queryset.select_related("city"):
            fetched = fetch_all(Probe.from_restaurant(restaurant), sources=sources)
            if not fetched:
                not_found += 1
                continue
            fields = apply_fetched(restaurant, fetched, force=force)
            if fields:
                restaurant.save(update_fields=fields)
                updated += 1
            else:
                skipped += 1

        self.message_user(
            request,
            f"{label}: {updated} updated, {not_found} not found, {skipped} already complete.",
        )


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "color"]
    search_fields = ["name"]


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_default", "hidden"]
    list_filter = ["hidden"]
    list_editable = ["hidden"]
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = [
        (None, {"fields": ["name", "slug", "is_default", "hidden"]}),
        ("Map bounding box", {
            "fields": ["bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat"],
            "description": (
                'Look up values at <a href="http://bboxfinder.com" target="_blank">bboxfinder.com</a>. '
                "Leave blank to disable the map tab for this city."
            ),
        }),
    ]
    actions = ["fetch_tiles"]

    def save_model(self, request, obj, form, change):
        # Flip off any previous default so the partial unique constraint
        # stays satisfied when an admin user picks a new default city.
        if obj.is_default:
            City.objects.exclude(pk=obj.pk).filter(is_default=True).update(is_default=False)
        super().save_model(request, obj, form, change)

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
