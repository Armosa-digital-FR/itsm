"""Opérations métier sur les tickets (US1, FR-010 à FR-038).

Les vues restent minces : toute règle passe par ce module ou par `lifecycle`.
"""

from dataclasses import dataclass, field
from datetime import date

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.models import Settings
from directory.models import DirectoryUser
from helpdesk.mail import outbound
from helpdesk.models import (
    Attachment,
    EmailMessage,
    TechnicianGroup,
    Ticket,
    TicketEvent,
    TicketNote,
    TimeEntry,
)
from helpdesk.services.lifecycle import change_status, record_event, reopen_deadline_passed
from helpdesk.signals import ticket_created, ticket_qualified

S = Ticket.Status
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


@dataclass
class IncomingFile:
    name: str
    content_type: str
    content: bytes | None  # None si la pièce dépasse la limite
    size: int
    content_id: str = ""


@dataclass
class TooLarge:
    names: list[str] = field(default_factory=list)


def find_requester(email: str) -> DirectoryUser | None:
    if not email:
        return None
    return (
        DirectoryUser.objects.filter(email__iexact=email.strip())
        .order_by("-is_active")
        .select_related("subsidiary")
        .first()
    )


def _sender_domain_is_internal(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    return domain in {d.lower().lstrip("@") for d in Settings.load().internal_domains}


def save_files(ticket: Ticket, files, note: TicketNote | None = None) -> list[str]:
    """Enregistre les pièces jointes ; renvoie les noms refusés car trop volumineuses."""
    refused, _ = save_files_with_cids(ticket, files, note)
    return refused


def save_files_with_cids(ticket: Ticket, files, note: TicketNote | None = None):
    """Comme `save_files`, et renvoie aussi la table Content-ID → URL de la pièce jointe."""
    from django.urls import reverse

    refused, cid_map = [], {}
    for item in files:
        if isinstance(item, IncomingFile):
            if item.content is None or item.size > MAX_ATTACHMENT_BYTES:
                refused.append(item.name)
                continue
            content, name, ctype, cid = (
                ContentFile(item.content),
                item.name,
                item.content_type,
                item.content_id,
            )
            size = item.size
        else:  # fichier téléversé (UploadedFile)
            if item.size > MAX_ATTACHMENT_BYTES:
                refused.append(item.name)
                continue
            content, name, ctype, cid, size = item, item.name, item.content_type, "", item.size
        attachment = Attachment(
            ticket=ticket,
            note=note,
            filename=name[:255],
            content_type=ctype or "",
            size=size,
            content_id=cid[:255],
        )
        attachment.file.save(name, content, save=False)
        attachment.save()
        if attachment.content_id:
            cid_map[attachment.content_id] = reverse("helpdesk:attachment", args=[attachment.pk])
    return refused, cid_map


def _with_inline_images(body_html: str, cid_map: dict) -> str:
    if not body_html or not cid_map:
        return body_html
    from helpdesk.mail.parsing import sanitize_html

    return sanitize_html(body_html, cid_map)


def _rich(html: str):
    """Texte enrichi de l'éditeur, ou None s'il n'y a ni texte ni image."""
    if not (html or "").strip():
        return None
    from helpdesk.services.rich_text import prepare

    rich = prepare(html)
    return None if rich.is_empty and not rich.refused else rich


def _store_rich(ticket: Ticket, rich, *, target, html_field: str, note=None) -> None:
    """Enregistre les images intégrées puis le HTML avec leurs URL protégées."""
    _, cid_map = save_files_with_cids(ticket, rich.files, note=note)
    html = _with_inline_images(rich.html, cid_map) if cid_map else rich.html
    if rich.refused:
        html += "<p><em>Images non conservées : " + ", ".join(rich.refused) + ".</em></p>"
    setattr(target, html_field, html)
    target.save(update_fields=[html_field])


def _too_large_mention(names: list[str]) -> str:
    if not names:
        return ""
    return "\n\n[Pièces jointes non conservées, au-delà de 25 Mo : " + ", ".join(names) + "]"


@transaction.atomic
def create_from_email(
    *,
    subject: str,
    body_text: str,
    body_html: str,
    sender_email: str,
    mailbox: str,
    email_message: EmailMessage,
    files=(),
    related_ticket: Ticket | None = None,
) -> Ticket:
    from helpdesk.mail.parsing import clean_subject

    requester = find_requester(sender_email)
    ticket = Ticket(
        title=clean_subject(subject)[:255],
        description=body_text,
        description_html=body_html,
        channel=Ticket.Channel.EMAIL,
        mailbox=mailbox,
        requester=requester,
        requester_email=sender_email.lower(),
        subsidiary=requester.subsidiary if requester else None,
        site=requester.site if requester else None,
        related_ticket=related_ticket,
    )
    ticket.save()
    refused, cid_map = save_files_with_cids(ticket, files)
    if refused or cid_map:
        ticket.description += _too_large_mention(refused)
        ticket.description_html = _with_inline_images(ticket.description_html, cid_map)
        ticket.save(update_fields=["description", "description_html"])
    email_message.ticket = ticket
    email_message.save(update_fields=["ticket"])
    record_event(
        ticket,
        TicketEvent.Kind.CREATION,
        None,
        "",
        "e-mail",
        sender=sender_email.lower(),
        related=related_ticket.reference if related_ticket else "",
    )
    if requester is not None or _sender_domain_is_internal(sender_email):
        outbound.queue_email(ticket, EmailMessage.Kind.ACCUSE_RECEPTION)
    ticket_created.send(sender=Ticket, ticket=ticket)
    return ticket


@transaction.atomic
def create_manual(
    *,
    technician,
    requester: DirectoryUser,
    title: str,
    description: str = "",
    type: str = "",
    category=None,
    tool=None,
    priority: str = Ticket.Priority.NORMALE,
    files=(),
    equipment=(),
    description_html: str = "",
) -> Ticket:
    """Création par un technicien pour le compte d'un demandeur (FR-014, FR-014a).

    `description_html` vient de l'éditeur enrichi (images intégrées, FR-014c) ; à défaut,
    la description texte est utilisée telle quelle.
    """
    rich = _rich(description_html)
    ticket = Ticket(
        title=title.strip()[:255],
        description=(rich.text if rich else description).strip(),
        channel=Ticket.Channel.APP,
        created_by=technician,
        requester=requester,
        requester_email=(requester.email or "").lower(),
        subsidiary=requester.subsidiary,
        site=requester.site,
        type=type or "",
        category=category,
        tool=tool,
        priority=priority or Ticket.Priority.NORMALE,
        mailbox=outbound.default_mailbox(),
    )
    ticket.save()
    save_files(ticket, files)
    if rich:
        _store_rich(ticket, rich, target=ticket, html_field="description_html")
    for item in equipment:
        link_equipment(ticket, technician, item)
    record_event(
        ticket,
        TicketEvent.Kind.CREATION,
        technician,
        "",
        "application",
        created_by=technician.display_name,
    )
    outbound.queue_email(ticket, EmailMessage.Kind.ACCUSE_RECEPTION)
    ticket_created.send(sender=Ticket, ticket=ticket)
    if tool is not None:
        ticket_qualified.send(sender=Ticket, ticket=ticket, actor=technician, changed={"tool"})
    return ticket


QUALIFY_FIELDS = {
    "type": TicketEvent.Kind.TYPE,
    "category": TicketEvent.Kind.CATEGORIE,
    "tool": TicketEvent.Kind.OUTIL,
    "priority": TicketEvent.Kind.PRIORITE,
    "subsidiary": TicketEvent.Kind.FILIALE,
    "site": TicketEvent.Kind.SITE,
    "requester": TicketEvent.Kind.DEMANDEUR,
}


def _label(ticket: Ticket, name: str) -> str:
    value = getattr(ticket, name)
    if value in (None, ""):
        return ""
    if name in {"type", "priority"}:
        return getattr(ticket, f"get_{name}_display")()
    return str(value)


@transaction.atomic
def qualify(ticket: Ticket, actor, **fields) -> set[str]:
    """Met à jour la qualification ; un événement par champ modifié (FR-015 à FR-019)."""
    changed = set()
    for name, value in fields.items():
        if name not in QUALIFY_FIELDS:
            raise ValueError(f"Champ non qualifiable : {name}")
        if value == "" and name != "type":
            value = None
        current = getattr(ticket, name)
        if current == value or (current in (None, "") and value in (None, "")):
            continue
        old = _label(ticket, name)
        setattr(ticket, name, value if value is not None else ("" if name == "type" else None))
        if name == "requester" and value is not None:
            ticket.requester_email = (value.email or ticket.requester_email).lower()
            if ticket.subsidiary_id is None and "subsidiary" not in fields:
                ticket.subsidiary = value.subsidiary
            if ticket.site_id is None and "site" not in fields:
                ticket.site = value.site
        changed.add(name)
        record_event(ticket, QUALIFY_FIELDS[name], actor, old, _label(ticket, name))
    if changed:
        if "priority" in changed and not ticket.priority:
            raise ValidationError("La priorité est obligatoire.")
        ticket.save()
        ticket_qualified.send(sender=Ticket, ticket=ticket, actor=actor, changed=changed)
    return changed


@transaction.atomic
def take(ticket: Ticket, technician) -> Ticket:
    """Le technicien devient responsable ; prise en compte si le ticket est qualifié (FR-023)."""
    if ticket.assignee_id != technician.pk:
        old = ticket.assignee.display_name if ticket.assignee_id else ""
        ticket.assignee = technician
        ticket.save(update_fields=["assignee", "updated_at"])
        record_event(
            ticket,
            TicketEvent.Kind.AFFECTATION,
            technician,
            old,
            technician.display_name,
            assignee=technician.pk,
        )
    if ticket.status == S.CREE:
        from helpdesk.services.lifecycle import missing_qualification

        if not missing_qualification(ticket):
            change_status(ticket, S.PRIS_EN_COMPTE, technician)
    return ticket


@transaction.atomic
def assign(ticket: Ticket, actor, assignee=None, group: TechnicianGroup | None = None) -> Ticket:
    """Réaffectation manuelle (FR-024) : désactive l'affectation automatique."""
    old = _assignment_label(ticket)
    ticket.assignee = assignee
    ticket.assigned_group = group
    ticket.assignment_mode = Ticket.AssignmentMode.MANUEL
    ticket.save(update_fields=["assignee", "assigned_group", "assignment_mode", "updated_at"])
    record_event(
        ticket,
        TicketEvent.Kind.AFFECTATION,
        actor,
        old,
        _assignment_label(ticket),
        mode="manuel",
        assignee=getattr(assignee, "pk", None),
        group=getattr(group, "pk", None),
    )
    return ticket


def _assignment_label(ticket: Ticket) -> str:
    parts = []
    if ticket.assignee_id:
        parts.append(ticket.assignee.display_name)
    if ticket.assigned_group_id:
        parts.append(f"groupe {ticket.assigned_group.name}")
    return " · ".join(parts)


@transaction.atomic
def bulk_reassign(from_technician, actor, to_technician=None, to_group=None) -> int:
    """Réaffecte tous les tickets ouverts d'un technicien (absence, départ)."""
    tickets = Ticket.objects.select_for_update().filter(
        assignee=from_technician, status__in=Ticket.OPEN_STATUSES
    )
    count = 0
    for ticket in tickets:
        assign(ticket, actor, assignee=to_technician, group=to_group or ticket.assigned_group)
        count += 1
    return count


@transaction.atomic
def add_note(
    ticket: Ticket, actor, visibility: str, body: str, files=(), body_html: str = ""
) -> TicketNote:
    rich = _rich(body_html)
    body = (rich.text if rich else body or "").strip()
    if not body and not (rich and rich.files):
        raise ValidationError("La note est vide.")
    external = visibility == TicketNote.Visibility.EXTERNE
    note = TicketNote.objects.create(
        ticket=ticket,
        visibility=visibility,
        direction=TicketNote.Direction.SORTANT if external else TicketNote.Direction.INTERNE,
        author=actor,
        body_text=body or "(image)",
    )
    save_files(ticket, files, note=note)
    if rich:
        _store_rich(ticket, rich, target=note, html_field="body_html", note=note)
    record_event(
        ticket, TicketEvent.Kind.NOTE, actor, "", note.get_visibility_display(), note=note.pk
    )
    if external:
        outbound.queue_email(ticket, EmailMessage.Kind.NOTE_EXTERNE, note=note)
    return note


def add_time(
    ticket: Ticket,
    technician,
    day: date,
    minutes: int,
    comment: str = "",
    source: str = TimeEntry.Source.MANUEL,
) -> TimeEntry:
    entry = TimeEntry(
        ticket=ticket,
        technician=technician,
        date=day,
        minutes=minutes,
        comment=(comment or "")[:500],
        source=source,
    )
    entry.full_clean()
    entry.save()
    record_event(
        ticket,
        TicketEvent.Kind.TEMPS,
        technician,
        "",
        f"{minutes} min" + (" (chronomètre)" if source == TimeEntry.Source.CHRONO else ""),
        date=day.isoformat(),
        entry=entry.pk,
    )
    return entry


def time_totals(ticket: Ticket, user=None) -> dict:
    per_tech = list(
        ticket.time_entries.values("technician").annotate(total=Sum("minutes")).order_by("-total")
    )
    from directory.models import Account

    names = {
        a.pk: a.display_name
        for a in Account.objects.filter(
            pk__in=[row["technician"] for row in per_tech]
        ).select_related("directory_user")
    }
    mine = next(
        (row["total"] for row in per_tech if row["technician"] == getattr(user, "pk", 0)), 0
    )
    return {
        "total": sum(row["total"] for row in per_tech),
        "mine": mine,
        "per_technician": [(names.get(row["technician"], "?"), row["total"]) for row in per_tech],
    }


@transaction.atomic
def register_requester_reply(
    ticket: Ticket,
    *,
    email_message: EmailMessage,
    body_text: str,
    body_html: str,
    sender_email: str,
    files=(),
) -> tuple[Ticket, bool]:
    """Réponse du demandeur. Renvoie (ticket concerné, nouveau ticket créé ?)."""
    if ticket.status == S.RESOLU and reopen_deadline_passed(ticket):
        change_status(ticket, S.FERME)
    if ticket.status == S.FERME:
        new = create_from_email(
            subject=email_message.subject,
            body_text=body_text,
            body_html=body_html,
            sender_email=sender_email,
            mailbox=email_message.mailbox,
            email_message=email_message,
            files=files,
            related_ticket=ticket,
        )
        return new, True

    note = TicketNote.objects.create(
        ticket=ticket,
        visibility=TicketNote.Visibility.EXTERNE,
        direction=TicketNote.Direction.ENTRANT,
        author_email=sender_email.lower(),
        body_text=body_text,
        body_html=body_html,
        email_message=email_message,
    )
    refused, cid_map = save_files_with_cids(ticket, files, note=note)
    if refused or cid_map:
        note.body_text += _too_large_mention(refused)
        note.body_html = _with_inline_images(note.body_html, cid_map)
        note.save(update_fields=["body_text", "body_html"])
    email_message.ticket = ticket
    email_message.save(update_fields=["ticket"])
    record_event(
        ticket, TicketEvent.Kind.FUSION_REPONSE, None, "", sender_email.lower(), note=note.pk
    )
    ticket.has_unread_reply = True
    ticket.save(update_fields=["has_unread_reply", "updated_at"])
    if ticket.status in (S.ATTENTE_REPONSE, S.RESOLU):
        change_status(ticket, S.PRIS_EN_COMPTE)
    return ticket, False


def mark_read(ticket: Ticket, user) -> None:
    if ticket.has_unread_reply and ticket.assignee_id == getattr(user, "pk", None):
        Ticket.objects.filter(pk=ticket.pk).update(has_unread_reply=False)
        ticket.has_unread_reply = False


def auto_close_due(now=None) -> int:
    """Ferme les tickets résolus depuis plus de N jours ouvrés (FR-033)."""
    now = now or timezone.now()
    closed = 0
    for ticket in Ticket.objects.filter(status=S.RESOLU).order_by("resolved_at"):
        if reopen_deadline_passed(ticket, now):
            change_status(ticket, S.FERME)
            closed += 1
    return closed


def link_equipment(ticket: Ticket, actor, equipment) -> bool:
    """Lie un équipement du parc au ticket (FR-017) ; vrai si le lien est nouveau."""
    if ticket.equipment.filter(pk=equipment.pk).exists():
        return False
    ticket.equipment.add(equipment)
    record_event(
        ticket, TicketEvent.Kind.EQUIPEMENT, actor, "", f"{equipment} lié", equipment=equipment.pk
    )
    return True


def unlink_equipment(ticket: Ticket, actor, equipment) -> bool:
    if not ticket.equipment.filter(pk=equipment.pk).exists():
        return False
    ticket.equipment.remove(equipment)
    record_event(
        ticket,
        TicketEvent.Kind.EQUIPEMENT,
        actor,
        f"{equipment} lié",
        "délié",
        equipment=equipment.pk,
    )
    return True
