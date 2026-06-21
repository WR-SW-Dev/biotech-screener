"""Deterministic artifact I/O helpers for scientific cartography."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def deterministic_timestamp(as_of_date: str) -> str:
    """Return deterministic UTC timestamp derived from as_of_date."""
    return f"{as_of_date}T00:00:00Z" if as_of_date else ""


def atomic_write_text(path: Path | str, content: str) -> None:
    """Atomically write UTF-8 text with a trailing newline."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    fd, tmp_path = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        Path(tmp_path).replace(output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_json(path: Path | str, data: object, *, sort_keys: bool = True) -> None:
    """Atomically write deterministic JSON."""
    content = json.dumps(data, indent=2, sort_keys=sort_keys, ensure_ascii=False)
    atomic_write_text(path, content)


def write_jsonl(path: Path | str, rows: Iterable[object]) -> None:
    """Atomically write JSONL with deterministic key ordering."""
    content = "\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows)
    atomic_write_text(path, content)


def write_csv(path: Path | str, rows: Sequence[Mapping[str, object]], fieldnames: Sequence[str]) -> None:
    """Atomically write CSV rows using repository newline conventions."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        Path(tmp_path).replace(output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
