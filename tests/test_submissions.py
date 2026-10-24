import pandas as pd
import pytest

from chatting.config import ColumnsConfig
from chatting.models import Song
from chatting.names import People
from chatting.submissions import (
    SubmissionError, build_songs, detect_columns, find_duplicates, merge_registry,
    parse_submissions, read_registry, write_registry,
)

HEADERS = (
    ["Timestamp", "Email Address", "Name"]
    + [h for i in range(1, 6) for h in (f"Song {i} title", f"Song {i} artist", f"Song {i} link")]
    + ["Profile picture", "Timestamps go here"]
)


def test_detect_standard():
    cm = detect_columns(HEADERS, ColumnsConfig())
    assert cm.submitted_at == "Timestamp"
    assert cm.email == "Email Address"
    assert cm.name == "Name"
    assert cm.picture == "Profile picture"
    assert cm.timestamps == "Timestamps go here"
    assert cm.titles[3] == "Song 3 title"
    assert cm.artists[5] == "Song 5 artist"
    assert cm.links[1] == "Song 1 link"
    assert len(cm.links) == len(cm.titles) == len(cm.artists) == 5


def test_detect_legacy_headers():
    cm = detect_columns(["Timestamp", "Nickname"] + [f"Song {i} link" for i in range(1, 6)] + ["Timestamps go here"], ColumnsConfig())
    assert cm.name == "Nickname"
    assert sorted(cm.links) == [1, 2, 3, 4, 5]
    assert cm.titles == {}


def test_detect_song_n_is_title():
    cm = detect_columns(["Name", "Song 1", "Song 1 name", "Song 2", "Song 1 link"], ColumnsConfig())
    assert cm.titles[1] == "Song 1"      # first one wins
    assert cm.titles[2] == "Song 2"


def test_detect_romanian():
    headers = ["Marcaj de timp", "Adresă de e-mail", "Nume"]
    for i in range(1, 3):
        headers += [f"Piesa {i} titlu", f"Piesa {i} artistă", f"Piesa {i} link"]
    headers += ["Poza ta", "La ce minut să înceapă fiecare piesă?"]
    cm = detect_columns(headers, ColumnsConfig())
    assert cm.submitted_at == "Marcaj de timp"
    assert cm.email == "Adresă de e-mail"
    assert cm.name == "Nume"
    assert cm.picture == "Poza ta"
    assert cm.timestamps == "La ce minut să înceapă fiecare piesă?"
    assert cm.titles[2] == "Piesa 2 titlu"
    assert cm.artists[1] == "Piesa 1 artistă"
    assert cm.links[2] == "Piesa 2 link"


def test_detect_repeated_sections():
    headers = ["Timestamp", "Name"]
    for i in range(5):
        suffix = "" if i == 0 else f".{i}"
        headers += [f"Title{suffix}", f"Artist{suffix}", f"Link{suffix}"]
    cm = detect_columns(headers, ColumnsConfig())
    assert cm.name == "Name"
    assert cm.titles == {1: "Title", 2: "Title.1", 3: "Title.2", 4: "Title.3", 5: "Title.4"}
    assert cm.links[5] == "Link.4"
    assert cm.artists[2] == "Artist.1"


def test_detect_name_from_email_or_error():
    warnings = []
    cm = detect_columns(["Email", "Song 1 link"], ColumnsConfig(), warnings.append)
    assert cm.name is None and warnings
    with pytest.raises(SubmissionError):
        detect_columns(["Song 1 link"], ColumnsConfig())


def test_overrides():
    headers = ["Who", "Mail", "Tune {1}", "Url 1", "Url 2"]
    cm = detect_columns(headers, ColumnsConfig(name="who", song_link="Url {n}", email="Mail"))
    assert cm.name == "Who" and cm.email == "Mail"
    assert cm.links == {1: "Url 1", 2: "Url 2"}
    with pytest.raises(SubmissionError, match="Available columns"):
        detect_columns(headers, ColumnsConfig(name="Nope"))


def _df(rows):
    return pd.DataFrame(rows, columns=HEADERS, dtype=object).fillna("")


def _row(name, n=5, ts="", link_suffix=""):
    row = ["2026-01-01", f"{name.lower()}@x.com", name]
    for i in range(1, 6):
        if i <= n:
            row += [f"T{name}{i}", f"A{name}{i}", f"https://youtu.be/{i:011d}{link_suffix}"[:30]]
        else:
            row += ["", "", ""]
    return row + ["pic.png", ts]


def test_parse_submissions_basic():
    warnings = []
    df = _df([_row("Ana", ts="1: 0:45, 3: 1:20"), _row("Bob", n=3)])
    subs = parse_submissions(df, ColumnsConfig(), People(), warnings.append)
    assert [s.name for s in subs] == ["Ana", "Bob"]
    assert [e.slot for e in subs[0].songs] == [1, 2, 3, 4, 5]
    assert subs[0].songs[0].start == 45 and subs[0].songs[2].start == 80
    assert subs[0].songs[1].start is None
    assert subs[0].email == "ana@x.com" and subs[0].picture == "pic.png"
    assert len(subs[1].songs) == 3
    assert warnings == []


def test_start_from_link_param():
    row = _row("Ana", n=1)
    row[5] = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1m5s"
    subs = parse_submissions(_df([row]), ColumnsConfig(), People(), lambda m: None)
    assert subs[0].songs[0].start == 65


def test_duplicate_person_keeps_last_and_warnings():
    warnings = []
    bad = _row("Ana", n=2)
    bad[5] = ""             # song 1 no link
    bad[6] = ""             # song 2 title removed
    bad[8] = "not a url"
    df = _df([_row("Ana", n=5), [""] * len(HEADERS), bad, _row("Cy", n=0)])
    subs = parse_submissions(df, ColumnsConfig(), People({"Ana": ["ana"]}), warnings.append)
    assert [s.name for s in subs] == ["Ana", "Cy"]
    assert len(subs[0].songs) == 2
    text = "\n".join(warnings)
    assert "more than once" in text and "no link" in text and "not a URL" in text
    assert "no title" in text and "no songs" in text


def _subs():
    df = _df([_row("Ana"), _row("Bob"), _row("Cy", n=2)])
    return parse_submissions(df, ColumnsConfig(), People(), lambda m: None)


def test_build_songs_deterministic():
    a, b = build_songs(_subs(), "seed"), build_songs(_subs(), "seed")
    assert a == b
    assert [s.id for s in a] == list(range(1, 13))
    assert build_songs(_subs(), "other") != a
    assert {(s.submitter, s.slot) for s in a} == {(n, i) for n in ("Ana", "Bob") for i in range(1, 6)} | {("Cy", 1), ("Cy", 2)}


def test_find_duplicates():
    songs = [
        Song(1, "A", "X", "https://youtu.be/dQw4w9WgXcQ", "p"),
        Song(2, "B", "Y", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3", "q"),
        Song(3, "Hello!", "Adele", "https://youtu.be/aaaaaaaaaaa", "p"),
        Song(4, "hello", "ADELE", "https://youtu.be/bbbbbbbbbbb", "q"),
        Song(5, "Other", "Z", "https://youtu.be/ccccccccccc", "q"),
    ]
    pairs = find_duplicates(songs)
    assert [(a.id, b.id) for a, b in pairs] == [(1, 2), (3, 4)]


def test_registry_roundtrip_and_merge(tmp_path):
    people = People()
    reg = [
        Song(1, "T1", "A1", "https://youtu.be/aaaaaaaaaaa", "Ana", 1, 45),
        Song(2, "T2", "A2", "https://youtu.be/bbbbbbbbbbb", "Bob", 1, None),
        Song(3, "T3", "A3", "https://youtu.be/ccccccccccc", "Cy", 1, 3723),
    ]
    path = tmp_path / "sub" / "reg.csv"
    write_registry(reg, path)
    assert read_registry(path) == reg

    fresh = [
        Song(1, "T1 fixed", "A1", "https://youtu.be/aaaaaaaaaaa", "ana", 1, 50),     # typo fix
        Song(2, "T2", "A2", "https://youtu.be/zzzzzzzzzzz", "Bob", 1, None),         # link changed
        Song(3, "New", "N", "https://youtu.be/ddddddddddd", "Dee", 1, None),         # new
    ]
    warnings = []
    merged = merge_registry(reg, fresh, people, warnings.append)
    assert [s.id for s in merged] == [1, 2, 3, 4]
    assert merged[0].title == "T1 fixed" and merged[0].start == 50 and merged[0].submitter == "Ana"
    assert merged[1].link.endswith("zzzzzzzzzzz")
    assert merged[2].title == "T3"                       # registry-only kept
    assert merged[3].submitter == "Dee"
    text = "\n".join(warnings)
    assert "link changed" in text and "added after" in text and "no longer" in text


def test_ordinal_song_headers():
    from chatting.config import ColumnsConfig
    from chatting.submissions import detect_columns

    headers = ["Timestamp", "Name", "First song title", "First song link", "Second song title",
               "Second song link", "5th song link"]
    cm = detect_columns(headers, ColumnsConfig())
    assert cm.titles == {1: "First song title", 2: "Second song title"}
    assert cm.links == {1: "First song link", 2: "Second song link", 5: "5th song link"}


def test_label_falls_back_to_link():
    from chatting.models import Song

    assert Song(1, "", "", "https://youtu.be/x", "A").label == "https://youtu.be/x"


def test_registry_follows_the_song_not_the_form_slot():
    people = People()
    reg = [
        Song(1, "A", "X", "https://youtu.be/aaaaaaaaaaa", "Ana", 1, 10),
        Song(2, "B", "X", "https://youtu.be/bbbbbbbbbbb", "Ana", 2, 20),
    ]
    # Ana swapped her two songs in the form.
    swapped = [
        Song(1, "B", "X", "https://youtu.be/bbbbbbbbbbb", "Ana", 1, 20),
        Song(2, "A", "X", "https://youtu.be/aaaaaaaaaaa", "Ana", 2, 10),
    ]
    merged = merge_registry(reg, swapped, people, lambda m: None)
    assert [(s.id, s.title, s.slot) for s in merged] == [(1, "A", 2), (2, "B", 1)]

    # Ana replaced song A with C: C must not inherit A's number (and its ratings).
    replaced = [
        Song(1, "C", "Y", "https://youtu.be/ccccccccccc", "Ana", 1, 5),
        Song(2, "B", "X", "https://youtu.be/bbbbbbbbbbb", "Ana", 2, 20),
    ]
    warnings = []
    merged = merge_registry(reg, replaced, people, warnings.append)
    assert [(s.id, s.title) for s in merged] == [(1, "A"), (2, "B"), (3, "C")]
    assert any("no longer in the responses" in w for w in warnings)


def test_name_question_with_a_digit_is_not_a_song_column():
    from chatting.config import ColumnsConfig

    headers = ["Timestamp", "Name (2 words max)", "Song 1 title", "Song 1 link",
               "Song 2 title", "Song 2 link", "Track 3 name", "Song 3 link"]
    cm = detect_columns(headers, ColumnsConfig())
    assert cm.name == "Name (2 words max)"
    assert cm.titles == {1: "Song 1 title", 2: "Song 2 title", 3: "Track 3 name"}
    assert cm.links == {1: "Song 1 link", 2: "Song 2 link", 3: "Song 3 link"}


def test_registry_saved_by_excel(tmp_path):
    path = tmp_path / "songs.csv"
    # Semicolons, cp1250 (Romanian Excel), start times as h:mm:ss.
    path.write_bytes("id;title;artist;link;submitter;slot;start\n"
                     "2;Doi;Ş;https://youtu.be/b;Ştefan;1;0:43:00\n"
                     "1;Unu;A;https://youtu.be/a;Ana;2;1:05\n".encode("cp1250"))
    songs = read_registry(path)
    assert [(s.id, s.start) for s in songs] == [(1, 65), (2, 43)]
    assert songs[1].submitter == "Ştefan"


def test_registry_without_id_column(tmp_path):
    path = tmp_path / "songs.csv"
    path.write_text("title,artist\nx,y\n", encoding="utf-8")
    with pytest.raises(SubmissionError):
        read_registry(path)
