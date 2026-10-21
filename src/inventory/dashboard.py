"""Section « Parc » de l'accueil (FR-081, T111)."""

from django.db.models import Count, Q
from django.urls import reverse

from inventory.models import Equipment
from inventory.services import licences


def inventory_dashboard(request) -> dict:
    E = Equipment.Status
    counts = Equipment.objects.aggregate(
        total=Count("pk"),
        en_utilisation=Count("pk", filter=Q(status=E.EN_UTILISATION)),
        stock=Count("pk", filter=Q(status=E.STOCK)),
        retires=Count("pk", filter=Q(intune_removed_at__isnull=False)),
        intune=Count("pk", filter=Q(source=Equipment.Source.INTUNE)),
    )
    stock_by_site = list(
        Equipment.objects.filter(status=E.STOCK)
        .values("site__name", "type__name")
        .annotate(count=Count("pk"))
        .order_by("site__name", "type__name")
    )
    licence_alerts = list(licences.alerts_queryset().order_by("expires_at", "name")[:5])
    for licence in licence_alerts:
        licence.state = licences.licence_state(licence)
    base = reverse("inventory:equipment_list")
    kpis = [
        ("Équipements", counts["total"], base, ""),
        ("En utilisation", counts["en_utilisation"], f"{base}?status=en_utilisation", ""),
        ("En stock", counts["stock"], f"{base}?status=stock", ""),
        (
            "Retirés d'Intune",
            counts["retires"],
            f"{base}?retire=on",
            "danger" if counts["retires"] else "",
        ),
        (
            "Licences à surveiller",
            licences.alerts_queryset().count(),
            reverse("inventory:licence_list"),
            "",
        ),
    ]
    return {
        "kpis": kpis,
        "stock_by_site": stock_by_site,
        "licence_alerts": licence_alerts,
        "counts": counts,
    }
