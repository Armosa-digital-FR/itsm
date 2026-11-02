"""Mentions « @technicien » dans les notes internes (FR-014d).

Une note interne qui contient « @Prénom Nom », « @prenom.nom » (partie locale de l'e-mail)
ou « @Prénom » (si un seul technicien porte ce prénom) prévient le technicien concerné :
e-mail depuis la boîte du support et pastille « Mentions » dans l'en-tête. Seuls les comptes
actifs techniciens ou administrateurs sont mentionnables ; le contenu ne sort pas de l'équipe.
"""

import re
import unicodedata
from collections import Counter

from django.utils import timezone
from django.utils.html import escape

from directory.models import Account
from helpdesk.mail.outbound import send_technician_alert
from helpdesk.models import Mention, Ticket, TicketNote

EXCERPT_CHARS = 1500


def _fold(text: str) -> str:
    """Comparaison sans casse ni accents : « Hélène » == « helene »."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def mentionable():
    return (
        Account.objects.filter(
            is_active=True, roles__overlap=[Account.ROLE_TECHNICIAN, Account.ROLE_ADMIN]
        )
        .select_related("directory_user")
        .order_by("directory_user__display_name", "username")
    )


def _first_name(account: Account) -> str:
    person = account.directory_user
    if person and person.given_name:
        return person.given_name
    return account.display_name.split(" ")[0] if " " in account.display_name else ""


def aliases(account: Account, unique_first_names: set[str] | None = None) -> set[str]:
    """Formes reconnues après « @ » pour ce technicien (non repliées)."""
    names = {account.display_name}
    if account.email:
        names.add(account.email.split("@")[0])
    first = _first_name(account)
    if first and (unique_first_names is None or _fold(first) in unique_first_names):
        names.add(first)
    return {n.strip() for n in names if n and n.strip()}


def _pattern(names) -> re.Pattern:
    # Les noms longs d'abord : « @Ivan Martin » ne doit pas s'arrêter à « @Ivan ».
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![\w@])@({alternatives})(?![\w-])", re.IGNORECASE)


def find_mentions(text: str, author=None) -> list[Account]:
    candidates = list(mentionable())
    counts = Counter(_fold(_first_name(a)) for a in candidates if _first_name(a))
    unique = {name for name, n in counts.items() if n == 1}
    folded = _fold(text)
    found = []
    for account in candidates:
        if author is not None and account.pk == author.pk:
            continue  # on ne se notifie pas soi-même
        names = {_fold(n) for n in aliases(account, unique)}
        if names and _pattern(names).search(folded):
            found.append(account)
    return found


def notify(note: TicketNote) -> list[Mention]:
    """Enregistre les mentions d'une note interne et prévient les techniciens cités."""
    if note.visibility != TicketNote.Visibility.INTERNE:
        return []
    accounts = find_mentions(note.body_text, note.author)
    mentions = [Mention.objects.create(note=note, account=a) for a in accounts]
    if mentions:
        ticket = note.ticket
        author = note.author.display_name if note.author else "Un technicien"
        excerpt = note.body_text.strip()
        if len(excerpt) > EXCERPT_CHARS:
            excerpt = excerpt[:EXCERPT_CHARS].rstrip() + "…"
        send_technician_alert(
            [a.email for a in accounts],
            f"{author} vous a mentionné sur {ticket.reference}",
            f"{ticket.reference} · {ticket.title}\n\n{author} a écrit :\n{excerpt}",
            ticket=ticket,
        )
    return mentions


def unread_count(account) -> int:
    return Mention.objects.filter(account=account, read_at=None).count()


def mark_read(account, ticket: Ticket | None = None) -> int:
    """Ouvrir le ticket vaut lecture de ses mentions ; sans ticket : tout marquer comme lu."""
    pending = Mention.objects.filter(account=account, read_at=None)
    if ticket is not None:
        pending = pending.filter(note__ticket=ticket)
    return pending.update(read_at=timezone.now())


def highlight(html: str, note: TicketNote) -> str:
    """Met en évidence « @nom » des techniciens mentionnés dans un HTML déjà échappé."""
    names = set()
    for mention in note.mentions.all():
        names |= aliases(mention.account)
    if not names:
        return html
    pattern = _pattern({escape(n) for n in names})
    parts = re.split(r"(<[^>]+>)", html)
    return "".join(
        part if part.startswith("<") else pattern.sub(r'<span class="mention">@\1</span>', part)
        for part in parts
    )
