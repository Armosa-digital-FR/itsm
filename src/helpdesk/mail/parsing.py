"""Analyse des e-mails entrants (contracts/email.md, research R10)."""

import html
import re
from html.parser import HTMLParser

import nh3

TICKET_REF = re.compile(r"\[T-(\d{5,})\]", re.IGNORECASE)
SUBJECT_PREFIX = re.compile(r"^\s*((re|tr|fw|fwd|réf|ref)\s*:\s*)+", re.IGNORECASE)
AUTOMATIC_SENDERS = re.compile(
    r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster)(\+[^@]*)?@", re.IGNORECASE
)

# Séparateurs d'historique cité (Outlook FR/EN, clients courants).
QUOTE_MARKERS = [
    re.compile(r"^\s*-{2,}\s*(message d'origine|original message)\s*-{2,}", re.IGNORECASE),
    re.compile(r"^\s*_{10,}\s*$"),
    re.compile(r"^\s*De\s*:\s*.+", re.IGNORECASE),
    re.compile(r"^\s*From\s*:\s*.+", re.IGNORECASE),
    re.compile(r"^\s*Le .+ a écrit\s*:\s*$", re.IGNORECASE),
    re.compile(r"^\s*On .+ wrote\s*:\s*$", re.IGNORECASE),
    re.compile(r"^\s*>"),
]

ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "cid"}


def extract_ticket_number(subject: str | None) -> int | None:
    match = TICKET_REF.search(subject or "")
    return int(match.group(1)) if match else None


def clean_subject(subject: str | None) -> str:
    """Retire les préfixes de réponse/transfert et la référence de ticket."""
    value = TICKET_REF.sub("", subject or "")
    value = SUBJECT_PREFIX.sub("", value.strip())
    value = re.sub(r"\s{2,}", " ", value).strip(" -–:")
    return value or "(sans objet)"


def is_automatic(headers: dict[str, str], sender: str) -> bool:
    """Règle 3 de contracts/email.md. `headers` : clés en minuscules."""
    auto_submitted = headers.get("auto-submitted", "").strip().lower()
    if auto_submitted and auto_submitted != "no":
        return True
    if "x-auto-response-suppress" in headers:
        return True
    if headers.get("precedence", "").strip().lower() in {"bulk", "junk", "list"}:
        return True
    if "list-id" in headers:
        return True
    return bool(AUTOMATIC_SENDERS.match(sender or ""))


def split_quoted(text: str) -> tuple[str, str]:
    """Sépare le message de l'historique cité : (message, historique)."""
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        if index == 0:
            continue
        if any(marker.match(line) for marker in QUOTE_MARKERS):
            main = "\n".join(lines[:index]).rstrip()
            if main:
                return main, "\n".join(lines[index:]).strip()
    return (text or "").strip(), ""


def sanitize_html(value: str | None, cid_map: dict[str, str] | None = None) -> str:
    """Assainit un corps HTML (nh3, liste blanche) et réécrit les images `cid:`."""
    if not value:
        return ""
    cleaned = nh3.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
    )
    if cid_map:

        def replace(match: re.Match) -> str:
            target = cid_map.get(match.group(1).strip("<>"))
            return f'src="{target}"' if target else 'src=""'

        cleaned = re.sub(r'src="cid:([^"]+)"', replace, cleaned)
    return cleaned


class _TextExtractor(HTMLParser):
    BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "blockquote", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head", "title"}:
            self._skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head", "title"}:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    text = html.unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = [line.rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def header_values(raw: str | None) -> list[str]:
    """Message-IDs d'un en-tête In-Reply-To / References."""
    return re.findall(r"<[^<>\s]+>", raw or "")
