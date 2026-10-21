"""Base de résolution : recherche plein texte et suggestions (US6, FR-041, FR-042)."""

import re

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import F, Q

from helpdesk.models import Ticket

CONFIG = "french_unaccent"
# Marqueurs neutres : ts_headline n'échappe pas le HTML ; le gabarit échappe tout le texte
# puis transforme ces marqueurs en <mark> (filtre `highlight`).
MARK_START, MARK_STOP = "\x02", "\x03"
STOPWORDS = {
    "le",
    "la",
    "les",
    "de",
    "des",
    "du",
    "un",
    "une",
    "et",
    "ou",
    "a",
    "au",
    "aux",
    "en",
    "pour",
    "sur",
    "pas",
    "ne",
    "plus",
    "est",
    "mon",
    "ma",
    "mes",
    "je",
    "il",
}


def closed_tickets():
    return Ticket.objects.filter(status=Ticket.Status.FERME).select_related(
        "category__parent__parent", "tool", "subsidiary", "site"
    )


def search(
    query: str = "", *, category=None, tool=None, subsidiary=None, date_from=None, date_to=None
):
    """Tickets fermés correspondant à la recherche, classés par pertinence (`ts_rank`)."""
    qs = closed_tickets()
    if category is not None:
        qs = qs.filter(
            Q(category=category)
            | Q(category__parent=category)
            | Q(category__parent__parent=category)
        )
    if tool is not None:
        qs = qs.filter(tool=tool)
    if subsidiary is not None:
        qs = qs.filter(subsidiary=subsidiary)
    if date_from:
        qs = qs.filter(closed_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(closed_at__date__lte=date_to)
    query = (query or "").strip()
    if not query:
        return qs.order_by("-closed_at")
    search_query = SearchQuery(query, config=CONFIG, search_type="websearch")
    return (
        qs.filter(search_vector=search_query)
        .annotate(
            rank=SearchRank(F("search_vector"), search_query),
            excerpt=SearchHeadline(
                "resolution",
                search_query,
                config=CONFIG,
                start_sel=MARK_START,
                stop_sel=MARK_STOP,
                max_words=30,
                min_words=10,
            ),
        )
        .order_by("-rank", "-closed_at")
    )


def _keywords(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[\wÀ-ÿ'-]{3,}", (text or "").lower())
    seen, result = set(), []
    for word in words:
        if word not in STOPWORDS and word not in seen:
            seen.add(word)
            result.append(word)
    return result[:limit]


def suggestions(ticket: Ticket, limit: int = 5):
    """Résolutions de tickets fermés de même catégorie ou même outil, classées par proximité
    du texte (titre et description du ticket)."""
    criteria = Q()
    if ticket.category_id:
        criteria |= Q(category_id=ticket.category_id)
    if ticket.tool_id:
        criteria |= Q(tool_id=ticket.tool_id)
    if not criteria:
        return Ticket.objects.none()
    qs = closed_tickets().filter(criteria).exclude(pk=ticket.pk).exclude(resolution="")
    words = _keywords(f"{ticket.title} {ticket.description}")
    if words:
        search_query = None
        for word in words:
            term = SearchQuery(word, config=CONFIG, search_type="plain")
            search_query = term if search_query is None else search_query | term
        qs = qs.annotate(rank=SearchRank(F("search_vector"), search_query)).order_by(
            "-rank", "-closed_at"
        )
    else:
        qs = qs.order_by("-closed_at")
    return qs[:limit]
