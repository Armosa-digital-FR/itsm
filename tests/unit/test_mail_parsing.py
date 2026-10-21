"""Analyse des e-mails entrants (T035, contracts/email.md)."""

import pytest

from helpdesk.mail.parsing import (
    clean_subject,
    extract_ticket_number,
    header_values,
    html_to_text,
    is_automatic,
    sanitize_html,
    split_quoted,
)


@pytest.mark.parametrize(
    "subject,number",
    [
        ("RE: [T-00042] Imprimante en panne", 42),
        ("[t-123456] objet", 123456),
        ("Problème [T-0042]", None),  # moins de 5 chiffres
        ("Sans référence", None),
        (None, None),
    ],
)
def test_extract_ticket_number(subject, number):
    assert extract_ticket_number(subject) == number


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("RE: TR: Imprimante en panne", "Imprimante en panne"),
        ("Fw: Re: [T-00042] Accès VPN", "Accès VPN"),
        ("re : écran noir", "écran noir"),
        ("Réf : commande", "commande"),
        ("", "(sans objet)"),
    ],
)
def test_clean_subject(subject, expected):
    assert clean_subject(subject) == expected


@pytest.mark.parametrize(
    "headers,sender",
    [
        ({"auto-submitted": "auto-replied"}, "camille@armosa.test"),
        ({"x-auto-response-suppress": "All"}, "camille@armosa.test"),
        ({"precedence": "bulk"}, "camille@armosa.test"),
        ({"precedence": "List"}, "camille@armosa.test"),
        ({"list-id": "<news.armosa.test>"}, "camille@armosa.test"),
        ({}, "noreply@editeur.test"),
        ({}, "no-reply@editeur.test"),
        ({}, "MAILER-DAEMON@armosa.test"),
        ({}, "postmaster@armosa.test"),
    ],
)
def test_emails_automatiques(headers, sender):
    assert is_automatic(headers, sender)


def test_email_humain_non_automatique():
    assert not is_automatic({"auto-submitted": "no"}, "camille.martin@armosa.test")
    assert not is_automatic({}, "noreplyer@armosa.test")


@pytest.mark.parametrize(
    "separator",
    [
        "De : Support <support@armosa.test>",
        "From: Support <support@armosa.test>",
        "Le mar. 20 oct. 2026 à 10:00, Support <support@armosa.test> a écrit :",
        "-----Original Message-----",
        "> ancien message",
    ],
)
def test_split_quoted(separator):
    text = f"Toujours en panne.\nMerci\n{separator}\nVotre ticket a été créé."
    main, quoted = split_quoted(text)
    assert main == "Toujours en panne.\nMerci"
    assert quoted.startswith(separator.strip())


def test_split_quoted_sans_historique():
    assert split_quoted("Bonjour,\nl'écran est noir.") == ("Bonjour,\nl'écran est noir.", "")


def test_sanitize_html_retire_scripts_et_evenements():
    dirty = (
        '<p onclick="x()">Bonjour <script>alert(1)</script>'
        '<img src="x" onerror="alert(2)"><a href="javascript:alert(3)">lien</a>'
        '<iframe src="https://evil.test"></iframe><style>p{}</style></p>'
    )
    clean = sanitize_html(dirty)
    assert "script" not in clean and "onerror" not in clean and "onclick" not in clean
    assert "javascript:" not in clean and "iframe" not in clean and "style" not in clean
    assert "Bonjour" in clean


def test_sanitize_html_reecrit_les_images_inline():
    clean = sanitize_html('<img src="cid:image001@01D0">', {"image001@01D0": "/attachments/7/"})
    assert 'src="/attachments/7/"' in clean


def test_sanitize_html_liens_autorises():
    clean = sanitize_html('<a href="https://armosa.eu">site</a><a href="mailto:a@b.test">m</a>')
    assert 'href="https://armosa.eu"' in clean and 'href="mailto:a@b.test"' in clean
    assert "noopener" in clean


def test_html_to_text():
    text = html_to_text(
        "<html><head><style>p{}</style></head><body><p>Bonjour&nbsp;!</p>"
        "<div>L'écran<br>reste noir.</div><script>x</script></body></html>"
    )
    assert text == "Bonjour !\n\nL'écran\nreste noir."


def test_header_values():
    assert header_values("<a@x> <b@y>\n <c@z>") == ["<a@x>", "<b@y>", "<c@z>"]
    assert header_values(None) == []
