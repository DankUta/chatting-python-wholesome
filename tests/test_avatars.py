from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from chatting import avatars
from chatting.config import Config
from chatting.names import People


def make_cfg(tmp_path: Path) -> Config:
    cfg = Config(base_dir=tmp_path)
    cfg.input.avatars_dir = "avatars_in"
    (tmp_path / "avatars_in").mkdir()
    return cfg


def save(path: Path, size=(300, 200), color=(200, 30, 30)):
    Image.new("RGB", size, color).save(path)


def test_local_file_match_with_accents_and_drive_names(tmp_path):
    cfg = make_cfg(tmp_path)
    save(tmp_path / "avatars_in" / "CALIN.jpg", color=(10, 200, 10))
    save(tmp_path / "avatars_in" / "photo.jpg - Ana Maria.png", color=(10, 10, 200))
    out = avatars.prepare_avatars({"Călin": "", "Ana Maria": ""}, cfg, People(), warn=lambda m: None,
                                  offline=True)
    a = Image.open(out["Călin"])
    b = Image.open(out["Ana Maria"])
    assert a.size == b.size == (512, 512)
    assert all(abs(x - y) <= 3 for x, y in zip(a.getpixel((256, 256))[:3], (10, 200, 10)))
    assert b.getpixel((256, 256))[:3] == (10, 10, 200)


def test_exif_rotation_and_square_crop(tmp_path):
    cfg = make_cfg(tmp_path)
    im = Image.new("RGB", (400, 200), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6   # rotate 90 CW when displayed
    im.save(tmp_path / "avatars_in" / "sam.jpg", exif=exif)
    out = avatars.prepare_avatars({"Sam": ""}, cfg, People(), warn=lambda m: None, offline=True)
    assert Image.open(out["Sam"]).size == (512, 512)


def test_placeholder_when_nothing_exists(tmp_path):
    cfg = make_cfg(tmp_path)
    out = avatars.prepare_avatars({"Zed Zoo": ""}, cfg, People(), warn=lambda m: None, offline=True)
    img = Image.open(out["Zed Zoo"]).convert("RGB")
    assert img.size == (512, 512)
    assert img.getcolors(512 * 512) is not None and len(img.getcolors(512 * 512)) > 1   # background plus initials
    assert out["Zed Zoo"].parent == cfg.work_dir / "avatars"


def test_non_image_download_warns_and_uses_placeholder(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"<html>login</html>", "text/html"

    monkeypatch.setattr(avatars, "_fetch", fake_fetch)
    warnings = []
    out = avatars.prepare_avatars({"Dana": "https://drive.google.com/open?id=ABCDEFGHIJKLMN"}, cfg,
                                  People(), warn=warnings.append)
    assert calls == ["https://drive.google.com/uc?export=download&id=ABCDEFGHIJKLMN"]
    assert len(warnings) == 1 and "isn't shared publicly" in warnings[0]
    assert "Dana.png" in warnings[0]
    assert Image.open(out["Dana"]).size == (512, 512)


def test_download_is_cached(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (1, 2, 3)).save(buf, "PNG")
    calls = []
    monkeypatch.setattr(avatars, "_fetch", lambda url: (calls.append(url), (buf.getvalue(), "image/png"))[1])
    value = "https://drive.google.com/file/d/ABCDEFGHIJKLMN/view, https://x.example/other"
    avatars.prepare_avatars({"Dana": value}, cfg, People(), warn=lambda m: None)
    avatars.prepare_avatars({"Dana": value}, cfg, People(), warn=lambda m: None)
    assert len(calls) == 1
    assert (cfg.work_dir / "avatars" / "raw" / "dana.png").exists()


def test_offline_never_fetches(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)

    def boom(url):
        raise AssertionError("network used")

    monkeypatch.setattr(avatars, "_fetch", boom)
    out = avatars.prepare_avatars({"Dana": "https://example.com/a.png"}, cfg, People(),
                                  warn=lambda m: None, offline=True)
    assert out["Dana"].exists()


def test_corrupt_local_file_falls_through(tmp_path):
    cfg = make_cfg(tmp_path)
    (tmp_path / "avatars_in" / "dana.png").write_bytes(b"not an image")
    warnings = []
    out = avatars.prepare_avatars({"Dana": ""}, cfg, People(), warn=warnings.append, offline=True)
    assert warnings and Image.open(out["Dana"]).size == (512, 512)
