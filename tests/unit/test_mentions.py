"""Mentions « @technicien » des notes internes (FR-014d) : reconnaissance et notification."""

import pytest

from helpdesk.models import EmailMessage, Mention, TicketNote
from helpdesk.services import mentions
from helpdesk.services.tickets import add_note
from tests.factories import AccountFactory, DirectoryUserFactory, TicketFactory

pytestmark = pytest.mark.django_db
V = TicketNote.Visibility


def tech(given, surname, email=None, **extra):
    person = DirectoryUserFactory(
        given_name=given,
        surname=surname,
        display_name=f"{given} {surname}",
        email=email or f"{given}.{surname}@armosa.test".lower(),
    )
    return AccountFactory(directory_user=person, **extra)


def test_formes_reconnues():
    ivan = tech("Ivan", "Martin")
    helene = tech("Hélène", "Durand", email="hdurand@armosa.test")
    assert mentions.find_mentions("@Ivan Martin : peux-tu regarder ?") == [ivan]
    assert mentions.find_mentions("cc @ivan.martin") == [ivan]
    assert mentions.find_mentions("@ivan : peux-tu commenter la solution ?") == [ivan]
    assert mentions.find_mentions("@helene et @HDURAND") == [helene]  # accents et casse ignorés
    assert mentions.find_mentions("Écrire à support@ivan.martin.fr") == []  # adresse e-mail
    assert mentions.find_mentions("@Ivanhoé n'est pas Ivan") == []


def test_prenom_ambigu_auteur_et_comptes_exclus():
    camille_a = tech("Camille", "Martin")
    camille_b = tech("Camille", "Petit")
    tech("Paul", "Sans-role", roles=[])
    tech("Zoé", "Partie", is_active=False)
    assert mentions.find_mentions("@Camille ?") == []  # deux Camille : il faut le nom complet
    assert mentions.find_mentions("@Camille Petit ?") == [camille_b]
    assert mentions.find_mentions("@Camille Martin @Camille Petit", author=camille_a) == [camille_b]
    assert mentions.find_mentions("@Paul Sans-role @Zoé Partie") == []


def test_note_interne_previent_les_mentionnes(django_capture_on_commit_callbacks):
    author = tech("Michael", "Bouchery")
    ivan = tech("Ivan", "Martin")
    lea = tech("Léa", "Roux")
    ticket = TicketFactory(title="VPN instable")
    note = add_note(ticket, author, V.INTERNE, "@ivan @Léa Roux : peux-tu commenter la solution ?")
    assert {m.account for m in note.mentions.all()} == {ivan, lea}
    alert = EmailMessage.objects.get(kind=EmailMessage.Kind.ALERTE_TECHNICIEN, ticket=ticket)
    assert sorted(alert.to_addresses) == ["ivan.martin@armosa.test", "léa.roux@armosa.test"]
    assert alert.subject == f"[ITSM] Michael Bouchery vous a mentionné sur {ticket.reference}"
    assert "peux-tu commenter la solution ?" in alert.body_text
    assert f"/tickets/{ticket.number}/" in alert.body_html


def test_pas_de_mention_hors_note_interne():
    tech("Ivan", "Martin")
    author = tech("Michael", "Bouchery")
    ticket = TicketFactory()
    add_note(ticket, author, V.EXTERNE, "Bonjour, @Ivan Martin reprend votre demande.")
    add_note(ticket, author, V.INTERNE, "Rien à signaler.")
    assert not Mention.objects.exists()
    assert not EmailMessage.objects.filter(kind=EmailMessage.Kind.ALERTE_TECHNICIEN).exists()


def test_lecture_et_mise_en_evidence():
    author = tech("Michael", "Bouchery")
    ivan = tech("Ivan", "Martin")
    first, second = TicketFactory(), TicketFactory()
    note = add_note(first, author, V.INTERNE, "@ivan regarde <ça>")
    add_note(second, author, V.INTERNE, "@Ivan Martin aussi")
    assert mentions.unread_count(ivan) == 2
    assert mentions.mark_read(ivan, first) == 1 and mentions.unread_count(ivan) == 1
    assert mentions.mark_read(ivan) == 1 and mentions.unread_count(ivan) == 0
    html = mentions.highlight("@ivan regarde &lt;ça&gt; <a href='@ivan'>x</a>", note)
    assert html == ("<span class=\"mention\">@ivan</span> regarde &lt;ça&gt; <a href='@ivan'>x</a>")
