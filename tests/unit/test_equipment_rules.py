"""Règles des équipements (T076, FR-061 à FR-063)."""

import pytest

from inventory.models import Equipment, EquipmentEvent, EquipmentType
from inventory.services import equipment as svc
from tests.factories import DirectoryUserFactory, EquipmentFactory, SiteFactory

pytestmark = pytest.mark.django_db


def test_types_initiaux():
    names = set(EquipmentType.objects.values_list("name", flat=True))
    assert {"PC", "Écran", "Imprimante", "Télévision", "Caméra", "Téléphone", "Tablette"} <= names


def test_creation_manuelle_en_stock(technician):
    screen = svc.create_manual(
        technician,
        type=EquipmentType.objects.get(name="Écran"),
        site=SiteFactory(),
        name="Écran 27 pouces",
        serial_number=" cn-0 12 ",
    )
    assert screen.status == "stock" and screen.source == "manuel"
    assert screen.serial_number == "CN-012"
    assert screen.events.get().kind == EquipmentEvent.Kind.CREATION


def test_affectation_passe_en_utilisation_puis_retour_en_stock(technician):
    screen = EquipmentFactory(status="stock")
    person = DirectoryUserFactory()
    svc.assign(screen, technician, person)
    assert screen.status == "en_utilisation" and screen.assigned_to == person
    svc.assign(screen, technician, None)
    assert screen.status == "stock"
    kinds = list(screen.events.values_list("kind", flat=True))
    assert kinds.count("affectation") == 2 and kinds.count("statut") == 2


def test_retrait_sans_retour_en_stock(technician):
    screen = EquipmentFactory(status="en_utilisation", assigned_to=DirectoryUserFactory())
    svc.assign(screen, technician, None, back_to_stock=False)
    assert screen.status == "en_utilisation" and screen.assigned_to is None


def test_champs_intune_ignores_a_l_enregistrement(technician):
    device = EquipmentFactory(
        source=Equipment.Source.INTUNE, name="PC-RENNES-014", serial_number="ABC123"
    )
    new_site = SiteFactory()
    changed = svc.update(
        device,
        technician,
        {
            "name": "renommé",
            "serial_number": "ZZZ",
            "manufacturer": "x",
            "site": new_site,
            "notes": "Bureau 12",
        },
    )
    device.refresh_from_db()
    assert set(changed) == {"site", "notes"}
    assert (device.name, device.serial_number) == ("PC-RENNES-014", "ABC123")
    assert device.site == new_site
    assert device.events.filter(kind=EquipmentEvent.Kind.SITE).exists()


def test_equipement_manuel_modifiable(technician):
    screen = EquipmentFactory(name="Écran")
    svc.update(screen, technician, {"name": "Écran 24 pouces", "serial_number": "new 1"})
    screen.refresh_from_db()
    assert (screen.name, screen.serial_number) == ("Écran 24 pouces", "NEW1")


def test_numero_de_serie_unique_sauf_generique():
    from django.db import IntegrityError, transaction

    EquipmentFactory(serial_number="DUP1")
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentFactory(serial_number="dup1")
    EquipmentFactory(serial_number="To Be Filled By O.E.M.")
    EquipmentFactory(serial_number="to be filled by o.e.m.")  # générique : autorisé
