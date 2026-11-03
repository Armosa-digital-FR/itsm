"""Corrections des saisies de temps (FR-035a) : seul l'auteur d'une saisie la modifie ou la
supprime ; chaque modification est tracée dans l'historique du ticket."""

from django.core.exceptions import PermissionDenied
from django.db import transaction

from helpdesk.models import TicketEvent, TimeEntry
from helpdesk.services.lifecycle import record_event


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
