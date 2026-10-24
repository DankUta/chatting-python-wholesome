"""Turning clips and overlays into the final countdown video with ffmpeg."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

from . import log
from .clips import ClipError, Downloader, find_tool, local_clip, probe
from .config import Config
from .models import Results
from .overlay import HEIGHT, VID_H, VID_W, VID_X, VID_Y, WIDTH, OverlayPlan, build_overlays
from .text import get_fontset
from .timestamps import format_time, parse_time

SAMPLE_RATE = 48000
AUDIO_BITRATE = "192k"
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
STDERR_LINES = 20
FALLBACK_START = 30.0           # used when [video] default_start can't be read


class RenderError(Exception):
    pass


def _ffmpeg(cfg: Config) -> str:
    path = find_tool("ffmpeg", cfg)
    if not path:
        raise RenderError("ffmpeg was not found. Install it (winget install Gyan.FFmpeg / "
                          "brew install ffmpeg / apt install ffmpeg) or set [video] ffmpeg.")
    return path


def _run_ffmpeg(cmd: list, tmp: Path) -> None:
    done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        tmp.unlink(missing_ok=True)
        tail = "\n".join((done.stderr or "").strip().splitlines()[-STDERR_LINES:])
        raise RenderError(f"ffmpeg failed:\n{tail}")


def _num(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def page_enable(start: float, end: float, last_page: bool) -> str:
    """ffmpeg `enable` expression for a comment page. Half-open [start, end), so two pages
    never show on the same frame; the last page stays up to the end."""
    if last_page:
        return f"gte(t,{_num(start)})"
    return f"gte(t,{_num(start)})*lt(t,{_num(end)})"


def render_segment(plan: OverlayPlan, clip: Optional[Path], out: Path, cfg: Config,
                   offset: float = 0.0) -> Path:
    """Render one clip with its overlay to `out` (written atomically)."""
    video = cfg.video
    T, fps = video.clip_seconds, video.fps
    ffmpeg = _ffmpeg(cfg)

    has_video = has_audio = False
    if clip is not None:
        try:
            info = probe(clip, cfg)
            has_video, has_audio = info["has_video"], info["has_audio"]
        except ClipError:
            pass

    cmd = [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error"]
    seek = ["-ss", _num(offset)] if offset > 0 else []
    n = 0
    if has_video:
        cmd += seek + ["-i", str(clip)]
        video_idx, audio_idx = 0, (0 if has_audio else None)
        n = 1
    else:
        cmd += ["-f", "lavfi", "-t", _num(T), "-i", f"color=black:s={VID_W}x{VID_H}:r={fps}"]
        video_idx, audio_idx = 0, None
        n = 1
        if has_audio:
            cmd += seek + ["-i", str(clip)]
            audio_idx = 1
            n = 2
    png_inputs = ["-loop", "1", "-framerate", str(fps), "-t", _num(T), "-i"]
    cmd += png_inputs + [str(plan.base)]
    base_idx = n
    n += 1
    page_idx = []
    for path, _, _ in plan.pages:
        cmd += png_inputs + [str(path)]
        page_idx.append(n)
        n += 1

    graph = [
        f"[{video_idx}:v]scale={VID_W}:{VID_H}:force_original_aspect_ratio=decrease,"
        f"pad={VID_W}:{VID_H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},"
        f"tpad=stop_mode=clone:stop_duration={_num(T)}[vid]",
        f"color=c=black:s={WIDTH}x{HEIGHT}:r={fps}:d={_num(T)}[bg]",
        f"[bg][vid]overlay={VID_X}:{VID_Y}:shortest=1[v0]",
        f"[v0][{base_idx}:v]overlay=0:0:format=auto[v1]",
    ]
    last = "v1"
    for k, (idx, (_, start, end)) in enumerate(zip(page_idx, plan.pages)):
        nxt = f"p{k}"
        enable = page_enable(start, end, last_page=k == len(plan.pages) - 1)
        graph.append(f"[{last}][{idx}:v]overlay=0:0:format=auto:enable='{enable}'[{nxt}]")
        last = nxt
    graph.append(f"[{last}]format=yuv420p[outv]")

    chain = ["aresample=%d" % SAMPLE_RATE]
    if has_audio and video.normalize_audio:
        chain += [LOUDNORM, f"aresample={SAMPLE_RATE}"]
    if video.audio_fade > 0:
        fade = min(video.audio_fade, T / 2)
        chain += [f"afade=t=in:st=0:d={_num(fade)}", f"afade=t=out:st={_num(T - fade)}:d={_num(fade)}"]
    chain += ["apad", f"atrim=0:{_num(T)}", "asetpts=N/SR/TB"]
    source = f"[{audio_idx}:a]" if audio_idx is not None else f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
    graph.append(source + ",".join(chain) + "[outa]")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp.mp4")
    cmd += [
        "-filter_complex", ";".join(graph), "-map", "[outv]", "-map", "[outa]",
        "-t", _num(T), "-r", str(fps),
        "-c:v", "libx264", "-preset", video.preset, "-crf", str(video.crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(SAMPLE_RATE), "-ac", "2",
        "-movflags", "+faststart", str(tmp),
    ]
    _run_ffmpeg(cmd, tmp)
    os.replace(tmp, out)
    return out


def segment_name(position: int, plan: OverlayPlan, clip: Optional[Path], offset: float,
                 cfg: Config) -> str:
    """`seg_<position>_<hash>.mp4`; the hash changes whenever the output would."""
    h = hashlib.sha1()
    for path in [plan.base] + [p[0] for p in plan.pages]:
        h.update(Path(path).read_bytes())
    h.update(repr([(round(s, 3), round(e, 3)) for _, s, e in plan.pages]).encode())
    if clip is not None and Path(clip).exists():
        st = Path(clip).stat()
        h.update(f"{Path(clip).resolve()}|{st.st_size}|{st.st_mtime_ns}".encode())
    else:
        h.update(b"no-clip")
    v = cfg.video
    h.update(f"|{offset}|{v.clip_seconds}|{v.fps}|{v.crf}|{v.preset}|{v.audio_fade}|"
             f"{v.normalize_audio}".encode())
    return f"seg_{position:03d}_{h.hexdigest()[:12]}.mp4"


def concat_segments(segments: list, out: Path, cfg: Config) -> Path:
    """Join finished segments without re-encoding."""
    ffmpeg = _ffmpeg(cfg)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    listing = cfg.work_dir / "concat.txt"
    lines = []
    for seg in segments:
        escaped = str(Path(seg).resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp = out.with_name(out.name + ".tmp.mp4")
    cmd = [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "concat",
           "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(tmp)]
    _run_ffmpeg(cmd, tmp)
    os.replace(tmp, out)
    return out


def render_video(results: Results, cfg: Config, avatars: dict, ranks: Optional[set] = None,
                 download: bool = True, warn: Callable[[str], None] = log.warn,
                 info: Callable[[str], None] = log.info,
                 downloader: Optional[Downloader] = None) -> Path:
    """Render every song (worst first) and join them into cfg.video_path."""
    fonts = get_fontset(cfg.fonts)
    T = cfg.video.clip_seconds
    default_start = parse_time(cfg.video.default_start)
    if default_start is None:
        warn(f"Can't read [video] default_start = {cfg.video.default_start!r}; using 0:30.")
        default_start = FALLBACK_START
    countdown = list(reversed(results.songs))
    total = len(countdown)
    overlays_dir = cfg.work_dir / "overlays"
    segments_dir = cfg.work_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    if download and downloader is None:
        downloader = Downloader(cfg, warn=warn)

    segments = []
    failed = []
    for position, item in enumerate(countdown, start=1):
        if ranks is not None and item.rank not in ranks:
            continue
        song = item.song
        start = song.start if song.start is not None else default_start
        info(f"[{position}/{total}] #{item.rank}  {song.label}  (start {format_time(start)})")

        clip: Optional[Path] = local_clip(song, cfg)
        offset = start if clip is not None else 0.0
        if clip is not None:
            try:
                length = probe(clip, cfg).get("duration")
            except ClipError as exc:
                warn(f"#{item.rank} {song.label}: can't read {clip.name}, ignoring it. {exc}")
                clip, offset, length = None, 0.0, None
            if length is not None and start + T > length:
                # A file that ends before the timestamp was cut by hand: play it from the top.
                # One that just ends too soon after it: take its last T seconds.
                offset = 0.0 if length <= start else max(0.0, length - T)
                info(f"    {clip.name} is {format_time(length)} long, shorter than start + "
                     f"{T:g}s — using it from {format_time(offset)}")
        if clip is None and download and downloader is not None:
            try:
                clip = downloader.get(song, start, T)
            except ClipError as exc:
                failed.append((item.rank, song, str(exc)))
                warn(f"#{item.rank} {song.label}: no clip, the video box will be black.\n{exc}")
        elif clip is None:
            failed.append((item.rank, song, "no local clip and downloads are off"))

        plan = build_overlays(item, results.voters, avatars.get(song.submitter), fonts, T,
                              overlays_dir, f"{position:03d}", warn=warn)
        out = segments_dir / segment_name(position, plan, clip, offset, cfg)
        if not out.exists():
            render_segment(plan, clip, out, cfg, offset)
        for stale in segments_dir.glob(f"seg_{position:03d}_*.mp4"):
            if stale != out:
                stale.unlink()
        segments.append(out)

    if not segments:
        raise RenderError("Nothing to render: no songs matched.")
    video_path = concat_segments(segments, cfg.video_path, cfg)
    if failed:
        lines = [f"  #{rank} {song.label} ({song.link})" for rank, song, _ in failed]
        warn(f"{len(failed)} song(s) have a black video box because no clip was available:\n"
             + "\n".join(lines)
             + f"\nFix: put the video in {cfg.input.clips_dir} as <song id>.mp4 "
               f"(or update yt-dlp / set yt_dlp_args), then run again; finished songs are reused.")
    return video_path
