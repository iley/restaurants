from django.urls import path

from . import views

urlpatterns = [
    path("", views.index),
    path("<slug:city_slug>/<int:pk>/", views.restaurant_detail, name="restaurant_detail"),
    path("<slug:city_slug>/", views.restaurant_list, name="restaurant_list"),
]
