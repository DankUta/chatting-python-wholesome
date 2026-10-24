"""Settings, read from a `chatting.toml` file. Every key is optional.

Relative paths in the file are resolved against the folder the file lives in, so an
edition's folder can be moved around as a whole.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.9/3.10
    import tomli as tomllib

DEFAULT_CONFIG_NAME = "chatting.toml"


class ConfigError(Exception):
    pass


@dataclass
class ContestConfig:
    title: str = "Chatting"
    edition: str = ""


@dataclass
class InputConfig:
    # Form responses: a local .csv/.xlsx/.ods file or a Google Sheets link.
    responses: str = "data/responses.csv"
    # Folder holding every voter's filled-in rating sheet; the file name is the voter.
    ratings_dir: str = "data/ratings"
    # Optional voter -> Google Sheets link, for voters who shared their sheet instead.
    rating_links: dict[str, str] = field(default_factory=dict)
    # Profile pictures: "<name>.png/.jpg/..." (any spelling of the name works).
    avatars_dir: str = "data/avatars"
    # Optional hand-picked videos: "<song id>.mp4" (or any video file) replaces the download.
    clips_dir: str = "data/clips"


@dataclass
class ColumnsConfig:
    """Form column headers. Empty = detect automatically. `{n}` stands for 1..5."""

    name: str = ""
    email: str = ""
    picture: str = ""
    timestamps: str = ""
    song_title: str = ""
    song_artist: str = ""
    song_link: str = ""


@dataclass
class VotingConfig:
    min: float = 0.0
    max: float = 10.0
    exclude_own: bool = True       # a submitter's rating of their own song never counts
    voter_order: list[str] = field(default_factory=list)  # side-panel order; empty = A-Z


@dataclass
class VideoConfig:
    clip_seconds: float = 15.0
    default_start: str = "0:30"    # used when a song has no timestamp
    audio_fade: float = 1.0        # seconds of fade-in and fade-out per clip; 0 = off
    normalize_audio: bool = True   # even out loudness between songs
    fps: int = 30
    crf: int = 20
    preset: str = "medium"
    max_download_height: int = 1080
    sleep_between_downloads: float = 3.0
    download_retries: int = 3
    yt_dlp_args: list[str] = field(default_factory=list)   # e.g. ["--cookies-from-browser", "firefox"]
    ffmpeg: str = ""               # path to ffmpeg; empty = find it on PATH / next to the project


@dataclass
class FontsConfig:
    """Font files. Empty = try common system fonts (Arial, Segoe UI, DejaVu, ...)."""

    regular: str = ""
    bold: str = ""
    emoji: str = ""


@dataclass
class OutputConfig:
    dir: str = "output"            # rating sheet, master sheet, final video
    work_dir: str = "work"         # caches: downloaded clips, overlays, segments, avatars
    video_name: str = ""           # empty = "<title> <edition>.mp4"
    seed: str = "chatting"         # shuffles the rating sheet order


@dataclass
class Config:
    contest: ContestConfig = field(default_factory=ContestConfig)
    input: InputConfig = field(default_factory=InputConfig)
    columns: ColumnsConfig = field(default_factory=ColumnsConfig)
    people: dict[str, list[str]] = field(default_factory=dict)   # display name -> aliases
    voting: VotingConfig = field(default_factory=VotingConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    fonts: FontsConfig = field(default_factory=FontsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    base_dir: Path = field(default_factory=Path.cwd)   # folder of the config file

    def path(self, value: str) -> Path:
        """Resolve a path from the config against the config file's folder."""
        p = Path(value).expanduser()
        return p if p.is_absolute() else self.base_dir / p

    @property
    def output_dir(self) -> Path:
        return self.path(self.output.dir)

    @property
    def work_dir(self) -> Path:
        return self.path(self.output.work_dir)

    @property
    def video_path(self) -> Path:
        name = self.output.video_name or " ".join(
            part for part in (self.contest.title, self.contest.edition) if part
        )
        if not name.lower().endswith(".mp4"):
            name += ".mp4"
        return self.output_dir / name


_SECTIONS = {
    "contest": ContestConfig,
    "input": InputConfig,
    "columns": ColumnsConfig,
    "voting": VotingConfig,
    "video": VideoConfig,
    "fonts": FontsConfig,
    "output": OutputConfig,
}


def _build(cls: type, data: dict[str, Any], section: str) -> Any:
    known = {f.name: f for f in fields(cls)}
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise ConfigError(f"[{section}] has unknown key(s): {', '.join(unknown)}")
    return cls(**data)


def load_config(path: Optional[Path] = None) -> Config:
    """Load `path`, or `./chatting.toml` if it exists, or plain defaults."""
    if path is None:
        candidate = Path.cwd() / DEFAULT_CONFIG_NAME
        if not candidate.exists():
            return Config(base_dir=Path.cwd())
        path = candidate
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    cfg = Config(base_dir=path.resolve().parent)
    for key, value in data.items():
        if key in _SECTIONS:
            if not isinstance(value, dict):
                raise ConfigError(f"[{key}] must be a table")
            setattr(cfg, key, _build(_SECTIONS[key], value, key))
        elif key == "people":
            if not isinstance(value, dict):
                raise ConfigError("[people] must be a table of  Name = [\"alias\", ...]")
            cfg.people = {
                str(k): ([v] if isinstance(v, str) else [str(x) for x in v])
                for k, v in value.items()
            }
        else:
            raise ConfigError(f"Unknown section [{key}] in {path}")
    return cfg
