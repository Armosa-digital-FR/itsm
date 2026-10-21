"""Section « Tickets » de l'accueil (FR-081)."""

from datetime import timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .models import Ticket

S = Ticket.Status
IN_PROGRESS = [S.PRIS_EN_COMPTE, S.ATTENTE_REPONSE, S.EN_ATTENTE]


def tickets_dashboard(request) -> dict:
    now = timezone.localtime()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    open_q = Q(status__in=Ticket.OPEN_STATUSES)
    counts = Ticket.objects.aggregate(
        a_traiter=Count("pk", filter=Q(status=S.CREE)),
        en_cours=Count("pk", filter=Q(status__in=IN_PROGRESS)),
        attente_reponse=Count("pk", filter=Q(status=S.ATTENTE_REPONSE)),
        non_affectes=Count(
            "pk", filter=open_q & Q(assignee__isnull=True, assigned_group__isnull=True)
        ),
        depasses=Count("pk", filter=open_q & Q(ack_breached=True)),
        mes_tickets=Count("pk", filter=open_q & Q(assignee=request.user)),
        nouvelles_reponses=Count(
            "pk", filter=open_q & Q(assignee=request.user, has_unread_reply=True)
        ),
        resolus_semaine=Count("pk", filter=Q(resolved_at__gte=week_start)),
        haute=Count("pk", filter=open_q & Q(priority=Ticket.Priority.HAUTE)),
        normale=Count("pk", filter=open_q & Q(priority=Ticket.Priority.NORMALE)),
        basse=Count("pk", filter=open_q & Q(priority=Ticket.Priority.BASSE)),
    )
    base = reverse("helpdesk:ticket_list")
    kpis = [
        ("À traiter", counts["a_traiter"], f"{base}?onglet=a_traiter", ""),
        ("En cours", counts["en_cours"], f"{base}?onglet=en_cours", ""),
        ("Non affectés", counts["non_affectes"], f"{base}?onglet=tous&assignee=aucun", ""),
        (
            "Délais dépassés",
            counts["depasses"],
            f"{base}?onglet=tous&breached=on",
            "danger" if counts["depasses"] else "",
        ),
        ("Mes tickets ouverts", counts["mes_tickets"], f"{base}?onglet=tous&assignee=moi", ""),
        ("Résolus cette semaine", counts["resolus_semaine"], f"{base}?onglet=traites", ""),
    ]
    upcoming = (
        Ticket.objects.filter(status=S.CREE)
        .select_related("requester", "subsidiary", "site")
        .order_by("ack_due_at", "created_at")[:5]
    )
    mine = (
        Ticket.objects.filter(open_q, assignee=request.user)
        .select_related("requester")
        .order_by("-has_unread_reply", "-updated_at")[:5]
    )
    return {
        "counts": counts,
        "kpis": kpis,
        "upcoming": upcoming,
        "mine": mine,
        "list_url": base,
    }
