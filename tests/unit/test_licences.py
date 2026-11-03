"""Licences : postes consommés, dépassements, expirations (T076, FR-064)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from inventory.services import licences
from tests.factories import DirectoryUserFactory, EquipmentFactory, LicenceFactory

pytestmark = pytest.mark.django_db


def test_postes_consommes_et_depassement():
    licence = LicenceFactory(seats=2)
    licence.assigned_users.add(DirectoryUserFactory(), DirectoryUserFactory())
    assert licences.seats_used(licence) == 2 and not licences.is_over_allocated(licence)
    licence.assigned_equipment.add(EquipmentFactory())
    assert licences.seats_used(licence) == 3 and licences.is_over_allocated(licence)
    assert list(licences.over_allocated()) == [licence]


def test_expiration_sous_30_jours():
    today = timezone.localdate()
    soon = LicenceFactory(expires_at=today + timedelta(days=20))
    LicenceFactory(expires_at=today + timedelta(days=60))
    LicenceFactory(expires_at=None)  # perpétuelle
    assert list(licences.expiring_soon()) == [soon]


def test_etat_d_affichage():
    today = timezone.localdate()
    expired = licences.licence_state(LicenceFactory(expires_at=today - timedelta(days=1)))
    assert expired["expired"] and not expired["expiring"]
    soon = licences.licence_state(LicenceFactory(expires_at=today + timedelta(days=3)))
    assert soon["expiring"] and not soon["over"]
