from django.shortcuts import get_object_or_404, redirect, render

from .models import City, Restaurant

DEFAULT_CITY_SLUG = "dublin"


def index(request):
    return redirect("restaurant_list", city_slug=DEFAULT_CITY_SLUG)


def restaurant_list(request, city_slug):
    city = get_object_or_404(City, slug=city_slug)
    base_qs = Restaurant.objects.filter(city=city)
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

    context = {
        "city": city,
        "restaurants": restaurants,
        "cities": City.objects.all(),
        "cuisines": cuisines,
        "venue_categories": Restaurant.VenueCategory.choices,
        "michelin_statuses": [
            (value, label)
            for value, label in Restaurant.MichelinStatus.choices
            if value != Restaurant.MichelinStatus.NONE
        ],
        "rating_tiers": rating_tier_choices,
        "filters": filters,
    }

    if request.headers.get("HX-Request"):
        return render(request, "restaurants/_restaurant_table.html", context)
    return render(request, "restaurants/restaurant_list.html", context)
