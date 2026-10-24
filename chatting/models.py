"""Plain data classes shared by every stage of the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SongEntry:
    """One song as typed into the submission form."""

    slot: int                       # 1..5, position in the submitter's form
    title: str
    artist: str
    link: str
    start: Optional[float] = None   # clip start in seconds; None = use the default


@dataclass
class Submission:
    """One participant's form response (the latest one if they submitted twice)."""

    name: str                       # canonical display name (see names.People)
    raw_name: str                   # name exactly as typed in the form
    email: str = ""
    submitted_at: str = ""          # the form's own "Timestamp" column, as text
    picture: str = ""               # raw value of the profile-picture upload field
    timestamps_raw: str = ""        # raw value of the free-text timestamps field
    songs: list[SongEntry] = field(default_factory=list)


@dataclass
class Song:
    """A song in the contest. `id` is the number shown on the rating sheet."""

    id: int
    title: str
    artist: str
    link: str
    submitter: str                  # canonical display name of who submitted it
    slot: int = 0
    start: Optional[float] = None   # clip start in seconds; None = use the default

    @property
    def label(self) -> str:
        """How the song is written on the rating sheet: "Artist - Title"."""
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.artist


@dataclass
class Vote:
    """One voter's rating and comment for one song, read from their rating sheet."""

    voter: str                      # canonical display name
    song_id: int
    rating: Optional[float]         # None = blank, "-", "forgot", invalid, ...
    raw: str = ""                   # the rating cell exactly as written
    comment: str = ""


@dataclass
class RankedSong:
    """A song with every voter's rating, its average and its final rank."""

    song: Song
    ratings: dict[str, Optional[float]]   # voter -> rating used (None = no rating)
    comments: dict[str, str]              # voter -> comment ("" = none)
    excluded: set[str] = field(default_factory=set)  # voters whose rating was left out (own song)
    average: Optional[float] = None       # None when nobody rated it
    votes: int = 0                        # number of ratings that count toward the average
    rank: int = 0                         # 1 = best; tied averages share a rank


@dataclass
class Results:
    """Everything the video needs: voters in display order and songs best-first."""

    voters: list[str]
    songs: list[RankedSong]
