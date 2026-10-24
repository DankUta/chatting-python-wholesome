from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from chatting.clips import find_tool, probe
from chatting.config import Config, FontsConfig
from chatting.models import RankedSong, Results, Song
from chatting.overlay import build_overlays
from chatting.render import (
    RenderError, concat_segments, render_segment, render_video, segment_name,
)
from chatting.text import FontSet

pytestmark = pytest.mark.slow

T = 4


@pytest.fixture(scope="module")
def fonts():
    return FontSet(FontsConfig(), warn=lambda m: None)


def ffmpeg(*args):
    exe = find_tool("ffmpeg", Config())
    if not exe:
        pytest.skip("ffmpeg not installed")
    done = subprocess.run([exe, "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1280x720:r=25:d=20", "-f", "lavfi",
           "-i", "sine=f=440:r=44100:d=20", "-c:v", "libx264", "-c:a", "aac", "-shortest",
           str(d / "long.mp4"))
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x480:r=25:d=2", "-f", "lavfi",
           "-i", "sine=f=330:r=44100:d=2", "-c:v", "libx264", "-c:a", "aac", "-shortest",
           str(d / "short.mp4"))
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=6", "-c:v", "libx264",
           str(d / "silent.mp4"))
    return d


def make_cfg(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.video.clip_seconds = T
    cfg.video.preset = "ultrafast"
    cfg.video.crf = 30
    return cfg


def make_item(i, comments=None, voters=("Ana", "Bob")):
    song = Song(id=i, title=f"Song {i}", artist="Artist", link=f"https://youtu.be/{i}", submitter="Ana")
    return RankedSong(song=song, ratings={"Ana": None, "Bob": 7.5}, comments=comments or {},
                      excluded={"Ana"}, average=7.5, votes=1, rank=i)


def info(path, cfg):
    exe = find_tool("ffprobe", cfg)
    out = subprocess.run([exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    return json.loads(out)


def check_output(path, cfg, seconds=T):
    data = info(path, cfg)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    a = next(s for s in data["streams"] if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1920, 1080)
    assert v["pix_fmt"] == "yuv420p" and v["codec_name"] == "h264"
    assert a["codec_name"] == "aac" and a["sample_rate"] == "48000" and a["channels"] == 2
    assert float(data["format"]["duration"]) == pytest.approx(seconds, abs=0.15)


def plan_for(tmp_path, fonts, i=1, comments=None):
    return build_overlays(make_item(i, comments), ["Ana", "Bob"], None, fonts, T, tmp_path / "ov", f"{i:03d}")


def test_segments_from_various_clips(tmp_path, fonts, clips):
    cfg = make_cfg(tmp_path)
    plan = plan_for(tmp_path, fonts, comments={"Bob": "great 💀", "Ana": "mine"})
    for name, offset in [("long.mp4", 3.0), ("short.mp4", 0.0), ("silent.mp4", 0.0)]:
        out = render_segment(plan, clips / name, tmp_path / f"{name}.out.mp4", cfg, offset)
        check_output(out, cfg)
        assert not list(tmp_path.glob("*.tmp.mp4"))


def test_segment_without_clip_and_with_pages(tmp_path, fonts):
    cfg = make_cfg(tmp_path)
    voters = ["Ana", "Bob", "Cy", "Di", "Ed", "Flo"]
    item = make_item(1, {v: "word " * 150 for v in voters})
    plan = build_overlays(item, voters, None, fonts, T, tmp_path / "ov", "001")
    assert len(plan.pages) > 1
    out = render_segment(plan, None, tmp_path / "none.mp4", cfg)
    check_output(out, cfg)


def test_ffmpeg_failure_raises(tmp_path, fonts):
    cfg = make_cfg(tmp_path)
    plan = plan_for(tmp_path, fonts)
    plan.base.unlink()
    with pytest.raises(RenderError):
        render_segment(plan, None, tmp_path / "bad.mp4", cfg)
    assert not (tmp_path / "bad.mp4").exists()


def test_concat(tmp_path, fonts, clips):
    cfg = make_cfg(tmp_path)
    plan = plan_for(tmp_path, fonts)
    segs = [render_segment(plan, clips / "long.mp4", tmp_path / f"s{i}.mp4", cfg) for i in range(3)]
    out = concat_segments(segs, tmp_path / "final" / "all.mp4", cfg)
    check_output(out, cfg, 3 * T)


def test_segment_name_changes_with_inputs(tmp_path, fonts, clips):
    cfg = make_cfg(tmp_path)
    plan = plan_for(tmp_path, fonts)
    a = segment_name(1, plan, clips / "long.mp4", 0, cfg)
    assert a == segment_name(1, plan, clips / "long.mp4", 0, cfg)
    assert a.startswith("seg_001_")
    assert a != segment_name(1, plan, clips / "long.mp4", 5, cfg)
    assert a != segment_name(1, plan, clips / "short.mp4", 0, cfg)
    assert a != segment_name(1, plan, None, 0, cfg)
    cfg.video.crf = 18
    assert a != segment_name(1, plan, clips / "long.mp4", 0, cfg)


def test_render_video_end_to_end_and_reuse(tmp_path, clips):
    cfg = make_cfg(tmp_path)
    clips_dir = tmp_path / "data" / "clips"
    clips_dir.mkdir(parents=True)
    for i, name in [(1, "long.mp4"), (2, "short.mp4"), (3, "silent.mp4")]:
        (clips_dir / f"{i}.mp4").write_bytes((clips / name).read_bytes())
    items = [make_item(1, {"Bob": "best"}), make_item(2), make_item(3)]
    items[1].song.start = 1.0
    results = Results(voters=["Ana", "Bob"], songs=items)
    lines, warns = [], []
    out = render_video(results, cfg, {}, download=False, warn=warns.append, info=lines.append)
    assert out == cfg.video_path and out.exists()
    check_output(out, cfg, 3 * T)
    progress = [line for line in lines if line.startswith("[")]
    assert progress[0].startswith("[1/3] #3") and progress[2].startswith("[3/3] #1")
    assert not warns
    segs = sorted((cfg.work_dir / "segments").glob("seg_*.mp4"))
    assert len(segs) == 3
    mtimes = [s.stat().st_mtime_ns for s in segs]

    render_video(results, cfg, {}, download=False, warn=warns.append, info=lines.append)
    assert [s.stat().st_mtime_ns for s in sorted((cfg.work_dir / "segments").glob("seg_*.mp4"))] == mtimes

    only = render_video(results, cfg, {}, ranks={1}, download=False, warn=warns.append, info=lines.append)
    check_output(only, cfg, T)


def test_missing_clip_is_collected_and_warned(tmp_path):
    cfg = make_cfg(tmp_path)
    from chatting.clips import ClipError

    class Failing:
        def get(self, song, start, duration):
            raise ClipError("nope")

    results = Results(voters=["Ana", "Bob"], songs=[make_item(1)])
    warns = []
    out = render_video(results, cfg, {}, warn=warns.append, info=lambda m: None, downloader=Failing())
    check_output(out, cfg)
    assert any("black" in w and "Song 1" in w for w in warns)


def test_short_local_clip_is_used_from_its_start(tmp_path, clips):
    # A pre-cut 2 s file whose song says "start at 1:00" must not be seeked past its end.
    cfg = make_cfg(tmp_path)
    clips_dir = cfg.path(cfg.input.clips_dir)
    clips_dir.mkdir(parents=True)
    (clips_dir / "1.mp4").write_bytes((clips / "short.mp4").read_bytes())
    item = make_item(1)
    item.song.start = 60
    notes = []
    video = render_video(Results(voters=["Ana", "Bob"], songs=[item]), cfg, {}, download=False,
                         info=notes.append, warn=lambda m: None)
    check_output(video, cfg)
    assert any("shorter than start" in n and "from 0:00" in n for n in notes)
    exe = find_tool("ffmpeg", cfg)
    out = subprocess.run([exe, "-i", str(video), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    max_volume = float(out.split("max_volume:")[1].split("dB")[0])
    assert max_volume > -40


def test_unreadable_local_clip_is_ignored(tmp_path):
    cfg = make_cfg(tmp_path)
    clips_dir = cfg.path(cfg.input.clips_dir)
    clips_dir.mkdir(parents=True)
    (clips_dir / "1.mp4").write_bytes(b"not a video")
    warns = []
    video = render_video(Results(voters=["Ana", "Bob"], songs=[make_item(1)]), cfg, {},
                         download=False, info=lambda m: None, warn=warns.append)
    check_output(video, cfg)
    assert any("can't read 1.mp4" in w for w in warns)
