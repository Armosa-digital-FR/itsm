"""Fermeture automatique, réactions à l'annuaire, fiche personne, commandes, admin (US1)."""

from pathlib import Path

import pytest
import time_machine
from django.core.management import call_command
from django.urls import reverse

from core.models import Settings
from directory.signals import directory_user_deactivated
from helpdesk.models import Category, Ticket
from helpdesk.services.lifecycle import change_status
from helpdesk.services.tickets import auto_close_due
from helpdesk.tasks import auto_close
from tests.factories import AccountFactory, CategoryFactory, TicketFactory

pytestmark = pytest.mark.django_db
MAIL = Path(__file__).parent.parent / "fixtures" / "mail"


def resolved_ticket(technician, when):
    with time_machine.travel(when, tick=False):
        ticket = TicketFactory(qualified=True, status=Ticket.Status.PRIS_EN_COMPTE)
        change_status(ticket, Ticket.Status.RESOLU, technician, resolution="Fait.")
    return ticket


def test_fermeture_automatique_apres_5_jours_ouvres(technician):
    # Résolu le mercredi 21/10 à 10:00 → fermeture possible le mercredi 28/10 à 10:00.
    ticket = resolved_ticket(technician, "2026-10-21 10:00 +0200")
    with time_machine.travel("2026-10-28 09:59 +0100", tick=False):
        assert auto_close_due() == 0
    with time_machine.travel("2026-10-28 10:01 +0100", tick=False):
        assert auto_close(0) == 1
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.FERME and ticket.closed_at


def test_delai_de_fermeture_parametrable(technician):
    conf = Settings.load()
    conf.auto_close_business_days = 1
    conf.save()
    resolved_ticket(technician, "2026-10-21 10:00 +0200")
    with time_machine.travel("2026-10-22 10:01 +0200", tick=False):
        assert auto_close_due() == 1


def test_technicien_desactive_alerte_les_administrateurs(monkeypatch):
    alerts = []
    monkeypatch.setattr("helpdesk.receivers.alert_admins", lambda s, b: alerts.append((s, b)))
    leaving = AccountFactory()
    TicketFactory(assignee=leaving)
    TicketFactory(assignee=leaving, status=Ticket.Status.FERME)
    directory_user_deactivated.send(sender=None, user=leaving.directory_user)
    assert alerts and "1 ticket(s)" in alerts[0][1]


def test_utilisateur_sans_compte_ne_declenche_rien(monkeypatch):
    alerts = []
    monkeypatch.setattr("helpdesk.receivers.alert_admins", lambda s, b: alerts.append(s))
    ticket = TicketFactory()
    directory_user_deactivated.send(sender=None, user=ticket.requester)
    assert alerts == []


def test_bloc_tickets_sur_la_fiche_personne(technician_client):
    ticket = TicketFactory(title="Clavier HS")
    response = technician_client.get(reverse("directory:person", args=[ticket.requester.entra_id]))
    content = response.content.decode()
    assert "Clavier HS" in content and ticket.reference in content
    assert f"?requester={ticket.requester.pk}" in content


def test_creation_preremplie_depuis_la_fiche(technician_client):
    ticket = TicketFactory()
    response = technician_client.get(
        reverse("helpdesk:ticket_new"), {"requester": ticket.requester.pk}
    )
    assert str(ticket.requester) in response.content.decode()


def test_inject_email(capsys):
    conf = Settings.load()
    conf.support_mailboxes = ["support@armosa.test"]
    conf.save()
    call_command(
        "inject_email", str(MAIL / "expediteur_inconnu_interne.eml"), str(MAIL / "liste.eml")
    )
    out = capsys.readouterr().out
    assert "ticket_cree → T-" in out and "ignore_automatique" in out
    assert Ticket.objects.count() == 1


def test_admin_categories_limite_a_3_niveaux(admin_client_itsm):
    level1 = CategoryFactory(name="Matériel")
    level2 = CategoryFactory(name="Impression", parent=level1)
    level3 = CategoryFactory(name="Bourrage", parent=level2)
    response = admin_client_itsm.post(
        reverse("admin:helpdesk_category_add"),
        {"name": "Niveau 4", "parent": level3.pk, "position": 0, "is_active": "on"},
    )
    assert response.status_code == 200  # formulaire réaffiché avec erreur
    assert not Category.objects.filter(name="Niveau 4").exists()
    admin_client_itsm.post(
        reverse("admin:helpdesk_category_add"),
        {"name": "Scan", "parent": level2.pk, "position": 0, "is_active": "on"},
    )
    assert Category.objects.get(name="Scan").level == 3


def test_admin_desactivation_de_categorie(admin_client_itsm):
    category = CategoryFactory()
    admin_client_itsm.post(
        reverse("admin:helpdesk_category_changelist"),
        {"action": "deactivate", "_selected_action": [category.pk]},
    )
    category.refresh_from_db()
    assert not category.is_active


def test_admin_suppression_d_outil_auditee(admin_client_itsm):
    from core.models import AuditEntry
    from tests.factories import ToolFactory

    tool = ToolFactory(name="Ancien logiciel")
    admin_client_itsm.post(reverse("admin:helpdesk_tool_delete", args=[tool.pk]), {"post": "yes"})
    entry = AuditEntry.objects.get(action="admin.delete")
    assert entry.target_type == "helpdesk.Tool" and "Ancien logiciel" in entry.details["objet"]
