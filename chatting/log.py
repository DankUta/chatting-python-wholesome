"""Console output shared by all stages: plain progress lines and collected warnings."""

from __future__ import annotations

import sys

_warnings: list[str] = []


def info(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    """Print a warning now and remember it for the end-of-run summary."""
    _warnings.append(message)
    print(f"  ! {message}", file=sys.stderr, flush=True)


def warnings() -> list[str]:
    return list(_warnings)


def reset() -> None:
    _warnings.clear()
