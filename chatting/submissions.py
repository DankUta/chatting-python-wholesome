"""Form responses -> submissions -> numbered songs (and the private id registry)."""

from __future__ import annotations

import csv
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from . import log
from .config import ColumnsConfig, Config
from .links import is_url, youtube_id, youtube_start_param
from .models import Song, SongEntry, Submission
from .names import People, normalize
from .sources import read_table
from .timestamps import format_time, parse_time, parse_timestamps_field

SLOTS = 5


class SubmissionError(Exception):
    pass


@dataclass
class ColumnMap:
    name: Optional[str] = None
    email: Optional[str] = None
    submitted_at: Optional[str] = None
    picture: Optional[str] = None
    timestamps: Optional[str] = None
    titles: dict[int, str] = field(default_factory=dict)    # slot -> header
    artists: dict[int, str] = field(default_factory=dict)
    links: dict[int, str] = field(default_factory=dict)


_SUBMITTED_AT = {
    "timestamp", "marcaj de timp", "marca temporal", "horodateur", "zeitstempel",
    "informazioni cronologiche", "carimbo de data/hora", "sygnatura czasowa",
}
_LINK_KW = r"link|url|youtube|\byt\b"
_ARTIST_KW = r"artist|singer|band|artist[aă]|interpret"
_TITLE_KW = r"title|titlu|song|track|piesa|piesă|melodie"
_TITLE_REPEAT_KW = r"title|titlu|song|piesa|piesă|melodie"
_PICTURE_KW = r"picture|pfp|avatar|photo|image|profile|poz[aă]|imagine|poza"
_NAME_KW = r"name|nickname|username|discord|nume|porecl|who are you"
_SONG_WORDS = r"song|title|artist|link|piesa|piesă|melodie|titlu"


def _norm(header: str) -> str:
    return " ".join(str(header).split()).casefold()


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
             "fourth": 4, "4th": 4, "fifth": 5, "5th": 5}


def _slot_of(header: str) -> Optional[int]:
    header = re.sub(r"\([^)]*\)", " ", header)      # "Name (2 words max)" has no song number
    m = re.search(r"\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\b", header, re.I)
    if m:
        return _ORDINALS[m.group(1).lower()]
    m = re.search(r"(?<![\d.])([1-9])(?![\d])", header)
    return int(m.group(1)) if m and int(m.group(1)) <= SLOTS else None


def _base(header: str) -> str:
    return re.sub(r"\.\d+$", "", _norm(header))


def _override(value: str, headers: list[str], what: str) -> Optional[str]:
    if not value:
        return None
    wanted = _norm(value)
    for h in headers:
        if _norm(h) == wanted:
            return h
    raise SubmissionError(
        f"Column '{value}' ({what}) not found in the responses. Available columns: "
        + ", ".join(f"'{h}'" for h in headers)
    )


def _override_slots(template: str, headers: list[str], what: str) -> dict[int, str]:
    out: dict[int, str] = {}
    if not template:
        return out
    for n in range(1, SLOTS + 1):
        wanted = _norm(template.replace("{n}", str(n)))
        for h in headers:
            if _norm(h) == wanted:
                out[n] = h
                break
        else:
            if "{n}" not in template:
                raise SubmissionError(
                    f"Column '{template}' ({what}) not found in the responses. Available columns: "
                    + ", ".join(f"'{h}'" for h in headers)
                )
    return out


def detect_columns(
    headers: list[str], overrides: ColumnsConfig, warn: Callable[[str], None] = log.warn
) -> ColumnMap:
    headers = [str(h) for h in headers]
    cm = ColumnMap()
    taken: set[str] = set()

    cm.email = _override(overrides.email, headers, "email")
    cm.picture = _override(overrides.picture, headers, "picture")
    cm.timestamps = _override(overrides.timestamps, headers, "timestamps")
    cm.name = _override(overrides.name, headers, "name")
    cm.titles = _override_slots(overrides.song_title, headers, "song title")
    cm.artists = _override_slots(overrides.song_artist, headers, "song artist")
    cm.links = _override_slots(overrides.song_link, headers, "song link")

    for h in headers:
        if _norm(h) in _SUBMITTED_AT:
            cm.submitted_at = h
            break
    taken.update(h for h in (cm.submitted_at, cm.email, cm.picture, cm.timestamps, cm.name) if h)
    taken.update(cm.titles.values())
    taken.update(cm.artists.values())
    taken.update(cm.links.values())

    def free() -> list[str]:
        return [h for h in headers if h not in taken]

    if not cm.email:
        cm.email = next((h for h in free() if _has(r"e-?mail", h)), None)
        if cm.email:
            taken.add(cm.email)
    if not cm.timestamps:
        cands = [h for h in free() if _has(r"time\s*stamps?|start time|where should|minut", h)]
        best = [h for h in cands if _has("timestamps", h)] or cands
        if best:
            cm.timestamps = best[0]
            taken.add(cm.timestamps)
    if not cm.picture:
        cm.picture = next((h for h in free() if _has(_PICTURE_KW, h)), None)
        if cm.picture:
            taken.add(cm.picture)

    if not cm.name:
        cands = [
            h for h in free()
            if _has(_NAME_KW, h) and not _has(_SONG_WORDS, h) and not _has(r"e-?mail", h)
        ]
        exact = [h for h in cands if _norm(h) in ("name", "nickname", "nume")]
        pick = (exact or cands or [None])[0]
        cm.name = pick
        if pick:
            taken.add(pick)

    # numbered song columns: link, then artist, then title
    for target, kw, given in (
        (cm.links, _LINK_KW, bool(overrides.song_link)),
        (cm.artists, _ARTIST_KW, bool(overrides.song_artist)),
        (cm.titles, _TITLE_KW, bool(overrides.song_title)),
    ):
        if given:
            continue
        for h in free():
            n = _slot_of(h)
            if n is None or n in target:
                continue
            if target is cm.artists and _has(_LINK_KW, h):
                continue
            if target is cm.titles and (_has(_LINK_KW, h) or _has(_ARTIST_KW, h)):
                continue
            if target is cm.artists and not _has(kw, h):
                continue
            if _has(kw, h):
                target[n] = h
                taken.add(h)
        # repeated sections with identical question titles
        if not target:
            rkw = _TITLE_REPEAT_KW if target is cm.titles else kw
            repeated = [h for h in free() if _has(rkw, _base(h))]
            if target is cm.artists:
                repeated = [h for h in repeated if not _has(_LINK_KW, _base(h))]
            if target is cm.titles:
                repeated = [h for h in repeated if not _has(_LINK_KW + "|" + _ARTIST_KW, _base(h))]
            for i, h in enumerate(repeated[:SLOTS], 1):
                target[i] = h
                taken.add(h)

    if not cm.name and not cm.email:
        raise SubmissionError(
            "Could not find a name column in the responses. Set [columns] name in chatting.toml. "
            "Available columns: " + ", ".join(f"'{h}'" for h in headers)
        )
    if not cm.name:
        warn(f"No name column found; using the part of '{cm.email}' before the @ as the name.")
    if not cm.links and not cm.titles:
        raise SubmissionError(
            "Could not find the song columns in the responses. Set [columns] song_title / "
            "song_link in chatting.toml (use {n} for the song number). Available columns: "
            + ", ".join(f"'{h}'" for h in headers)
        )
    return cm


def _cell(row: pd.Series, header: Optional[str]) -> str:
    if not header or header not in row.index:
        return ""
    value = row[header]
    if isinstance(value, pd.Series):  # duplicate header names
        value = value.iloc[0]
    text = "" if value is None else str(value).strip()
    return "" if text.lower() == "nan" else text


def parse_submissions(
    df: pd.DataFrame, columns: ColumnsConfig, people: People,
    warn: Callable[[str], None] = log.warn,
) -> list[Submission]:
    cm = detect_columns([str(c) for c in df.columns], columns, warn)
    by_key: dict[str, Submission] = {}
    order: list[str] = []
    for _, row in df.iterrows():
        raw_name = _cell(row, cm.name)
        email = _cell(row, cm.email)
        if not raw_name and email:
            raw_name = email.split("@")[0]
        slots = sorted(set(cm.titles) | set(cm.links))
        if not raw_name and not any(_cell(row, cm.titles.get(n)) or _cell(row, cm.links.get(n)) for n in slots):
            continue
        name = people.canonical(raw_name)
        if not name:
            warn("A response has songs but no name; skipped.")
            continue
        ts_raw = _cell(row, cm.timestamps)
        starts = parse_timestamps_field(ts_raw, SLOTS) if ts_raw else {}
        sub = Submission(
            name=name, raw_name=raw_name, email=email,
            submitted_at=_cell(row, cm.submitted_at), picture=_cell(row, cm.picture),
            timestamps_raw=ts_raw,
        )
        for n in slots:
            title = _cell(row, cm.titles.get(n))
            artist = _cell(row, cm.artists.get(n))
            link = _cell(row, cm.links.get(n))
            if not (title or link):
                continue
            if not link:
                warn(f"{name}: song {n} ('{title}') has no link.")
            elif not is_url(link):
                warn(f"{name}: song {n} link is not a URL: '{link}'.")
            if not title:
                warn(f"{name}: song {n} ({link}) has no title.")
            start = starts.get(n)
            if start is None and link:
                start = youtube_start_param(link)
            sub.songs.append(SongEntry(slot=n, title=title, artist=artist, link=link, start=start))
        if not sub.songs:
            warn(f"{name}: no songs in their response.")
        key = people.key(name)
        if key in by_key:
            warn(f"{name} submitted more than once; using the last response.")
        else:
            order.append(key)
        by_key[key] = sub
    return [by_key[k] for k in order]


def load_submissions(cfg: Config, people: People, warn: Callable[[str], None] = log.warn) -> list[Submission]:
    df = read_table(cfg.input.responses, cfg.base_dir)
    return parse_submissions(df, cfg.columns, people, warn)


def build_songs(submissions: list[Submission], seed: str) -> list[Song]:
    """Number the songs 1..N in a seeded shuffle (same input + seed = same numbers)."""
    people = People()
    flat = [
        Song(id=0, title=e.title, artist=e.artist, link=e.link, submitter=s.name, slot=e.slot, start=e.start)
        for s in submissions for e in s.songs
    ]
    flat.sort(key=lambda s: (people.key(s.submitter), s.slot))
    random.Random(seed).shuffle(flat)
    for i, song in enumerate(flat, 1):
        song.id = i
    return sorted(flat, key=lambda s: s.id)


def find_duplicates(songs: list[Song]) -> list[tuple[Song, Song]]:
    pairs: list[tuple[Song, Song]] = []
    for i, a in enumerate(songs):
        for b in songs[i + 1:]:
            ya, yb = youtube_id(a.link), youtube_id(b.link)
            same_link = ya is not None and ya == yb
            ta, tb = (normalize(a.artist), normalize(a.title)), (normalize(b.artist), normalize(b.title))
            same_text = bool(ta[1]) and ta == tb
            if same_link or same_text:
                pairs.append((a, b))
    return pairs


# --- registry: pins song ids once rating sheets have been sent out -------------------

_REG_COLUMNS = ["id", "title", "artist", "link", "submitter", "slot", "start"]


def write_registry(songs: list[Song], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_REG_COLUMNS)
        for s in sorted(songs, key=lambda s: s.id):
            w.writerow([s.id, s.title, s.artist, s.link, s.submitter, s.slot, format_time(s.start)])


def read_registry(path: Path) -> list[Song]:
    songs = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            songs.append(Song(
                id=int(row["id"]), title=row.get("title", ""), artist=row.get("artist", ""),
                link=row.get("link", ""), submitter=row.get("submitter", ""),
                slot=int(row.get("slot") or 0), start=parse_time(row.get("start", "")),
            ))
    return sorted(songs, key=lambda s: s.id)


def _link_key(song: Song) -> str:
    yid = youtube_id(song.link)
    return f"yt:{yid}" if yid else normalize(song.link)


def _title_key(song: Song) -> str:
    key = normalize(song.artist) + "|" + normalize(song.title)
    return "" if key == "|" else key


def merge_registry(
    registry: list[Song], fresh: list[Song], people: People, warn: Callable[[str], None] = log.warn
) -> list[Song]:
    """Keep every song's number from the registry; ratings were given to those numbers.

    A song is recognised by its submitter plus its link (then its artist + title), never by
    its position in the form — so reordering songs keeps their numbers, and a replaced song
    gets a new number instead of inheriting the old song's ratings.
    """
    remaining = list(fresh)
    pairs: dict[int, Song] = {}
    for key_fn in (_link_key, _title_key):
        for old in registry:
            key = key_fn(old)
            if old.id in pairs or not key:
                continue
            for new in remaining:
                if people.key(new.submitter) == people.key(old.submitter) and key_fn(new) == key:
                    pairs[old.id] = new
                    remaining.remove(new)
                    break

    merged: list[Song] = []
    for old in registry:
        new = pairs.get(old.id)
        if new is None:
            warn(f"Song {old.id} ({old.label}, by {old.submitter}) is no longer in the responses; "
                 "keeping it, since the rating sheets have it.")
            merged.append(old)
            continue
        if new.link != old.link:
            warn(f"Song {old.id} ({new.label}): the link changed since the rating sheets went out.")
        merged.append(Song(id=old.id, title=new.title, artist=new.artist, link=new.link,
                           submitter=old.submitter, slot=new.slot, start=new.start))
    next_id = max((s.id for s in registry), default=0) + 1
    for s in remaining:
        warn(f"Song '{s.label}' by {s.submitter} was added after the rating sheets went out; "
             f"it gets number {next_id} and has no ratings unless voters add it.")
        merged.append(Song(id=next_id, title=s.title, artist=s.artist, link=s.link,
                           submitter=s.submitter, slot=s.slot, start=s.start))
        next_id += 1
    return sorted(merged, key=lambda s: s.id)
