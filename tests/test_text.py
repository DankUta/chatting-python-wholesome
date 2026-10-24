from __future__ import annotations

import pytest
from PIL import Image, ImageChops

from chatting.config import FontsConfig
from chatting.text import FontError, FontSet


@pytest.fixture(scope="module")
def fonts():
    return FontSet(FontsConfig(), warn=lambda m: None)


def test_measure_grows_with_size_and_text(fonts):
    w1, h1 = fonts.measure("hello", 20)
    w2, h2 = fonts.measure("hello", 40)
    assert w2 > w1 and h2 > h1
    assert fonts.measure("hello world", 20)[0] > w1
    assert fonts.measure("a\nb", 20)[1] == 2 * fonts.measure("a", 20)[1]


def test_wrap_respects_width_and_newlines(fonts):
    lines = fonts.wrap("one two three four five six seven\nnext", 24, 150)
    assert len(lines) > 2
    assert all(fonts.measure(line, 24)[0] <= 150 for line in lines)
    assert "next" in lines
    long = fonts.wrap("x" * 80, 24, 150)
    assert len(long) > 1 and "".join(long) == "x" * 80


def test_fit_size(fonts):
    text = "A fairly long line of text"
    size = fonts.fit_size(text, 300, 60, 10)
    assert 10 <= size <= 60
    assert fonts.measure(text, size)[0] <= 300
    assert size == 60 or fonts.measure(text, size + 1)[0] > 300
    assert fonts.fit_size(text, 5, 60, 12) == 12


def test_draw_anchors(fonts):
    img = Image.new("RGBA", (400, 100), (0, 0, 0, 0))
    fonts.draw(img, (400, 50), "right", 30, (255, 255, 255, 255), anchor="rm")
    box = img.getbbox()
    assert box and box[2] <= 400 and box[0] > 200


def test_emoji_draws_pixels(fonts):
    if not fonts.has_emoji:
        pytest.skip("no emoji font installed")
    text_w = fonts.measure("lol ", 40)[0]
    img = Image.new("RGBA", (400, 80), (0, 0, 0, 0))
    fonts.draw(img, (0, 0), "lol 💀😂", 40, (255, 255, 255, 255))
    emoji_area = img.crop((text_w + 2, 0, 400, 80))
    assert emoji_area.getchannel("A").getbbox() is not None
    assert fonts.measure("lol 💀😂", 40)[0] > text_w + 40


def _run_faces(fonts, text):
    return [(r.face, r.text) for r in fonts._split(text, False)]


def test_emoji_presentation_prefers_emoji_face(fonts):
    if not fonts.has_emoji:
        pytest.skip("no emoji font installed")
    for text in ("\u2764\uFE0F", "\U0001F600"):
        runs = _run_faces(fonts, text)
        assert len(runs) == 1 and runs[0][0] is fonts._emoji and runs[0][1] == text
    for text in ("A", "\u2665"):
        runs = _run_faces(fonts, text)
        assert all(face is fonts._regular for face, _ in runs)


def test_dejavu_covered_emoji_are_colored(fonts):
    if not fonts.has_emoji:
        pytest.skip("no emoji font installed")
    text = "I \u2764\uFE0F this \U0001F600"
    start = fonts.measure("I ", 40)[0]
    img = Image.new("RGBA", (500, 80), (0, 0, 0, 0))
    fonts.draw(img, (0, 0), text, 40, (255, 255, 255, 255))
    area = img.crop((start, 0, 500, 80))
    r, g, b, _ = area.split()
    spread = ImageChops.difference(r, b).histogram()
    assert sum(spread[41:]) > 20   # clearly non-grey pixels


def test_unknown_characters_do_not_crash_and_warn_once():
    seen = []
    fs = FontSet(FontsConfig(), warn=seen.append)
    img = Image.new("RGBA", (300, 60), (0, 0, 0, 0))
    fs.draw(img, (0, 0), "a\U0010FFFFb\U0010FFFF", 30, (255, 255, 255, 255))
    fs.draw(img, (0, 0), "\U0010FFFF", 30, (255, 255, 255, 255))
    assert len(seen) <= 1


def test_missing_configured_font_is_an_error(tmp_path):
    with pytest.raises(FontError):
        FontSet(FontsConfig(regular=str(tmp_path / "nope.ttf")))
