"""Délais de prise en compte (T066, FR-036, FR-037) — test obligatoire."""

import pytest
import time_machine
from django.utils import timezone

from core.business_time import PARIS, get_calendar
from core.models import Settings
from helpdesk.models import EmailMessage, Ticket, TicketEvent
from helpdesk.services import tickets as svc
from helpdesk.services.lifecycle import change_status
from helpdesk.services.sla import check_ack_deadlines, deadline_state, targets
from tests.factories import (
    AccountFactory,
    CategoryFactory,
    DirectoryUserFactory,
    TechnicianGroupFactory,
)

pytestmark = pytest.mark.django_db


def at(text):
    return timezone.datetime.fromisoformat(text).replace(tzinfo=PARIS)


def create(when, technician, priority="normale"):
    with time_machine.travel(at(when), tick=False):
        return svc.create_manual(
            technician=technician,
            requester=DirectoryUserFactory(),
            title="Panne",
            priority=priority,
        )


@pytest.mark.parametrize(
    "priority,due",
    [
        ("haute", "2026-10-21 11:00"),
        ("normale", "2026-10-21 14:00"),
        ("basse", "2026-10-22 10:00"),
    ],
)
def test_echeance_selon_la_priorite(technician, priority, due):
    ticket = create("2026-10-21 10:00", technician, priority)
    assert ticket.ack_due_at == at(due)


def test_vendredi_17h30_priorite_haute_echeance_lundi_9h30(technician):
    ticket = create("2026-10-23 17:30", technician, "haute")
    assert ticket.ack_due_at == at("2026-10-26 09:30")


def test_cibles_parametrables(technician):
    conf = Settings.load()
    conf.ack_target_high_minutes = 30
    conf.save()
    assert create("2026-10-21 10:00", technician, "haute").ack_due_at == at("2026-10-21 10:30")


def test_priorite_changee_avant_prise_en_compte_recalcule(technician):
    ticket = create("2026-10-21 10:00", technician, "basse")
    with time_machine.travel(at("2026-10-21 10:10"), tick=False):
        svc.qualify(ticket, technician, priority="haute")
    assert ticket.ack_due_at == at("2026-10-21 11:00")


def test_priorite_changee_apres_prise_en_compte_sans_effet(technician):
    ticket = create("2026-10-21 10:00", technician, "basse")
    svc.qualify(ticket, technician, type="incident", category=CategoryFactory())
    change_status(ticket, Ticket.Status.PRIS_EN_COMPTE, technician)
    due = ticket.ack_due_at
    svc.qualify(ticket, technician, priority="haute")
    assert ticket.ack_due_at == due


def test_depassement_marque_et_alerte_une_seule_fois(technician, admin_account):
    ticket = create("2026-10-21 10:00", technician, "haute")
    with time_machine.travel(at("2026-10-21 10:59"), tick=False):
        assert check_ack_deadlines() == 0
    with time_machine.travel(at("2026-10-21 11:01"), tick=False):
        assert check_ack_deadlines() == 1
        assert check_ack_deadlines() == 0  # pas de seconde alerte
    ticket.refresh_from_db()
    assert ticket.ack_breached and ticket.breach_alerted_at
    assert ticket.events.filter(kind=TicketEvent.Kind.ALERTE_DELAI).count() == 1
    alerts = EmailMessage.objects.filter(kind=EmailMessage.Kind.ALERTE_TECHNICIEN, ticket=ticket)
    assert alerts.count() == 1


def test_prise_en_compte_tardive_marquee_depassee(technician):
    ticket = create("2026-10-21 10:00", technician, "haute")
    svc.qualify(ticket, technician, type="incident", category=CategoryFactory())
    with time_machine.travel(at("2026-10-21 12:00"), tick=False):
        change_status(ticket, Ticket.Status.PRIS_EN_COMPTE, technician)
    assert ticket.ack_breached and ticket.ack_business_minutes == 120


def test_destinataires_de_l_alerte(technician, admin_account):
    from helpdesk.services.sla import alert_recipients

    ticket = create("2026-10-21 10:00", technician)
    assert alert_recipients(ticket) == [admin_account.email]  # ni assigné ni groupe
    group = TechnicianGroupFactory()
    member = AccountFactory()
    group.members.add(member)
    ticket.assigned_group = group
    assert alert_recipients(ticket) == [member.email]
    group.email = "reseau@armosa.test"
    assert alert_recipients(ticket) == ["reseau@armosa.test"]
    ticket.assignee = technician
    assert alert_recipients(ticket) == [technician.email]


def test_etat_de_l_echeance(technician):
    ticket = create("2026-10-21 10:00", technician, "normale")  # échéance 14:00 (240 min)
    cal, tgt = get_calendar(), targets()
    assert deadline_state(ticket, at("2026-10-21 11:00"), cal, tgt) == "ok"
    assert deadline_state(ticket, at("2026-10-21 13:30"), cal, tgt) == "bientot"  # 30 < 60
    assert deadline_state(ticket, at("2026-10-21 14:00"), cal, tgt) == "depasse"
