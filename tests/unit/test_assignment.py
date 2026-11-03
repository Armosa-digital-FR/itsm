"""Règle d'affectation automatique (T060, FR-021 à FR-023, data-model.md)."""

import pytest
import time_machine

from helpdesk.models import Skill, Ticket, TicketEvent
from helpdesk.services import tickets as svc
from helpdesk.services.assignment import auto_assign
from tests.factories import AccountFactory, TechnicianGroupFactory, TicketFactory, ToolFactory

pytestmark = pytest.mark.django_db


def skilled(tool, **kwargs):
    account = AccountFactory(**kwargs)
    Skill.objects.create(technician=account, tool=tool)
    return account


def qualify_with(ticket, tool, actor=None):
    svc.qualify(ticket, actor, tool=tool)
    ticket.refresh_from_db()
    return ticket


def test_cas2_un_seul_technicien_competent():
    tool = ToolFactory(default_group=TechnicianGroupFactory())
    tech = skilled(tool)
    ticket = qualify_with(TicketFactory(), tool)
    assert ticket.assignee == tech and ticket.assigned_group is None
    assert ticket.assignment_mode == Ticket.AssignmentMode.AUTO
    event = ticket.events.get(kind=TicketEvent.Kind.AFFECTATION)
    assert event.actor is None and event.data["mode"] == "auto"


def test_cas3_groupe_de_l_outil():
    group = TechnicianGroupFactory()
    tool = ToolFactory(default_group=group)
    skilled(tool), skilled(tool)
    ticket = qualify_with(TicketFactory(), tool)
    assert ticket.assigned_group == group and ticket.assignee is None


def test_cas3_groupe_sans_competence_individuelle():
    group = TechnicianGroupFactory()
    ticket = qualify_with(TicketFactory(), ToolFactory(default_group=group))
    assert ticket.assigned_group == group


def test_cas4_le_moins_charge():
    tool = ToolFactory()
    busy, free = skilled(tool), skilled(tool)
    TicketFactory(assignee=busy, status=Ticket.Status.PRIS_EN_COMPTE)
    TicketFactory(assignee=free, status=Ticket.Status.FERME)  # fermé : non compté
    ticket = qualify_with(TicketFactory(), tool)
    assert ticket.assignee == free


def test_cas4_egalite_le_moins_recemment_affecte():
    tool = ToolFactory()
    first, second = skilled(tool), skilled(tool)
    with time_machine.travel("2026-10-20 10:00 +0200"):
        t1 = qualify_with(TicketFactory(), tool)
    Ticket.objects.filter(pk=t1.pk).update(status=Ticket.Status.FERME)
    with time_machine.travel("2026-10-21 10:00 +0200"):
        t2 = qualify_with(TicketFactory(), tool)
    assert {t1.assignee, t2.assignee} == {first, second}  # alternance à charge égale


def test_cas5_aucun_competent_file_de_dispatch():
    ticket = qualify_with(TicketFactory(), ToolFactory())
    assert ticket.assignee is None and ticket.assigned_group is None
    assert ticket.assignment_mode == Ticket.AssignmentMode.AUCUN
    assert not ticket.events.filter(kind=TicketEvent.Kind.AFFECTATION).exists()


def test_technicien_inactif_exclu():
    tool = ToolFactory()
    skilled(tool, is_active=False)
    active = skilled(tool)
    assert qualify_with(TicketFactory(), tool).assignee == active


def test_compte_sans_role_exclu():
    tool = ToolFactory()
    skilled(tool, roles=[])
    assert qualify_with(TicketFactory(), tool).assignee is None


def test_non_executee_apres_reaffectation_manuelle(technician):
    tool = ToolFactory()
    skilled(tool)
    ticket = TicketFactory()
    svc.assign(ticket, technician, assignee=technician)
    qualify_with(ticket, tool, technician)
    assert ticket.assignee == technician and ticket.assignment_mode == "manuel"


@pytest.mark.parametrize("status", [Ticket.Status.PRIS_EN_COMPTE, Ticket.Status.EN_ATTENTE])
def test_non_executee_hors_statut_cree(status):
    tool = ToolFactory()
    skilled(tool)
    ticket = qualify_with(TicketFactory(status=status), tool)
    assert ticket.assignee is None


def test_changement_d_outil_reaffecte_ou_rend_au_dispatch():
    tool_a, tool_b, tool_c = ToolFactory(), ToolFactory(), ToolFactory()
    tech_a, tech_b = skilled(tool_a), skilled(tool_b)
    ticket = qualify_with(TicketFactory(), tool_a)
    assert ticket.assignee == tech_a
    ticket = qualify_with(ticket, tool_b)
    assert ticket.assignee == tech_b
    ticket = qualify_with(ticket, tool_c)  # outil sans compétence : retour au dispatch
    assert ticket.assignee is None and ticket.assignment_mode == Ticket.AssignmentMode.AUCUN


def test_creation_manuelle_avec_outil(technician):
    tool = ToolFactory()
    tech = skilled(tool)
    ticket = svc.create_manual(
        technician=technician, requester=TicketFactory().requester, title="ERP bloqué", tool=tool
    )
    ticket.refresh_from_db()
    assert ticket.assignee == tech


def test_auto_assign_idempotent():
    tool = ToolFactory()
    skilled(tool)
    ticket = qualify_with(TicketFactory(), tool)
    assert auto_assign(ticket) is False
    assert ticket.events.filter(kind=TicketEvent.Kind.AFFECTATION).count() == 1
