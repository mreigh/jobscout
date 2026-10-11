"""Text helpers shared by collectors: HTML to plain text, pay ranges, remote hints."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: str | None) -> str | None:
    """Plain text from HTML. Handles Greenhouse's double-escaped content too."""
    if not raw:
        return None
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)  # Greenhouse sends HTML as escaped entities
    p = _TextExtractor()
    p.feed(raw)
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


# --- Pay ranges -------------------------------------------------------------

_NUM = r"\$\s?(\d{2,3}(?:,\d{3})+(?:\.\d{2})?|\d{2,3}(?:\.\d)?\s?[kK])"
_RANGE = re.compile(_NUM + r"\s*(?:-|–|—|to)\s*(?:USD\s*)?" + _NUM)


def _to_int(s: str) -> int:
    s = s.replace(",", "").replace(" ", "")
    if s[-1] in "kK":
        return int(float(s[:-1]) * 1000)
    return int(float(s))


def salary_from_text(text: str | None) -> tuple[int, int] | None:
    """The first plausible annual USD range in a description ($120,000 - $150,000, $120k-$150k).
    Hourly rates and nonsense are ignored: both ends must land between $30k and $1M."""
    if not text:
        return None
    for m in _RANGE.finditer(text):
        lo, hi = _to_int(m.group(1)), _to_int(m.group(2))
        if 30_000 <= lo <= hi <= 1_000_000:
            return lo, hi
    return None


# --- Remote hints -----------------------------------------------------------

_REMOTE = re.compile(r"\bremote\b|\bwork from home\b|\banywhere\b", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)


def remote_from(*hints: str | None) -> bool | None:
    """True if any hint says remote (and none says hybrid), False if hybrid, None if silent."""
    text = " ".join(h for h in hints if h)
    if not text:
        return None
    if _HYBRID.search(text):
        return False
    if _REMOTE.search(text):
        return True
    return None


# --- Dates ------------------------------------------------------------------


def iso_date(value) -> str | None:
    """ISO date from an ISO string or epoch milliseconds."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, UTC).date().isoformat()
    s = str(value)
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else None


_POSTED = re.compile(r"(\d+)\+?\s+days?\s+ago", re.I)


def workday_posted(text: str | None, today=None) -> str | None:
    """Workday says 'Posted Today', 'Posted Yesterday', 'Posted 3 Days Ago',
    'Posted 30+ Days Ago'."""
    if not text:
        return None
    today = today or datetime.now(UTC).date()
    t = text.lower()
    if "today" in t:
        return today.isoformat()
    if "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    m = _POSTED.search(t)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    return None
