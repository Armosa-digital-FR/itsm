"""Licences : postes consommés, dépassements, expirations (FR-064)."""

from datetime import timedelta

from django.db.models import Count, F, Q
from django.utils import timezone

from core.models import Settings
from inventory.models import Licence


def with_usage(queryset=None):
    """Annoté de `seats_used` (utilisateurs + équipements) et `over_allocated`."""
    queryset = queryset if queryset is not None else Licence.objects.all()
    return queryset.annotate(
        users_count=Count("assigned_users", distinct=True),
        equipment_count=Count("assigned_equipment", distinct=True),
    ).annotate(seats_used=F("users_count") + F("equipment_count"))


def seats_used(licence: Licence) -> int:
    return licence.assigned_users.count() + licence.assigned_equipment.count()


def is_over_allocated(licence: Licence) -> bool:
    return seats_used(licence) > licence.seats


def expiry_limit(days: int | None = None):
    days = Settings.load().licence_expiry_warning_days if days is None else days
    return timezone.localdate() + timedelta(days=days)


def expiring_soon(days: int | None = None):
    return Licence.objects.filter(expires_at__isnull=False, expires_at__lte=expiry_limit(days))


def over_allocated():
    return with_usage().filter(seats_used__gt=F("seats"))


def licence_state(licence: Licence, limit=None) -> dict:
    """Pour l'affichage : expirée, expire bientôt, dépassement."""
    limit = limit or expiry_limit()
    used = getattr(licence, "seats_used", None)
    used = seats_used(licence) if used is None else used
    today = timezone.localdate()
    return {
        "seats_used": used,
        "over": used > licence.seats,
        "expired": bool(licence.expires_at and licence.expires_at < today),
        "expiring": bool(licence.expires_at and today <= licence.expires_at <= limit),
    }


def alerts_queryset():
    return with_usage().filter(
        Q(seats_used__gt=F("seats")) | Q(expires_at__isnull=False, expires_at__lte=expiry_limit())
    )
