"""Name matching: the same person can be spelled differently in the form, in a rating
file name and in the config ("Călin", "calin", "Calin_123")."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable, Mapping


def _strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize(name: object) -> str:
    """Comparison key: accents removed, case-folded, letters and digits only (any script).

    A name with no letters or digits at all ("🦊") keeps its own case-folded text, so two
    such people never share the empty key.
    """
    raw = " ".join(str(name or "").split())
    key = re.sub(r"[\W_]+", "", _strip_accents(raw).casefold())
    return key or raw.casefold()


def slug(name: object) -> str:
    """Readable, file-system-safe version of a name ("Călin M." -> "calin-m")."""
    raw = " ".join(str(name or "").split())
    text = re.sub(r"[\W_]+", "-", _strip_accents(raw).casefold()).strip("-")
    if text:
        return text
    return "person-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8] if raw else "unnamed"


class People:
    """Maps any spelling of a person's name to one canonical display name.

    `aliases` comes from the config's [people] table: {display name: [other spellings]}.
    Names not listed there are their own canonical form (trimmed).
    """

    def __init__(self, aliases: Mapping[str, Iterable[str]] | None = None):
        self._by_key: dict[str, str] = {}
        for display, others in (aliases or {}).items():
            self._by_key[normalize(display)] = display
            for other in others:
                self._by_key[normalize(other)] = display

    def canonical(self, raw: object) -> str:
        text = " ".join(str(raw or "").split())
        return self._by_key.get(normalize(text), text)

    def key(self, raw: object) -> str:
        return normalize(self.canonical(raw))

    def same(self, a: object, b: object) -> bool:
        ka, kb = self.key(a), self.key(b)
        return bool(ka) and ka == kb
