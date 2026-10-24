"""Clip start times: single values ("1:30", "1m30s") and the form's free-text field."""

from __future__ import annotations

import re
from typing import Optional


def parse_time(text: object) -> Optional[float]:
    """Seconds from "1:30", "01:02:03", "90", "90s", "1m30s", "1.30", ...; None if unreadable."""
    s = str(text if text is not None else "").strip().lower()
    if not s or s == "nan":
        return None
    s = s.replace(",", ".") if re.fullmatch(r"\d+,\d+", s) else s
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)", s)
    if m:
        h, mi, sec = m.groups()
        return int(h or 0) * 3600 + int(mi) * 60 + float(sec)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)?", s)
    if m and not re.fullmatch(r"\d+\.\d\d", s):
        return float(m.group(1))
    # "1.30" / "0.45": minutes.seconds typed with a period
    m = re.fullmatch(r"(\d{1,3})\.(\d{2})", s)
    if m and int(m.group(2)) < 60:
        return int(m.group(1)) * 60 + int(m.group(2))
    if m:
        return float(s)
    m = re.fullmatch(
        r"(?:(\d+)\s*h(?:ours?|rs?)?)?\s*(?:(\d+)\s*(?:m|min|mins|minutes?))\s*(?:(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)?)?",
        s,
    )
    if m:
        h, mi, sec = m.groups()
        return int(h or 0) * 3600 + int(mi) * 60 + float(sec or 0)
    return None


def format_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    total = int(round(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# A time as people write it inside the free-text field.
_TIME = (
    r"(?:\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2}(?:\.\d+)?"
    r"|\d+\s*h\s*\d+\s*m(?:\s*\d+\s*s?)?|\d+\s*m(?:in)?\s*\d*\s*s?"
    r"|\d+(?:\.\d+)?\s*s(?:ec)?\b|\d{1,2}[.,]\d{2}\b)"
)
def parse_timestamps_field(text: object, slots: int = 5) -> dict[int, float]:
    """Parse the free-text timestamps field into {slot: seconds}."""
    raw = str(text if text is not None else "")
    if not raw.strip() or raw.strip().lower() == "nan":
        return {}
    found: dict[int, float] = {}
    for line in re.split(r"[\n;]+", raw):
        _numbered_in_line(line, slots, found)
    if found:
        return found
    # No numbered entries: unnumbered times in order.
    times = []
    for line in re.split(r"[\n;,]+", raw):
        line = line.strip()
        if not line:
            continue
        t = parse_time(re.split(r"\s*[-–—]\s*", line)[0])
        if t is None:
            m = re.search(_TIME, line, re.I)
            t = parse_time(m.group(0)) if m else None
        if t is not None:
            times.append(t)
    return {i + 1: t for i, t in enumerate(times) if i < slots}


def _numbered_in_line(line: str, slots: int, found: dict[int, float]) -> None:
    # Split a line on commas that start a new numbered entry ("1: 0:45, 2: 1:20").
    pieces = re.split(r",\s*(?=(?:song\s*|#\s*)?[1-9]\s*[:.)=\-–—\s])", line, flags=re.I)
    for piece in pieces:
        m = re.match(r"\s*(?:song\s*|#\s*)?([1-9])\s*[:.)=\-–—]?\s*(.*)$", piece, re.I | re.S)
        if not m:
            continue
        slot, rest = int(m.group(1)), m.group(2).strip()
        has_sep = bool(re.match(r"\s*(?:song\s*|#\s*)?[1-9]\s*[:.)=\-–—\s]", piece, re.I))
        if not has_sep or slot > slots or slot in found or not rest:
            continue
        t = _leading_time(rest)
        if t is not None:
            found[slot] = t


def _leading_time(rest: str) -> Optional[float]:
    # "1:0:45" -> rest "0:45"; ranges "0:45-1:00" -> start.
    m = re.match(r"(" + _TIME + r")", rest, re.I)
    if not m:
        return None
    return parse_time(m.group(1).strip())
