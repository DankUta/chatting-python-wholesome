import pytest

from chatting.timestamps import format_time, parse_time, parse_timestamps_field


@pytest.mark.parametrize("text,expected", [
    ("1:30", 90), ("01:02:03", 3723), ("1:30.5", 90.5), ("90", 90), ("90s", 90), ("90 sec", 90),
    ("1m30s", 90), ("1m 30s", 90), ("1 min 30", 90), ("1min30s", 90), ("2m", 120),
    ("1.30", 90), ("1,30", 90), ("0.45", 45), (" 0:45 ", 45),
    ("", None), ("abc", None), (None, None), ("nan", None),
])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


def test_format_time():
    assert format_time(90) == "1:30"
    assert format_time(3723) == "1:02:03"
    assert format_time(5) == "0:05"
    assert format_time(None) == ""


@pytest.mark.parametrize("text,expected", [
    ("1: 0:45, 2: 1:20", {1: 45, 2: 80}),
    ("1. 0:45\n2. 1:20", {1: 45, 2: 80}),
    ("1) 1:02", {1: 62}),
    ("1 - 0:45", {1: 45}),
    ("1 – 0:45", {1: 45}),
    ("Song 1: 0:45", {1: 45}),
    ("song1 - 1:05", {1: 65}),
    ("#1 0:45", {1: 45}),
    ("1 = 0:45", {1: 45}),
    ("1:0:45", {1: 45}),
    ("1: 0:45-1:00", {1: 45}),
    ("1: 45s", {1: 45}),
    ("1: 1m20s", {1: 80}),
    ("1. 1.20", {1: 80}),
    ("1: 0:10\n2: 0:20\n3: 0:30\n4: 0:40\n5: 0:50\n6: 1:00", {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}),
    ("3: 1:00", {3: 60}),
    ("0:45, 1:20, 2:00", {1: 45, 2: 80, 3: 120}),
    ("0:45\n1:20", {1: 45, 2: 80}),
    ("", {}),
    ("no idea", {}),
])
def test_parse_timestamps_field(text, expected):
    assert parse_timestamps_field(text) == expected
