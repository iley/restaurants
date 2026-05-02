from django.db import migrations


def seed_default(apps, schema_editor):
    City = apps.get_model("restaurants", "City")
    if City.objects.filter(is_default=True).exists():
        return
    dublin = City.objects.filter(slug="dublin").first()
    if dublin is None:
        return
    dublin.is_default = True
    dublin.save(update_fields=["is_default"])


def unseed_default(apps, schema_editor):
    City = apps.get_model("restaurants", "City")
    City.objects.filter(is_default=True).update(is_default=False)


class Migration(migrations.Migration):

    dependencies = [
        ("restaurants", "0013_city_is_default_city_one_default_city"),
    ]

    operations = [
        migrations.RunPython(seed_default, unseed_default),
    ]
