"""Texte enrichi avec images intégrées : description et notes (FR-014c).

L'éditeur envoie du HTML où les images collées sont des URL `data:`. Côté serveur :
1. chaque image `data:` autorisée devient une pièce jointe, référencée par `cid:` ;
2. le HTML est assaini (nh3 : ni script, ni gestionnaire d'événement, ni `data:` restant) ;
3. une version texte est dérivée (recherche, e-mails, aperçus) ;
4. après enregistrement des pièces jointes, `cid:` est réécrit vers l'URL protégée.
"""

import base64
import binascii
import re
import uuid
from dataclasses import dataclass, field

from helpdesk.mail.parsing import html_to_text, sanitize_html
from helpdesk.services.tickets import IncomingFile

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES = 20

# Types acceptés et signature binaire attendue (le type déclaré ne suffit pas).
IMAGE_TYPES = {
    "image/png": ("png", (b"\x89PNG\r\n\x1a\n",)),
    "image/jpeg": ("jpg", (b"\xff\xd8\xff",)),
    "image/gif": ("gif", (b"GIF87a", b"GIF89a")),
    "image/webp": ("webp", (b"RIFF",)),
}

DATA_IMAGE = re.compile(
    r"""(?P<quote>["'])data:(?P<type>image/[a-z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=\s]*)(?P=quote)""",
    re.IGNORECASE,
)


@dataclass
class RichText:
    html: str  # assaini, images référencées en cid:
    text: str
    files: list[IncomingFile] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip() and not self.files


def _valid_image(content_type: str, content: bytes) -> bool:
    expected = IMAGE_TYPES.get(content_type)
    if expected is None:
        return False
    if not any(content.startswith(magic) for magic in expected[1]):
        return False
    return content_type != "image/webp" or content[8:12] == b"WEBP"


def extract_images(html: str) -> tuple[str, list[IncomingFile], list[str]]:
    """Remplace les images `data:` par des `cid:` ; renvoie (html, fichiers, refus)."""
    files: list[IncomingFile] = []
    refused: list[str] = []

    def replace(match: re.Match) -> str:
        content_type = match.group("type").lower()
        number = len(files) + len(refused) + 1
        try:
            content = base64.b64decode(re.sub(r"\s+", "", match.group("data")), validate=True)
        except (binascii.Error, ValueError):
            refused.append(f"image {number} (illisible)")
            return '""'
        if len(files) >= MAX_IMAGES:
            refused.append(f"image {number} (plus de {MAX_IMAGES} images)")
            return '""'
        if len(content) > MAX_IMAGE_BYTES:
            refused.append(f"image {number} (plus de 10 Mo)")
            return '""'
        if not _valid_image(content_type, content):
            refused.append(f"image {number} (format non accepté)")
            return '""'
        content_id = f"img-{uuid.uuid4().hex}"
        extension = IMAGE_TYPES[content_type][0]
        files.append(
            IncomingFile(
                name=f"image-{len(files) + 1}.{extension}",
                content_type=content_type,
                content=content,
                size=len(content),
                content_id=content_id,
            )
        )
        return f'"cid:{content_id}"'

    return DATA_IMAGE.sub(replace, html or ""), files, refused


def prepare(html: str) -> RichText:
    html, files, refused = extract_images(html)
    clean = sanitize_html(html)
    # Une image non retenue laisse src="" : on retire ces balises vides.
    clean = re.sub(r"<img(?![^>]*\bsrc=\"cid:)[^>]*>", "", clean)
    return RichText(html=clean, text=html_to_text(clean), files=files, refused=refused)
