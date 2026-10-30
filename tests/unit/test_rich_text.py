"""Texte enrichi avec images intégrées (T121, FR-014c)."""

import base64

import pytest

from helpdesk.services.rich_text import MAX_IMAGES, extract_images, prepare

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16


def data_url(content: bytes, kind: str = "image/png") -> str:
    return f"data:{kind};base64,{base64.b64encode(content).decode()}"


@pytest.mark.parametrize(
    "content,kind,ext",
    [
        (PNG, "image/png", "png"),
        (JPEG, "image/jpeg", "jpg"),
        (GIF, "image/gif", "gif"),
        (WEBP, "image/webp", "webp"),
    ],
)
def test_images_acceptees_deviennent_des_pieces_jointes(content, kind, ext):
    html, files, refused = extract_images(f'Voir : <img src="{data_url(content, kind)}" alt="x">')
    assert refused == [] and len(files) == 1
    image = files[0]
    assert (image.content, image.content_type, image.name) == (content, kind, f"image-1.{ext}")
    assert f'src="cid:{image.content_id}"' in html and "data:" not in html


def test_type_declare_ne_suffit_pas():
    _, files, refused = extract_images(f'<img src="{data_url(b"<script>", "image/png")}">')
    assert files == [] and refused == ["image 1 (format non accepté)"]


def test_svg_refuse():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'
    rich = prepare(f'<p>x</p><img src="{data_url(svg, "image/svg+xml")}">')
    assert rich.files == [] and "<img" not in rich.html and "svg" not in rich.html


def test_trop_lourde_et_trop_nombreuses(monkeypatch):
    monkeypatch.setattr("helpdesk.services.rich_text.MAX_IMAGE_BYTES", 10)
    _, files, refused = extract_images(f'<img src="{data_url(PNG)}">')
    assert files == [] and "plus de 10 Mo" in refused[0]
    monkeypatch.undo()
    many = "".join(f'<img src="{data_url(PNG)}">' for _ in range(MAX_IMAGES + 2))
    _, files, refused = extract_images(many)
    assert len(files) == MAX_IMAGES and len(refused) == 2


def test_base64_illisible():
    _, files, refused = extract_images('<img src="data:image/png;base64,abcde">')
    assert files == [] and "illisible" in refused[0]


def test_url_data_hors_motif_supprimee_par_l_assainissement():
    rich = prepare('<p>x</p><img src="data:image/png;base64,@@@@">')
    assert rich.files == [] and "<img" not in rich.html and "data:" not in rich.html


def test_assainissement_et_texte_derive():
    rich = prepare(
        '<div onclick="x()">Écran noir<script>alert(1)</script></div>'
        f'<img src="{data_url(PNG)}" onerror="alert(2)"><a href="javascript:alert(3)">lien</a>'
    )
    assert "script" not in rich.html and "onerror" not in rich.html and "onclick" not in rich.html
    assert "javascript:" not in rich.html
    assert rich.text.startswith("Écran noir") and len(rich.files) == 1


def test_image_seule_n_est_pas_vide():
    assert not prepare(f'<img src="{data_url(PNG)}">').is_empty
    assert prepare("<div><br></div>").is_empty
