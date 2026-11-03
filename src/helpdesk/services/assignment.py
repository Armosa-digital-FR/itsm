"""Affectation automatique selon les compétences (US2, FR-021 à FR-023, data-model.md).

Exécutée quand l'outil d'un ticket est renseigné ou modifié, si le ticket est « créé » et
qu'il n'a pas été réaffecté à la main :

1. C = techniciens actifs compétents sur l'outil ;
2. |C| = 1 → ce technicien ;
3. sinon, si l'outil a un groupe compétent → ce groupe ;
4. sinon, si |C| ≥ 2 → le moins chargé (tickets ouverts), puis le moins récemment affecté ;
5. sinon → aucune affectation (file de dispatch).
"""

from datetime import UTC, datetime

from django.db.models import BigIntegerField, Count, Max, OuterRef, Q, Subquery, Value
from django.db.models.fields.json import KT
from django.db.models.functions import Cast, Coalesce
from django.dispatch import receiver

from directory.models import Account
from helpdesk.models import Ticket, TicketEvent, Tool
from helpdesk.services.lifecycle import record_event
from helpdesk.signals import ticket_qualified

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def competent_technicians(tool: Tool):
    return Account.objects.filter(is_active=True, skills__tool=tool).exclude(roles=[]).distinct()


def pick_least_loaded(candidates):
    """Moins de tickets ouverts, puis affecté le moins récemment, puis identifiant."""
    last_assigned = (
        TicketEvent.objects.filter(kind=TicketEvent.Kind.AFFECTATION)
        .annotate(assignee_pk=Cast(KT("data__assignee"), BigIntegerField()))
        .filter(assignee_pk=OuterRef("pk"))
        .order_by()
        .values("assignee_pk")
        .annotate(last=Max("at"))
        .values("last")
    )
    return (
        candidates.annotate(
            open_tickets=Count(
                "assigned_tickets",
                filter=Q(assigned_tickets__status__in=Ticket.OPEN_STATUSES),
                distinct=True,
            ),
            last_assigned=Coalesce(Subquery(last_assigned), Value(EPOCH)),
        )
        .order_by("open_tickets", "last_assigned", "pk")
        .first()
    )


def _label(ticket: Ticket) -> str:
    parts = []
    if ticket.assignee_id:
        parts.append(ticket.assignee.display_name)
    if ticket.assigned_group_id:
        parts.append(f"groupe {ticket.assigned_group.name}")
    return " · ".join(parts)


def auto_assign(ticket: Ticket) -> bool:
    """Applique la règle ; renvoie vrai si l'affectation a changé."""
    if ticket.status != Ticket.Status.CREE:
        return False
    if ticket.assignment_mode == Ticket.AssignmentMode.MANUEL:
        return False

    assignee = group = None
    if ticket.tool_id:
        candidates = competent_technicians(ticket.tool)
        count = candidates.count()
        if count == 1:
            assignee = candidates.first()
        elif ticket.tool.default_group_id:
            group = ticket.tool.default_group
        elif count >= 2:
            assignee = pick_least_loaded(candidates)

    previous_auto = ticket.assignment_mode == Ticket.AssignmentMode.AUTO
    if assignee is None and group is None and not previous_auto:
        return False  # étape 5 : rien à défaire, le ticket reste dans la file de dispatch
    if (ticket.assignee_id, ticket.assigned_group_id) == (
        getattr(assignee, "pk", None),
        getattr(group, "pk", None),
    ):
        return False

    old = _label(ticket)
    ticket.assignee, ticket.assigned_group = assignee, group
    ticket.assignment_mode = (
        Ticket.AssignmentMode.AUTO if (assignee or group) else Ticket.AssignmentMode.AUCUN
    )
    ticket.save(update_fields=["assignee", "assigned_group", "assignment_mode", "updated_at"])
    record_event(
        ticket,
        TicketEvent.Kind.AFFECTATION,
        None,
        old,
        _label(ticket) or "file de dispatch",
        mode="auto",
        assignee=getattr(assignee, "pk", None),
        group=getattr(group, "pk", None),
        tool=ticket.tool_id,
    )
    return True


@receiver(ticket_qualified, dispatch_uid="helpdesk_auto_assign")
def on_ticket_qualified(sender, ticket, actor=None, changed=(), **kwargs):
    if "tool" in changed:
        auto_assign(ticket)
