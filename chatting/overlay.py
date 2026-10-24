"""The picture drawn over each song's clip: ranks, ratings, names and comment boxes.

Everything but the comments goes into one `base` image (opaque black with a transparent
hole where the video shows through). Comments go into one transparent image per "page";
pages are shown one after another so every comment gets read.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw

from . import log
from .config import FontsConfig
from .models import RankedSong
from .text import FontSet, get_fontset

WIDTH, HEIGHT = 1920, 1080
VID_W, VID_H = 1310, 736
VID_X, VID_Y = (WIDTH - VID_W) // 2, (HEIGHT - VID_H) // 2   # (305, 172)

GREEN = (0, 255, 0, 255)
RED = (224, 90, 71, 255)
BLUE = (91, 155, 213, 255)
ORANGE = (230, 145, 56, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
YELLOW = (255, 255, 0, 255)

RANK_SIZE = 90
NOMINATOR_SIZE = 52
NOMINATOR_MIN_SIZE = 24
BAND_MARGIN = 10               # text distance from the video box's left/right edge
BAND_GAP = 40                  # minimum space between two texts in the same band
AVERAGE_SIZE = 85
LABEL_SIZE = 44
LABEL_MIN_SIZE = 26

AVATAR_PX = 155

PANEL_MARGIN = 30              # top/bottom space kept free in the side panels
PANEL_STEP = 108
PANEL_FONT = 38
PANEL_FONT_RATIO = 0.6
PANEL_NAME_EDGE = 20           # name distance from the screen edge
PANEL_GRADE_EDGE = 15          # grade distance from the video box
PANEL_NAME_GAP = 20
PANEL_MIN_FONT = 14

BOX_W = 330
BOX_HEADER_H = 32
BOX_HEADER_FONT = 22
BOX_PAD_X = 10
BOX_PAD_Y = 10
BOX_FONT = 24
BOX_MIN_FONT = 18
MAX_BODY_H = 300
BOX_GAP = 14
BOX_MARGIN = 12                # distance from the video box edge
MIN_PAGE_SECONDS = 4.0         # below this per page, warn that comments are hard to read


@dataclass
class OverlayPlan:
    base: Path
    pages: list   # [(png path, start seconds, end seconds)]
    boxes: list = field(default_factory=list)   # every comment box drawn, in reading order


@dataclass
class _Box:
    voter: str
    lines: list
    font: int
    body_h: int
    header: str = ""   # text in the header strip; the voter's name unless the comment is split

    @property
    def height(self) -> int:
        return BOX_HEADER_H + self.body_h


def grade_text(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _grade(item: RankedSong, voter: str) -> tuple:
    value = item.ratings.get(voter)
    if voter in item.excluded or value is None:
        return "-", BLUE
    text = grade_text(value)
    if value >= 10:
        return text, GREEN
    if value < 5:
        return text, RED
    return text, WHITE


def _draw_top_band(img: Image.Image, item: RankedSong, fonts: FontSet) -> None:
    mid = VID_Y // 2
    left, right = VID_X + BAND_MARGIN, VID_X + VID_W - BAND_MARGIN
    rank = f"#{item.rank}"
    fonts.draw(img, (left, mid), rank, RANK_SIZE, GREEN, bold=True, anchor="lm")
    rank_w = fonts.measure(rank, RANK_SIZE, bold=True)[0]
    text = f"nominated by {item.song.submitter}"
    room = right - (left + rank_w + BAND_GAP)
    size = fonts.fit_size(text, room, NOMINATOR_SIZE, NOMINATOR_MIN_SIZE)
    fonts.draw(img, (right, mid), text, size, WHITE, anchor="rm")


def _draw_bottom_band(img: Image.Image, item: RankedSong, fonts: FontSet) -> None:
    top = VID_Y + VID_H
    mid = top + (HEIGHT - top) // 2
    left, right = VID_X + BAND_MARGIN, VID_X + VID_W - BAND_MARGIN
    avg = f"{item.average:.2f}" if item.average is not None else "–"
    fonts.draw(img, (left, mid), avg, AVERAGE_SIZE, ORANGE, anchor="lm")
    avg_w = fonts.measure(avg, AVERAGE_SIZE)[0]

    start = left + avg_w + BAND_GAP
    room = right - start
    song = item.song
    label = f"“{song.title}” by {song.artist}" if song.artist else song.title
    size = fonts.fit_size(label, room, LABEL_SIZE, LABEL_MIN_SIZE)
    if fonts.measure(label, size)[0] > room:
        lines = fonts.wrap(label, size, room)
        if len(lines) > 2:
            lines = lines[:2]
            while lines[1] and fonts.measure(lines[1] + "…", size)[0] > room:
                lines[1] = lines[1][:-1]
            lines[1] = lines[1].rstrip() + "…"
        label = "\n".join(lines)
    fonts.draw(img, ((start + right) // 2, mid), label, size, WHITE, anchor="mm")


def _draw_panels(img: Image.Image, item: RankedSong, voters: list, fonts: FontSet) -> None:
    if not voters:
        return
    half = math.ceil(len(voters) / 2)
    left_voters, right_voters = voters[:half], voters[half:]
    rows = len(left_voters)
    step = min(PANEL_STEP, (HEIGHT - 2 * PANEL_MARGIN) / rows)
    top = (HEIGHT - rows * step) / 2
    size = int(min(PANEL_FONT, step * PANEL_FONT_RATIO))
    panel_w = VID_X - PANEL_GRADE_EDGE - PANEL_NAME_EDGE
    grades = {v: _grade(item, v) for v in voters}
    grade_w = max(fonts.measure(g[0], size)[0] for g in grades.values())
    name_room = panel_w - PANEL_NAME_GAP - grade_w

    def name_size(name: str) -> int:
        return fonts.fit_size(name, name_room, size, PANEL_MIN_FONT)

    for i, voter in enumerate(left_voters):
        y = round(top + (i + 0.5) * step)
        text, color = grades[voter]
        fonts.draw(img, (PANEL_NAME_EDGE, y), voter, name_size(voter), WHITE, anchor="lm")
        fonts.draw(img, (VID_X - PANEL_GRADE_EDGE, y), text, size, color, anchor="rm")
    for i, voter in enumerate(right_voters):
        y = round(top + (i + 0.5) * step)
        text, color = grades[voter]
        fonts.draw(img, (VID_X + VID_W + PANEL_GRADE_EDGE, y), text, size, color, anchor="lm")
        fonts.draw(img, (WIDTH - PANEL_NAME_EDGE, y), voter, name_size(voter), WHITE, anchor="rm")


def _make_box(voter: str, comment: str, fonts: FontSet) -> list:
    """One box per comment, or several consecutive boxes when it is too long for one."""
    room = BOX_W - 2 * BOX_PAD_X
    for size in range(BOX_FONT, BOX_MIN_FONT - 1, -1):
        lines = fonts.wrap(comment, size, room)
        line_h = fonts.measure("Ag", size)[1]
        body_h = len(lines) * line_h + 2 * BOX_PAD_Y
        if body_h <= MAX_BODY_H:
            return [_Box(voter, lines, size, body_h, voter)]
    # too tall even at the minimum font: split the lines over several boxes
    size = BOX_MIN_FONT
    line_h = fonts.measure("Ag", size)[1]
    lines = []
    for line in fonts.wrap(comment, size, room):
        if fonts.measure(line, size)[0] > room:   # last resort: a single glyph that can't fit
            while line and fonts.measure(line + "…", size)[0] > room:
                line = line[:-1]
            line = line.rstrip() + "…"
        lines.append(line)
    fit = max(1, (MAX_BODY_H - 2 * BOX_PAD_Y) // line_h)
    chunks = [lines[i:i + fit] for i in range(0, len(lines), fit)]
    total = len(chunks)
    return [_Box(voter, chunk, size, len(chunk) * line_h + 2 * BOX_PAD_Y,
                 f"{voter} ({k}/{total})" if total > 1 else voter)
            for k, chunk in enumerate(chunks, 1)]


def _pack(boxes: list) -> list:
    """Greedy layout: returns pages, each a list of (box, x, y)."""
    bottom = VID_Y + VID_H - BOX_MARGIN
    column_x = [VID_X + BOX_MARGIN, VID_X + VID_W - BOX_MARGIN - BOX_W]
    column_top = [VID_Y + BOX_MARGIN, VID_Y + AVATAR_PX + BOX_MARGIN]
    pages: list = []
    cursor: list = []

    def new_page():
        pages.append([])
        cursor[:] = column_top

    for box in boxes:
        if not pages:
            new_page()
        for attempt in range(2):
            fits = [c for c in (0, 1) if cursor[c] + box.height <= bottom]
            if fits:
                col = max(fits, key=lambda c: (bottom - cursor[c], -c))
                pages[-1].append((box, column_x[col], cursor[col]))
                cursor[col] += box.height + BOX_GAP
                break
            if attempt == 0:
                new_page()
    return pages


def _draw_page(boxes: list, fonts: FontSet) -> Image.Image:
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for box, x, y in boxes:
        draw.rectangle([x, y, x + BOX_W - 1, y + BOX_HEADER_H - 1], fill=WHITE)
        header = box.header or box.voter
        size = fonts.fit_size(header, BOX_W - 12, BOX_HEADER_FONT, 12, bold=True)
        fonts.draw(img, (x + BOX_W // 2, y + BOX_HEADER_H // 2), header, size, BLACK,
                   bold=True, anchor="mm")
        body_y = y + BOX_HEADER_H
        draw.rectangle([x, body_y, x + BOX_W - 1, body_y + box.body_h - 1], fill=YELLOW)
        fonts.draw(img, (x + BOX_W // 2, body_y + box.body_h // 2), "\n".join(box.lines),
                   box.font, BLACK, anchor="mm")
    return img


def build_overlays(item: RankedSong, voters: list, avatar: Optional[Path], fonts: FontSet,
                   clip_seconds: float, out_dir: Path, name: str,
                   warn: Callable[[str], None] = log.warn) -> OverlayPlan:
    """Write `<name>_base.png` and `<name>_comments_<k>.png` into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Image.new("RGBA", (WIDTH, HEIGHT), BLACK)
    base.paste((0, 0, 0, 0), (VID_X, VID_Y, VID_X + VID_W, VID_Y + VID_H))
    _draw_top_band(base, item, fonts)
    _draw_bottom_band(base, item, fonts)
    _draw_panels(base, item, voters, fonts)
    if avatar is not None:
        with Image.open(avatar) as raw:
            pic = raw.convert("RGBA").resize((AVATAR_PX, AVATAR_PX), Image.LANCZOS)
        backing = Image.new("RGBA", pic.size, BLACK)
        backing.alpha_composite(pic)
        base.paste(backing, (VID_X + VID_W - AVATAR_PX, VID_Y))
    base_path = out_dir / f"{name}_base.png"
    base.save(base_path)

    boxes = []
    for voter in voters:
        comment = (item.comments.get(voter) or "").strip()
        if comment:
            boxes.extend(_make_box(voter, comment, fonts))
    pages = _pack(boxes)
    plan_pages = []
    for k, page in enumerate(pages):
        path = out_dir / f"{name}_comments_{k}.png"
        _draw_page(page, fonts).save(path)
        plan_pages.append((path, k * clip_seconds / len(pages), (k + 1) * clip_seconds / len(pages)))
    if pages and clip_seconds / len(pages) < MIN_PAGE_SECONDS:
        warn(f"#{item.rank} {item.song.label}: {len(pages)} comment pages of "
             f"{clip_seconds / len(pages):.1f} s each — hard to read; "
             f"consider a longer [video] clip_seconds")
    return OverlayPlan(base=base_path, pages=plan_pages,
                       boxes=boxes)


def compose_preview(plan: OverlayPlan, frame: Optional[Image.Image] = None) -> list:
    """What the video will look like: one RGB image per comment page."""
    screen = Image.new("RGBA", (WIDTH, HEIGHT), BLACK)
    if frame is None:
        box = Image.new("RGBA", (VID_W, VID_H), (40, 40, 40, 255))
        get_fontset(FontsConfig()).draw(box, (VID_W // 2, VID_H // 2), "VIDEO", 120,
                                        (90, 90, 90, 255), bold=True, anchor="mm")
    else:
        rgba = frame.convert("RGBA")
        scale = min(VID_W / rgba.width, VID_H / rgba.height)
        rgba = rgba.resize((max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))),
                           Image.LANCZOS)
        box = Image.new("RGBA", (VID_W, VID_H), BLACK)
        box.paste(rgba, ((VID_W - rgba.width) // 2, (VID_H - rgba.height) // 2))
    screen.paste(box, (VID_X, VID_Y))
    with Image.open(plan.base) as base:
        screen.alpha_composite(base.convert("RGBA"))
    pages = [p[0] for p in plan.pages] or [None]
    out = []
    for page in pages:
        shot = screen.copy()
        if page is not None:
            with Image.open(page) as layer:
                shot.alpha_composite(layer.convert("RGBA"))
        out.append(shot.convert("RGB"))
    return out
