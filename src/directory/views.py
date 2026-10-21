"""Vues de l'annuaire : fiche personne (FR-065)."""

from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from core.auth import technician_required

from .models import DirectoryUser
from .registry import person_blocks


@technician_required
def person_detail(request, entra_id):
    person = get_object_or_404(
        DirectoryUser.objects.select_related("subsidiary", "site", "manager"), entra_id=entra_id
    )
    blocks = [
        {"template": block.template, "context": block.context(person)} for block in person_blocks
    ]
    return render(request, "directory/person.html", {"person": person, "blocks": blocks})


SEARCH_LIMIT = 10


@technician_required
def directory_search(request):
    """Recherche d'un demandeur (FR-014) : 10 utilisateurs actifs max, 2 caractères min."""
    query = (request.GET.get("q") or "").strip()
    people = []
    if len(query) >= 2:
        people = (
            DirectoryUser.objects.filter(is_active=True)
            .filter(Q(display_name__icontains=query) | Q(email__icontains=query))
            .select_related("subsidiary", "site")
            .order_by("display_name")[:SEARCH_LIMIT]
        )
    return render(
        request,
        "directory/partials/search_results.html",
        {"people": people, "query": query, "target": request.GET.get("target", "requester")},
    )
