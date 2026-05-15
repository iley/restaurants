import json
from urllib.parse import urlencode

from django.contrib.admin.views.decorators import staff_member_required
from django.db import models
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import CommentsForm, PhotoCaptionForm, PhotoForm, RatingForm, VisitForm
from .models import City, Photo, Restaurant, Visit

DEFAULT_SORT = "-rating,name"

# Defaults for the visibility checkboxes. The template emits these as data-default
# attributes so the URL-cleanup JS doesn't redeclare the same policy.
DEFAULT_SHOW_VISITED = True
DEFAULT_SHOW_WISHLIST = False

# Single source of truth for sortable columns: order, labels, default direction.
# `field` is the URL-facing name; `db` is the underlying model field (defaults to `field`).
SORT_COLUMNS = [
    {"field": "name", "label": "Name", "default_dir": "asc"},
    {"field": "rating", "label": "My Rating", "default_dir": "desc"},
    {"field": "cuisine", "label": "Cuisine", "default_dir": "asc"},
    {"field": "type", "db": "venue_category", "label": "Type", "default_dir": "asc"},
    {"field": "michelin", "db": "michelin_status", "label": "Michelin", "default_dir": "desc"},
]
_SORTABLE_FIELDS = {col["field"] for col in SORT_COLUMNS}
_SORT_DB_FIELD = {col["field"]: col.get("db", col["field"]) for col in SORT_COLUMNS}

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

_TEXT_SORT_FIELDS = {"name", "cuisine", "type"}


def _parse_checkbox_param(request, name, default):
    raw = request.GET.get(name)
    if raw is None:
        return default
    return raw == "1"


def _michelin_filter_choices():
    """Dropdown choices: each tier means "this level or higher" (e.g. "1 Star +")."""
    tiers = [
        (value, label) for value, label in Restaurant.MichelinStatus.choices
        if value != Restaurant.MichelinStatus.NONE
    ]
    last = len(tiers) - 1
    return [
        (value, label if i == last else f"{label} +")
        for i, (value, label) in enumerate(tiers)
    ]


def index(request):
    visible = City.objects.filter(hidden=False)
    city = visible.filter(is_default=True).first() or visible.first()
    if city is None:
        raise Http404("No cities configured")
    return redirect("restaurant_list", city_slug=city.slug)


def restaurant_detail(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
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
        "cities": City.objects.filter(hidden=False),
        "visits": visits,
        "has_notes": has_notes,
    })


@staff_member_required
def restaurant_edit(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    return render(request, "restaurants/restaurant_edit.html", {
        "restaurant": restaurant,
        "city": city,
        "cities": City.objects.filter(hidden=False),
        "rating_form": RatingForm(instance=restaurant),
        "comments_form": CommentsForm(instance=restaurant),
        "visits": restaurant.visits.all(),
        "add_form": VisitForm(),
        "photos": restaurant.photos.all(),
        "photo_form": PhotoForm(),
    })


@staff_member_required
@require_POST
def restaurant_toggle_pinned(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    restaurant.pinned = not restaurant.pinned
    restaurant.save(update_fields=["pinned"])
    return render(request, "restaurants/_pinned_toggle.html", {
        "restaurant": restaurant,
        "city": city,
    })


@staff_member_required
def restaurant_edit_rating(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    saved = False
    if request.method == "POST":
        form = RatingForm(request.POST, instance=restaurant)
        if form.is_valid():
            form.save()
            saved = True
    else:
        form = RatingForm(instance=restaurant)
    return render(request, "restaurants/_rating_form.html", {
        "restaurant": restaurant,
        "city": city,
        "form": form,
        "saved": saved,
    })


@staff_member_required
def restaurant_edit_comments(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    saved = False
    if request.method == "POST":
        form = CommentsForm(request.POST, instance=restaurant)
        if form.is_valid():
            form.save()
            saved = True
    else:
        form = CommentsForm(instance=restaurant)
    return render(request, "restaurants/_comments_form.html", {
        "restaurant": restaurant,
        "city": city,
        "form": form,
        "saved": saved,
    })


def _render_visits_section(request, city, restaurant, add_form=None):
    return render(request, "restaurants/_visits_section.html", {
        "city": city,
        "restaurant": restaurant,
        "visits": restaurant.visits.all(),
        "add_form": add_form or VisitForm(),
    })


@staff_member_required
def restaurant_visits_section(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    return _render_visits_section(request, city, restaurant)


@staff_member_required
@require_POST
def visit_create(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    form = VisitForm(request.POST)
    if form.is_valid():
        visit = form.save(commit=False)
        visit.restaurant = restaurant
        visit.save()
        return _render_visits_section(request, city, restaurant)
    return _render_visits_section(request, city, restaurant, add_form=form)


@staff_member_required
def visit_edit(request, city_slug, pk, visit_pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    visit = get_object_or_404(Visit, pk=visit_pk, restaurant=restaurant)
    if request.method == "POST":
        form = VisitForm(request.POST, instance=visit)
        if form.is_valid():
            form.save()
            return render(request, "restaurants/_visit_row.html", {
                "city": city,
                "restaurant": restaurant,
                "visit": visit,
            })
    else:
        form = VisitForm(instance=visit)
    return render(request, "restaurants/_visit_edit_row.html", {
        "city": city,
        "restaurant": restaurant,
        "visit": visit,
        "form": form,
    })


@staff_member_required
@require_POST
def visit_delete(request, city_slug, pk, visit_pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    visit = get_object_or_404(Visit, pk=visit_pk, restaurant=restaurant)
    visit.delete()
    return _render_visits_section(request, city, restaurant)


def _render_photos_section(request, city, restaurant, photo_form=None):
    return render(request, "restaurants/_photos_section.html", {
        "city": city,
        "restaurant": restaurant,
        "photos": restaurant.photos.all(),
        "photo_form": photo_form or PhotoForm(),
    })


@staff_member_required
def restaurant_photos_section(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    return _render_photos_section(request, city, restaurant)


@staff_member_required
@require_POST
def photo_upload(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    files = request.FILES.getlist("image")
    # Caption only applies to single-file uploads; bulk drops set captions later
    # via the per-card "Edit caption" button.
    caption = request.POST.get("caption", "") if len(files) <= 1 else ""

    last = restaurant.photos.aggregate(models.Max("order"))["order__max"]
    next_order = 0 if last is None else last + 1

    # Validate each file through PhotoForm so ImageField rejects non-images.
    # Save the valid ones; if every file is invalid, re-render with the form's
    # errors so the user sees a message.
    last_invalid_form = None
    saved_any = False
    for f in files:
        form = PhotoForm({"caption": caption}, {"image": f})
        if form.is_valid():
            photo = form.save(commit=False)
            photo.restaurant = restaurant
            photo.order = next_order
            photo.save()
            next_order += 1
            saved_any = True
        else:
            last_invalid_form = form

    if not saved_any and last_invalid_form is not None:
        return _render_photos_section(request, city, restaurant, photo_form=last_invalid_form)
    return _render_photos_section(request, city, restaurant)


@staff_member_required
def photo_edit_caption(request, city_slug, pk, photo_pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    photo = get_object_or_404(Photo, pk=photo_pk, restaurant=restaurant)
    if request.method == "POST":
        form = PhotoCaptionForm(request.POST, instance=photo)
        if form.is_valid():
            form.save()
            return render(request, "restaurants/_photo_card.html", {
                "city": city,
                "restaurant": restaurant,
                "photo": photo,
            })
    else:
        form = PhotoCaptionForm(instance=photo)
    return render(request, "restaurants/_photo_caption_form.html", {
        "city": city,
        "restaurant": restaurant,
        "photo": photo,
        "form": form,
    })


@staff_member_required
@require_POST
def photo_delete(request, city_slug, pk, photo_pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    photo = get_object_or_404(Photo, pk=photo_pk, restaurant=restaurant)
    # Django doesn't auto-delete ImageField files; remove them so disk doesn't leak.
    if photo.image:
        photo.image.delete(save=False)
    if photo.thumbnail:
        photo.thumbnail.delete(save=False)
    photo.delete()
    return _render_photos_section(request, city, restaurant)


@staff_member_required
@require_POST
def photo_reorder(request, city_slug, pk):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    restaurant = get_object_or_404(Restaurant, pk=pk, city=city, hidden=False)
    raw_ids = request.POST.getlist("photo_ids")
    # Only consider ids that belong to this restaurant — silently drop strangers.
    valid_ids = set(restaurant.photos.values_list("pk", flat=True))
    for index, raw in enumerate(raw_ids):
        try:
            photo_id = int(raw)
        except (TypeError, ValueError):
            continue
        if photo_id in valid_ids:
            Photo.objects.filter(pk=photo_id, restaurant=restaurant).update(order=index)
    return _render_photos_section(request, city, restaurant)


def restaurant_list(request, city_slug):
    city = get_object_or_404(City, slug=city_slug, hidden=False)
    base_qs = Restaurant.objects.filter(city=city, hidden=False).prefetch_related("tags")
    restaurants = base_qs

    # Read filters from query params
    cuisine = request.GET.get("cuisine", "")
    venue_category = request.GET.get("type", "")
    michelin_status = request.GET.get("michelin", "")
    rating_tier = request.GET.get("rating", "")

    # Visibility checkboxes: visited (rating set) vs wishlist (rating null).
    # Absent params apply the defaults; "1"/"0" override.
    show_visited = _parse_checkbox_param(request, "visited", DEFAULT_SHOW_VISITED)
    show_wishlist = _parse_checkbox_param(request, "wishlist", DEFAULT_SHOW_WISHLIST)

    if show_visited and not show_wishlist:
        restaurants = restaurants.filter(rating__isnull=False)
    elif show_wishlist and not show_visited:
        restaurants = restaurants.filter(rating__isnull=True)
    elif not show_visited and not show_wishlist:
        restaurants = restaurants.none()

    if cuisine:
        restaurants = restaurants.filter(cuisine=cuisine)
    if venue_category:
        restaurants = restaurants.filter(venue_category=venue_category)
    if michelin_status:
        # "Tier or higher": include the selected status and every more prestigious one.
        ranks = [v for v, _ in Restaurant.MichelinStatus.choices]
        if michelin_status in ranks:
            restaurants = restaurants.filter(michelin_status__in=ranks[ranks.index(michelin_status):])
    if rating_tier and rating_tier in Restaurant.RATING_TIERS:
        lo, hi = Restaurant.RATING_TIERS[rating_tier]["range"]
        restaurants = restaurants.filter(rating__gte=lo, rating__lte=hi)

    # Sorting
    sort_param = request.GET.get("sort", DEFAULT_SORT)
    current_sort = _parse_sort(sort_param) or _parse_sort(DEFAULT_SORT)

    # Pinned rows always float to the top, regardless of the user's chosen sort.
    order_by_args = ["-pinned"]
    for f, d in current_sort:
        if f == "michelin":
            expr = _MICHELIN_RANK
        elif f == "rating":
            expr = _RATING_TIER_RANK
        elif f in _TEXT_SORT_FIELDS:
            expr = Lower(_SORT_DB_FIELD[f])
        else:
            expr = models.F(_SORT_DB_FIELD[f])
        order_by_args.append(expr.desc() if d == "desc" else expr.asc())
    restaurants = restaurants.order_by(*order_by_args)

    cuisines = base_qs.values_list("cuisine", flat=True).distinct().order_by("cuisine")

    rating_tier_choices = {
        key: tier["label"] for key, tier in Restaurant.RATING_TIERS.items()
    }

    filters = {
        "cuisine": cuisine,
        "type": venue_category,
        "michelin": michelin_status,
        "rating": rating_tier,
    }

    # Build sort header links (preserve current filters in each link).
    # Only carry visibility params when they differ from defaults — keeps URLs short.
    filter_params = {k: v for k, v in filters.items() if v}
    if show_visited != DEFAULT_SHOW_VISITED:
        filter_params["visited"] = "1" if show_visited else "0"
    if show_wishlist != DEFAULT_SHOW_WISHLIST:
        filter_params["wishlist"] = "1" if show_wishlist else "0"
    base_url = reverse("restaurant_list", kwargs={"city_slug": city.slug})
    sort_headers = _build_sort_headers(current_sort, filter_params, base_url)

    view_mode = request.GET.get("view", "list")
    is_htmx = request.headers.get("HX-Request") == "true"

    # Serialize restaurant coordinates for the map.
    # `rating` is null for wishlist entries; the map renders those with a distinct color.
    restaurants_json = json.dumps([
        {
            "id": r.pk,
            "name": r.name,
            "cuisine": r.cuisine,
            "latitude": float(r.latitude),
            "longitude": float(r.longitude),
            "rating": r.rating,
            "url": reverse("restaurant_detail", kwargs={"city_slug": city.slug, "pk": r.pk}),
        }
        for r in restaurants
        if r.latitude is not None and r.longitude is not None
    ])

    context = {
        "city": city,
        "restaurants": restaurants,
        "cities": City.objects.filter(hidden=False),
        "cuisines": cuisines,
        "venue_categories": Restaurant.VenueCategory.choices,
        "michelin_statuses": _michelin_filter_choices(),
        "rating_tiers": rating_tier_choices,
        "filters": filters,
        "show_visited": show_visited,
        "show_wishlist": show_wishlist,
        "sort_headers": sort_headers,
        "current_sort_param": _sort_to_param(current_sort),
        "default_sort_param": DEFAULT_SORT,
        "default_show_visited": "1" if DEFAULT_SHOW_VISITED else "0",
        "default_show_wishlist": "1" if DEFAULT_SHOW_WISHLIST else "0",
        "is_htmx": is_htmx,
        "view_mode": view_mode,
        "restaurants_json": restaurants_json,
    }

    if is_htmx:
        template = "restaurants/_restaurant_map.html" if view_mode == "map" else "restaurants/_restaurant_table.html"
        return render(request, template, context)
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

        params = dict(filter_params)
        sort_str = _sort_to_param(new_sort)
        if sort_str != DEFAULT_SORT:
            params["sort"] = sort_str
        qs = urlencode(params)
        headers.append({
            "label": col["label"],
            "url": f"{base_url}?{qs}" if qs else base_url,
            "is_primary": is_primary,
            "direction": current_sort[0][1] if is_primary else None,
        })
    return headers
