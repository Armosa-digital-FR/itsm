"""Pièces jointes stockées dans PostgreSQL (hébergement Render)."""

import pytest
from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse

from core.models import StoredFile
from core.storage import DatabaseStorage
from helpdesk.models import Attachment
from tests.factories import TicketFactory

pytestmark = pytest.mark.django_db

DATABASE_STORAGES = {
    "default": {"BACKEND": "core.storage.DatabaseStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def test_save_open_size_delete():
    storage = DatabaseStorage()
    name = storage.save("tickets/1/capture.png", ContentFile(b"\x89PNG data"))
    assert name == "tickets/1/capture.png"
    assert storage.exists(name)
    assert storage.size(name) == 9
    with storage.open(name) as handle:
        assert handle.read() == b"\x89PNG data"
    storage.delete(name)
    assert not storage.exists(name)
    assert not StoredFile.objects.exists()


def test_same_name_gets_a_distinct_file():
    storage = DatabaseStorage()
    first = storage.save("tickets/1/a.txt", ContentFile(b"un"))
    second = storage.save("tickets/1/a.txt", ContentFile(b"deux"))
    assert first != second
    assert storage.open(first).read() == b"un"
    assert storage.open(second).read() == b"deux"


def test_missing_file():
    storage = DatabaseStorage()
    with pytest.raises(FileNotFoundError):
        storage.open("absent.txt")
    with pytest.raises(FileNotFoundError):
        storage.size("absent.txt")


@override_settings(STORAGES=DATABASE_STORAGES)
def test_attachment_round_trip(technician_client):
    ticket = TicketFactory()
    attachment = Attachment(ticket=ticket, filename="rapport.pdf", content_type="application/pdf")
    attachment.file.save("rapport.pdf", ContentFile(b"%PDF-1.7"), save=False)
    attachment.size = attachment.file.size
    attachment.save()

    stored = StoredFile.objects.get()
    assert stored.name == attachment.file.name
    assert bytes(stored.content) == b"%PDF-1.7"

    response = technician_client.get(reverse("helpdesk:attachment", args=[attachment.pk]))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"%PDF-1.7"

    attachment.file.delete(save=False)
    assert not StoredFile.objects.exists()
