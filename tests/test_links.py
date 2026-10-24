import pytest

from chatting.links import is_url, youtube_id, youtube_start_param

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?t=10",
    f"https://www.youtube.com/watch?v={VID}",
    f"https://www.youtube.com/watch?feature=share&v={VID}&t=5",
    f"youtube.com/watch?v={VID}",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"https://www.youtube.com/live/{VID}?feature=share",
    f"https://music.youtube.com/watch?v={VID}&si=abc",
    f"https://m.youtube.com/watch?v={VID}",
    f"  http://youtu.be/{VID}  ",
])
def test_youtube_id(url):
    assert youtube_id(url) == VID


@pytest.mark.parametrize("url", ["", "https://example.com/watch?v=" + VID, "https://youtu.be/short", "hello"])
def test_youtube_id_none(url):
    assert youtube_id(url) is None


@pytest.mark.parametrize("suffix,expected", [
    ("?t=95", 95), ("?t=95s", 95), ("?t=1m35s", 95), ("?t=1h2m3s", 3723),
    ("?start=95", 95), ("#t=1:35", 95), ("&t=2m", 120), ("?t=abc", None), ("", None),
])
def test_start_param(suffix, expected):
    url = f"https://www.youtube.com/watch?v={VID}{suffix.replace(chr(63), chr(38))}" if suffix[:1] != "#" else f"https://youtu.be/{VID}{suffix}"
    assert youtube_start_param(url) == expected


def test_is_url():
    assert is_url("https://x.com")
    assert is_url("http://x.com/a")
    assert is_url("www.youtube.com/watch?v=1")
    assert not is_url("youtube")
    assert not is_url("")
