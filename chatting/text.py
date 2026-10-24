"""Text drawing with font fallback: regular text, bold text and color emoji in one line."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFont

from . import log
from .config import FontsConfig

REGULAR_NAMES = ["arial.ttf", "Arial.ttf", "segoeui.ttf", "DejaVuSans.ttf",
                 "LiberationSans-Regular.ttf", "FreeSans.ttf"]
BOLD_NAMES = ["arialbd.ttf", "Arial Bold.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf",
              "LiberationSans-Bold.ttf", "FreeSansBold.ttf"]
EMOJI_NAMES = ["seguiemj.ttf", "NotoColorEmoji.ttf", "Apple Color Emoji.ttc"]
FALLBACK_NAMES = ["DejaVuSans.ttf", "seguisym.ttf", "NotoSansSymbols2-Regular.ttf", "unifont.otf"]

BITMAP_EMOJI_SIZE = 109   # the only size CBDT color fonts (Noto Color Emoji) can be loaded at
ZWJ = 0x200D
KEYCAP = 0x20E3
STICKY = {ZWJ, KEYCAP, 0xFE0E, 0xFE0F} | set(range(0x1F3FB, 0x1F400))


class FontError(Exception):
    pass


class _Face:
    """One font file that can be loaded at any size (bitmap fonts get scaled)."""

    def __init__(self, source: str, is_emoji: bool = False):
        self.source = source
        self.is_emoji = is_emoji
        self._fonts: dict[int, tuple] = {}
        self._cmap: Optional[set] = None
        self._cmap_loaded = False
        first = self.get(BITMAP_EMOJI_SIZE if is_emoji else 20)   # raises OSError if unusable
        self.path: Optional[str] = getattr(first[0], "path", None)

    def get(self, size: int):
        """(font, scale): draw with `font`, then scale the result by `scale`."""
        size = max(1, int(size))
        if size not in self._fonts:
            try:
                self._fonts[size] = (ImageFont.truetype(self.source, size), 1.0)
            except OSError:
                font = ImageFont.truetype(self.source, BITMAP_EMOJI_SIZE)
                self._fonts[size] = (font, size / BITMAP_EMOJI_SIZE)
        return self._fonts[size]

    def covers(self, code: int) -> bool:
        if not self._cmap_loaded:
            self._cmap_loaded = True
            try:
                from fontTools.ttLib import TTFont
                if self.path:
                    self._cmap = set(TTFont(self.path, fontNumber=0, lazy=True).getBestCmap() or {})
            except Exception:
                self._cmap = None
        return True if self._cmap is None else code in self._cmap


def _first_loadable(names: list, is_emoji: bool = False) -> Optional[_Face]:
    for name in names:
        try:
            return _Face(name, is_emoji)
        except OSError:
            continue
    return None


@dataclass
class _Run:
    face: Optional[_Face]
    text: str


@dataclass
class FontSet:
    fonts_cfg: FontsConfig
    warn: Callable[[str], None] = log.warn
    _warned: set = field(default_factory=set, init=False, repr=False)

    def __post_init__(self):
        cfg = self.fonts_cfg
        self._regular = self._pick(cfg.regular, REGULAR_NAMES, "regular")
        self._bold = self._pick(cfg.bold, BOLD_NAMES, "bold") or self._regular
        self._emoji = self._pick(cfg.emoji, EMOJI_NAMES, "emoji", True)
        self._fallbacks = [f for f in (_first_loadable([n]) for n in FALLBACK_NAMES) if f]
        self._metrics: dict[tuple, tuple] = {}

    @staticmethod
    def _pick(configured: str, names: list, what: str, is_emoji: bool = False) -> Optional[_Face]:
        if configured:
            try:
                return _Face(configured, is_emoji)
            except OSError as exc:
                raise FontError(f"Can't load the {what} font {configured!r}: {exc}") from exc
        return _first_loadable(names, is_emoji)

    @property
    def has_emoji(self) -> bool:
        return self._emoji is not None

    def describe(self) -> str:
        """Which font files are in use, for `chatting check`."""
        def name(face: Optional[_Face]) -> str:
            return os.path.basename(face.path or face.source) if face else "none (Pillow's built-in font)"
        emoji = name(self._emoji) if self._emoji else "none (emoji in comments will be left out)"
        return f"regular {name(self._regular)}, bold {name(self._bold)}, emoji {emoji}"

    def _primary(self, bold: bool) -> Optional[_Face]:
        return self._bold if bold else self._regular

    def _faces(self, bold: bool) -> list:
        faces = [self._primary(bold), self._emoji, *self._fallbacks]
        return [f for f in faces if f is not None]

    # -- layout ----------------------------------------------------------

    def _line_metrics(self, size: int, bold: bool) -> tuple:
        key = (size, bold)
        if key not in self._metrics:
            face = self._primary(bold)
            if face is None:
                font = ImageFont.load_default(size)
            else:
                font = face.get(size)[0]
            try:
                asc, desc = font.getmetrics()
            except AttributeError:
                asc, desc = size, size // 4
            self._metrics[key] = (asc, desc)
        return self._metrics[key]

    def _split(self, line: str, bold: bool) -> list:
        faces = self._faces(bold)
        runs: list = []
        dropped_prev = False
        for ch in line:
            code = ord(ch)
            if ch == "\t":
                ch, code = " ", 32
            if code in STICKY and runs and not dropped_prev:
                face = runs[-1].face
                if face is None or face.is_emoji or face.covers(code):
                    runs[-1].text += ch
                continue
            if code in STICKY:
                continue
            face = next((f for f in faces if f.covers(code)), None)
            if face is None:
                dropped_prev = True
                if ch not in self._warned and ch.isprintable():
                    self._warned.add(ch)
                    self.warn(f"No font has the character {ch!r} (U+{code:04X}); it was left out.")
                continue
            dropped_prev = False
            if runs and runs[-1].face is face:
                runs[-1].text += ch
            else:
                runs.append(_Run(face, ch))
        return runs

    def _run_width(self, run: _Run, size: int) -> float:
        if run.face is None:
            return ImageFont.load_default(size).getlength(run.text)
        font, scale = run.face.get(size)
        return font.getlength(run.text) * scale

    def _line_size(self, line: str, size: int, bold: bool) -> tuple:
        asc, desc = self._line_metrics(size, bold)
        width = sum(self._run_width(r, size) for r in self._split(line, bold))
        return math.ceil(width), asc + desc

    def measure(self, text: str, size: int, bold: bool = False) -> tuple:
        lines = str(text).split("\n")
        sizes = [self._line_size(line, size, bold) for line in lines]
        return max(w for w, _ in sizes), sum(h for _, h in sizes)

    def _render_line(self, line: str, size: int, bold: bool, fill: tuple) -> Image.Image:
        asc, desc = self._line_metrics(size, bold)
        runs = self._split(line, bold)
        width = max(1, math.ceil(sum(self._run_width(r, size) for r in runs)))
        out = Image.new("RGBA", (width, asc + desc), (0, 0, 0, 0))
        x = 0.0
        for run in runs:
            w = self._run_width(run, size)
            if run.face is None:
                font, scale = ImageFont.load_default(size), 1.0
            else:
                font, scale = run.face.get(size)
            try:
                r_asc, r_desc = font.getmetrics()
            except AttributeError:
                r_asc, r_desc = asc, desc
            raw_w = max(1, math.ceil(w / scale))
            if run.face is not None and run.face.is_emoji:
                layer = Image.new("RGBA", (raw_w, r_asc + r_desc), (0, 0, 0, 0))
                ImageDraw.Draw(layer).text((0, r_asc), run.text, font=font, anchor="ls",
                                           embedded_color=True)
            else:
                mask = Image.new("L", (raw_w, r_asc + r_desc), 0)
                ImageDraw.Draw(mask).text((0, r_asc), run.text, font=font, anchor="ls", fill=255)
                layer = Image.new("RGBA", mask.size, fill[:3] + (0,))
                layer.putalpha(mask)
            if scale != 1.0:
                layer = layer.resize((max(1, round(layer.width * scale)),
                                      max(1, round(layer.height * scale))), Image.LANCZOS)
            top = asc - round(r_asc * scale)
            out.alpha_composite(*_clip(layer, (round(x), top), out.size))
            x += w
        if len(fill) > 3 and fill[3] < 255:
            alpha = out.getchannel("A").point(lambda v: v * fill[3] // 255)
            out.putalpha(alpha)
        return out

    def draw(self, img: Image.Image, xy: tuple, text: str, size: int, fill: tuple,
             bold: bool = False, anchor: str = "lt") -> None:
        if len(fill) == 3:
            fill = tuple(fill) + (255,)
        lines = str(text).split("\n")
        rendered = [self._render_line(line, size, bold, fill) for line in lines]
        total_w = max(r.width for r in rendered)
        total_h = sum(r.height for r in rendered)
        x0, y0 = xy
        h, v = anchor[0], anchor[1]
        top = y0 - (0 if v == "t" else total_h / 2 if v == "m" else total_h)
        y = top
        for r in rendered:
            if h == "l":
                x = x0
            elif h == "m":
                x = x0 - r.width / 2
            else:
                x = x0 - r.width
            _paste(img, r, (round(x), round(y)))
            y += r.height

    def wrap(self, text: str, size: int, max_width: int, bold: bool = False) -> list:
        out: list = []
        for para in str(text).split("\n"):
            current = ""
            for word in para.split(" "):
                candidate = word if not current else current + " " + word
                if self.measure(candidate, size, bold)[0] <= max_width:
                    current = candidate
                    continue
                if current:
                    out.append(current)
                    current = ""
                # a word that is too long on its own is broken by character
                while word and self.measure(word, size, bold)[0] > max_width:
                    cut = 1
                    while cut < len(word) and self.measure(word[:cut + 1], size, bold)[0] <= max_width:
                        cut += 1
                    out.append(word[:cut])
                    word = word[cut:]
                current = word
            out.append(current)
        return out

    def fit_size(self, text: str, max_width: int, max_size: int, min_size: int,
                 bold: bool = False) -> int:
        for size in range(int(max_size), int(min_size) - 1, -1):
            if self.measure(text, size, bold)[0] <= max_width:
                return size
        return int(min_size)


def _clip(layer: Image.Image, pos: tuple, size: tuple):
    """Crop `layer` so it fits a canvas of `size` when placed at `pos`."""
    x, y = pos
    left, top = max(0, -x), max(0, -y)
    right = min(layer.width, size[0] - x)
    bottom = min(layer.height, size[1] - y)
    if right <= left or bottom <= top:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0)), (0, 0)
    return layer.crop((left, top, right, bottom)), (x + left, y + top)


def _paste(img: Image.Image, layer: Image.Image, pos: tuple) -> None:
    piece, dest = _clip(layer, pos, img.size)
    if img.mode == "RGBA":
        img.alpha_composite(piece, dest)
    else:
        img.paste(piece.convert("RGB"), dest, piece.getchannel("A"))


_cache: dict = {}


def get_fontset(fonts_cfg: FontsConfig) -> FontSet:
    key = (fonts_cfg.regular, fonts_cfg.bold, fonts_cfg.emoji)
    if key not in _cache:
        _cache[key] = FontSet(fonts_cfg)
    return _cache[key]
