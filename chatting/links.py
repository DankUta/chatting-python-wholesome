"""Pick apart YouTube links."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = ("youtube.com", "youtube-nocookie.com")


def is_url(text: str) -> bool:
    return bool(re.match(r"^\s*(https?://|www\.)\S+", str(text or ""), re.I))


def _parse(url: str):
    text = str(url or "").strip()
    if not text:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        text = "https://" + text
    try:
        return urlparse(text)
    except ValueError:
        return None


def _host(parsed) -> str:
    host = (parsed.hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def youtube_id(url: str) -> Optional[str]:
    """The 11-character video id of a YouTube link, or None."""
    parsed = _parse(url)
    if parsed is None:
        return None
    host = _host(parsed)
    parts = [p for p in parsed.path.split("/") if p]
    candidate = None
    if host == "youtu.be":
        candidate = parts[0] if parts else None
    elif host == "youtube.com" or host.endswith(".youtube.com") or host.endswith("youtube-nocookie.com"):
        if parts and parts[0] in ("shorts", "embed", "live", "v") and len(parts) > 1:
            candidate = parts[1]
        else:
            candidate = (parse_qs(parsed.query).get("v") or [None])[0]
    if candidate and _ID.match(candidate):
        return candidate
    return None


def _parse_start(text: str) -> Optional[float]:
    text = text.strip().lower()
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?s?", text):
        return float(text.rstrip("s"))
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", text)
    if m and any(m.groups()):
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+)", text)
    if m:
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi) * 60 + int(s)
    return None


def youtube_start_param(url: str) -> Optional[float]:
    """Start offset in seconds from `t=`/`start=`/`#t=`, or None."""
    parsed = _parse(url)
    if parsed is None:
        return None
    queries = [parse_qs(parsed.query)]
    if parsed.fragment:
        queries.append(parse_qs(parsed.fragment))
    for q in queries:
        for key in ("t", "start"):
            if q.get(key):
                value = _parse_start(q[key][0])
                if value is not None:
                    return value
    return None
