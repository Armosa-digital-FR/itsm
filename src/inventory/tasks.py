"""Tâches planifiées du parc (contracts/scheduled-jobs.md)."""

from procrastinate.contrib.django import app

from core.alerts import alert_admins
from directory.models import SyncRun
from directory.services.entra_sync import consecutive_failures
from inventory.services import licences
from inventory.services.intune_sync import sync_devices

ALERT_AFTER_FAILURES = 3


@app.periodic(cron="23 * * * *")
@app.task(name="inventory.sync_intune", queueing_lock="inventory.sync_intune")
def sync_intune(timestamp: int) -> dict:
    run = sync_devices()
    if (
        run.status == SyncRun.STATUS_FAILED
        and consecutive_failures(SyncRun.KIND_INTUNE) == ALERT_AFTER_FAILURES
    ):
        alert_admins(
            "Synchronisation Intune en échec",
            f"La synchronisation des appareils Intune a échoué {ALERT_AFTER_FAILURES} fois de "
            f"suite. Dernière erreur : {run.error}",
        )
    return {
        "status": run.status,
        "created": run.created,
        "updated": run.updated,
        "removed": run.deactivated,
    }


@app.periodic(cron="0 8 * * 1")
@app.task(name="inventory.licence_digest", queueing_lock="inventory.licence_digest")
def licence_digest(timestamp: int) -> int:
    """Lundi 8 h : licences à échéance ou en dépassement, récapitulées aux administrateurs."""
    rows = list(licences.alerts_queryset().order_by("expires_at", "name"))
    if not rows:
        return 0
    lines = []
    for licence in rows:
        state = licences.licence_state(licence)
        reasons = []
        if state["over"]:
            reasons.append(f"{state['seats_used']} postes utilisés sur {licence.seats}")
        if state["expired"]:
            reasons.append(f"expirée le {licence.expires_at:%d/%m/%Y}")
        elif state["expiring"]:
            reasons.append(f"expire le {licence.expires_at:%d/%m/%Y}")
        lines.append(f"- {licence.name} : {', '.join(reasons)}")
    alert_admins("Licences à surveiller", "\n".join(lines))
    return len(rows)
