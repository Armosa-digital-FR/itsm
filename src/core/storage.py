"""Pièces jointes stockées dans PostgreSQL, pour un hébergement sans stockage objet (Render).

Le web et le worker écrivent tous deux des pièces jointes : la base est leur seul espace
partagé. Les fichiers sont servis par la vue de téléchargement, jamais par une URL directe.
"""

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class DatabaseStorage(Storage):
    def _open(self, name, mode="rb"):
        from core.models import StoredFile

        try:
            content = StoredFile.objects.values_list("content", flat=True).get(name=name)
        except StoredFile.DoesNotExist:
            raise FileNotFoundError(name) from None
        return ContentFile(bytes(content), name=name)

    def _save(self, name, content):
        from core.models import StoredFile

        if hasattr(content, "seek"):
            content.seek(0)
        data = b"".join(content.chunks())
        StoredFile.objects.create(name=name, content=data, size=len(data))
        return name

    def exists(self, name):
        from core.models import StoredFile

        return StoredFile.objects.filter(name=name).exists()

    def delete(self, name):
        from core.models import StoredFile

        StoredFile.objects.filter(name=name).delete()

    def size(self, name):
        from core.models import StoredFile

        try:
            return StoredFile.objects.values_list("size", flat=True).get(name=name)
        except StoredFile.DoesNotExist:
            raise FileNotFoundError(name) from None
