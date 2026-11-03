"""Tâches planifiées du socle (contracts/scheduled-jobs.md)."""

from procrastinate.contrib.django import app

from core.gdpr import apply_retention


@app.periodic(cron="0 3 * * *")
@app.task(name="core.gdpr_retention", queueing_lock="core.gdpr_retention")
def gdpr_retention(timestamp: int) -> dict:
    """Chaque nuit : anonymisation au-delà de la durée de conservation, purge de l'audit."""
    return apply_retention()
