"""Messagerie entrante (FR-010 à FR-013, contracts/email.md, research R10).

Relève de chaque boîte support par requête delta Graph, puis lecture complète de chaque
message. Les règles 1 à 7 du contrat s'appliquent dans l'ordre ; chaque message traité est
déplacé dans « ITSM/Traités » ou « ITSM/Ignorés ».
"""

import base64
import email
import email.policy
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.alerts import alert_admins
from core.graph import GraphClient, GraphNotFound, get_client
from core.models import Settings
from directory.models import SyncRun
from helpdesk.mail.parsing import (
    extract_ticket_number,
    header_values,
    html_to_text,
    is_automatic,
    sanitize_html,
)
from helpdesk.models import EmailMessage, Ticket
from helpdesk.services import tickets as svc

logger = logging.getLogger(__name__)

P = EmailMessage.Processing
RATE_LIMIT_PER_HOUR = 20
MAX_ATTACHMENT_BYTES = svc.MAX_ATTACHMENT_BYTES
FOLDER_ROOT, FOLDER_DONE, FOLDER_IGNORED = "ITSM", "Traités", "Ignorés"
MESSAGE_SELECT = (
    "id,internetMessageId,conversationId,subject,from,toRecipients,body,"
    "receivedDateTime,hasAttachments,internetMessageHeaders"
)


@dataclass
class InboundMessage:
    internet_message_id: str
    subject: str
    from_address: str
    body_html: str = ""
    body_text: str = ""
    headers: dict[str, str] = field(default_factory=dict)  # clés en minuscules
    conversation_id: str = ""
    graph_id: str = ""
    to_addresses: list[str] = field(default_factory=list)
    received_at: datetime | None = None
    files: list[svc.IncomingFile] = field(default_factory=list)

    @property
    def in_reply_to(self) -> str:
        return self.headers.get("in-reply-to", "")

    @property
    def references(self) -> str:
        return self.headers.get("references", "")


@dataclass
class Outcome:
    processing: str
    ticket: Ticket | None = None
    duplicate: bool = False

    @property
    def ignored(self) -> bool:
        return self.processing in (P.IGNORE_AUTOMATIQUE, P.IGNORE_BOUCLE, P.IGNORE_LIMITE)


# --- Règles de traitement (communes à la relève et à inject_email) ---------


def _find_ticket(message: InboundMessage) -> Ticket | None:
    number = extract_ticket_number(message.subject)
    if number:
        ticket = Ticket.objects.filter(number=number).first()
        if ticket:
            return ticket
    ids = header_values(message.in_reply_to) + header_values(message.references)
    if ids:
        sent = (
            EmailMessage.objects.filter(internet_message_id__in=ids, ticket__isnull=False)
            .select_related("ticket")
            .order_by("-created_at")
            .first()
        )
        if sent:
            return sent.ticket
    if message.conversation_id:
        known = (
            EmailMessage.objects.filter(
                conversation_id=message.conversation_id, ticket__isnull=False
            )
            .select_related("ticket")
            .order_by("-created_at")
            .first()
        )
        if known:
            return known.ticket
    return None


def _over_rate_limit(sender: str, now) -> bool:
    # Date de traitement (et non la date annoncée par l'e-mail, falsifiable).
    recent = EmailMessage.objects.filter(
        direction=EmailMessage.Direction.ENTRANT,
        from_address__iexact=sender,
        created_at__gte=now - timedelta(hours=1),
    ).count()
    return recent >= RATE_LIMIT_PER_HOUR


def handle_message(message: InboundMessage, mailbox: str) -> Outcome:
    """Applique les règles 1 à 7 de contracts/email.md."""
    sender = (message.from_address or "").lower()
    now = timezone.now()

    # Règle 1 : doublon.
    if EmailMessage.objects.filter(internet_message_id=message.internet_message_id).exists():
        return Outcome(P.NOTE_AJOUTEE, duplicate=True)

    conf = Settings.load()
    processing = None
    if sender in {m.lower() for m in conf.support_mailboxes} or sender == mailbox.lower():
        processing = P.IGNORE_BOUCLE  # règle 2
    elif is_automatic(message.headers, sender):
        processing = P.IGNORE_AUTOMATIQUE  # règle 3
    elif _over_rate_limit(sender, now):
        processing = P.IGNORE_LIMITE  # règle 4
        _alert_rate_limit(sender, now)

    try:
        with transaction.atomic():
            record = EmailMessage.objects.create(
                direction=EmailMessage.Direction.ENTRANT,
                kind=EmailMessage.Kind.ENTRANT,
                processing=processing or P.NOTE_AJOUTEE,
                mailbox=mailbox,
                graph_id=message.graph_id,
                internet_message_id=message.internet_message_id,
                conversation_id=message.conversation_id[:255],
                in_reply_to=message.in_reply_to,
                references=message.references,
                subject=(message.subject or "")[:998],
                from_address=sender[:254],
                to_addresses=message.to_addresses[:20],
                received_at=message.received_at or now,
            )
            if processing:
                return Outcome(processing)

            body_html = sanitize_html(message.body_html)
            body_text = message.body_text or html_to_text(message.body_html)
            ticket = _find_ticket(message)
            if ticket is not None:  # règles 5 et 6
                result, created = svc.register_requester_reply(
                    ticket,
                    email_message=record,
                    body_text=body_text,
                    body_html=body_html,
                    sender_email=sender,
                    files=message.files,
                )
                outcome = Outcome(P.TICKET_CREE if created else P.NOTE_AJOUTEE, result)
            else:  # règle 7
                ticket = svc.create_from_email(
                    subject=message.subject,
                    body_text=body_text,
                    body_html=body_html,
                    sender_email=sender,
                    mailbox=mailbox,
                    email_message=record,
                    files=message.files,
                )
                outcome = Outcome(P.TICKET_CREE, ticket)
            record.processing = outcome.processing
            record.save(update_fields=["processing"])
            return outcome
    except IntegrityError:
        # Course entre deux relèves : le message a déjà été enregistré.
        return Outcome(P.NOTE_AJOUTEE, duplicate=True)


def _alert_rate_limit(sender: str, now) -> None:
    already = EmailMessage.objects.filter(
        from_address__iexact=sender,
        processing=P.IGNORE_LIMITE,
        created_at__gte=now - timedelta(hours=1),
    ).exists()
    if not already:
        alert_admins(
            "Limite d'e-mails atteinte",
            f"Plus de {RATE_LIMIT_PER_HOUR} e-mails en une heure de {sender} : les suivants "
            "sont ignorés pendant une heure. Vérifiez s'il s'agit d'une boucle ou d'un envoi "
            "automatique.",
        )


# --- Relève Graph -----------------------------------------------------------

_folder_cache: dict[tuple[str, str], str] = {}


def _child_folder(client: GraphClient, mailbox: str, parent: str | None, name: str) -> str:
    key = (mailbox, f"{parent}/{name}")
    if key in _folder_cache:
        return _folder_cache[key]
    base = f"/users/{mailbox}/mailFolders"
    path = f"{base}/{parent}/childFolders" if parent else base
    escaped = name.replace("'", "''")
    found = client.get(path, {"$filter": f"displayName eq '{escaped}'"}).get("value", [])
    folder_id = found[0]["id"] if found else client.post(path, json={"displayName": name})["id"]
    _folder_cache[key] = folder_id
    return folder_id


def ensure_folders(client: GraphClient, mailbox: str) -> tuple[str, str]:
    root = _child_folder(client, mailbox, None, FOLDER_ROOT)
    return (
        _child_folder(client, mailbox, root, FOLDER_DONE),
        _child_folder(client, mailbox, root, FOLDER_IGNORED),
    )


def _parse_graph_message(client: GraphClient, mailbox: str, data: dict) -> InboundMessage:
    headers = {h["name"].lower(): h["value"] for h in data.get("internetMessageHeaders") or []}
    body = data.get("body") or {}
    content = body.get("content") or ""
    is_html = (body.get("contentType") or "").lower() == "html"
    sender = ((data.get("from") or {}).get("emailAddress") or {}).get("address", "")
    to = [(r.get("emailAddress") or {}).get("address", "") for r in data.get("toRecipients") or []]
    message = InboundMessage(
        internet_message_id=data.get("internetMessageId") or f"<graph-{data['id']}>",
        subject=data.get("subject") or "",
        from_address=sender,
        body_html=content if is_html else "",
        body_text="" if is_html else content,
        headers=headers,
        conversation_id=data.get("conversationId") or "",
        graph_id=data["id"],
        to_addresses=[a for a in to if a],
        received_at=parse_datetime(data["receivedDateTime"])
        if data.get("receivedDateTime")
        else None,
    )
    if data.get("hasAttachments") or "cid:" in content:
        message.files = _graph_attachments(client, mailbox, data["id"])
    return message


def _graph_attachments(client: GraphClient, mailbox: str, message_id: str):
    base = f"/users/{mailbox}/messages/{message_id}/attachments"
    listing = client.get(base, {"$select": "id,name,contentType,size,isInline,contentId"})
    files = []
    for item in listing.get("value", []):
        if item.get("@odata.type", "").endswith("itemAttachment"):
            continue  # message joint : non conservé
        size = int(item.get("size") or 0)
        content = None
        if size <= MAX_ATTACHMENT_BYTES:
            content = client.request("GET", f"{base}/{item['id']}/$value").content
        files.append(
            svc.IncomingFile(
                name=item.get("name") or "piece-jointe",
                content_type=item.get("contentType") or "",
                content=content,
                size=size,
                content_id=(item.get("contentId") or "").strip("<>"),
            )
        )
    return files


def _last_delta_token(mailbox: str) -> str:
    run = (
        SyncRun.objects.filter(
            kind=SyncRun.KIND_MAILBOX, mailbox=mailbox, status=SyncRun.STATUS_SUCCESS
        )
        .exclude(delta_token="")
        .order_by("-started_at")
        .first()
    )
    return run.delta_token if run else ""


def poll_mailbox(mailbox: str, client: GraphClient | None = None) -> SyncRun:
    run = SyncRun.objects.create(kind=SyncRun.KIND_MAILBOX, mailbox=mailbox)
    try:
        client = client or get_client()
        done_id, ignored_id = ensure_folders(client, mailbox)
        token = _last_delta_token(mailbox)
        if token:
            pages = client.get_paged(token)
        else:
            pages = client.get_paged(
                f"/users/{mailbox}/mailFolders/inbox/messages/delta", {"$select": "id"}
            )
        delta_link = ""
        for page in pages:
            for item in page.get("value", []):
                if "@removed" in item:
                    continue
                _process_graph_item(client, mailbox, item["id"], run, done_id, ignored_id)
            delta_link = page.get("@odata.deltaLink", delta_link)
        run.status = SyncRun.STATUS_SUCCESS
        run.delta_token = delta_link
    except Exception as exc:
        logger.exception("échec de la relève", extra={"mailbox": mailbox})
        run.status = SyncRun.STATUS_FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
    run.finished_at = timezone.now()
    run.save()
    return run


def _process_graph_item(client, mailbox, message_id, run, done_id, ignored_id) -> None:
    try:
        data = client.get(f"/users/{mailbox}/messages/{message_id}", {"$select": MESSAGE_SELECT})
    except GraphNotFound:
        return  # déjà déplacé ou supprimé
    message = _parse_graph_message(client, mailbox, data)
    outcome = handle_message(message, mailbox)
    if outcome.duplicate or outcome.ignored:
        run.skipped += 1
    elif outcome.processing == P.TICKET_CREE:
        run.created += 1
    else:
        run.updated += 1
    target = ignored_id if outcome.ignored else done_id
    client.post(f"/users/{mailbox}/messages/{message_id}/move", json={"destinationId": target})


# --- Fichiers .eml (inject_email, développement) ------------------------------


def parse_eml(raw: bytes) -> InboundMessage:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    headers = {k.lower(): str(v) for k, v in msg.items()}
    body_html_part = msg.get_body(preferencelist=("html",))
    body_text_part = msg.get_body(preferencelist=("plain",))
    body_parts = {id(body_html_part), id(body_text_part)}
    files = []
    for part in msg.walk():
        if part.is_multipart() or id(part) in body_parts:
            continue
        disposition = part.get_content_disposition()
        if disposition is None and not part.get("Content-ID"):
            continue
        payload = part.get_payload(decode=True) or b""
        files.append(
            svc.IncomingFile(
                name=part.get_filename() or "piece-jointe",
                content_type=part.get_content_type(),
                content=payload if len(payload) <= MAX_ATTACHMENT_BYTES else None,
                size=len(payload),
                content_id=(part.get("Content-ID") or "").strip("<>"),
            )
        )
    received = None
    if msg.get("Date"):
        try:
            received = parsedate_to_datetime(msg["Date"])
        except (TypeError, ValueError):
            received = None
    return InboundMessage(
        internet_message_id=(msg.get("Message-ID") or "").strip()
        or f"<eml-{base64.b32encode(raw[:30]).decode()}>",
        subject=str(msg.get("Subject") or ""),
        from_address=parseaddr(str(msg.get("From") or ""))[1],
        body_html=body_html_part.get_content() if body_html_part else "",
        body_text=body_text_part.get_content() if body_text_part else "",
        headers=headers,
        to_addresses=[addr for _, addr in getaddresses([str(msg.get("To") or "")]) if addr],
        received_at=received,
        files=files,
    )
