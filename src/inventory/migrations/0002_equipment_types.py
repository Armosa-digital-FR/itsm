"""Types d'équipement initiaux (FR-060), extensibles par un administrateur."""

from django.db import migrations

INITIAL_TYPES = ["PC", "Écran", "Imprimante", "Télévision", "Caméra", "Téléphone", "Tablette"]


def create_types(apps, schema_editor):
    EquipmentType = apps.get_model("inventory", "EquipmentType")
    for name in INITIAL_TYPES:
        EquipmentType.objects.get_or_create(name=name)


def remove_types(apps, schema_editor):
    apps.get_model("inventory", "EquipmentType").objects.filter(
        name__in=INITIAL_TYPES, equipment__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [migrations.RunPython(create_types, remove_types)]
