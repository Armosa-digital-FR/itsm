# Temps de traitement calculé à partir des statuts (FR-035b) ; le chronomètre disparaît.

import math

from django.db import migrations, models
from django.utils import timezone

IN_TREATMENT = "Pris en compte"  # libellé enregistré dans les événements de statut


def _calendar(apps):
    from core.business_time import Calendar

    Settings = apps.get_model("core", "Settings")
    ClosureDay = apps.get_model("core", "ClosureDay")
    conf = Settings.objects.first()
    closures = frozenset(ClosureDay.objects.values_list("date", flat=True))
    if conf is None:
        return Calendar(closures=closures)
    return Calendar(
        days=frozenset(conf.business_days),
        start=conf.business_start,
        end=conf.business_end,
        closures=closures,
    )


def backfill(apps, schema_editor):
    """Rejoue l'historique des statuts de chaque ticket pris en compte au moins une fois."""
    from core.business_time import business_seconds_between

    Ticket = apps.get_model("helpdesk", "Ticket")
    TicketEvent = apps.get_model("helpdesk", "TicketEvent")
    cal = _calendar(apps)
    for ticket in Ticket.objects.exclude(acknowledged_at=None).iterator():
        total, since = 0, None
        for event in TicketEvent.objects.filter(ticket=ticket, kind="statut").order_by("at", "id"):
            if event.new_value == IN_TREATMENT and since is None:
                since = event.at
            elif event.new_value != IN_TREATMENT and since is not None:
                total += business_seconds_between(since, event.at, cal)
                since = None
        if ticket.status == "pris_en_compte" and since is None:
            since = ticket.acknowledged_at
        ticket.treatment_seconds = total
        ticket.treatment_started_at = since if ticket.status == "pris_en_compte" else None
        ticket.save(update_fields=["treatment_seconds", "treatment_started_at"])


def save_running_timers(apps, schema_editor):
    """Les chronomètres encore actifs deviennent des saisies de temps (rien n'est perdu)."""
    RunningTimer = apps.get_model("helpdesk", "RunningTimer")
    TimeEntry = apps.get_model("helpdesk", "TimeEntry")
    now = timezone.now()
    for timer in RunningTimer.objects.all():
        minutes = max(1, math.ceil((now - timer.started_at).total_seconds() / 60))
        TimeEntry.objects.create(
            ticket_id=timer.ticket_id,
            technician_id=timer.technician_id,
            date=timezone.localdate(timer.started_at),
            minutes=min(minutes, 1440),
            comment="Chronomètre",
            source="chrono",
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_stored_file"),
        ("helpdesk", "0007_time_tracking"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="treatment_seconds",
            field=models.PositiveIntegerField(
                default=0, verbose_name="temps de traitement (secondes ouvrées)"
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="treatment_started_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="en traitement depuis"),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.RunPython(save_running_timers, migrations.RunPython.noop),
        migrations.DeleteModel(name="RunningTimer"),
    ]
