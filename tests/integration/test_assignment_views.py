"""Affectation automatique dans l'interface et l'admin (T061, US2)."""

import pytest
from django.urls import reverse

from core.models import AuditEntry
from directory.signals import directory_user_deactivated
from helpdesk.models import Skill, Ticket, TicketEvent
from tests.factories import (
    AccountFactory,
    CategoryFactory,
    TechnicianGroupFactory,
    TicketFactory,
    ToolFactory,
)

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def qualify(client, ticket, tool):
    return client.post(
        reverse("helpdesk:ticket_qualify", args=[ticket.number]),
        {
            "type": "incident",
            "category": CategoryFactory().pk,
            "tool": tool.pk,
            "priority": "normale",
            "subsidiary": ticket.subsidiary.pk,
        },
        **HX,
    )


def test_qualification_avec_outil_affecte_et_l_affiche(technician_client):
    tool = ToolFactory(name="ERP")
    expert = AccountFactory(directory_user__display_name="Zoé Bonnet")
    Skill.objects.create(technician=expert, tool=tool)
    ticket = TicketFactory()
    content = qualify(technician_client, ticket, tool).content.decode()
    ticket.refresh_from_db()
    assert ticket.assignee == expert
    assert "Zoé Bonnet" in content and "affectation automatique" in content


def test_membre_du_groupe_prend_le_ticket(client):
    group = TechnicianGroupFactory(name="Réseau")
    member = AccountFactory()
    group.members.add(member)
    ticket = TicketFactory(qualified=True)
    qualify_ticket = ToolFactory(default_group=group)
    client.force_login(member)
    qualify(client, ticket, qualify_ticket)
    ticket.refresh_from_db()
    assert ticket.assigned_group == group and ticket.assignee is None
    listing = client.get(reverse("helpdesk:ticket_list"), {"assignee": "mes_groupes"})
    assert ticket in list(listing.context["page"])
    client.post(reverse("helpdesk:ticket_take", args=[ticket.number]))
    ticket.refresh_from_db()
    assert ticket.assignee == member and ticket.assigned_group == group
    assert ticket.status == Ticket.Status.PRIS_EN_COMPTE


def test_reaffectation_manuelle_bloque_l_affectation_automatique(technician_client, technician):
    tool = ToolFactory()
    Skill.objects.create(technician=AccountFactory(), tool=tool)
    ticket = TicketFactory()
    technician_client.post(
        reverse("helpdesk:ticket_assign", args=[ticket.number]), {"assignee": technician.pk}
    )
    qualify(technician_client, ticket, tool)
    ticket.refresh_from_db()
    assert ticket.assignee == technician
    assert ticket.events.filter(kind=TicketEvent.Kind.AFFECTATION, data__mode="manuel").exists()


def test_file_de_dispatch(technician_client):
    group = TechnicianGroupFactory()
    waiting = TicketFactory(title="Personne")
    TicketFactory(title="Groupe", assigned_group=group)
    TicketFactory(title="Quelqu'un", assignee=AccountFactory())
    for params in ({"view": "dispatch"}, {"assignee": "aucun"}):
        page = technician_client.get(reverse("helpdesk:ticket_list"), params).context["page"]
        assert list(page) == [waiting]


def test_admin_competences_auditees(admin_client_itsm):
    tool = ToolFactory(name="VPN")
    tech = AccountFactory(directory_user__display_name="Nathan Dupont")
    response = admin_client_itsm.post(
        reverse("admin:helpdesk_tool_change", args=[tool.pk]),
        {
            "name": "VPN",
            "description": "",
            "is_active": "on",
            "skills-TOTAL_FORMS": "1",
            "skills-INITIAL_FORMS": "0",
            "skills-MIN_NUM_FORMS": "0",
            "skills-MAX_NUM_FORMS": "1000",
            "skills-0-technician": tech.pk,
            "skills-0-id": "",
            "skills-0-tool": tool.pk,
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    assert Skill.objects.filter(tool=tool, technician=tech).exists()
    entry = AuditEntry.objects.get(action="skill.change")
    assert entry.details["ajouts"] == ["Nathan Dupont · VPN"]


def test_admin_membres_de_groupe_audites(admin_client_itsm):
    group = TechnicianGroupFactory(name="Poste de travail")
    tech = AccountFactory(directory_user__display_name="Hugo Girard")
    inactive = AccountFactory(is_active=False)
    url = reverse("admin:helpdesk_techniciangroup_change", args=[group.pk])
    form = admin_client_itsm.get(url).context["adminform"].form
    assert inactive not in form.fields["members"].queryset
    admin_client_itsm.post(url, {"name": group.name, "email": "", "members": [tech.pk]})
    entry = AuditEntry.objects.get(action="group.change")
    assert entry.details["ajouts"] == ["Hugo Girard"]


def test_desactivation_retire_competences_et_groupes():
    tech = AccountFactory()
    group = TechnicianGroupFactory()
    group.members.add(tech)
    Skill.objects.create(technician=tech, tool=ToolFactory(name="Teams"))
    directory_user_deactivated.send(sender=None, user=tech.directory_user)
    assert not Skill.objects.filter(technician=tech).exists()
    assert not group.members.exists()
    entry = AuditEntry.objects.get(action="skill.change")
    assert entry.details["retraits"] == ["Teams"] and entry.actor is None
