"""Filtres d'affichage des tickets (badges toujours accompagnés d'un libellé)."""

from django import template
from django.utils.html import format_html

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
