"""Temps par ticket dans l'interface : chronomètre, mon temps / total, délai de résolution
(T117, FR-035a, FR-035b, FR-037a)."""

import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone

from helpdesk.models import RunningTimer, Ticket, TimeEntry
from helpdesk.services.lifecycle import change_status
from tests.factories import AccountFactory, TicketFactory

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def url(name, ticket):
    return reverse(f"helpdesk:{name}", args=[ticket.number])


def test_chronometre_depuis_la_fiche_et_l_en_tete(technician_client, technician):
    ticket = TicketFactory()
    response = technician_client.post(url("timer_start", ticket), **HX)
    content = response.content.decode()
    assert "Arrêter et enregistrer" in content
    assert 'id="timer-slot" hx-swap-oob="true"' in content  # en-tête mis à jour sans recharger
    page = technician_client.get(reverse("helpdesk:ticket_list")).content.decode()
    assert "timer-chip" in page and ticket.reference in page  # visible sur toutes les pages
    response = technician_client.post(
        url("timer_stop", ticket), {"next": reverse("helpdesk:ticket_list")}
    )
    assert response.status_code == 302 and response["Location"] == reverse("helpdesk:ticket_list")
    assert not RunningTimer.objects.exists()
    assert TimeEntry.objects.get().source == "chrono"


def test_demarrer_ailleurs_arrete_le_precedent(technician_client):
    first, second = TicketFactory(), TicketFactory()
    technician_client.post(url("timer_start", first), **HX)
    response = technician_client.post(url("timer_start", second), **HX)
    assert f"Celui de {first.reference} a été arrêté" in response.content.decode()
    assert RunningTimer.objects.get().ticket == second


def test_mon_temps_et_total_sur_la_fiche(technician_client, technician):
    ticket = TicketFactory()
    TimeEntry.objects.create(
        ticket=ticket, technician=technician, date=timezone.localdate(), minutes=80
    )
    TimeEntry.objects.create(
        ticket=ticket, technician=AccountFactory(), date=timezone.localdate(), minutes=45
    )
    response = technician_client.get(url("ticket_detail", ticket))
    assert response.context["time"]["mine"] == 80 and response.context["time"]["total"] == 125
    content = response.content.decode()
    assert "Mon temps <strong>1 h 20</strong>" in content
    assert "Temps total <strong>2 h 05</strong>" in content


def test_correction_d_une_saisie_par_son_auteur_seulement(client, technician_client, technician):
    ticket = TicketFactory()
    mine = TimeEntry.objects.create(
        ticket=ticket, technician=technician, date=timezone.localdate(), minutes=30
    )
    theirs = TimeEntry.objects.create(
        ticket=ticket, technician=AccountFactory(), date=timezone.localdate(), minutes=30
    )
    today = timezone.localdate().isoformat()
    edit = technician_client.post(
        reverse("helpdesk:time_entry_edit", args=[mine.pk]),
        {"date": today, "minutes": 50, "comment": "x"},
        **HX,
    )
    assert edit.status_code == 200
    mine.refresh_from_db()
    assert mine.minutes == 50
    refused = technician_client.post(
        reverse("helpdesk:time_entry_edit", args=[theirs.pk]), {"date": today, "minutes": 1}, **HX
    )
    assert refused.status_code == 403
    assert (
        technician_client.post(
            reverse("helpdesk:time_entry_delete", args=[theirs.pk]), **HX
        ).status_code
        == 403
    )
    technician_client.post(reverse("helpdesk:time_entry_delete", args=[mine.pk]), **HX)
    assert list(TimeEntry.objects.values_list("pk", flat=True)) == [theirs.pk]


def test_colonne_temps_filtre_et_export(technician_client, technician):
    worked = TicketFactory(title="Travaillé")
    TicketFactory(title="Jamais touché")
    TimeEntry.objects.create(
        ticket=worked, technician=technician, date=timezone.localdate(), minutes=30
    )
    TimeEntry.objects.create(
        ticket=worked, technician=technician, date=timezone.localdate(), minutes=20
    )
    TimeEntry.objects.create(
        ticket=worked, technician=AccountFactory(), date=timezone.localdate(), minutes=15
    )
    listing = technician_client.get(reverse("helpdesk:ticket_list"))
    row = next(t for t in listing.context["page"] if t.title == "Travaillé")
    assert (row.my_minutes, row.total_minutes) == (50, 65)  # sans doublon de jointure
    assert "50 min / 1 h 05" in listing.content.decode()
    mine = technician_client.get(reverse("helpdesk:ticket_list"), {"mon_temps": "on"})
    assert [t.title for t in mine.context["page"]] == ["Travaillé"]
    csv_lines = (
        technician_client.get(reverse("helpdesk:ticket_export"))
        .content.decode("utf-8-sig")
        .splitlines()
    )
    header = csv_lines[0].split(";")
    assert header[-3:] == [
        "Délai de résolution (h ouvrées)",
        "Temps total (min)",
        "Mon temps (min)",
    ]
    worked_line = next(line for line in csv_lines if "Travaillé" in line).split(";")
    assert worked_line[-2:] == ["65", "50"]


def test_delai_de_resolution(technician_client, technician):
    with time_machine.travel("2026-10-21 09:00 +0200", tick=False):
        ticket = TicketFactory(qualified=True, status=Ticket.Status.PRIS_EN_COMPTE)
    with time_machine.travel("2026-10-22 11:30 +0200", tick=False):
        change_status(ticket, Ticket.Status.RESOLU, technician, resolution="Fait.")
    assert ticket.resolution_business_minutes == 540 + 150  # 1 j ouvré + 2 h 30
    content = technician_client.get(url("ticket_detail", ticket)).content.decode()
    assert "1 j 2 h 30 ouvrées" in content
    traites = technician_client.get(
        reverse("helpdesk:ticket_list"), {"onglet": "traites"}
    ).content.decode()
    assert "en 1 j 2 h 30 ouvrées" in traites
    change_status(ticket, Ticket.Status.PRIS_EN_COMPTE, technician)  # réouverture
    assert ticket.resolution_business_minutes is None


def test_delai_moyen_de_resolution_sur_le_suivi(technician_client):
    now = timezone.now()
    for minutes in (60, 120):
        TicketFactory(
            priority="haute",
            status=Ticket.Status.RESOLU,
            resolved_at=now,
            resolution_business_minutes=minutes,
        )
    rates = technician_client.get(reverse("helpdesk:tracking")).context["rates"]
    haute = next(r for r in rates if r["priority"] == "haute")
    assert (haute["avg_resolution"], haute["resolved_count"]) == (90, 2)


def test_filtre_business_duration():
    from helpdesk.templatetags.helpdesk_tags import business_duration

    assert business_duration(45) == "45 min"
    assert business_duration(540) == "1 j"
    assert business_duration(1230) == "2 j 2 h 30"
    assert business_duration(None) == "—"
