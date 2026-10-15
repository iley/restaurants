from datetime import date

from django.test import TestCase
from django.urls import reverse

from restaurants.models import City, Photo, Restaurant, Visit


class RecentTests(TestCase):
    def setUp(self):
        self.city = City.objects.create(name="Dublin", slug="dublin")
        self.place = Restaurant.objects.create(
            city=self.city, name="First Place", cuisine="Irish", comments="A **lovely** meal."
        )
        self.url = reverse("recent")

    def visit(self, when, restaurant=None):
        return Visit.objects.create(restaurant=restaurant or self.place, date=when)

    def test_complete_month_batches_and_global_history(self):
        other_city = City.objects.create(name="London", slug="london")
        other = Restaurant.objects.create(city=other_city, name="London Place", cuisine="British")
        oldest = self.visit("2025-12-31")
        self.visit("2026-01-01")
        self.visit("2026-03-01")
        self.visit("2026-03-31")
        newest = self.visit("2026-04-30", other)
        response = self.client.get(self.url)
        groups = response.context["month_groups"]
        self.assertEqual([month for month, _ in groups], [date(2026, 4, 1), date(2026, 3, 1), date(2026, 1, 1)])
        self.assertEqual([len(entries) for _, entries in groups], [1, 2, 1])
        self.assertEqual(groups[0][1][0].pk, newest.pk)
        self.assertContains(response, "London Place")
        self.assertContains(response, "for the 4th time")
        self.assertNotContains(response, "lovely")
        self.assertNotContains(response, "2026-04-30")
        self.assertEqual(response.context["next_before"], "2026-01")

        older = self.client.get(self.url, {"before": "2026-01"}, HTTP_HX_REQUEST="true")
        self.assertEqual(older.context["month_groups"][0][1][0].pk, oldest.pk)
        self.assertContains(older, "<strong>lovely</strong>", html=True)
        self.assertNotContains(older, "Load 3 more months")
        self.assertNotContains(older, "<html")
        self.assertIn("HX-Request", older.headers["Vary"])
        self.assertContains(self.client.get(self.url, {"before": "2026-01"}), "<html")

    def test_same_day_order_and_photos_only_on_first_visit(self):
        first = self.visit("2026-05-12")
        second = self.visit("2026-05-12")
        # Bulk creation avoids image processing; only the rendered URLs matter here.
        Photo.objects.bulk_create([Photo(
            restaurant=self.place, image="photos/full.jpg", thumbnail="photos/thumbs/preview.jpg", caption="Dinner"
        )])
        response = self.client.get(self.url)
        entries = response.context["month_groups"][0][1]
        self.assertEqual([(v.pk, v.visit_number) for v in entries], [(second.pk, 2), (first.pk, 1)])
        self.assertContains(response, 'src="/media/photos/thumbs/preview.jpg"', count=1)
        self.assertContains(response, 'href="/media/photos/full.jpg"', count=1)
        self.assertNotContains(response, 'src="/media/photos/full.jpg"')
        self.assertContains(response, "<strong>lovely</strong>", count=1, html=True)
        self.assertContains(response, 'loading="lazy"')

    def test_hidden_places_and_cities_are_excluded(self):
        hidden_city = City.objects.create(name="Secret city", slug="secret", hidden=True)
        hidden_place = Restaurant.objects.create(city=self.city, name="Secret place", hidden=True)
        hidden_city_place = Restaurant.objects.create(city=hidden_city, name="Other secret place")
        self.visit("2026-05-01", hidden_place)
        self.visit("2026-05-01", hidden_city_place)
        response = self.client.get(self.url)
        self.assertContains(response, "No visits to show yet.")
        self.assertNotContains(response, "Secret")
        self.assertNotContains(response, "Other secret")

    def test_empty_database_and_invalid_cursors(self):
        self.assertContains(self.client.get(self.url), "No visits to show yet.")
        for cursor in ["", "garbage", "2026-13", "2026-02-01", "0000-01"]:
            with self.subTest(cursor=cursor):
                self.assertEqual(self.client.get(self.url, {"before": cursor}).status_code, 404)

    def test_ordinal_suffixes(self):
        for day in range(1, 24):
            self.visit(date(2026, 1, day))
        response = self.client.get(self.url)
        for ordinal in ["2nd", "3rd", "11th", "12th", "13th", "21st", "22nd", "23rd"]:
            self.assertContains(response, f"for the {ordinal} time")

    def test_navigation_and_bounded_query_count(self):
        for i in range(10):
            place = Restaurant.objects.create(city=self.city, name=f"Place {i}")
            self.visit("2026-05-01", place)
        with self.assertNumQueries(4):
            response = self.client.get(self.url)
        self.assertContains(response, 'aria-current="page">Recent</a>')
        response = self.client.get(reverse("restaurant_list", args=[self.city.slug]))
        self.assertContains(response, 'href="/recent/"')
