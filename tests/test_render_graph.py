"""Fast checks of the ffmpeg expressions render.py builds (the real renders are in test_render.py)."""

from chatting.render import page_enable


def test_comment_pages_never_overlap():
    first = page_enable(0, 7.5, last_page=False)
    second = page_enable(7.5, 15, last_page=True)
    assert first == "gte(t,0)*lt(t,7.5)"
    assert second == "gte(t,7.5)"
