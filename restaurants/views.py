from urllib.parse import urlencode

from django.db import models
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import City, Restaurant

DEFAULT_CITY_SLUG = "dublin"
DEFAULT_SORT = "-rating,name"

# Single source of truth for sortable columns: order, labels, default direction.
SORT_COLUMNS = [
    {"field": "name", "label": "Name", "default_dir": "asc"},
    {"field": "rating", "label": "My Rating", "default_dir": "desc"},
    {"field": "cuisine", "label": "Cuisine", "default_dir": "asc"},
    {"field": "venue_category", "label": "Type", "default_dir": "asc"},
    {"field": "michelin_status", "label": "Michelin", "default_dir": "desc"},
]
_SORTABLE_FIELDS = {col["field"] for col in SORT_COLUMNS}

# Michelin status has no natural DB ordering — map to numeric rank.
_MICHELIN_RANK = Case(
    *(
        When(michelin_status=choice.value, then=Value(i))
        for i, choice in enumerate(Restaurant.MichelinStatus)
    ),
    output_field=IntegerField(),
)

# Rating tiers: sort by tier, not by raw numeric rating (which is internal).
_RATING_TIER_RANK = Case(
    *(
        When(rating__gte=tier["range"][0], rating__lte=tier["range"][1], then=Value(-i))
        for i, tier in enumerate(Restaurant.RATING_TIERS.values())
    ),
    output_field=IntegerField(),
)

_TEXT_FIELDS = {"name", "cuisine", "venue_category"}


def index(request):
    return redirect("restaurant_list", city_slug=DEFAULT_CITY_SLUG)


def restaurant_detail(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug)
    restaurant = get_object_or_404(
        Restaurant.objects.prefetch_related("visits", "photos", "tags"),
        pk=pk,
        city=city,
        hidden=False,
    )
    visits = restaurant.visits.order_by("date")
    has_notes = any(v.notes for v in visits)
    return render(request, "restaurants/restaurant_detail.html", {
        "restaurant": restaurant,
        "city": city,
        "cities": City.objects.all(),
        "visits": visits,
        "has_notes": has_notes,
    })


def restaurant_list(request, city_slug):
    city = get_object_or_404(City, slug=city_slug)
    base_qs = Restaurant.objects.filter(city=city, hidden=False).prefetch_related("tags")
    restaurants = base_qs

    # Read filters from query params
    cuisine = request.GET.get("cuisine", "")
    venue_category = request.GET.get("venue_category", "")
    michelin_status = request.GET.get("michelin_status", "")
    rating_tier = request.GET.get("rating_tier", "")

    if cuisine:
        restaurants = restaurants.filter(cuisine=cuisine)
    if venue_category:
        restaurants = restaurants.filter(venue_category=venue_category)
    if michelin_status:
        restaurants = restaurants.filter(michelin_status=michelin_status)
    if rating_tier and rating_tier in Restaurant.RATING_TIERS:
        lo, hi = Restaurant.RATING_TIERS[rating_tier]["range"]
        restaurants = restaurants.filter(rating__gte=lo, rating__lte=hi)

    # Sorting
    sort_param = request.GET.get("sort", DEFAULT_SORT)
    current_sort = _parse_sort(sort_param) or _parse_sort(DEFAULT_SORT)

    order_by_args = []
    for f, d in current_sort:
        if f == "michelin_status":
            expr = _MICHELIN_RANK
        elif f == "rating":
            expr = _RATING_TIER_RANK
        elif f in _TEXT_FIELDS:
            expr = Lower(f)
        else:
            expr = models.F(f)
        order_by_args.append(expr.desc() if d == "desc" else expr.asc())
    restaurants = restaurants.order_by(*order_by_args)

    cuisines = base_qs.values_list("cuisine", flat=True).distinct().order_by("cuisine")

    rating_tier_choices = {
        key: tier["label"] for key, tier in Restaurant.RATING_TIERS.items()
    }

    filters = {
        "cuisine": cuisine,
        "venue_category": venue_category,
        "michelin_status": michelin_status,
        "rating_tier": rating_tier,
    }

    # Build sort header links (preserve current filters in each link)
    filter_params = {k: v for k, v in filters.items() if v}
    base_url = reverse("restaurant_list", kwargs={"city_slug": city.slug})
    sort_headers = _build_sort_headers(current_sort, filter_params, base_url)

    is_htmx = request.headers.get("HX-Request") == "true"

    context = {
        "city": city,
        "restaurants": restaurants,
        "cities": City.objects.all(),
        "cuisines": cuisines,
        "venue_categories": Restaurant.VenueCategory.choices,
        "michelin_statuses": [
            (value, "No designation" if value == Restaurant.MichelinStatus.NONE else label)
            for value, label in Restaurant.MichelinStatus.choices
        ],
        "rating_tiers": rating_tier_choices,
        "filters": filters,
        "sort_headers": sort_headers,
        "current_sort_param": _sort_to_param(current_sort),
        "is_htmx": is_htmx,
    }

    if is_htmx:
        return render(request, "restaurants/_restaurant_table.html", context)
    return render(request, "restaurants/restaurant_list.html", context)


# -- sorting helpers --


def _parse_sort(sort_param):
    """Parse a comma-separated sort string into [(field, 'asc'|'desc'), ...]."""
    result = []
    seen = set()
    for part in sort_param.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("-"):
            field, direction = part[1:], "desc"
        else:
            field, direction = part, "asc"
        if field in _SORTABLE_FIELDS and field not in seen:
            result.append((field, direction))
            seen.add(field)
    return result


def _sort_to_param(sort_list):
    """Convert [(field, direction), ...] back to a comma-separated string."""
    return ",".join(f"-{f}" if d == "desc" else f for f, d in sort_list)


def _build_sort_headers(current_sort, filter_params, base_url):
    """For each sortable column, compute the URL and indicator state."""
    headers = []
    for col in SORT_COLUMNS:
        field = col["field"]
        is_primary = bool(current_sort) and current_sort[0][0] == field
        if is_primary:
            new_dir = "asc" if current_sort[0][1] == "desc" else "desc"
            new_sort = [(field, new_dir)] + [
                (f, d) for f, d in current_sort[1:] if f != field
            ]
        else:
            new_sort = [(field, col["default_dir"])] + [
                (f, d) for f, d in current_sort if f != field
            ]

        params = {**filter_params, "sort": _sort_to_param(new_sort)}
        headers.append({
            "label": col["label"],
            "url": f"{base_url}?{urlencode(params)}",
            "is_primary": is_primary,
            "direction": current_sort[0][1] if is_primary else None,
        })
    return headers
