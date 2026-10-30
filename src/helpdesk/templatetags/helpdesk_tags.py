"""Filtres d'affichage des tickets (badges toujours accompagnés d'un libellé)."""

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()

STATUS_CLASSES = {
    "cree": "tag-info",
    "pris_en_compte": "",
    "attente_reponse": "tag-warning",
    "en_attente": "tag-muted",
    "resolu": "tag-success",
    "ferme": "tag-muted",
}
PRIORITY_CLASSES = {"haute": "tag-danger", "normale": "tag-plain", "basse": "tag-muted"}


@register.filter
def duration(minutes) -> str:
    """125 → « 2 h 05 » ; 45 → « 45 min »."""
    if minutes in (None, ""):
        return "—"
    minutes = int(minutes)
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"


@register.filter
def business_duration(minutes, day_minutes=540) -> str:
    """Durée ouvrée : 1 230 min avec des journées de 540 min → « 2 j 2 h 30 »."""
    if minutes in (None, ""):
        return "—"
    minutes, day = int(minutes), int(day_minutes or 540)
    days, rest = divmod(minutes, day)
    if not days:
        return duration(rest)
    return f"{days} j {duration(rest)}" if rest else f"{days} j"


@register.simple_tag
def status_tag(ticket):
    return format_html(
        '<span class="tag {}">{}</span>',
        STATUS_CLASSES.get(ticket.status, ""),
        ticket.get_status_display(),
    )


@register.simple_tag
def priority_tag(ticket):
    return format_html(
        '<span class="tag {}">Priorité {}</span>',
        PRIORITY_CLASSES.get(ticket.priority, ""),
        ticket.get_priority_display().lower(),
    )


@register.filter
def highlight(text) -> str:
    """Extrait de recherche : texte échappé, seuls les marqueurs deviennent <mark>."""
    from helpdesk.services.knowledge import MARK_START, MARK_STOP

    escaped = str(escape(text or ""))
    return mark_safe(  # noqa: S308 - tout le texte est échappé avant l'ajout des balises
        escaped.replace(MARK_START, "<mark>").replace(MARK_STOP, "</mark>")
    )


@register.filter
def rich_html(value) -> str:
    """HTML enregistré (déjà assaini) : assaini à nouveau à l'affichage, par précaution."""
    from helpdesk.mail.parsing import sanitize_html

    return mark_safe(sanitize_html(value or ""))  # noqa: S308 - sortie de nh3 (liste blanche)


@register.filter
def elapsed(minutes) -> str:
    """Durée calendaire courte : 50 → « 50 min » ; 1 570 → « 1 j 2 h »."""
    if minutes in (None, ""):
        return "—"
    minutes = int(minutes)
    days, rest = divmod(minutes, 1440)
    if not days:
        return duration(rest)
    hours = rest // 60
    return f"{days} j {hours} h" if hours else f"{days} j"


@register.filter
def initials(name) -> str:
    """« Camille Martin » → « CM » ; « support@x.fr » → « SU » (pastilles d'avatar)."""
    name = str(name or "").split("@")[0].replace(".", " ").replace("-", " ").strip()
    words = [w for w in name.split() if w[:1].isalnum()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()
