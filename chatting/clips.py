"""Finding the external tools and getting a video clip for each song."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from . import log
from .config import Config
from .models import Song
from .names import slug

MEDIA_EXTENSIONS = [".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv",
                    ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac"]
PARTIAL_SUFFIXES = {".part", ".ytdl", ".temp", ".tmp"}
RETRY_BACKOFF = [5, 15, 45]    # seconds to wait before the 1st, 2nd, 3rd... retry
STDERR_LINES = 8


class ClipError(Exception):
    pass


def find_tool(name: str, cfg: Config) -> Optional[str]:
    """Path of "ffmpeg" or "ffprobe": config, then PATH, then next to the project."""
    exe = name + (".exe" if sys.platform.startswith("win") else "")
    configured = cfg.video.ffmpeg
    if configured:
        ffmpeg = Path(configured)
        candidate = ffmpeg if name == "ffmpeg" else ffmpeg.with_name(name + ffmpeg.suffix)
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    for folder in (cfg.base_dir, Path(__file__).resolve().parent.parent):
        for file_name in (name, exe):
            candidate = folder / file_name
            if candidate.is_file():
                return str(candidate)
    return None


def check_tools(cfg: Config) -> list:
    """Human-readable problems with ffmpeg / ffprobe / yt-dlp (empty = all fine)."""
    problems = []
    hint = ("Install it with: winget install Gyan.FFmpeg (Windows), brew install ffmpeg (macOS) "
            "or apt install ffmpeg (Linux), or set [video] ffmpeg = \"path/to/ffmpeg\".")
    for tool in ("ffmpeg", "ffprobe"):
        if not find_tool(tool, cfg):
            problems.append(f"{tool} was not found. {hint}")
    try:
        done = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"],
                              capture_output=True, text=True)
        ok = done.returncode == 0
    except OSError:
        ok = False
    if not ok:
        problems.append(f"yt-dlp is not installed for this Python. Install it with: "
                        f"{sys.executable} -m pip install yt-dlp")
    return problems


def probe(path: Path, cfg: Config) -> dict:
    """{"duration": seconds or None, "has_video": bool, "has_audio": bool} via ffprobe."""
    ffprobe = find_tool("ffprobe", cfg)
    if not ffprobe:
        raise ClipError("ffprobe was not found (it comes with ffmpeg).")
    done = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(path)], capture_output=True, text=True)
    if done.returncode != 0:
        raise ClipError(f"ffprobe can't read {path}: {done.stderr.strip()[-300:]}")
    data = json.loads(done.stdout or "{}")
    types = [s.get("codec_type") for s in data.get("streams", [])]
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return {"duration": duration, "has_video": "video" in types, "has_audio": "audio" in types}


def local_clip(song: Song, cfg: Config) -> Optional[Path]:
    """A hand-picked file in the clips folder: "<song id>.mp4" or "<artist - title>.mp4"."""
    folder = cfg.path(cfg.input.clips_dir)
    if not folder.is_dir():
        return None
    wanted = {str(song.id), slug(song.label)}
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS \
                and (path.stem in wanted or slug(path.stem) in wanted):
            return path
    return None


def _run(cmd: list):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


class Downloader:
    """Downloads just the needed part of a song's video with yt-dlp, with a cache."""

    def __init__(self, cfg: Config, warn: Callable[[str], None] = log.warn,
                 runner: Callable = _run, sleep: Callable[[float], None] = time.sleep):
        self.cfg = cfg
        self.warn = warn
        self.runner = runner
        self.sleep = sleep
        self._downloads = 0

    def _cached(self, folder: Path, key: str) -> Optional[Path]:
        if not folder.is_dir():
            return None
        for path in sorted(folder.iterdir()):
            if path.stem == key and path.suffix.lower() not in PARTIAL_SUFFIXES:
                return path
        return None

    def command(self, song: Song, start: float, duration: float, folder: Path, key: str) -> list:
        video = self.cfg.video
        height = video.max_download_height
        return [
            sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-progress",
            "--ffmpeg-location", find_tool("ffmpeg", self.cfg) or "ffmpeg",
            "-f", f"bv*[height<={height}]+ba/b[height<={height}]/bv*+ba/b",
            "--download-sections", f"*{start}-{start + duration + 1}",
            "--force-keyframes-at-cuts",
            "-o", f"{folder}/{key}.%(ext)s",
            *video.yt_dlp_args, song.link,
        ]

    def get(self, song: Song, start: float, duration: float) -> Path:
        key = hashlib.sha1(f"{song.link}|{start}|{duration}".encode("utf-8")).hexdigest()[:16]
        folder = self.cfg.work_dir / "clips"
        hit = self._cached(folder, key)
        if hit:
            return hit
        folder.mkdir(parents=True, exist_ok=True)
        if self._downloads:
            self.sleep(self.cfg.video.sleep_between_downloads)
        self._downloads += 1

        cmd = self.command(song, start, duration, folder, key)
        attempts = 1 + max(0, self.cfg.video.download_retries)
        error = ""
        for attempt in range(attempts):
            if attempt:
                self.sleep(RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)])
            done = self.runner(cmd)
            hit = self._cached(folder, key)
            if done.returncode == 0 and hit:
                return hit
            error = (done.stderr or "").strip()
            if done.returncode == 0:
                error = error or "yt-dlp finished but produced no file"
        tail = "\n".join(error.splitlines()[-STDERR_LINES:])
        raise ClipError(
            f"Couldn't download {song.link}:\n{tail}\n"
            f"Try: update yt-dlp (pip install -U yt-dlp); or set yt_dlp_args = "
            f"[\"--cookies-from-browser\", \"firefox\"] in [video]; or put the video in "
            f"{self.cfg.input.clips_dir} as {song.id}.mp4")
