"""Mentions dans la fiche, pastille de l'en-tête et page « Mes mentions » (FR-014d)."""

import json

import pytest
from django.test import Client
from django.urls import reverse

from helpdesk.models import EmailMessage, Mention, TicketNote
from helpdesk.services.tickets import add_note
from tests.factories import AccountFactory, DirectoryUserFactory, TicketFactory

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def ivan(db):
    person = DirectoryUserFactory(
        given_name="Ivan", surname="Martin", display_name="Ivan Martin", email="ivan@armosa.test"
    )
    return AccountFactory(directory_user=person)


def as_user(account):
    client = Client()
    client.force_login(account)
    return client


def test_note_avec_mention_depuis_la_fiche(technician_client, technician, ivan):
    ticket = TicketFactory()
    response = technician_client.post(
        reverse("helpdesk:ticket_note", args=[ticket.number]),
        {"visibility": "interne", "body": "@ivan : peux-tu commenter la solution ?"},
        **HX,
    )
    assert response.status_code == 200
    mention = Mention.objects.get()
    assert mention.account == ivan and mention.note.author == technician
    content = response.content.decode()
    assert '<span class="mention">@ivan</span> : peux-tu commenter la solution ?' in content
    assert 'Notifié : Ivan Martin <span class="muted">(non lu)</span>' in content
    assert EmailMessage.objects.filter(
        kind=EmailMessage.Kind.ALERTE_TECHNICIEN, to_addresses=["ivan@armosa.test"]
    ).exists()


def test_composeur_propose_les_collegues(technician_client, technician, ivan):
    AccountFactory(roles=[])  # sans rôle : pas mentionnable
    ticket = TicketFactory()
    content = technician_client.get(
        reverse("helpdesk:ticket_detail", args=[ticket.number])
    ).content.decode()
    start = '<script id="mentionable" type="application/json">'
    people = json.loads(content.split(start)[1].split("</script>")[0])
    assert {"name": "Ivan Martin", "email": "ivan@armosa.test"} in people
    assert technician.display_name not in [p["name"] for p in people]  # pas soi-même
    assert len(people) == 1
    assert "Tapez @ pour prévenir un collègue." in content


def test_pastille_page_et_lecture(technician, ivan):
    first, second = TicketFactory(title="VPN instable"), TicketFactory(title="Imprimante")
    note = add_note(first, technician, TicketNote.Visibility.INTERNE, "@Ivan Martin un avis ?")
    add_note(second, technician, TicketNote.Visibility.INTERNE, "@ivan et celui-ci ?")
    client = as_user(ivan)
    home = client.get(reverse("core:home")).content.decode()
    assert '<span class="count" aria-label="2 non lues">2</span>' in home

    page = client.get(reverse("helpdesk:mentions")).content.decode()
    assert "VPN instable" in page and "Imprimante" in page and page.count("Non lue") == 2
    assert f'href="/tickets/{first.number}/#note-{note.pk}"' in page

    client.get(reverse("helpdesk:ticket_detail", args=[first.number]))  # ouvrir = lire
    assert Mention.objects.filter(read_at=None).count() == 1
    home = client.get(reverse("core:home")).content.decode()
    assert 'aria-label="1 non lue">1</span>' in home

    response = client.post(reverse("helpdesk:mentions"))
    assert response.status_code == 302 and not Mention.objects.filter(read_at=None).exists()
    home = client.get(reverse("core:home")).content.decode()
    assert 'class="count"' not in home and ">Mentions</a>" in home


def test_mentions_reservees_aux_techniciens(no_role_client):
    assert no_role_client.get(reverse("helpdesk:mentions")).status_code == 403
    response = Client().get(reverse("helpdesk:mentions"))
    assert response.status_code == 302
