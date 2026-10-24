from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from chatting.clips import ClipError, Downloader, local_clip, find_tool
from chatting.config import Config
from chatting.models import Song


def make(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.video.sleep_between_downloads = 3
    cfg.video.download_retries = 2
    song = Song(id=7, title="Title", artist="Artist", link="https://youtu.be/abc", submitter="X")
    return cfg, song


class FakeRunner:
    def __init__(self, fail_times=0):
        self.calls = []
        self.fail_times = fail_times

    def __call__(self, cmd):
        self.calls.append(cmd)
        if len(self.calls) <= self.fail_times:
            return subprocess.CompletedProcess(cmd, 1, "", "line1\nERROR: boom")
        out = cmd[cmd.index("-o") + 1].replace("%(ext)s", "mp4")
        Path(out).write_bytes(b"video")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_command_cache_and_sleep(tmp_path):
    cfg, song = make(tmp_path)
    cfg.video.yt_dlp_args = ["--cookies-from-browser", "firefox"]
    sleeps = []
    runner = FakeRunner()
    dl = Downloader(cfg, runner=runner, sleep=sleeps.append)
    first = dl.get(song, 65.0, 15.0)
    assert sleeps == []
    cmd = runner.calls[0]
    assert cmd[:3] == [sys.executable, "-m", "yt_dlp"]
    assert "--no-playlist" in cmd and "--force-keyframes-at-cuts" in cmd
    assert cmd[cmd.index("--download-sections") + 1] == "*65.0-81.0"
    assert cmd[cmd.index("-f") + 1] == "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"
    assert cmd[-3:] == ["--cookies-from-browser", "firefox", song.link][-3:] or cmd[-1] == song.link
    assert cmd[-1] == song.link and "--cookies-from-browser" in cmd
    assert first.parent == cfg.work_dir / "clips" and first.suffix == ".mp4"

    assert dl.get(song, 65.0, 15.0) == first
    assert len(runner.calls) == 1 and sleeps == []

    dl.get(song, 100.0, 15.0)
    assert len(runner.calls) == 2 and sleeps == [3]


def test_partial_files_are_not_cache_hits(tmp_path):
    cfg, song = make(tmp_path)
    runner = FakeRunner()
    dl = Downloader(cfg, runner=runner, sleep=lambda s: None)
    path = dl.get(song, 1.0, 15.0)
    path.rename(path.with_suffix(".part"))
    dl2 = Downloader(cfg, runner=runner, sleep=lambda s: None)
    dl2.get(song, 1.0, 15.0)
    assert len(runner.calls) == 2


def test_retries_then_succeeds(tmp_path):
    cfg, song = make(tmp_path)
    sleeps = []
    runner = FakeRunner(fail_times=2)
    Downloader(cfg, runner=runner, sleep=sleeps.append).get(song, 1.0, 15.0)
    assert len(runner.calls) == 3 and sleeps == [5, 15]


def test_gives_up_with_hint(tmp_path):
    cfg, song = make(tmp_path)
    sleeps = []
    runner = FakeRunner(fail_times=99)
    with pytest.raises(ClipError) as exc:
        Downloader(cfg, runner=runner, sleep=sleeps.append).get(song, 1.0, 15.0)
    assert len(runner.calls) == 3 and sleeps == [5, 15]
    text = str(exc.value)
    assert "ERROR: boom" in text and "pip install -U yt-dlp" in text and "7.mp4" in text


def test_local_clip(tmp_path):
    cfg, song = make(tmp_path)
    assert local_clip(song, cfg) is None
    folder = tmp_path / "data" / "clips"
    folder.mkdir(parents=True)
    (folder / "readme.txt").write_text("x")
    assert local_clip(song, cfg) is None
    (folder / "7.mp4").write_bytes(b"x")
    assert local_clip(song, cfg) == folder / "7.mp4"
    (folder / "7.mp4").unlink()
    (folder / "Artist - Title.webm").write_bytes(b"x")
    assert local_clip(song, cfg) == folder / "Artist - Title.webm"


def test_find_tool_uses_config(tmp_path):
    cfg = Config(base_dir=tmp_path)
    (tmp_path / "ffmpeg").write_text("")
    (tmp_path / "ffprobe").write_text("")
    cfg.video.ffmpeg = str(tmp_path / "ffmpeg")
    assert find_tool("ffmpeg", cfg) == str(tmp_path / "ffmpeg")
    assert find_tool("ffprobe", cfg) == str(tmp_path / "ffprobe")
