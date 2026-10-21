"""Vues des tickets (T039, contracts/ui-routes.md section Tickets)."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from core.models import Settings
from helpdesk.models import EmailMessage, Ticket, TicketEvent, TicketNote
from tests.factories import (
    AccountFactory,
    CategoryFactory,
    DirectoryUserFactory,
    TechnicianGroupFactory,
    TicketFactory,
    ToolFactory,
)

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture(autouse=True)
def conf():
    s = Settings.load()
    s.support_mailboxes = ["support@armosa.test"]
    s.save()


def url(name, ticket=None, **kwargs):
    args = [ticket.number] if ticket is not None else []
    return reverse(f"helpdesk:{name}", args=args, kwargs=kwargs or None)


# --- Création manuelle (FR-014, FR-014a) ----------------------------------------


def test_creation_manuelle(technician_client, technician):
    requester = DirectoryUserFactory()
    category = CategoryFactory(name="Messagerie")
    response = technician_client.post(
        url("ticket_new"),
        {
            "requester": requester.pk,
            "title": "Pas de son en visio",
            "description": "Depuis ce matin.",
            "type": "incident",
            "category": category.pk,
            "priority": "haute",
            "files": [SimpleUploadedFile("capture.png", b"img", content_type="image/png")],
        },
    )
    ticket = Ticket.objects.get()
    assert response.status_code == 302
    assert response["Location"] == url("ticket_detail", ticket)
    assert ticket.channel == Ticket.Channel.APP and ticket.created_by == technician
    assert ticket.requester == requester and ticket.subsidiary == requester.subsidiary
    assert ticket.priority == "haute" and ticket.attachments.count() == 1
    assert ticket.events.get(kind=TicketEvent.Kind.CREATION).new_value == "application"
    assert ticket.emails.filter(kind=EmailMessage.Kind.ACCUSE_RECEPTION).count() == 1


def test_creation_manuelle_sans_demandeur(technician_client):
    response = technician_client.post(url("ticket_new"), {"title": "x", "priority": "normale"})
    assert response.status_code == 200
    assert "Choisissez le demandeur" in response.content.decode()
    assert not Ticket.objects.exists()


def test_recherche_annuaire(technician_client):
    DirectoryUserFactory(display_name="Camille Martin", email="camille@armosa.test")
    DirectoryUserFactory(display_name="Camille Inactive", is_active=False)
    for i in range(12):
        DirectoryUserFactory(display_name=f"Camille {i:02d}")
    content = technician_client.get(reverse("directory:search"), {"q": "camille"}).content.decode()
    assert content.count("data-pick-person") == 10
    assert "Camille Inactive" not in content
    short = technician_client.get(reverse("directory:search"), {"q": "c"}).content.decode()
    assert "data-pick-person" not in short


# --- Fiche et actions -----------------------------------------------------------


def test_fiche_affiche_le_fil_et_marque_la_reponse_lue(technician_client, technician):
    ticket = TicketFactory(assignee=technician, has_unread_reply=True)
    TicketNote.objects.create(
        ticket=ticket,
        visibility="externe",
        direction="entrant",
        author_email="x@armosa.test",
        body_text="Réponse.\nDe : Support\nAncien message",
    )
    response = technician_client.get(url("ticket_detail", ticket))
    content = response.content.decode()
    assert response.status_code == 200
    assert ticket.reference in content and "Réponse du demandeur" in content
    assert "Afficher l'historique cité" in content
    ticket.refresh_from_db()
    assert not ticket.has_unread_reply


def test_qualification_et_prise_en_compte(technician_client, technician):
    ticket = TicketFactory()
    category = CategoryFactory()
    response = technician_client.post(
        url("ticket_qualify", ticket),
        {
            "type": "demande",
            "category": category.pk,
            "priority": "basse",
            "subsidiary": ticket.subsidiary.pk,
        },
        **HX,
    )
    assert response.status_code == 200 and 'id="ticket"' in response.content.decode()
    response = technician_client.post(url("ticket_take", ticket), **HX)
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.PRIS_EN_COMPTE and ticket.assignee == technician
    kinds = set(ticket.events.values_list("kind", flat=True))
    assert {"type", "categorie", "priorite", "statut", "affectation"} <= kinds


def test_prise_en_compte_refusee_sans_qualification(technician_client):
    ticket = TicketFactory()
    response = technician_client.post(
        url("ticket_status", ticket), {"status": "pris_en_compte"}, **HX
    )
    assert response.status_code == 422
    assert "Qualifiez le ticket" in response.content.decode()


def test_resolution_sans_texte_refusee_422(technician_client):
    ticket = TicketFactory(qualified=True, status=Ticket.Status.PRIS_EN_COMPTE)
    response = technician_client.post(
        url("ticket_status", ticket), {"status": "resolu", "resolution": " "}, **HX
    )
    assert response.status_code == 422
    assert "résolution est obligatoire" in response.content.decode()


def test_resolution_puis_fermeture(technician_client):
    ticket = TicketFactory(qualified=True, status=Ticket.Status.PRIS_EN_COMPTE)
    technician_client.post(
        url("ticket_status", ticket), {"status": "resolu", "resolution": "Câble remplacé."}
    )
    technician_client.post(url("ticket_status", ticket), {"status": "ferme"})
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.FERME and ticket.resolution == "Câble remplacé."


def test_notes_interne_et_externe(technician_client):
    ticket = TicketFactory()
    technician_client.post(
        url("ticket_note", ticket), {"visibility": "interne", "body": "Voir avec le fournisseur."}
    )
    technician_client.post(
        url("ticket_note", ticket),
        {
            "visibility": "externe",
            "body": "Pouvez-vous redémarrer ?",
            "files": [SimpleUploadedFile("guide.pdf", b"%PDF", content_type="application/pdf")],
        },
    )
    internal, external = ticket.notes.order_by("id")
    assert internal.email_message is None
    assert external.email_message.kind == EmailMessage.Kind.NOTE_EXTERNE
    assert external.attachments.get().filename == "guide.pdf"


def test_note_vide_refusee(technician_client):
    ticket = TicketFactory()
    response = technician_client.post(
        url("ticket_note", ticket), {"visibility": "interne", "body": ""}, **HX
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "minutes,day,ok",
    [(30, 0, True), (1440, 0, True), (0, 0, False), (1441, 0, False), (30, 1, False)],
)
def test_saisie_de_temps(technician_client, minutes, day, ok):
    ticket = TicketFactory()
    date = (timezone.localdate() + timedelta(days=day)).isoformat()
    response = technician_client.post(
        url("ticket_time", ticket), {"date": date, "minutes": minutes}, **HX
    )
    assert (response.status_code == 200) is ok
    assert ticket.time_entries.exists() is ok


def test_reaffectation_manuelle(technician_client):
    ticket = TicketFactory()
    other, group = AccountFactory(), TechnicianGroupFactory()
    technician_client.post(url("ticket_assign", ticket), {"assignee": other.pk, "group": group.pk})
    ticket.refresh_from_db()
    assert (ticket.assignee, ticket.assigned_group) == (other, group)
    assert ticket.assignment_mode == Ticket.AssignmentMode.MANUEL


def test_reaffectation_en_masse(technician_client):
    leaving, other = AccountFactory(), AccountFactory()
    open_tickets = [TicketFactory(assignee=leaving) for _ in range(3)]
    closed = TicketFactory(assignee=leaving, status=Ticket.Status.FERME)
    response = technician_client.post(
        url("bulk_assign"), {"from_technician": leaving.pk, "assignee": other.pk}
    )
    assert response.status_code == 302
    assert all(Ticket.objects.get(pk=t.pk).assignee == other for t in open_tickets)
    assert Ticket.objects.get(pk=closed.pk).assignee == leaving


# --- Liste, filtres, export -------------------------------------------------------


def test_liste_et_filtres(technician_client, technician):
    mine = TicketFactory(title="Écran noir", assignee=technician, priority="haute")
    TicketFactory(title="Clavier", priority="basse")
    TicketFactory(title="Ancien", status=Ticket.Status.FERME)
    content = technician_client.get(url("ticket_list")).content.decode()
    assert "Écran noir" in content and "Clavier" in content and "Ancien" not in content
    filtered = technician_client.get(url("ticket_list"), {"assignee": "moi"}, **HX)
    assert "Écran noir" in filtered.content.decode() and "Clavier" not in filtered.content.decode()
    by_number = technician_client.get(url("ticket_list"), {"q": mine.reference}).content.decode()
    assert "Écran noir" in by_number and "Clavier" not in by_number
    all_tickets = technician_client.get(url("ticket_list"), {"status": "tous"}).content.decode()
    assert "Ancien" in all_tickets


def test_filtre_par_categorie_inclut_les_sous_categories(technician_client):
    root = CategoryFactory(name="Matériel")
    child = CategoryFactory(name="Imprimante", parent=root)
    TicketFactory(title="Bourrage", category=child)
    TicketFactory(title="Autre sujet")
    content = technician_client.get(url("ticket_list"), {"category": root.pk}).content.decode()
    assert "Bourrage" in content and "Autre sujet" not in content


def test_export_csv(technician_client):
    TicketFactory(title="Écran noir", tool=ToolFactory(name="Teams"))
    response = technician_client.get(url("ticket_export"))
    body = response.content.decode("utf-8-sig")
    assert response["Content-Type"].startswith("text/csv")
    assert body.splitlines()[0].startswith("Référence;Titre;Statut")
    assert "Écran noir" in body and "Teams" in body


# --- Contrôle d'accès ---------------------------------------------------------------

ROUTES = [
    ("get", "ticket_list", False),
    ("get", "ticket_export", False),
    ("get", "ticket_new", False),
    ("post", "bulk_assign", False),
    ("get", "ticket_detail", True),
    ("post", "ticket_qualify", True),
    ("post", "ticket_status", True),
    ("post", "ticket_take", True),
    ("post", "ticket_assign", True),
    ("post", "ticket_note", True),
    ("post", "ticket_time", True),
]


@pytest.mark.parametrize("method,name,with_ticket", ROUTES)
def test_routes_refusees_sans_role(no_role_client, method, name, with_ticket):
    ticket = TicketFactory() if with_ticket else None
    response = getattr(no_role_client, method)(url(name, ticket))
    assert response.status_code == 403


@pytest.mark.parametrize("method,name,with_ticket", ROUTES)
def test_routes_redirigent_les_anonymes(client, method, name, with_ticket):
    ticket = TicketFactory() if with_ticket else None
    response = getattr(client, method)(url(name, ticket))
    assert response.status_code == 302 and response["Location"].startswith("/connexion/")


def test_piece_jointe_protegee(technician_client):
    from django.test import Client

    anonymous = Client()
    ticket = TicketFactory()
    note_file = SimpleUploadedFile("secret.pdf", b"%PDF", content_type="application/pdf")
    from helpdesk.services.tickets import save_files

    save_files(ticket, [note_file])
    attachment = ticket.attachments.get()
    assert anonymous.get(reverse("helpdesk:attachment", args=[attachment.pk])).status_code == 302
    response = technician_client.get(reverse("helpdesk:attachment", args=[attachment.pk]))
    assert response.status_code == 200 and b"".join(response.streaming_content) == b"%PDF"
