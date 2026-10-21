"""Chronomètre et corrections du temps passé (FR-035a).

Un seul chronomètre actif par technicien ; l'arrêt crée une saisie de temps (source
« chrono ») que son auteur peut ensuite corriger ou supprimer.
"""

import math
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.dispatch import receiver
from django.utils import timezone

from helpdesk.models import RunningTimer, Ticket, TicketEvent, TimeEntry
from helpdesk.services.lifecycle import record_event
from helpdesk.services.tickets import add_time
from helpdesk.signals import ticket_status_changed

MAX_MINUTES = 1440


@dataclass
class Stopped:
    entry: TimeEntry
    capped: bool  # durée réelle supérieure à 24 h : à vérifier


def running_timer(technician) -> RunningTimer | None:
    return RunningTimer.objects.filter(technician=technician).select_related("ticket").first()


def elapsed_minutes(started_at, now=None) -> int:
    seconds = ((now or timezone.now()) - started_at).total_seconds()
    return max(1, math.ceil(seconds / 60))


@transaction.atomic
def stop(technician, now=None) -> Stopped | None:
    timer = RunningTimer.objects.select_for_update().filter(technician=technician).first()
    if timer is None:
        return None
    minutes = elapsed_minutes(timer.started_at, now)
    entry = add_time(
        timer.ticket,
        technician,
        timezone.localdate(timer.started_at),
        min(minutes, MAX_MINUTES),
        "Chronomètre",
        source=TimeEntry.Source.CHRONO,
    )
    timer.delete()
    return Stopped(entry, capped=minutes > MAX_MINUTES)


@transaction.atomic
def start(ticket: Ticket, technician) -> tuple[RunningTimer, Stopped | None]:
    """Démarre le chronomètre ; un chronomètre actif sur un autre ticket est arrêté et
    enregistré."""
    current = RunningTimer.objects.select_for_update().filter(technician=technician).first()
    if current is not None and current.ticket_id == ticket.pk:
        return current, None
    previous = stop(technician) if current is not None else None
    return RunningTimer.objects.create(technician=technician, ticket=ticket), previous


def _check_author(entry: TimeEntry, actor) -> None:
    if entry.technician_id != getattr(actor, "pk", None):
        raise PermissionDenied("Seul l'auteur d'une saisie de temps peut la modifier.")


@transaction.atomic
def edit_time(entry: TimeEntry, actor, *, minutes: int, comment: str, day) -> TimeEntry:
    _check_author(entry, actor)
    old = f"{entry.minutes} min"
    entry.minutes, entry.comment, entry.date = minutes, (comment or "")[:500], day
    entry.full_clean()
    entry.save()
    record_event(
        entry.ticket, TicketEvent.Kind.TEMPS, actor, old, f"{minutes} min (corrigé)", entry=entry.pk
    )
    return entry


@transaction.atomic
def delete_time(entry: TimeEntry, actor) -> None:
    _check_author(entry, actor)
    record_event(
        entry.ticket,
        TicketEvent.Kind.TEMPS,
        actor,
        f"{entry.minutes} min",
        "supprimé",
        entry=entry.pk,
    )
    entry.delete()


@receiver(ticket_status_changed, dispatch_uid="helpdesk_stop_timer_on_resolution")
def stop_timer_on_resolution(sender, ticket, old, new, actor=None, **kwargs):
    """Résoudre un ticket arrête le chronomètre que son auteur y faisait tourner."""
    if new != Ticket.Status.RESOLU or actor is None or not getattr(actor, "pk", None):
        return
    if RunningTimer.objects.filter(technician=actor, ticket=ticket).exists():
        stop(actor)
