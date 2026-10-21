"""Vues des tickets (contracts/ui-routes.md, section Tickets).

Les actions de la fiche répondent en HTMX par le fragment de la fiche (`#ticket`) ; sans
HTMX, elles redirigent vers la fiche. Une règle métier refusée renvoie 422 avec un message.
"""

import csv
from itertools import chain

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auth import technician_required
from directory.models import Account

from .forms import (
    AssignForm,
    BulkAssignForm,
    NoteForm,
    QualifyForm,
    StatusForm,
    TicketCreateForm,
    TicketFilterForm,
    TimeForm,
)
from .mail.parsing import split_quoted
from .models import Attachment, EmailMessage, Ticket, TicketEvent, TicketNote
from .services import lifecycle
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


@technician_required
def ticket_list(request):
    form = TicketFilterForm(request.GET or None)
    tab = current_tab(form)
    tickets = filtered_tickets(request, form)
    page = Paginator(tickets, PAGE_SIZE).get_page(request.GET.get("page"))
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
        ]
    )

    def fmt(value):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if value else ""

    for t in filtered_tickets(request, form).iterator(chunk_size=500):
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


def _timeline(ticket: Ticket) -> list[dict]:
    notes = [
        {
            "type": "note",
            "at": n.created_at,
            "note": n,
            "main": split_quoted(n.body_text)[0],
            "quoted": split_quoted(n.body_text)[1],
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
    return {
        "ticket": ticket,
        "description_main": main,
        "description_quoted": quoted,
        "timeline": _timeline(ticket),
        "initial_attachments": ticket.attachments.filter(note__isnull=True),
        "time": svc.time_totals(ticket),
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
    note = svc.add_note(ticket, request.user, data["visibility"], data["body"], data["files"])
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
