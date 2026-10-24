"""Command line: `python -m chatting <command>`. Run with -h for the list of commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from . import __version__, log
from .config import DEFAULT_CONFIG_NAME, Config, ConfigError, load_config
from .names import People

class CliError(Exception):
    pass


TEMPLATE = '''# Chatting — settings for one edition. Every key is optional; delete what you don't need.
# Relative paths are relative to this file's folder.

[contest]
title = "Chatting"
edition = "{edition}"

[input]
# Form responses: a Google Sheets link shared as "Anyone with the link -> Viewer",
# or the downloaded file (File -> Download -> .csv or .xlsx).
responses = "data/responses.csv"
# Everyone's filled-in rating sheet, one file per voter, named after the voter (calin.xlsx).
ratings_dir = "data/ratings"
# Profile pictures named after the person (calin.png). Used when the form's Drive upload
# can't be downloaded.
avatars_dir = "data/avatars"
# Optional: a video file named <song #>.mp4 here replaces the YouTube download for that song.
clips_dir = "data/clips"

# Voters who shared a link instead of sending a file:
[input.rating_links]
# Calin = "https://docs.google.com/spreadsheets/d/.../edit"

# Other spellings of the same person (form name, file names, ...):
[people]
# Calin = ["Călin", "calin_123"]

[voting]
min = 0
max = 10
exclude_own = true      # your rating of your own song doesn't count
voter_order = []        # order of the side panels in the video; empty = A-Z

[video]
clip_seconds = 15
default_start = "0:30"  # for songs without a timestamp
audio_fade = 1.0
normalize_audio = true
sleep_between_downloads = 3
yt_dlp_args = []        # e.g. ["--cookies-from-browser", "firefox"] if YouTube blocks downloads

# [columns]  — only if the form's questions aren't detected automatically. {{n}} = 1..5
# name = "Name"
# song_link = "Song {{n}} link"

[output]
dir = "output"
work_dir = "work"
'''


def parse_ranks(text: Optional[str]) -> Optional[set[int]]:
    """"1-10,15" -> {1..10, 15}."""
    if not text:
        return None
    ranks: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            a, b = int(lo), int(hi)
            ranks.update(range(min(a, b), max(a, b) + 1))
        else:
            ranks.add(int(part))
    return ranks


def _people(cfg: Config) -> People:
    return People(cfg.people)


def _registry_path(cfg: Config) -> Path:
    return cfg.output_dir / "songs.csv"


def _master_path(cfg: Config) -> Path:
    return cfg.output_dir / "master.xlsx"


def _load_songs(cfg: Config, people: People, reshuffle: bool = False):
    from .submissions import (build_songs, find_duplicates, load_submissions,
                              merge_registry, read_registry)

    submissions = load_submissions(cfg, people)
    fresh = build_songs(submissions, cfg.output.seed)
    registry = _registry_path(cfg)
    if registry.exists() and not reshuffle:
        songs = merge_registry(read_registry(registry), fresh, people)
    else:
        songs = fresh
    for a, b in find_duplicates(songs):
        log.warn(f"Same song twice: #{a.id} {a.label} ({a.submitter}) and #{b.id} {b.label} ({b.submitter})")
    return submissions, songs


# --- commands ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    folder = Path(args.folder).resolve()
    target = folder / DEFAULT_CONFIG_NAME
    if target.exists():
        log.info(f"{target} already exists — leaving it alone.")
    else:
        folder.mkdir(parents=True, exist_ok=True)
        target.write_text(TEMPLATE.format(edition=args.edition or ""), encoding="utf-8")
        log.info(f"Created {target}")
    for sub in ("data/ratings", "data/avatars", "data/clips"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    log.info(
        "Next: put the form responses in data/responses.csv (or a sheet link in the config), "
        "then run:  python -m chatting sheet"
    )
    return 0


def cmd_check(cfg: Config, args: argparse.Namespace) -> int:
    from .clips import check_tools, youtube_advice
    from .text import FontSet

    log.info(f"Config folder: {cfg.base_dir}")
    problems = check_tools(cfg)
    fonts = FontSet(cfg.fonts)
    log.info(f"Fonts: {fonts.describe()}")
    for problem in problems:
        log.warn(problem)
    if not problems:
        log.info("ffmpeg, ffprobe and yt-dlp found.")
    for advice in youtube_advice(cfg):
        log.warn(advice)
    return 1 if problems else 0


def cmd_sheet(cfg: Config, args: argparse.Namespace) -> int:
    from .ratings import write_rating_sheet
    from .submissions import write_registry
    from .timestamps import format_time

    people = _people(cfg)
    registry = _registry_path(cfg)
    if args.reshuffle and registry.exists():
        log.warn(f"--reshuffle: song numbers change; rating sheets already sent out won't match {registry.name}")
    submissions, songs = _load_songs(cfg, people, reshuffle=args.reshuffle)
    if not songs:
        log.warn("No songs found in the form responses.")
        return 1

    out = cfg.output_dir
    sheet = out / "rating_sheet.xlsx"
    write_rating_sheet(songs, sheet, out / "rating_sheet.csv", cfg.voting.min, cfg.voting.max)
    write_registry(songs, registry)

    log.info(f"{len(submissions)} participants, {len(songs)} songs.")
    log.info(f"Clip starts per song (– = none given, starts at {cfg.video.default_start}); "
             "check them against what people wrote:")
    width = max(len(sub.name) for sub in submissions)
    for sub in submissions:
        own = sorted((s for s in songs if people.same(s.submitter, sub.name)), key=lambda s: s.slot)
        starts = "  ".join(f"{s.slot}) {format_time(s.start) or '–':>5}" for s in own)
        written = " ".join(sub.timestamps_raw.split())
        if len(written) > 60:
            written = written[:59] + "…"
        log.info(f"  {sub.name:<{width}}  {starts}    \"{written}\"")
    log.info(f"Rating sheet:  {sheet}  (+ .csv) — upload it to Google Drive and share a copy with everyone.")
    log.info(f"Song list:     {registry}  — private (it shows who sent what); keep it until the video is done.")
    return 0


def _compile(cfg: Config):
    from .master import compile_results, write_master
    from .ratings import load_votes

    people = _people(cfg)
    if not _registry_path(cfg).exists():
        log.warn(
            f"{_registry_path(cfg)} not found — rebuilding the song numbers from the responses. "
            "That only matches the rating sheets if the responses haven't changed since `sheet`."
        )
    submissions, songs = _load_songs(cfg, people)
    voters, votes = load_votes(cfg, songs, people)
    if not voters:
        raise CliError(
            "No ratings to compile. Put each voter's filled-in sheet in "
            f"{cfg.path(cfg.input.ratings_dir)} (named after the voter, e.g. bianca.xlsx), "
            "or list their links under [input.rating_links] in chatting.toml."
        )
    results = compile_results(songs, voters, votes, people, cfg.voting)
    master = _master_path(cfg)
    write_master(results, master, title=cfg.contest.title)
    return submissions, results, master


def cmd_compile(cfg: Config, args: argparse.Namespace) -> int:
    people = _people(cfg)
    submissions, results, master = _compile(cfg)

    voter_keys = {people.key(v) for v in results.voters}
    missing = sorted({s.name for s in submissions if people.key(s.name) not in voter_keys})
    log.info(f"{len(results.voters)} voters: {', '.join(results.voters)}")
    if missing:
        log.warn(f"No rating sheet from: {', '.join(missing)}")

    log.info("")
    show = results.songs if args.all else results.songs[:5]
    for item in show:
        avg = f"{item.average:.2f}" if item.average is not None else "  – "
        log.info(f"  #{item.rank:<3} {avg}  {item.song.label}  ({item.song.submitter}, {item.votes} votes)")
    if not args.all and len(results.songs) > 5:
        log.info(f"  ... {len(results.songs) - 5} more (use --all, or open the master sheet)")
    log.info("")
    log.info(f"Master sheet: {master}")
    log.info("Fix anything in it you need (ratings, comments, start times), then: python -m chatting preview")
    return 0


def _results_for_video(cfg: Config):
    """The master sheet (with the admin's edits) if it exists, else compile it now."""
    from .master import read_master

    people = _people(cfg)
    master = _master_path(cfg)
    if master.exists():
        log.info(f"Using {master}")
        results = read_master(master, people, cfg.voting)
        submissions = []
        try:
            from .submissions import load_submissions
            submissions = load_submissions(cfg, people, warn=lambda msg: None)
        except Exception as exc:  # pictures are optional; the master has everything else
            log.warn(f"Couldn't read the form responses for profile pictures ({exc}); using {cfg.input.avatars_dir}")
        return submissions, results
    log.info("No master sheet yet — compiling it first.")
    submissions, results, _ = _compile(cfg)
    return submissions, results


def _avatars(cfg: Config, submissions, results, offline: bool):
    from .avatars import prepare_avatars

    people = _people(cfg)
    pictures = {item.song.submitter: "" for item in results.songs}
    for sub in submissions:
        for name in pictures:
            if people.same(name, sub.name) and sub.picture:
                pictures[name] = sub.picture
    return prepare_avatars(pictures, cfg, people, offline=offline)


def cmd_preview(cfg: Config, args: argparse.Namespace) -> int:
    from .overlay import build_overlays, compose_preview
    from .text import FontSet

    submissions, results = _results_for_video(cfg)
    avatars = _avatars(cfg, submissions, results, offline=args.offline)
    fonts = FontSet(cfg.fonts)
    ranks = parse_ranks(args.ranks)
    out = cfg.output_dir / "preview"
    out.mkdir(parents=True, exist_ok=True)
    work = cfg.work_dir / "overlays"

    countdown = list(reversed(results.songs))
    written = 0
    for position, item in enumerate(countdown, 1):
        if ranks is not None and item.rank not in ranks:
            continue
        name = f"{position:03d}"
        plan = build_overlays(item, results.voters, avatars.get(item.song.submitter), fonts,
                              cfg.video.clip_seconds, work, name)
        for page, image in enumerate(compose_preview(plan), 1):
            suffix = f"_p{page}" if len(plan.pages) > 1 else ""
            path = out / f"{name}_rank{item.rank}{suffix}.png"
            image.save(path)
            written += 1
    log.info(f"Wrote {written} preview image(s) to {out}")
    return 0


def cmd_render(cfg: Config, args: argparse.Namespace) -> int:
    from .clips import check_tools, youtube_advice
    from .render import render_video

    problems = check_tools(cfg)
    if problems:
        for problem in problems:
            log.warn(problem)
        if any("ffmpeg" in p.lower() for p in problems) or (not args.no_download and problems):
            return 1
    if not args.no_download:
        for advice in youtube_advice(cfg):
            log.warn(advice)
    submissions, results = _results_for_video(cfg)
    avatars = _avatars(cfg, submissions, results, offline=args.offline)
    video = render_video(results, cfg, avatars, ranks=parse_ranks(args.ranks),
                         download=not args.no_download)
    log.info(f"Done: {video}")
    return 0


# --- entry point --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chatting",
        description="Chatting song contest: form responses -> rating sheet -> master sheet -> countdown video.",
    )
    parser.add_argument("--version", action="version", version=f"chatting {__version__}")
    parser.add_argument("-c", "--config", type=Path, default=None,
                        help=f"settings file (default: ./{DEFAULT_CONFIG_NAME})")
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("init", help="create a folder for a new edition with a starter chatting.toml")
    p.add_argument("folder", nargs="?", default=".")
    p.add_argument("--edition", default="", help='e.g. "Edition 6"')

    sub.add_parser("check", help="check ffmpeg, yt-dlp and fonts")

    p = sub.add_parser("sheet", help="build the anonymous rating sheet from the form responses")
    p.add_argument("--reshuffle", action="store_true",
                   help="renumber every song (only before the rating sheets go out)")

    p = sub.add_parser("compile", help="collect everyone's ratings into the master sheet")
    p.add_argument("--all", action="store_true", help="print the whole ranking")

    for name, help_text in (("preview", "draw the video overlays as PNG images to check the layout"),
                            ("render", "download the clips and render the countdown video")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--ranks", help='only these ranks, e.g. "1-10" or "1,2,3"')
        p.add_argument("--offline", action="store_true",
                       help="don't download profile pictures (use avatars_dir / placeholders)")
        if name == "render":
            p.add_argument("--no-download", action="store_true",
                           help="don't download from YouTube (only clips_dir and the download cache)")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "init":
        return cmd_init(args)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    handlers = {
        "check": cmd_check,
        "sheet": cmd_sheet,
        "compile": cmd_compile,
        "preview": cmd_preview,
        "render": cmd_render,
    }
    log.reset()
    try:
        code = handlers[args.command](cfg, args)
    except KeyboardInterrupt:
        print("\nStopped. Run the same command again to continue — finished clips are kept.", file=sys.stderr)
        return 130
    except Exception as exc:
        if type(exc).__module__.startswith("chatting."):
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        raise
    warnings = log.warnings()
    if warnings:
        print(f"\n{len(warnings)} warning(s) — scroll up for details.", file=sys.stderr)
    return code
