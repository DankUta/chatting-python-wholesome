"""Profile pictures: a local file, a download from the form's upload field, or a placeholder."""

from __future__ import annotations

import colorsys
import hashlib
import io
import re
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from . import log
from .config import Config
from .names import People, slug
from .text import FontSet

AVATAR_SIZE = 512
IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"]
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DOWNLOAD_TIMEOUT = 30
DRIVE_DOWNLOAD = "https://drive.google.com/uc?export=download&id={id}"
_DRIVE_ID = re.compile(r"(?:/file/d/|[?&]id=)([A-Za-z0-9_-]{10,})")
_CONTENT_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
                "image/gif": ".gif", "image/bmp": ".bmp", "image/tiff": ".tiff",
                "image/heic": ".heic", "image/heif": ".heif"}


def _register_heif() -> bool:
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        return True
    except Exception:
        return False


def _fetch(url: str) -> tuple:
    """Download `url`; returns (bytes, content type). Replaced in tests."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
        return resp.read(), resp.headers.get_content_type()


def picture_url(value: str) -> str:
    """Download URL for the form's picture field ("" if there's nothing usable)."""
    first = next((part.strip() for part in str(value or "").split(",") if part.strip()), "")
    if not first.lower().startswith(("http://", "https://")):
        return ""
    if "drive.google.com" in first or "docs.google.com" in first:
        m = _DRIVE_ID.search(first)
        return DRIVE_DOWNLOAD.format(id=m.group(1)) if m else ""
    return first


def _process(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    return image.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)


def _load(source) -> Optional[Image.Image]:
    try:
        with Image.open(source) as im:
            im.load()
            return _process(im)
    except (OSError, UnidentifiedImageError, ValueError, SyntaxError):
        return None


def _find_local(folder: Path, name: str, people: People, extensions: set) -> list:
    if not folder.is_dir():
        return []
    want = people.key(name)
    found = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        stem = path.stem
        candidates = [stem]
        if " - " in stem:
            candidates.append(stem.rsplit(" - ", 1)[1])
        if any(people.key(c) == want for c in candidates):
            found.append(path)
    return found


def make_placeholder(name: str, fonts: FontSet) -> Image.Image:
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") / 65535
    r, g, b = colorsys.hls_to_rgb(hue, 0.38, 0.55)
    img = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), (round(r * 255), round(g * 255), round(b * 255), 255))
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    initials = "".join(next((c for c in w if c.isalnum()), "") for w in words[:2]).upper() or "?"
    fonts.draw(img, (AVATAR_SIZE // 2, AVATAR_SIZE // 2), initials, 240, (255, 255, 255, 255),
               bold=True, anchor="mm")
    return img


def _download(name: str, value: str, raw_dir: Path, avatars_dir: str,
              warn: Callable[[str], None]) -> Optional[Path]:
    """The raw picture file for `name` (cached), or None."""
    cached = sorted(raw_dir.glob(f"{slug(name)}.*")) if raw_dir.is_dir() else []
    if cached:
        return cached[0]
    url = picture_url(value)
    if not url:
        return None
    try:
        data, ctype = _fetch(url)
    except Exception as exc:
        warn(f"Couldn't download {name}'s profile picture ({exc}) — "
             f"save it as {avatars_dir}/{name}.png")
        return None
    ext = _CONTENT_EXT.get(str(ctype).lower())
    if ext is None:
        try:
            with Image.open(io.BytesIO(data)) as probe:
                ext = "." + (probe.format or "png").lower()
        except Exception:
            warn(f"{name}'s profile picture isn't shared publicly — "
                 f"save it as {avatars_dir}/{name}.png")
            return None
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{slug(name)}{ext}"
    path.write_bytes(data)
    return path


def prepare_avatars(pictures: dict, cfg: Config, people: People,
                    warn: Callable[[str], None] = log.warn, offline: bool = False) -> dict:
    """One 512x512 PNG per submitter (name -> path), in cfg.work_dir/avatars."""
    out_dir = cfg.work_dir / "avatars"
    out_dir.mkdir(parents=True, exist_ok=True)
    folder = cfg.path(cfg.input.avatars_dir)
    extensions = set(IMAGE_EXTENSIONS)
    if _register_heif():
        extensions |= {".heic", ".heif"}
    fonts = FontSet(cfg.fonts, warn=warn)
    result = {}
    for name, value in pictures.items():
        image = None
        for path in _find_local(folder, name, people, extensions):
            image = _load(path)
            if image is not None:
                break
            warn(f"Can't read the profile picture {path}; trying the next source.")
        if image is None and not offline:
            raw = _download(name, value, out_dir / "raw", cfg.input.avatars_dir, warn)
            if raw is not None:
                image = _load(raw)
                if image is None:
                    raw.unlink()   # don't keep a broken download in the cache
                    warn(f"{name}'s profile picture isn't a readable image — "
                         f"save it as {cfg.input.avatars_dir}/{name}.png")
        if image is None:
            image = make_placeholder(name, fonts)
        target = out_dir / f"{slug(name)}.png"
        image.save(target)
        result[name] = target
    return result
