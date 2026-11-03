"""Machine à états du ticket (T036, FR-030, data-model.md) — test obligatoire."""

from datetime import timedelta

import pytest
import time_machine
from django.utils import timezone

from helpdesk.models import EmailMessage, Ticket, TicketEvent
from helpdesk.services import tickets as svc
from helpdesk.services.lifecycle import (
    TRANSITIONS,
    InvalidTransition,
    allowed_targets,
    change_status,
)
from tests.factories import TicketFactory

pytestmark = pytest.mark.django_db
S = Ticket.Status

EXPECTED = {
    (S.CREE, S.PRIS_EN_COMPTE),
    (S.CREE, S.RESOLU),
    (S.PRIS_EN_COMPTE, S.ATTENTE_REPONSE),
    (S.PRIS_EN_COMPTE, S.EN_ATTENTE),
    (S.ATTENTE_REPONSE, S.PRIS_EN_COMPTE),
    (S.EN_ATTENTE, S.PRIS_EN_COMPTE),
    (S.PRIS_EN_COMPTE, S.RESOLU),
    (S.ATTENTE_REPONSE, S.RESOLU),
    (S.EN_ATTENTE, S.RESOLU),
    (S.RESOLU, S.PRIS_EN_COMPTE),
    (S.RESOLU, S.FERME),
}


def test_table_des_transitions_conforme_au_modele():
    assert TRANSITIONS == EXPECTED


def make(status, **kwargs):
    ticket = TicketFactory(qualified=True, **kwargs)
    Ticket.objects.filter(pk=ticket.pk).update(
        status=status,
        resolution="ok" if status in (S.RESOLU, S.FERME) else "",
        resolved_at=timezone.now() if status == S.RESOLU else None,
    )
    ticket.refresh_from_db()
    return ticket


@pytest.mark.parametrize("source,target", sorted(EXPECTED))
def test_transitions_autorisees(source, target, technician):
    ticket = make(source)
    change_status(ticket, target, technician, resolution="Redémarrage du poste.")
    ticket.refresh_from_db()
    assert ticket.status == target
    event = ticket.events.filter(kind=TicketEvent.Kind.STATUT).last()
    assert (event.old_value, event.new_value) == (S(source).label, S(target).label)
    assert event.actor == technician


FORBIDDEN = [
    (source, target)
    for source in S.values
    for target in S.values
    if source != target and (source, target) not in EXPECTED
]


@pytest.mark.parametrize("source,target", FORBIDDEN)
def test_transitions_refusees(source, target, technician):
    ticket = make(source)
    with pytest.raises(InvalidTransition):
        change_status(ticket, target, technician, resolution="x")
    ticket.refresh_from_db()
    assert ticket.status == source
    assert not ticket.events.filter(kind=TicketEvent.Kind.STATUT).exists()


@pytest.mark.parametrize("missing", ["type", "category", "subsidiary", "requester"])
def test_prise_en_compte_exige_la_qualification(missing, technician):
    ticket = make(S.CREE)
    setattr(ticket, missing, "" if missing == "type" else None)
    with pytest.raises(InvalidTransition, match="Qualifiez"):
        change_status(ticket, S.PRIS_EN_COMPTE, technician)


def test_prise_en_compte_renseigne_date_delai_et_assigne(technician):
    with time_machine.travel("2026-10-21 09:00 +0200", tick=False):
        ticket = TicketFactory(qualified=True)
    with time_machine.travel("2026-10-21 11:30 +0200", tick=False):
        change_status(ticket, S.PRIS_EN_COMPTE, technician)
    assert ticket.acknowledged_at is not None
    assert ticket.ack_business_minutes == 150
    assert ticket.assignee == technician
    assert ticket.events.filter(kind=TicketEvent.Kind.AFFECTATION).exists()


def test_resolution_obligatoire(technician):
    ticket = make(S.PRIS_EN_COMPTE)
    with pytest.raises(InvalidTransition, match="résolution est obligatoire"):
        change_status(ticket, S.RESOLU, technician, resolution="   ")


def test_resolution_directe_depuis_cree(technician):
    ticket = make(S.CREE)
    change_status(ticket, S.RESOLU, technician, resolution="Doublon.")
    assert ticket.acknowledged_at is not None
    assert ticket.resolved_at is not None
    assert ticket.resolution_kind == Ticket.ResolutionKind.TECHNICIEN
    assert ticket.events.filter(kind=TicketEvent.Kind.RESOLUTION).exists()
    assert ticket.emails.filter(kind=EmailMessage.Kind.RESOLUTION).count() == 1


def test_attente_reponse_initialise_les_rappels(technician):
    ticket = make(S.PRIS_EN_COMPTE)
    Ticket.objects.filter(pk=ticket.pk).update(reminders_sent=2)
    ticket.refresh_from_db()
    change_status(ticket, S.ATTENTE_REPONSE, technician)
    assert ticket.waiting_since is not None and ticket.reminders_sent == 0


def test_fermeture_renseigne_la_date(technician):
    ticket = make(S.RESOLU)
    change_status(ticket, S.FERME, technician)
    assert ticket.closed_at is not None


def test_allowed_targets():
    ticket = make(S.RESOLU)
    assert set(allowed_targets(ticket)) == {S.PRIS_EN_COMPTE, S.FERME}


# --- Réponses du demandeur --------------------------------------------------


def reply(ticket):
    message = EmailMessage.objects.create(
        direction=EmailMessage.Direction.ENTRANT,
        kind=EmailMessage.Kind.ENTRANT,
        processing=EmailMessage.Processing.NOTE_AJOUTEE,
        subject=f"RE: [{ticket.reference}] x",
        mailbox="support@armosa.test",
    )
    return svc.register_requester_reply(
        ticket,
        email_message=message,
        body_text="Toujours en panne.",
        body_html="",
        sender_email=ticket.requester.email,
    )


def test_reponse_en_attente_de_reponse_reprend_le_ticket():
    ticket = make(S.ATTENTE_REPONSE)
    result, created = reply(ticket)
    ticket.refresh_from_db()
    assert not created and result == ticket
    assert ticket.status == S.PRIS_EN_COMPTE and ticket.has_unread_reply
    assert ticket.waiting_since is None


def test_reponse_sur_ticket_resolu_le_rouvre():
    ticket = make(S.RESOLU)
    reply(ticket)
    ticket.refresh_from_db()
    assert ticket.status == S.PRIS_EN_COMPTE
    assert ticket.resolved_at is None


def test_reponse_sur_ticket_resolu_apres_le_delai_cree_un_nouveau_ticket():
    ticket = make(S.RESOLU)
    Ticket.objects.filter(pk=ticket.pk).update(resolved_at=timezone.now() - timedelta(days=10))
    ticket.refresh_from_db()
    new, created = reply(ticket)
    ticket.refresh_from_db()
    assert created and ticket.status == S.FERME
    assert new.related_ticket == ticket


@pytest.mark.parametrize("status", [S.CREE, S.PRIS_EN_COMPTE, S.EN_ATTENTE])
def test_reponse_ajoute_une_note_sans_changer_le_statut(status):
    ticket = make(status)
    reply(ticket)
    ticket.refresh_from_db()
    assert ticket.status == status
    assert ticket.notes.get().direction == "entrant"


def test_reponse_sur_ticket_ferme_cree_un_ticket_lie():
    ticket = make(S.FERME)
    new, created = reply(ticket)
    assert created and new.related_ticket == ticket and new.status == S.CREE
    assert new.requester == ticket.requester
