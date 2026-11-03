"""Fiche ticket refondue (design system Armosa v2) : frise, actions de statut, fil, filtres."""

import pytest
from django.urls import reverse

from helpdesk.models import Ticket, TicketNote
from helpdesk.services.lifecycle import change_status
from helpdesk.services.tickets import add_note
from helpdesk.templatetags.helpdesk_tags import hms, initials
from helpdesk.views import _status_actions, _steps, _thread
from tests.factories import TicketFactory

pytestmark = pytest.mark.django_db
S = Ticket.Status


def labels(actions):
    return [(a["label"], a["primary"]) for a in actions]


def test_frise_en_quatre_etapes_avec_sous_etat_d_attente(technician):
    ticket = TicketFactory(qualified=True, status=S.EN_ATTENTE)
    steps = _steps(ticket)
    assert [s["name"] for s in steps] == ["Nouveau", "En cours", "Résolu", "Fermé"]
    assert [s["state"] for s in steps] == ["done", "current", "todo", "todo"]
    assert steps[1]["detail"] == "En attente"
    assert steps[2]["at"] is None


def test_actions_ticket_cree_non_affecte(technician):
    ticket = TicketFactory(status=S.CREE)
    actions = _status_actions(ticket, technician, [S.PRIS_EN_COMPTE, S.RESOLU])
    # « Prendre le ticket » remplace la prise en compte et devient l'action principale.
    assert labels(actions) == [("Résoudre le ticket", False), ("Prendre le ticket", True)]


def test_actions_ticket_en_cours_puis_resolu(technician):
    ticket = TicketFactory(qualified=True, status=S.PRIS_EN_COMPTE, assignee=technician)
    actions = _status_actions(ticket, technician, [S.ATTENTE_REPONSE, S.EN_ATTENTE, S.RESOLU])
    assert labels(actions)[-1] == ("Résoudre le ticket", True)
    assert actions[-1]["kind"] == "resolve"
    ticket.status = S.RESOLU
    actions = _status_actions(ticket, technician, [S.FERME, S.PRIS_EN_COMPTE])
    assert labels(actions) == [("Rouvrir le ticket", False), ("Fermer le ticket", True)]


def test_fil_regroupe_les_evenements_entre_les_messages():
    items = [
        {"type": "event", "at": 1},
        {"type": "email", "at": 2},
        {"type": "note", "at": 3},
        {"type": "event", "at": 4},
    ]
    thread = _thread(items)
    assert [t["type"] for t in thread] == ["events", "note", "events"]
    assert len(thread[0]["items"]) == 2


def test_filtres_initiales_et_duree():
    assert initials("Camille Martin") == "CM"
    assert initials("Jean-Pierre de la Tour") == "JT"
    assert initials("support@armosa.test") == "SU"
    assert initials("") == "?"
    assert hms(3725) == "01:02:05"
    assert hms(400 * 3600) == "400:00:00"
    assert hms(None) == "00:00:00"


def test_fiche_affiche_la_conversation_et_le_bandeau(technician_client, technician):
    ticket = TicketFactory(qualified=True, status=S.PRIS_EN_COMPTE, assignee=technician)
    add_note(ticket, technician, TicketNote.Visibility.INTERNE, "Vérifier le tiroir 2.")
    content = technician_client.get(
        reverse("helpdesk:ticket_detail", args=[ticket.number])
    ).content.decode()
    assert 'class="msg msg-internal"' in content and "Vérifier le tiroir 2." in content
    assert 'aria-current="step"' in content and "Résoudre le ticket" in content
    assert "Enregistrer la note" in content  # note interne par défaut : pas d'e-mail par erreur


def test_resolution_affichee_une_fois_resolu(technician_client, technician):
    ticket = TicketFactory(qualified=True, status=S.PRIS_EN_COMPTE, assignee=technician)
    change_status(ticket, S.RESOLU, technician, resolution="Rouleau remplacé.")
    content = technician_client.get(
        reverse("helpdesk:ticket_detail", args=[ticket.number])
    ).content.decode()
    assert 'id="resolution-title"' in content and "Rouleau remplacé." in content
    assert "Fermer le ticket" in content and "Résolu en" in content
