from django.urls import path

from . import views

urlpatterns = [
    path("", views.index),
    path("<slug:city_slug>/<int:pk>/edit/", views.restaurant_edit, name="restaurant_edit"),
    path(
        "<slug:city_slug>/<int:pk>/edit/pinned/",
        views.restaurant_toggle_pinned,
        name="restaurant_toggle_pinned",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/rating/",
        views.restaurant_edit_rating,
        name="restaurant_edit_rating",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/comments/",
        views.restaurant_edit_comments,
        name="restaurant_edit_comments",
    ),
    path("<slug:city_slug>/<int:pk>/", views.restaurant_detail, name="restaurant_detail"),
    path("<slug:city_slug>/", views.restaurant_list, name="restaurant_list"),
]
