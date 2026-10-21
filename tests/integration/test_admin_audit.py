"""Audit des suppressions faites via l'admin (T025, FR-071)."""

from datetime import date

import pytest
from django.urls import reverse

from core.models import AuditEntry, ClosureDay

pytestmark = pytest.mark.django_db


def test_suppression_unitaire_auditee(admin_client_itsm, admin_account):
    day = ClosureDay.objects.create(date=date(2026, 12, 26), label="Pont")
    url = reverse("admin:core_closureday_delete", args=[day.pk])
    response = admin_client_itsm.post(url, {"post": "yes"})
    assert response.status_code == 302
    entry = AuditEntry.objects.get(action="admin.delete")
    assert entry.actor == admin_account
    assert entry.target_type == "core.ClosureDay"
    assert entry.target_id == str(day.pk)
    assert "Pont" in entry.details["objet"]


def test_suppression_groupee_auditee_pour_chaque_objet(admin_client_itsm):
    days = [ClosureDay.objects.create(date=date(2026, 12, d)) for d in (24, 26, 31)]
    response = admin_client_itsm.post(
        reverse("admin:core_closureday_changelist"),
        {"action": "delete_selected", "_selected_action": [d.pk for d in days], "post": "yes"},
    )
    assert response.status_code == 302
    assert not ClosureDay.objects.exists()
    audited = set(
        AuditEntry.objects.filter(action="admin.delete").values_list("target_id", flat=True)
    )
    assert audited == {str(d.pk) for d in days}
