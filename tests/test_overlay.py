from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from chatting.config import FontsConfig
from chatting.models import RankedSong, Song
from chatting.overlay import (
    BOX_W, HEIGHT, MAX_BODY_H, VID_H, VID_W, VID_X, VID_Y, WIDTH, build_overlays, compose_preview, grade_text, _pack,
)
from chatting.text import FontSet


@pytest.fixture(scope="module")
def fonts():
    return FontSet(FontsConfig(), warn=lambda m: None)


def make_item(voters, comments=None, title="Some Song", artist="Some Artist", submitter="Calin"):
    ratings = {}
    for i, v in enumerate(voters):
        ratings[v] = [10, 3.5, None, 7.25, 8][i % 5]
    excluded = set()
    if submitter in voters:
        excluded.add(submitter)
    return RankedSong(
        song=Song(id=1, title=title, artist=artist, link="x", submitter=submitter),
        ratings=ratings, comments=comments or {}, excluded=excluded, average=6.78, votes=10, rank=12,
    )


def voters_of(n):
    return [f"Voter{i}" if i else "Calin" for i in range(n)]


def avatar(tmp_path):
    p = tmp_path / "av.png"
    Image.new("RGBA", (512, 512), (200, 50, 50, 255)).save(p)
    return p


def test_grade_text():
    assert grade_text(6.78) == "6.78"
    assert grade_text(7.5) == "7.5"
    assert grade_text(10) == "10"
    assert grade_text(None) == "-"


def test_base_layout(tmp_path, fonts):
    voters = voters_of(17)
    plan = build_overlays(make_item(voters), voters, avatar(tmp_path), fonts, 15, tmp_path, "001")
    assert plan.pages == []
    base = Image.open(plan.base)
    assert base.size == (WIDTH, HEIGHT) and base.mode == "RGBA"
    alpha = base.getchannel("A")
    inside = alpha.crop((VID_X, VID_Y, VID_X + VID_W, VID_Y + VID_H))
    av = (VID_W - 155, 0, VID_W, 155)
    inside_no_av = inside.copy()
    inside_no_av.paste(0, av)
    assert inside_no_av.getextrema() == (0, 0)
    assert inside.crop(av).getextrema() == (255, 255)
    outside = alpha.copy()
    outside.paste(255, (VID_X, VID_Y, VID_X + VID_W, VID_Y + VID_H))
    assert outside.getextrema() == (255, 255)
    assert base.convert("RGB").getbbox() is not None   # text was drawn


def test_missing_average_and_no_artist(tmp_path, fonts):
    item = make_item(["A", "B"], title="Only Title", artist="")
    item.average = None
    plan = build_overlays(item, ["A", "B"], None, fonts, 15, tmp_path, "x")
    assert plan.base.exists()


COMMENT = "This song absolutely slaps, the second verse is unreal 💀😂🔥 and the bridge made me cry " * 2


def box_pixels_inside(path):
    alpha = Image.open(path).getchannel("A")
    left, top, right, bottom = alpha.getbbox()
    return left >= VID_X and top >= VID_Y and right <= VID_X + VID_W and bottom <= VID_Y + VID_H


def test_many_comments_paginate(tmp_path, fonts):
    voters = voters_of(17)
    comments = {v: COMMENT for v in voters[:16]}
    plan = build_overlays(make_item(voters, comments), voters, None, fonts, 15, tmp_path, "002")
    assert len(plan.pages) > 1
    assert plan.pages[0][1] == 0
    for (_, s, e), (_, s2, _) in zip(plan.pages, plan.pages[1:]):
        assert e == pytest.approx(s2)
    assert plan.pages[-1][2] == pytest.approx(15)
    for path, _, _ in plan.pages:
        assert box_pixels_inside(path)


def test_few_comments_single_page(tmp_path, fonts):
    voters = voters_of(5)
    plan = build_overlays(make_item(voters, {"Voter1": "nice", "Voter2": "  ", "Voter3": "ok"}), voters,
                          None, fonts, 15, tmp_path, "003")
    assert len(plan.pages) == 1
    assert plan.pages[0][1:] == (0, 15)
    shots = compose_preview(plan)
    assert len(shots) == 1 and shots[0].size == (WIDTH, HEIGHT) and shots[0].mode == "RGB"


def test_no_comments_preview_has_one_image(tmp_path, fonts):
    plan = build_overlays(make_item(voters_of(3)), voters_of(3), None, fonts, 15, tmp_path, "004")
    assert plan.pages == []
    assert len(compose_preview(plan)) == 1
    frame = Image.new("RGB", (640, 480), (0, 0, 255))
    shot = compose_preview(plan, frame)[0]
    assert shot.getpixel((VID_X + VID_W // 2, VID_Y + VID_H // 2)) == (0, 0, 255)


@pytest.mark.parametrize("n", [2, 30])
def test_voter_counts(tmp_path, fonts, n):
    voters = voters_of(n)
    comments = {v: "short one" for v in voters}
    plan = build_overlays(make_item(voters, comments), voters, None, fonts, 15, tmp_path, f"n{n}")
    assert plan.base.exists()
    for path, _, _ in plan.pages:
        assert box_pixels_inside(path)


def test_boxes_do_not_overlap(tmp_path, fonts):
    voters = voters_of(12)
    comments = {v: "word " * (5 + 7 * i) for i, v in enumerate(voters)}
    plan = build_overlays(make_item(voters, comments), voters, None, fonts, 15, tmp_path, "ov")
    for path, _, _ in plan.pages:
        alpha = Image.open(path).getchannel("A")
        # left column and right column each form vertical stacks; check the columns' x extents don't mix
        left = alpha.crop((VID_X, VID_Y, VID_X + VID_W // 2, VID_Y + VID_H)).getbbox()
        right = alpha.crop((VID_X + VID_W // 2, VID_Y, VID_X + VID_W, VID_Y + VID_H)).getbbox()
        for bb in (left, right):
            if bb:
                assert bb[2] - bb[0] <= BOX_W
        if right:
            # right column starts below the avatar
            assert right[1] + VID_Y >= VID_Y + 155


def test_dense_and_sparse_previews(tmp_path, fonts):
    out = Path("/tmp/claude-0/-home-user-chatting-python-wholesome/57193013-cdee-5590-bb7d-68a45decaea6/scratchpad")
    if not out.is_dir():
        pytest.skip("scratchpad missing")
    voters = voters_of(17)
    comments = {v: COMMENT[: 40 + 25 * i] for i, v in enumerate(voters[:10])}
    plan = build_overlays(make_item(voters, comments), voters, avatar(tmp_path), fonts, 15, tmp_path, "d")
    compose_preview(plan)[0].save(out / "preview_dense.png")
    sparse = {voters[1]: "Absolute banger 🔥", voters[2]: "I heard this at 3am once 💀",
              voters[3]: "Not my thing but the guitar is good"}
    plan = build_overlays(make_item(voters, sparse), voters, avatar(tmp_path), fonts, 15, tmp_path, "s")
    compose_preview(plan)[0].save(out / "preview_sparse.png")


LONG = " ".join(f"word{i}{'😀' if i % 9 == 0 else ''}" for i in range(120))   # ~720 characters


def test_long_comment_is_split_not_truncated(tmp_path, fonts):
    voters = voters_of(4)
    assert len(LONG) >= 700
    plan = build_overlays(make_item(voters, {"Voter1": LONG}), voters, None, fonts, 15, tmp_path, "long",
                          warn=lambda m: None)
    boxes = plan.boxes
    assert len(boxes) > 1
    assert not any(line.endswith("…") for box in boxes for line in box.lines)
    assert all(box.body_h <= MAX_BODY_H for box in boxes)
    n = len(boxes)
    assert [b.header for b in boxes] == [f"Voter1 ({k}/{n})" for k in range(1, n + 1)]
    words = " ".join(" ".join(b.lines) for b in boxes).split()
    assert words == LONG.split()
    for path, _, _ in plan.pages:
        assert box_pixels_inside(path)


def test_continuation_boxes_follow_the_first(tmp_path, fonts):
    voters = voters_of(6)
    comments = {"Voter1": LONG, "Voter2": "short", "Voter3": LONG}
    plan = build_overlays(make_item(voters, comments), voters, None, fonts, 15, tmp_path, "cont",
                          warn=lambda m: None)
    placed = [(page_no, b, x, y) for page_no, page in enumerate(_pack(plan.boxes))
              for b, x, y in page]
    assert len(placed) == len(plan.boxes)
    for voter in ("Voter1", "Voter3"):
        pages = [p for p, b, _, _ in placed if b.voter == voter]
        assert pages == sorted(pages)
        first = next(pl for pl in placed if pl[1].voter == voter)
        for p, b, x, y in placed:
            if b.voter == voter and b is not first[1]:
                assert p > first[0] or (p == first[0] and (x, y) != (first[2], first[3]))
                assert b.header > voter   # continuation headers carry the "(k/n)" suffix


def test_warns_when_pages_are_too_short(tmp_path, fonts):
    seen = []
    voters = voters_of(21)
    medium = "This song absolutely slaps, the second verse is unreal and the bridge made me cry"
    comments = {v: medium for v in voters[1:]}
    plan = build_overlays(make_item(voters, comments), voters, None, fonts, 15, tmp_path, "w1",
                          warn=seen.append)
    assert len(plan.pages) > 3
    assert len(seen) == 1
    assert "#12 Some Artist - Some Song" in seen[0] and "clip_seconds" in seen[0]
    quiet = []
    short = {"Voter1": "nice", "Voter2": "ok", "Voter3": "wow"}
    build_overlays(make_item(voters, short), voters, None, fonts, 15, tmp_path, "w2", warn=quiet.append)
    assert quiet == []
