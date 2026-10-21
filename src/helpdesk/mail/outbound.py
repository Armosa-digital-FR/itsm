"""Messagerie sortante (FR-012, FR-031, FR-034, FR-038, contracts/email.md, research R11).

Liste fermée des e-mails envoyés à un demandeur : accusé de réception, note externe, rappel,
résolution. Tout autre type est refusé. Envoi via Graph depuis la boîte support : brouillon
(pour connaître le Message-ID) puis envoi.
"""

import base64
import logging
from functools import cache

from django.conf import settings
from django.contrib.staticfiles import finders
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from core.graph import GraphClient, get_client
from core.models import Settings
from directory.models import Account
from helpdesk.models import EmailMessage, Ticket, TicketNote

logger = logging.getLogger(__name__)

REQUESTER_KINDS = frozenset(
    {
        EmailMessage.Kind.ACCUSE_RECEPTION,
        EmailMessage.Kind.NOTE_EXTERNE,
        EmailMessage.Kind.RAPPEL,
        EmailMessage.Kind.RESOLUTION,
    }
)
INLINE_ATTACHMENT_LIMIT = 3 * 1024 * 1024  # au-delà : session d'upload Graph


class EmailNotAllowed(ValueError):
    """Type d'e-mail non autorisé vers un demandeur (FR-038)."""


@cache
def logo_bytes() -> bytes:
    path = finders.find("img/logo.png")
    with open(path, "rb") as handle:
        return handle.read()


def default_mailbox() -> str:
    mailboxes = Settings.load().support_mailboxes
    return mailboxes[0] if mailboxes else ""


def _context(**extra) -> dict:
    return {"base_url": settings.ITSM_BASE_URL, **extra}


def queue_email(
    ticket: Ticket, kind: str, note: TicketNote | None = None, extra: dict | None = None
) -> EmailMessage | None:
    """Prépare un e-mail au demandeur et planifie son envoi après validation."""
    if kind not in REQUESTER_KINDS:
        raise EmailNotAllowed(f"Aucun e-mail « {kind} » ne peut être envoyé au demandeur.")
    if ticket.anonymized_at:
        return None
    recipient = ticket.recipient_email
    if not recipient:
        logger.info("pas de destinataire pour l'e-mail", extra={"ticket": ticket.pk, "kind": kind})
        return None
    mailbox = ticket.mailbox or default_mailbox()
    context = _context(ticket=ticket, note=note, extra=extra or {})
    message = EmailMessage.objects.create(
        direction=EmailMessage.Direction.SORTANT,
        kind=kind,
        processing=EmailMessage.Processing.A_ENVOYER,
        ticket=ticket,
        mailbox=mailbox,
        subject=f"[{ticket.reference}] {ticket.title}"[:998],
        from_address=mailbox,
        to_addresses=[recipient],
        body_html=render_to_string(f"email/{kind}.html", context),
        body_text=render_to_string(f"email/{kind}.txt", context),
    )
    if note is not None:
        note.email_message = message
        note.save(update_fields=["email_message"])
    _schedule(message)
    return message


def send_technician_alert(
    recipients: list[str], subject: str, body: str, ticket: Ticket | None = None
) -> EmailMessage | None:
    """Alerte aux techniciens ou administrateurs (jamais au demandeur)."""
    recipients = sorted({r for r in recipients if r})
    if not recipients:
        logger.warning("alerte sans destinataire", extra={"subject": subject})
        return None
    mailbox = (ticket.mailbox if ticket else "") or default_mailbox()
    context = _context(ticket=ticket, subject=subject, body=body)
    message = EmailMessage.objects.create(
        direction=EmailMessage.Direction.SORTANT,
        kind=EmailMessage.Kind.ALERTE_TECHNICIEN,
        processing=EmailMessage.Processing.A_ENVOYER,
        ticket=ticket,
        mailbox=mailbox,
        subject=f"[ITSM] {subject}"[:998],
        from_address=mailbox,
        to_addresses=recipients,
        body_html=render_to_string("email/alerte.html", context),
        body_text=render_to_string("email/alerte.txt", context),
    )
    _schedule(message)
    return message


def admin_emails() -> list[str]:
    return [
        account.email
        for account in Account.objects.filter(
            is_active=True, roles__contains=[Account.ROLE_ADMIN]
        ).select_related("directory_user")
        if account.email
    ]


def send_admin_alert(subject: str, body: str) -> None:
    send_technician_alert(admin_emails(), subject, body)


def _schedule(message: EmailMessage) -> None:
    def defer():
        from helpdesk.tasks import send_email

        send_email.defer(email_message_id=message.pk)

    transaction.on_commit(defer)


def _file_attachment(name: str, content_type: str, data: bytes, **extra) -> dict:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "contentType": content_type or "application/octet-stream",
        "contentBytes": base64.b64encode(data).decode(),
        **extra,
    }


def send(message: EmailMessage, client: GraphClient | None = None) -> EmailMessage:
    """Envoie un e-mail préparé. Lève une exception en cas d'échec (reprise par la tâche)."""
    if message.processing in (EmailMessage.Processing.ENVOYE, EmailMessage.Processing.SIMULE):
        return message
    if not settings.ITSM_GRAPH_ENABLED:
        message.processing = EmailMessage.Processing.SIMULE
        message.sent_at = timezone.now()
        message.save(update_fields=["processing", "sent_at"])
        return message
    try:
        if not message.mailbox:
            raise ValueError("Aucune boîte support n'est paramétrée pour l'envoi.")
        client = client or get_client()
        base = f"/users/{message.mailbox}/messages"
        inline, large = (
            [
                _file_attachment(
                    "logo.png", "image/png", logo_bytes(), isInline=True, contentId="logo"
                )
            ],
            [],
        )
        for note in message.notes.all():
            for attachment in note.attachments.all():
                if attachment.size <= INLINE_ATTACHMENT_LIMIT:
                    with attachment.file.open("rb") as handle:
                        inline.append(
                            _file_attachment(
                                attachment.filename, attachment.content_type, handle.read()
                            )
                        )
                else:
                    large.append(attachment)
        draft = client.post(
            base,
            json={
                "subject": message.subject,
                "body": {"contentType": "HTML", "content": message.body_html},
                "toRecipients": [{"emailAddress": {"address": a}} for a in message.to_addresses],
                "attachments": inline,
            },
        )
        message.graph_id = draft["id"]
        message.internet_message_id = draft.get("internetMessageId") or None
        message.conversation_id = draft.get("conversationId", "")
        message.save(update_fields=["graph_id", "internet_message_id", "conversation_id"])
        for attachment in large:
            session = client.post(
                f"{base}/{message.graph_id}/attachments/createUploadSession",
                json={
                    "AttachmentItem": {
                        "attachmentType": "file",
                        "name": attachment.filename,
                        "size": attachment.size,
                        "contentType": attachment.content_type or "application/octet-stream",
                    }
                },
            )
            with attachment.file.open("rb") as handle:
                client.upload_large_file(session["uploadUrl"], handle.read())
        client.post(f"{base}/{message.graph_id}/send")
    except Exception as exc:
        message.processing = EmailMessage.Processing.ECHEC
        message.error = f"{type(exc).__name__}: {exc}"[:2000]
        message.save(update_fields=["processing", "error"])
        raise
    message.processing = EmailMessage.Processing.ENVOYE
    message.sent_at = timezone.now()
    message.error = ""
    message.save(update_fields=["processing", "sent_at", "error"])
    return message
