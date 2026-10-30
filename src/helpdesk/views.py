"""Vues des tickets (contracts/ui-routes.md, section Tickets).

Les actions de la fiche répondent en HTMX par le fragment de la fiche (`#ticket`) ; sans
HTMX, elles redirigent vers la fiche. Une règle métier refusée renvoie 422 avec un message.
"""

import csv
from datetime import timedelta
from itertools import chain

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Exists, F, OuterRef, Q, Subquery, Sum
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auth import technician_required
from core.business_time import get_calendar
from core.models import Settings
from directory.models import Account

from .forms import (
    AssignForm,
    BulkAssignForm,
    EquipmentLinkForm,
    KnowledgeSearchForm,
    NoteForm,
    QualifyForm,
    RemoteSessionForm,
    StatusForm,
    TicketCreateForm,
    TicketFilterForm,
    TimeEntryEditForm,
    TimeForm,
)
from .mail.parsing import split_quoted
from .models import (
    Attachment,
    EmailMessage,
    Ticket,
    TicketEvent,
    TicketNote,
    TimeEntry,
)
from .services import knowledge, lifecycle, remote, sla, timers
from .services import tickets as svc

PAGE_SIZE = 50
TIMELINE_HIDDEN_EVENTS = {TicketEvent.Kind.NOTE, TicketEvent.Kind.FUSION_REPONSE}


def is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


# --- Liste ------------------------------------------------------------------


S = Ticket.Status
# Onglets de la liste : à traiter / en cours / traités (retour MVP, FR-082).
TABS = {
    "a_traiter": [S.CREE],
    "en_cours": [S.PRIS_EN_COMPTE, S.ATTENTE_REPONSE, S.EN_ATTENTE],
    "traites": [S.RESOLU, S.FERME],
    "tous": None,
}
DEFAULT_TAB = "a_traiter"


def current_tab(form: TicketFilterForm) -> str:
    tab = form.cleaned_data.get("onglet") if form.is_valid() else ""
    return tab if tab in TABS else DEFAULT_TAB


def base_tickets(request, form: TicketFilterForm):
    """Tickets filtrés, hors onglet de statut."""
    qs = Ticket.objects.select_related(
        "requester",
        "subsidiary",
        "site",
        "assignee__directory_user",
        "assigned_group",
        "category__parent__parent",
        "tool",
    )
    data = form.cleaned_data if form.is_valid() else {}
    if data.get("priority"):
        qs = qs.filter(priority=data["priority"])
    assignee = data.get("assignee")
    if request.GET.get("view") == "dispatch":  # contrat ui-routes : file de dispatch
        assignee = "aucun"
    if assignee == "moi":
        qs = qs.filter(assignee=request.user)
    elif assignee == "mes_groupes":
        qs = qs.filter(assignee__isnull=True, assigned_group__members=request.user)
    elif assignee == "aucun":
        qs = qs.filter(assignee__isnull=True, assigned_group__isnull=True)
    elif assignee:
        qs = qs.filter(assignee_id=assignee)
    for name in ("group", "subsidiary", "site", "tool"):
        if data.get(name):
            qs = qs.filter(**{"assigned_group" if name == "group" else name: data[name]})
    if data.get("category"):
        cat = data["category"]
        qs = qs.filter(Q(category=cat) | Q(category__parent=cat) | Q(category__parent__parent=cat))
    if data.get("breached"):
        qs = qs.filter(ack_breached=True)
    if data.get("mon_temps"):
        qs = qs.filter(
            Exists(TimeEntry.objects.filter(ticket=OuterRef("pk"), technician=request.user))
        )
    if query := (data.get("q") or "").strip():
        text = (
            Q(title__icontains=query)
            | Q(requester__display_name__icontains=query)
            | Q(requester_email__icontains=query)
        )
        digits = query.upper().removeprefix("T-").lstrip("0")
        if digits.isdigit():
            text |= Q(number=int(digits))
        qs = qs.filter(text)
    return qs


def tab_counts(qs) -> dict[str, int]:
    aggregates = {
        name: Count("pk", filter=Q(status__in=statuses)) if statuses else Count("pk")
        for name, statuses in TABS.items()
    }
    return qs.order_by().aggregate(**aggregates)


def filtered_tickets(request, form: TicketFilterForm):
    tab = current_tab(form)
    qs = base_tickets(request, form)
    if TABS[tab]:
        qs = qs.filter(status__in=TABS[tab])
    if tab == "traites":
        return qs.order_by(F("resolved_at").desc(nulls_last=True), "-created_at")
    return qs.order_by(F("ack_due_at").asc(nulls_last=True), "-created_at")


def annotate_deadlines(tickets) -> None:
    """Ajoute `sla_state` (depasse / bientot / ok / « ») à chaque ticket affiché."""
    now, cal, targets = timezone.now(), get_calendar(), sla.targets()
    for ticket in tickets:
        ticket.sla_state = sla.deadline_state(ticket, now, cal, targets)


def _minutes_subquery(**filters):
    return Subquery(
        TimeEntry.objects.filter(ticket=OuterRef("pk"), **filters)
        .order_by()
        .values("ticket")
        .annotate(total=Sum("minutes"))
        .values("total")[:1]
    )


def with_time(queryset, user):
    """Annote `total_minutes` et `my_minutes` (sous-requêtes : pas de doublons de jointure)."""
    return queryset.annotate(
        total_minutes=_minutes_subquery(),
        my_minutes=_minutes_subquery(technician=user),
    )


@technician_required
def ticket_list(request):
    form = TicketFilterForm(request.GET or None)
    tab = current_tab(form)
    tickets = filtered_tickets(request, form)
    tickets = with_time(tickets, request.user)
    page = Paginator(tickets, PAGE_SIZE).get_page(request.GET.get("page"))
    annotate_deadlines(page.object_list)
    query = request.GET.copy()
    query.pop("page", None)
    filters = query.copy()
    filters.pop("onglet", None)
    counts = tab_counts(base_tickets(request, form))
    tabs = [
        {"key": key, "label": label, "count": counts[key], "active": key == tab}
        for key, label in TicketFilterForm.TAB_CHOICES
    ]
    context = {
        "form": form,
        "page": page,
        "query": query.urlencode(),
        "filters": filters.urlencode(),
        "tabs": tabs,
        "day_minutes": Settings.load().business_day_minutes,
        "tab": tab,
        "now": timezone.now(),
    }
    template = (
        "helpdesk/partials/ticket_table.html" if is_htmx(request) else ("helpdesk/ticket_list.html")
    )
    return render(request, template, context)


@technician_required
def ticket_export(request):
    form = TicketFilterForm(request.GET or None)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="tickets-{timezone.localdate():%Y%m%d}.csv"'
    )
    response.write("﻿")  # BOM : ouverture correcte dans Excel
    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        [
            "Référence",
            "Titre",
            "Statut",
            "Priorité",
            "Type",
            "Catégorie",
            "Outil",
            "Demandeur",
            "E-mail demandeur",
            "Entité",
            "Site",
            "Assigné",
            "Groupe",
            "Canal",
            "Créé le",
            "Pris en compte le",
            "Échéance",
            "Délai dépassé",
            "Résolu le",
            "Fermé le",
            "Délai de résolution (h ouvrées)",
            "Temps total (min)",
            "Mon temps (min)",
        ]
    )

    def fmt(value):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if value else ""

    for t in with_time(filtered_tickets(request, form), request.user).iterator(chunk_size=500):
        writer.writerow(
            [
                t.reference,
                t.title,
                t.get_status_display(),
                t.get_priority_display(),
                t.get_type_display() if t.type else "",
                t.category.full_path if t.category else "",
                t.tool or "",
                t.requester or "",
                t.requester_email,
                t.subsidiary or "",
                t.site or "",
                t.assignee.display_name if t.assignee else "",
                t.assigned_group or "",
                t.get_channel_display(),
                fmt(t.created_at),
                fmt(t.acknowledged_at),
                fmt(t.ack_due_at),
                "oui" if t.ack_breached else "non",
                fmt(t.resolved_at),
                fmt(t.closed_at),
                (
                    f"{t.resolution_business_minutes / 60:.1f}".replace(".", ",")
                    if t.resolution_business_minutes is not None
                    else ""
                ),
                t.total_minutes or 0,
                t.my_minutes or 0,
            ]
        )
    return response


# --- Création manuelle ------------------------------------------------------


@technician_required
def ticket_new(request):
    form = TicketCreateForm(
        request.POST or None,
        request.FILES or None,
        initial={"requester": request.GET.get("requester")},
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        ticket = svc.create_manual(
            technician=request.user,
            requester=data["requester"],
            title=data["title"],
            description=data["description"],
            type=data["type"],
            category=data["category"],
            tool=data["tool"],
            priority=data["priority"],
            files=data["files"],
            equipment=data["equipment"],
            description_html=data["description_html"],
        )
        messages.success(request, f"Ticket {ticket.reference} créé ; le demandeur est prévenu.")
        return redirect("helpdesk:ticket_detail", number=ticket.number)
    requester = form["requester"].value()
    selected = None
    if requester:
        selected = form.fields["requester"].queryset.filter(pk=requester).first()
    return render(request, "helpdesk/ticket_new.html", {"form": form, "selected": selected})


# --- Fiche ------------------------------------------------------------------


def _get_ticket(number: int) -> Ticket:
    return get_object_or_404(
        Ticket.objects.select_related(
            "requester__subsidiary",
            "requester__site",
            "subsidiary",
            "site",
            "assignee__directory_user",
            "assigned_group",
            "category__parent__parent",
            "tool",
            "created_by__directory_user",
            "related_ticket",
        ),
        number=number,
    )


def not_inline(attachments, html: str) -> list:
    """Pièces jointes à lister : celles déjà affichées dans le texte (images) sont omises."""
    return [a for a in attachments if f"/attachments/{a.pk}/" not in (html or "")]


def _timeline(ticket: Ticket) -> list[dict]:
    notes = [
        {
            "type": "note",
            "at": n.created_at,
            "note": n,
            "main": split_quoted(n.body_text)[0],
            "quoted": split_quoted(n.body_text)[1],
            "files": not_inline(
                n.attachments.all(),
                n.body_html if n.direction != TicketNote.Direction.ENTRANT else "",
            ),
        }
        for n in ticket.notes.select_related("author__directory_user").prefetch_related(
            "attachments"
        )
    ]
    events = [
        {"type": "event", "at": e.at, "event": e}
        for e in ticket.events.select_related("actor__directory_user").exclude(
            kind__in=TIMELINE_HIDDEN_EVENTS
        )
    ]
    emails = [
        {"type": "email", "at": m.sent_at or m.created_at, "email": m}
        for m in ticket.emails.filter(direction=EmailMessage.Direction.SORTANT).exclude(
            kind=EmailMessage.Kind.NOTE_EXTERNE
        )
    ]
    return sorted(chain(notes, events, emails), key=lambda item: item["at"])


def detail_context(request, ticket: Ticket, **extra) -> dict:
    main, quoted = split_quoted(ticket.description)
    annotate_deadlines([ticket])
    return {
        "ticket": ticket,
        "description_main": main,
        "description_quoted": quoted,
        "timeline": _timeline(ticket),
        "initial_attachments": not_inline(
            ticket.attachments.filter(note__isnull=True), ticket.description_html
        ),
        "htmx": is_htmx(request),
        "time": svc.time_totals(ticket, request.user),
        "time_entries": ticket.time_entries.select_related("technician__directory_user").order_by(
            "-date", "-created_at"
        ),
        "running_here": timers.running_timer(request.user),
        "day_minutes": Settings.load().business_day_minutes,
        "equipment": ticket.equipment.select_related("type", "site"),
        "requester_equipment": (
            ticket.requester.equipment.exclude(pk__in=ticket.equipment.values("pk")).select_related(
                "type"
            )
            if ticket.requester_id
            else []
        ),
        "targets": [Ticket.Status(s) for s in sorted(lifecycle.allowed_targets(ticket))],
        "missing": lifecycle.missing_qualification(ticket),
        "qualify_form": extra.pop("qualify_form", None)
        or QualifyForm(
            initial={
                "type": ticket.type,
                "category": ticket.category_id,
                "tool": ticket.tool_id,
                "priority": ticket.priority,
                "subsidiary": ticket.subsidiary_id,
                "site": ticket.site_id,
                "requester": ticket.requester_id,
            }
        ),
        "assign_form": extra.pop("assign_form", None)
        or AssignForm(
            initial={
                "assignee": ticket.assignee_id,
                "group": ticket.assigned_group_id,
            }
        ),
        "note_form": extra.pop("note_form", None) or NoteForm(),
        "remote_form": extra.pop("remote_form", None) or RemoteSessionForm(ticket=ticket),
        "remote_sessions": ticket.remote_sessions.select_related(
            "technician__directory_user", "equipment"
        ),
        "time_form": extra.pop("time_form", None) or TimeForm(),
        "now": timezone.now(),
        **extra,
    }


def render_detail(request, ticket: Ticket, status: int = 200, **extra):
    ticket.refresh_from_db()
    template = (
        "helpdesk/partials/ticket_body.html"
        if is_htmx(request)
        else ("helpdesk/ticket_detail.html")
    )
    return render(request, template, detail_context(request, ticket, **extra), status=status)


@technician_required
def ticket_detail(request, number: int):
    ticket = _get_ticket(number)
    svc.mark_read(ticket, request.user)
    return render(request, "helpdesk/ticket_detail.html", detail_context(request, ticket))


def _done(request, ticket: Ticket, message: str = ""):
    if is_htmx(request):
        return render_detail(request, ticket, flash=message)
    if message:
        messages.success(request, message)
    return redirect("helpdesk:ticket_detail", number=ticket.number)


def _error(request, ticket: Ticket, error, **forms):
    text = "; ".join(error.messages) if isinstance(error, ValidationError) else str(error)
    return render_detail(request, ticket, status=422, error=text, **forms)


@technician_required
@require_POST
def ticket_qualify(request, number: int):
    ticket = _get_ticket(number)
    form = QualifyForm(request.POST)
    if not form.is_valid():
        return _error(request, ticket, "Qualification invalide.", qualify_form=form)
    data = form.cleaned_data
    fields = {k: data[k] for k in ("type", "category", "tool", "priority", "subsidiary", "site")}
    if data.get("requester"):
        fields["requester"] = data["requester"]
    try:
        changed = svc.qualify(ticket, request.user, **fields)
    except ValidationError as exc:
        return _error(request, ticket, exc, qualify_form=form)
    return _done(request, ticket, "Qualification enregistrée." if changed else "")


@technician_required
@require_POST
def ticket_status(request, number: int):
    ticket = _get_ticket(number)
    form = StatusForm(request.POST)
    if not form.is_valid():
        return _error(request, ticket, "Statut inconnu.")
    try:
        lifecycle.change_status(
            ticket,
            form.cleaned_data["status"],
            request.user,
            resolution=form.cleaned_data["resolution"] or None,
        )
    except lifecycle.InvalidTransition as exc:
        return _error(request, ticket, exc)
    return _done(request, ticket, f"Statut : {ticket.get_status_display()}.")


@technician_required
@require_POST
def ticket_take(request, number: int):
    ticket = _get_ticket(number)
    svc.take(ticket, request.user)
    message = "Vous êtes responsable de ce ticket."
    if ticket.status == Ticket.Status.CREE:
        message += " Qualifiez-le pour le prendre en compte."
    return _done(request, ticket, message)


@technician_required
@require_POST
def ticket_assign(request, number: int):
    ticket = _get_ticket(number)
    form = AssignForm(request.POST)
    if not form.is_valid():
        return _error(
            request,
            ticket,
            ValidationError(form.non_field_errors() or "Affectation invalide."),
            assign_form=form,
        )
    svc.assign(ticket, request.user, form.cleaned_data["assignee"], form.cleaned_data["group"])
    return _done(request, ticket, "Affectation enregistrée.")


@technician_required
@require_POST
def ticket_note(request, number: int):
    ticket = _get_ticket(number)
    form = NoteForm(request.POST, request.FILES)
    if not form.is_valid():
        return _error(request, ticket, "La note est vide.", note_form=form)
    data = form.cleaned_data
    note = svc.add_note(
        ticket,
        request.user,
        data["visibility"],
        data["body"],
        data["files"],
        body_html=data["body_html"],
    )
    text = (
        "Note envoyée au demandeur."
        if note.visibility == TicketNote.Visibility.EXTERNE
        else ("Note interne ajoutée.")
    )
    return _done(request, ticket, text)


@technician_required
@require_POST
def ticket_time(request, number: int):
    ticket = _get_ticket(number)
    form = TimeForm(request.POST)
    if not form.is_valid():
        errors = [e for errs in form.errors.values() for e in errs]
        return _error(request, ticket, ValidationError(errors), time_form=form)
    data = form.cleaned_data
    svc.add_time(ticket, request.user, data["date"], data["minutes"], data["comment"])
    return _done(request, ticket, f"{data['minutes']} min enregistrées.")


@technician_required
@require_POST
def ticket_equipment(request, number: int):
    ticket = _get_ticket(number)
    form = EquipmentLinkForm(request.POST)
    if not form.is_valid():
        return _error(request, ticket, "Équipement inconnu.")
    equipment = form.cleaned_data["equipment"]
    if form.cleaned_data["action"] == "lier":
        svc.link_equipment(ticket, request.user, equipment)
        return _done(request, ticket, f"{equipment} lié au ticket.")
    svc.unlink_equipment(ticket, request.user, equipment)
    return _done(request, ticket, f"{equipment} délié du ticket.")


@technician_required
@require_POST
def ticket_remote(request, number: int):
    """Déclare une prise en main TeamViewer réalisée (aucun lancement depuis l'ITSM)."""
    ticket = _get_ticket(number)
    form = RemoteSessionForm(request.POST, ticket=ticket)
    if not form.is_valid():
        errors = [e for errs in form.errors.values() for e in errs]
        return _error(request, ticket, ValidationError(errors), remote_form=form)
    data = form.cleaned_data
    try:
        remote.declare(
            ticket,
            request.user,
            data["equipment"],
            data["started_at"],
            data["ended_at"],
            data["comment"],
            request=request,
        )
    except ValidationError as exc:
        return _error(request, ticket, exc, remote_form=form)
    return _done(request, ticket, "Prise en main déclarée.")


@technician_required
@require_POST
def timer_start(request, number: int):
    ticket = _get_ticket(number)
    _, previous = timers.start(ticket, request.user)
    message = "Chronomètre démarré."
    if previous is not None:
        message += (
            f" Celui de {previous.entry.ticket.reference} a été arrêté "
            f"({previous.entry.minutes} min enregistrées)."
        )
    return _done(request, ticket, message)


@technician_required
@require_POST
def timer_stop(request, number: int):
    ticket = _get_ticket(number)
    stopped = timers.stop(request.user)
    if stopped is None:
        return _done(request, ticket, "Aucun chronomètre en cours.")
    message = f"{stopped.entry.minutes} min enregistrées sur {stopped.entry.ticket.reference}."
    if stopped.capped:
        message += " Le chronomètre est resté actif plus de 24 h : vérifiez la durée."
    if not is_htmx(request) and request.POST.get("next", "").startswith("/"):
        messages.success(request, message)
        return redirect(request.POST["next"])
    return _done(request, stopped.entry.ticket if is_htmx(request) else ticket, message)


@technician_required
@require_POST
def time_entry_edit(request, pk: int):
    entry = get_object_or_404(TimeEntry.objects.select_related("ticket"), pk=pk)
    ticket = _get_ticket(entry.ticket.number)
    form = TimeEntryEditForm(request.POST)
    if not form.is_valid():
        errors = [e for errs in form.errors.values() for e in errs]
        return _error(request, ticket, ValidationError(errors))
    data = form.cleaned_data
    timers.edit_time(
        entry, request.user, minutes=data["minutes"], comment=data["comment"], day=data["date"]
    )
    return _done(request, ticket, "Saisie de temps corrigée.")


@technician_required
@require_POST
def time_entry_delete(request, pk: int):
    entry = get_object_or_404(TimeEntry.objects.select_related("ticket"), pk=pk)
    ticket = _get_ticket(entry.ticket.number)
    timers.delete_time(entry, request.user)
    return _done(request, ticket, "Saisie de temps supprimée.")


@technician_required
def bulk_assign(request):
    form = BulkAssignForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        count = svc.bulk_reassign(
            data["from_technician"], request.user, data["assignee"], data["group"]
        )
        messages.success(request, f"{count} ticket(s) réaffecté(s).")
        return redirect("helpdesk:ticket_list")
    inactive = (
        Account.objects.filter(is_active=False, assigned_tickets__status__in=(Ticket.OPEN_STATUSES))
        .distinct()
        .select_related("directory_user")
    )
    return render(
        request,
        "helpdesk/bulk_assign.html",
        {"form": form, "inactive": inactive},
        status=422 if request.method == "POST" else 200,
    )


@technician_required
def attachment_download(request, pk: int):
    attachment = get_object_or_404(Attachment, pk=pk)
    inline = attachment.content_type.startswith("image/")
    return FileResponse(
        attachment.file.open("rb"),
        as_attachment=not inline,
        filename=attachment.filename,
        content_type=attachment.content_type or "application/octet-stream",
    )


# --- Suivi des délais et du temps (US3) ------------------------------------------

TRACKING_PERIODS = {7: "7 jours", 30: "30 jours", 90: "90 jours"}


@technician_required
def tracking(request):
    try:
        days = int(request.GET.get("jours", 30))
    except ValueError:
        days = 30
    days = days if days in TRACKING_PERIODS else 30
    now = timezone.now()
    since = now - timedelta(days=days)

    pending = list(
        Ticket.objects.filter(status=Ticket.Status.CREE)
        .select_related(
            "requester", "subsidiary", "site", "assignee__directory_user", "assigned_group"
        )
        .order_by(F("ack_due_at").asc(nulls_last=True), "created_at")
    )
    annotate_deadlines(pending)

    measured = Ticket.objects.filter(created_at__gte=since, ack_due_at__isnull=False).filter(
        Q(acknowledged_at__isnull=False) | Q(ack_breached=True)
    )
    rates = []
    for priority, label in Ticket.Priority.choices:
        row = measured.filter(priority=priority).aggregate(
            total=Count("pk"), on_time=Count("pk", filter=Q(ack_breached=False))
        )
        rate = round(100 * row["on_time"] / row["total"]) if row["total"] else None
        resolved = Ticket.objects.filter(
            priority=priority, resolved_at__gte=since, resolution_business_minutes__isnull=False
        ).aggregate(avg=Avg("resolution_business_minutes"), count=Count("pk"))
        rates.append(
            {
                "priority": priority,
                "label": label,
                **row,
                "rate": rate,
                "avg_resolution": round(resolved["avg"]) if resolved["avg"] is not None else None,
                "resolved_count": resolved["count"],
            }
        )

    time_rows = (
        TimeEntry.objects.filter(date__gte=timezone.localdate(since))
        .values("technician")
        .annotate(total=Sum("minutes"), tickets=Count("ticket", distinct=True))
        .order_by("-total")
    )
    from directory.models import Account

    names = {
        a.pk: a.display_name
        for a in Account.objects.filter(pk__in=[r["technician"] for r in time_rows]).select_related(
            "directory_user"
        )
    }
    time_per_technician = [
        {"name": names.get(r["technician"], "?"), "total": r["total"], "tickets": r["tickets"]}
        for r in time_rows
    ]
    return render(
        request,
        "helpdesk/tracking.html",
        {
            "pending": pending,
            "rates": rates,
            "time_per_technician": time_per_technician,
            "days": days,
            "periods": TRACKING_PERIODS,
            "day_minutes": Settings.load().business_day_minutes,
        },
    )


# --- Base de résolution (US6) ------------------------------------------------------


@technician_required
def knowledge_search(request):
    form = KnowledgeSearchForm(request.GET or None)
    results = None
    if form.is_valid() and any(form.cleaned_data.values()):
        data = form.cleaned_data
        results = Paginator(
            knowledge.search(
                data["q"],
                category=data["category"],
                tool=data["tool"],
                subsidiary=data["subsidiary"],
                date_from=data["date_from"],
                date_to=data["date_to"],
            ),
            25,
        ).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(
        request,
        "helpdesk/knowledge.html",
        {"form": form, "results": results, "query": query.urlencode()},
    )


@technician_required
def ticket_suggestions(request, number: int):
    ticket = _get_ticket(number)
    return render(
        request,
        "helpdesk/partials/suggestions.html",
        {"suggestions": knowledge.suggestions(ticket), "ticket": ticket},
    )
