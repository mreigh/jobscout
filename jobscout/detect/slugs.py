"""Turn a company name into the board slugs an ATS is likely to use.

"Proof (formerly Notarize)"    -> proof, notarize
"Partner One (Mortgage Cadence)" -> partnerone, partner-one, mortgagecadence, ...
"CSI (Computer Services Inc.)"  -> csi, computerservices, ...
"Modern Treasury"              -> moderntreasury, modern-treasury, modern
"""

from __future__ import annotations

import re
import unicodedata

# Words that are often dropped from board slugs
_SUFFIXES = {
    "inc", "llc", "ltd", "co", "corp", "corporation", "company", "group", "holdings",
    "technologies", "technology", "tech", "software", "solutions", "systems", "labs",
    "financial", "bank", "the", "formerly",
}
# Second words that are just descriptors, so the first word alone is worth a try:
# "Zest AI" -> zest, "Lumin Digital" -> lumin, "Cornerstone Advisors" -> cornerstone.
# Otherwise a lone first word ("jack", "west", "first") would hit someone else's board.
_DESCRIPTORS = {"ai", "digital", "advisors", "io", "hq", "app", "labs"}
_MAX = 8


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _words(s: str) -> list[str]:
    s = _ascii(s).lower().replace("&", " and ")
    return re.findall(r"[a-z0-9]+", s)


def _variants(words: list[str]) -> list[str]:
    if not words:
        return []
    out = ["".join(words), "-".join(words)]
    trimmed = [w for w in words if w not in _SUFFIXES]
    if trimmed and trimmed != words:
        out += ["".join(trimmed), "-".join(trimmed)]
    # "and" is often dropped: "Baker and Tilly" -> bakertilly
    no_and = [w for w in (trimmed or words) if w != "and"]
    if no_and != (trimmed or words):
        out.append("".join(no_and))
    base = trimmed or words
    if len(base) == 2 and base[1] in _DESCRIPTORS and len(base[0]) >= 4:
        out.append(base[0])
    return out


def slug_candidates(name: str) -> list[str]:
    """Ordered, de-duplicated slug guesses for a company name."""
    main = re.sub(r"\(.*?\)", " ", name)
    parens = re.findall(r"\((.*?)\)", name)

    candidates = _variants(_words(main))
    for p in parens:
        candidates += _variants([w for w in _words(p) if w != "formerly"])

    seen, out = set(), []
    for c in candidates:
        c = c.strip("-")
        if len(c) >= 2 and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:_MAX]
