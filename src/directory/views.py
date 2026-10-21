"""Vues de l'annuaire : fiche personne (FR-065)."""

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
