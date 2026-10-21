from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory"
    verbose_name = "Parc"

    def ready(self):
        from core.dashboard import register_section
        from directory.registry import register_person_block, register_sync

        from . import receivers  # noqa: F401
        from .dashboard import inventory_dashboard
        from .services.intune_sync import sync_devices

        register_sync("intune_devices", "Appareils Intune", sync_devices)
        register_section("parc", "Parc", "inventory/dashboard.html", inventory_dashboard, 20)
        register_person_block("inventory/person_equipment.html", person_equipment, order=20)


def person_equipment(person) -> dict:
    from .models import Equipment
    from .services.licences import with_usage

    return {
        "equipment": list(
            Equipment.objects.filter(assigned_to=person)
            .select_related("type", "site")
            .order_by("type__name", "name")
        ),
        "licences": list(with_usage(person.licences.all()).order_by("name")),
    }
