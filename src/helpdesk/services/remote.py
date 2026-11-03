"""Déclaration des interventions TeamViewer (US7, FR-050, FR-071).

Aucune intégration TeamViewer : la déclaration crée une trace dans le ticket et dans le
journal d'audit.
"""

from django.db import transaction
from django.utils import timezone

from core import audit
from helpdesk.models import RemoteSession, Ticket, TicketEvent
from helpdesk.services.lifecycle import record_event


@transaction.atomic
def declare(
    ticket: Ticket, technician, equipment, started_at, ended_at, comment: str = "", request=None
) -> RemoteSession:
    session = RemoteSession(
        ticket=ticket,
        technician=technician,
        equipment=equipment,
        started_at=started_at,
        ended_at=ended_at,
        comment=(comment or "")[:500],
    )
    session.full_clean()
    session.save()
    start, end = timezone.localtime(started_at), timezone.localtime(ended_at)
    record_event(
        ticket,
        TicketEvent.Kind.PRISE_EN_MAIN,
        technician,
        "",
        f"{equipment} · {start:%d/%m %H:%M}–{end:%H:%M} ({session.minutes} min)",
        session=session.pk,
        equipment=equipment.pk,
    )
    audit.record(
        technician,
        "remote_session.declare",
        session,
        {
            "ticket": ticket.reference,
            "equipment": equipment.pk,
            "teamviewer_id": equipment.teamviewer_id,
            "minutes": session.minutes,
        },
        request=request,
    )
    return session
