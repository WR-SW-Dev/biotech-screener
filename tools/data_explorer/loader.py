"""Dataset loader — CSV, JSON, JSONL with metadata preservation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)


def _infer_format(path: Path) -> str:
    """Infer file format from extension."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    if suffix == ".jsonl":
        return "jsonl"
    raise ValueError(f"Cannot infer format from extension: {suffix}")


def load_csv(path: Path) -> pd.DataFrame:
    """Load a CSV file into a DataFrame."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def load_json(path: Path) -> pd.DataFrame:
    """Load a JSON file into a DataFrame.

    Handles both array-of-objects and single-object (wraps in list).
    Nested dicts are kept as-is in the DataFrame.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return pd.DataFrame(data)
    if isinstance(data, dict):
        # If it has a recognizable list field, use that
        for key in ("scores", "records", "recommendations", "entries", "top_10", "bottom_10"):
            if key in data and isinstance(data[key], list):
                df = pd.DataFrame(data[key])
                # Attach top-level metadata as df.attrs
                for k, v in data.items():
                    if k != key and not isinstance(v, (list, dict)):
                        df.attrs[k] = v
                return df
        # Single record
        return pd.DataFrame([data])
    raise ValueError(f"Unexpected JSON structure in {path}")


def load_jsonl(path: Path) -> pd.DataFrame:
    """Load a JSONL file (one JSON object per line) into a DataFrame."""
    records: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed JSONL line in %s", path)
    return pd.DataFrame(records) if records else pd.DataFrame()


def load_file(
    path: Union[str, Path],
    fmt: Optional[str] = None,
) -> pd.DataFrame:
    """Load a single file into a DataFrame with metadata.

    Args:
        path: File path.
        fmt: Force format ("csv", "json", "jsonl"). Auto-detects if None.

    Returns:
        DataFrame with .attrs["source_path"] and .attrs["source_format"].
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    fmt = fmt or _infer_format(path)

    loaders = {
        "csv": load_csv,
        "json": load_json,
        "jsonl": load_jsonl,
    }
    if fmt not in loaders:
        raise ValueError(f"Unsupported format: {fmt}")

    df = loaders[fmt](path)
    df.attrs["source_path"] = str(path)
    df.attrs["source_format"] = fmt

    # Infer snapshot date from parent directory name (YYYY-MM-DD)
    parent = path.parent.name
    if len(parent) >= 10 and parent[:4].isdigit():
        df.attrs["snapshot_date"] = parent[:10]

    return df


def load_directory(
    directory: Union[str, Path],
    pattern: str = "*",
) -> Dict[str, pd.DataFrame]:
    """Load all recognized files in a directory.

    Returns dict keyed by stem name (e.g., "rankings", "cache_health").
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    results: Dict[str, pd.DataFrame] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".csv", ".json", ".jsonl"):
            continue
        if pattern != "*" and not path.match(pattern):
            continue
        try:
            df = load_file(path)
            results[path.stem] = df
        except Exception as e:
            logger.debug("Skipping %s: %s", path.name, e)

    return results


def load_rankings_series(
    snapshots_dir: Union[str, Path],
    n_latest: int = 30,
) -> pd.DataFrame:
    """Load rankings.csv across multiple snapshot dates into one DataFrame.

    Adds a 'snapshot_date' column. Returns the most recent n_latest snapshots.
    """
    snapshots_dir = Path(snapshots_dir)
    if not snapshots_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {snapshots_dir}")

    snap_dirs = sorted(
        [d for d in snapshots_dir.iterdir() if d.is_dir() and (d / "rankings.csv").exists()],
        key=lambda d: d.name,
        reverse=True,
    )[:n_latest]

    frames: List[pd.DataFrame] = []
    for d in reversed(snap_dirs):
        df = load_csv(d / "rankings.csv")
        df["snapshot_date"] = d.name[:10]
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
