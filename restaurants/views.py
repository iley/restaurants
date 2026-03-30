from django.shortcuts import get_object_or_404, redirect, render

from .models import City, Restaurant

DEFAULT_CITY_SLUG = "dublin"


def index(request):
    return redirect("restaurant_list", city_slug=DEFAULT_CITY_SLUG)


def restaurant_list(request, city_slug):
    city = get_object_or_404(City, slug=city_slug)
    restaurants = Restaurant.objects.filter(city=city)
    cities = City.objects.all()
    return render(request, "restaurants/restaurant_list.html", {
        "city": city,
        "restaurants": restaurants,
        "cities": cities,
    })
