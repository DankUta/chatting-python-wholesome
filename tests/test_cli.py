"""End to end through the command line: form responses -> sheet -> compile -> preview -> render."""

import csv
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from chatting.cli import main, parse_ranks
from chatting.config import load_config
from chatting.master import read_master
from chatting.names import People

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"

CONFIG = """
[contest]
title = "Chatting"
edition = "Test"

[input]
responses = "data/responses.csv"
ratings_dir = "data/ratings"
avatars_dir = "data/avatars"
clips_dir = "data/clips"

[people]
"Călin" = ["calin", "Calin_B"]

[video]
clip_seconds = 3
audio_fade = 0.5
normalize_audio = false
sleep_between_downloads = 0
preset = "ultrafast"
"""


@pytest.fixture
def edition(tmp_path):
    (tmp_path / "data").mkdir()
    shutil.copy(DEMO / "data" / "responses.csv", tmp_path / "data" / "responses.csv")
    (tmp_path / "chatting.toml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


def run(edition, *args):
    return main(["-c", str(edition / "chatting.toml"), *args])


def fill_ratings(edition, voters):
    """Every voter rates every song id*0.3 (capped) + their offset, with a comment on a few."""
    songs = list(csv.DictReader(open(edition / "output" / "songs.csv", encoding="utf-8-sig")))
    folder = edition / "data" / "ratings"
    folder.mkdir(parents=True, exist_ok=True)
    for offset, voter in enumerate(voters):
        with open(folder / f"{voter}.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["#", "Song", "Link", "Rating", "Comments"])
            for song in songs:
                rating = min(10, 1 + int(song["id"]) * 0.3 + offset)
                comment = "goes hard 🔥" if int(song["id"]) % 3 == 0 else ""
                writer.writerow([song["id"], f"{song['artist']} - {song['title']}", song["link"],
                                 f"{rating:g}", comment])
    return songs


def test_parse_ranks():
    assert parse_ranks("1-3,7, 10-9") == {1, 2, 3, 7, 9, 10}
    assert parse_ranks("") is None


def test_init_creates_edition(tmp_path):
    assert main(["init", str(tmp_path / "ed"), "--edition", "Edition 6"]) == 0
    cfg = load_config(tmp_path / "ed" / "chatting.toml")
    assert cfg.contest.edition == "Edition 6"
    assert (tmp_path / "ed" / "data" / "ratings").is_dir()


def test_sheet_and_compile(edition):
    assert run(edition, "sheet") == 0
    out = edition / "output"
    assert (out / "rating_sheet.xlsx").exists() and (out / "songs.csv").exists()

    songs = fill_ratings(edition, ["Andrei", "calin", "Gabi"])
    assert run(edition, "compile") == 0

    cfg = load_config(edition / "chatting.toml")
    results = read_master(out / "master.xlsx", People(cfg.people), cfg.voting)
    assert results.voters == ["Andrei", "Călin", "Gabi"]
    assert len(results.songs) == len(songs) == 25
    ranks = [item.rank for item in results.songs]
    assert ranks == sorted(ranks) and ranks[0] == 1
    # Own songs never count: Andrei's songs are rated by Călin and Gabi only.
    for item in results.songs:
        if item.song.submitter == "Andrei":
            assert item.excluded == {"Andrei"} and item.votes == 2
        if item.song.submitter == "Călin":
            assert item.excluded == {"Călin"}


def test_sheet_keeps_numbers_after_late_submission(edition):
    assert run(edition, "sheet") == 0
    before = (edition / "output" / "songs.csv").read_text(encoding="utf-8-sig").splitlines()
    with open(edition / "data" / "responses.csv", "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(["10/5/2026 10:00:00", "late@example.com", "Late"]
                                + ["Late song", "Someone", "https://youtu.be/abcdefghijk"]
                                + [""] * 12 + ["", "1: 0:10"])
    assert run(edition, "sheet") == 0
    after = (edition / "output" / "songs.csv").read_text(encoding="utf-8-sig").splitlines()
    assert after[: len(before)] == before
    assert after[-1].startswith("26,Late song")


def ffprobe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                          "-show_streams", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_preview_and_render(edition):
    assert run(edition, "sheet") == 0
    fill_ratings(edition, ["Andrei", "Bianca", "calin", "Diana", "Emi", "Gabi"])
    assert run(edition, "compile") == 0

    assert run(edition, "preview", "--offline", "--ranks", "1-2") == 0
    previews = sorted((edition / "output" / "preview").glob("*.png"))
    assert previews
    assert all(Image.open(p).size == (1920, 1080) for p in previews)

    cfg = load_config(edition / "chatting.toml")
    results = read_master(edition / "output" / "master.xlsx", People(cfg.people), cfg.voting)
    clips = edition / "data" / "clips"
    clips.mkdir(parents=True)
    for item in results.songs[:2]:
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=120",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=120", "-shortest",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                        str(clips / f"{item.song.id}.mp4")], check=True)

    assert run(edition, "render", "--offline", "--no-download", "--ranks", "1-2") == 0
    video = edition / "output" / "Chatting Test.mp4"
    info = ffprobe(video)
    assert abs(float(info["format"]["duration"]) - 6) < 0.3
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"], v["pix_fmt"]) == (1920, 1080, "yuv420p")
    assert any(s["codec_type"] == "audio" for s in info["streams"])
