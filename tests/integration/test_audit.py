"""Journal d'audit en ajout seul (research R14, constitution II)."""

from datetime import timedelta

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from core import audit
from core.models import AuditEntry

pytestmark = pytest.mark.django_db


def test_modification_refusee_par_la_base(technician):
    entry = audit.record(technician, "test.action", ("x", 1))
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEntry.objects.filter(pk=entry.pk).update(action="falsifie")
    entry.refresh_from_db()
    assert entry.action == "test.action"


def test_suppression_refusee_par_la_base(technician):
    entry = audit.record(technician, "test.action")
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEntry.objects.filter(pk=entry.pk).delete()
    assert AuditEntry.objects.filter(pk=entry.pk).exists()


def test_purge_de_retention_autorisee(technician):
    audit.record(technician, "ancienne")
    recent = audit.record(technician, "recente")
    deleted = audit.purge_before(recent.at)
    assert deleted == 1
    assert list(AuditEntry.objects.values_list("action", flat=True)) == ["recente"]


def test_purge_ne_desactive_pas_la_protection_apres_coup(technician):
    audit.purge_before(timezone.now() - timedelta(days=1))
    entry = audit.record(technician, "apres")
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEntry.objects.filter(pk=entry.pk).delete()
