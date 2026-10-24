"""Reading tables from local files and links (csv, tsv, xlsx, ods, Google Sheets)."""

from __future__ import annotations

import csv
import io
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import pandas as pd

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_SHARE_HINT = (
    'Share the sheet as "Anyone with the link -> Viewer", or download it as .xlsx/.csv '
    "and put the file path in chatting.toml instead."
)


class SourceError(Exception):
    pass


def google_sheet_export_url(url: str) -> Optional[str]:
    """Download link for a Google Sheets link, or None if it is not one."""
    url = str(url or "").strip()
    m = re.search(r"docs\.google\.com/spreadsheets/d/e/([\w-]+)", url)
    if m:
        return f"https://docs.google.com/spreadsheets/d/e/{m.group(1)}/pub?output=csv" + (
            f"&gid={g.group(1)}" if (g := re.search(r"[?&#]gid=(\d+)", url)) else ""
        )
    m = re.search(r"docs\.google\.com/spreadsheets/d/([\w-]+)", url)
    if not m:
        return None
    base = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export"
    g = re.search(r"[?&#]gid=(\d+)", url)
    if g:
        return f"{base}?format=csv&gid={g.group(1)}"
    return f"{base}?format=xlsx"


def fetch_bytes(url: str, timeout: float = 60) -> tuple[bytes, str]:
    """Download `url`; returns (data, content-type)."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "") or ""
    except urllib.error.HTTPError as exc:
        hint = f" {_SHARE_HINT}" if exc.code in (401, 403, 404) and "google.com" in url else ""
        raise SourceError(f"Could not download {url} (HTTP {exc.code}).{hint}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SourceError(f"Could not download {url}: {getattr(exc, 'reason', exc)}") from exc
    if "text/html" in ctype.lower() and "google.com" in url:
        raise SourceError(f"{url} returned a web page instead of a spreadsheet. {_SHARE_HINT}")
    return data, ctype


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.10g}"
    if hasattr(value, "strftime"):
        return str(value)
    return str(value).strip() if not isinstance(value, str) else value.strip()


def _to_grid(rows: list[list[object]]) -> pd.DataFrame:
    width = max((len(r) for r in rows), default=0)
    data = [[_cell_text(c) for c in r] + [""] * (width - len(r)) for r in rows]
    return pd.DataFrame(data, columns=range(width), dtype=object)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    # Not UTF-8: a CSV saved by Excel in the Windows code page. Romanian (and other Central
    # European) Excel uses cp1250, whose ş ţ Ş Ţ come out as º þ ª Þ when read as cp1252.
    western = data.decode("cp1252", errors="replace")
    if any(ch in western for ch in "ºªþÞ"):
        return data.decode("cp1250", errors="replace")
    return western


def _read_text_grid(text: str) -> pd.DataFrame:
    sample = text[:8192]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample.strip() else ""
        delim = max(",;\t", key=first.count)
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delim))
    return _to_grid(rows)


def _read_xlsx_grid(data: bytes) -> pd.DataFrame:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as exc:  # corrupt / not an xlsx
        raise SourceError(f"Could not read the spreadsheet: {exc}") from exc
    try:
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    return _to_grid(rows)


def _read_ods_grid(data: bytes) -> pd.DataFrame:
    try:
        df = pd.read_excel(io.BytesIO(data), engine="odf", header=None, dtype=object)
    except ImportError as exc:
        raise SourceError("Reading .ods files needs an extra package: pip install odfpy") from exc
    except Exception as exc:
        raise SourceError(f"Could not read the .ods file: {exc}") from exc
    return _to_grid(df.values.tolist())


def _grid_from_bytes(data: bytes, kind: str, label: str) -> pd.DataFrame:
    if kind in ("xlsx", "xlsm"):
        return _read_xlsx_grid(data)
    if kind == "ods":
        return _read_ods_grid(data)
    if kind in ("csv", "tsv", "txt"):
        return _read_text_grid(_decode(data))
    raise SourceError(f"Don't know how to read {label} (use .csv, .xlsx or .ods).")


def _kind_from_ctype(ctype: str, name: str) -> str:
    ctype = ctype.lower()
    if "spreadsheetml" in ctype or "excel" in ctype:
        return "xlsx"
    if "opendocument.spreadsheet" in ctype:
        return "ods"
    if "csv" in ctype or "text/plain" in ctype or "tab-separated" in ctype:
        return "csv"
    suffix = Path(name.split("?")[0]).suffix.lower().lstrip(".")
    return suffix or "csv"


def read_grid(source: str, base_dir: Path) -> pd.DataFrame:
    """Raw cell grid (header=None), every cell a string."""
    source = str(source).strip()
    if re.match(r"^https?://", source, re.I):
        url = google_sheet_export_url(source) or source
        data, ctype = fetch_bytes(url)
        kind = "xlsx" if "format=xlsx" in url else "csv" if "output=csv" in url or "format=csv" in url else _kind_from_ctype(ctype, url)
        return _grid_from_bytes(data, kind, url)
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = Path(base_dir) / path
    if not path.is_file():
        raise SourceError(f"File not found: {path}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SourceError(f"Could not read {path}: {exc}") from exc
    return _grid_from_bytes(data, path.suffix.lower().lstrip("."), str(path))


def find_header_row(grid: pd.DataFrame, patterns: list[str], max_rows: int = 15) -> Optional[int]:
    """Index of the first row where every pattern matches some cell."""
    regexes = [re.compile(p, re.I) for p in patterns]
    for i in range(min(max_rows, len(grid))):
        cells = [str(c).strip() for c in grid.iloc[i].tolist()]
        if all(any(rx.search(c) for c in cells if c) for rx in regexes):
            return i
    return None


def promote_header(grid: pd.DataFrame, row: int) -> pd.DataFrame:
    """Use grid row `row` as the column headers and the rows below as data."""
    seen: dict[str, int] = {}
    headers = []
    for n, cell in enumerate(grid.iloc[row].tolist(), 1):
        name = str(cell).strip() or f"Column {n}"
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        headers.append(name)
    body = grid.iloc[row + 1:].copy()
    body.columns = headers
    body = body[(body.astype(str).apply(lambda col: col.str.strip()) != "").any(axis=1)]
    return body.reset_index(drop=True)


def read_table(source: str, base_dir: Path) -> pd.DataFrame:
    grid = read_grid(source, base_dir)
    if grid.empty:
        raise SourceError(f"{source} is empty.")
    return promote_header(grid, 0)
