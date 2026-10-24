import pandas as pd
import pytest

from chatting.sources import (
    SourceError, find_header_row, google_sheet_export_url, promote_header, read_grid, read_table,
)

ID = "1AbC_dEf-123"


def test_google_urls():
    base = f"https://docs.google.com/spreadsheets/d/{ID}"
    assert google_sheet_export_url(f"{base}/edit#gid=0") == f"{base}/export?format=csv&gid=0"
    assert google_sheet_export_url(f"{base}/edit?gid=123&x=1") == f"{base}/export?format=csv&gid=123"
    assert google_sheet_export_url(f"{base}/edit?usp=sharing&gid=7") == f"{base}/export?format=csv&gid=7"
    assert google_sheet_export_url(f"{base}/edit?usp=sharing") == f"{base}/export?format=xlsx"
    assert google_sheet_export_url(f"{base}") == f"{base}/export?format=xlsx"
    pub = "https://docs.google.com/spreadsheets/d/e/2PACX-abc/pubhtml"
    assert google_sheet_export_url(pub) == "https://docs.google.com/spreadsheets/d/e/2PACX-abc/pub?output=csv"
    assert google_sheet_export_url("https://example.com/a.csv") is None


def test_csv_semicolon_utf8_sig(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes("﻿Name;Nota\nCălin;6,5\n;\n".encode("utf-8"))
    grid = read_grid("a.csv", tmp_path)
    assert grid.iloc[0].tolist() == ["Name", "Nota"]
    assert grid.iloc[1].tolist() == ["Călin", "6,5"]


def test_csv_cp1252_and_tab(tmp_path):
    p = tmp_path / "a.tsv"
    p.write_bytes("Name\tNota\nJos\xe9\t7\n".encode("cp1252"))
    grid = read_grid(str(p), tmp_path)
    assert grid.iloc[1].tolist() == ["José", "7"]


def test_xlsx_number_text(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["a", "b", "c", "d"])
    ws.append([7, 6.78, 6.7800000000000002, 7.0])
    ws.append([None, "x", 0.1 + 0.2, 10])
    wb.save(tmp_path / "a.xlsx")
    grid = read_grid("a.xlsx", tmp_path)
    assert grid.iloc[1].tolist() == ["7", "6.78", "6.78", "7"]
    assert grid.iloc[2].tolist() == ["", "x", "0.3", "10"]


def test_missing_file(tmp_path):
    with pytest.raises(SourceError):
        read_grid("nope.csv", tmp_path)


def test_ods_without_odfpy(tmp_path):
    try:
        import odf  # noqa: F401
    except ImportError:
        (tmp_path / "a.ods").write_bytes(b"x")
        with pytest.raises(SourceError, match="odfpy"):
            read_grid("a.ods", tmp_path)


def test_header_detection_and_promote():
    grid = pd.DataFrame([["My ratings", "", ""], ["#", "Song", "Rating"], ["1", "A - B", "7"], ["", "", ""], ["2", "C - D", "8"]])
    row = find_header_row(grid, [r"^#$", "rating"])
    assert row == 1
    assert find_header_row(grid, ["nothing"]) is None
    df = promote_header(grid, row)
    assert list(df.columns) == ["#", "Song", "Rating"]
    assert len(df) == 2
    assert df.index.tolist() == [0, 1]


def test_duplicate_and_empty_headers(tmp_path):
    (tmp_path / "a.csv").write_text("Title,Title,,Title\na,b,c,d\n", encoding="utf-8")
    df = read_table("a.csv", tmp_path)
    assert list(df.columns) == ["Title", "Title.1", "Column 3", "Title.2"]
