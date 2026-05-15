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
    path(
        "<slug:city_slug>/<int:pk>/edit/visits/",
        views.restaurant_visits_section,
        name="restaurant_visits_section",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/visits/add/",
        views.visit_create,
        name="visit_create",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/visits/<int:visit_pk>/",
        views.visit_edit,
        name="visit_edit",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/visits/<int:visit_pk>/delete/",
        views.visit_delete,
        name="visit_delete",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/photos/",
        views.restaurant_photos_section,
        name="restaurant_photos_section",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/photos/upload/",
        views.photo_upload,
        name="photo_upload",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/photos/reorder/",
        views.photo_reorder,
        name="photo_reorder",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/photos/<int:photo_pk>/caption/",
        views.photo_edit_caption,
        name="photo_edit_caption",
    ),
    path(
        "<slug:city_slug>/<int:pk>/edit/photos/<int:photo_pk>/delete/",
        views.photo_delete,
        name="photo_delete",
    ),
    path("<slug:city_slug>/<int:pk>/", views.restaurant_detail, name="restaurant_detail"),
    path("<slug:city_slug>/", views.restaurant_list, name="restaurant_list"),
]
