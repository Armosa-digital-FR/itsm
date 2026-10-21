"""Écriture du journal d'audit (FR-071, constitution II)."""

from django.db import connection, transaction

from .models import AuditEntry


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record(actor, action: str, target=None, details: dict | None = None, request=None):
    """Ajoute une entrée d'audit. `target` est un objet de modèle ou un couple (type, id)."""
    if target is None:
        target_type, target_id = "", ""
    elif isinstance(target, tuple):
        target_type, target_id = target
    else:
        target_type, target_id = target._meta.label, target.pk
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    return AuditEntry.objects.create(
        actor=actor,
        action=action,
        target_type=str(target_type),
        target_id=str(target_id or ""),
        details=details or {},
        ip_address=_client_ip(request),
    )


def purge_before(cutoff) -> int:
    """Supprime les entrées antérieures à `cutoff` (rétention, research R15).

    Seul chemin autorisé par le déclencheur : la variable de session `itsm.audit_purge`.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL itsm.audit_purge = 'on'")
        deleted, _ = AuditEntry.objects.filter(at__lt=cutoff).delete()
    return deleted
