"""Load repository `.env` for CLI tools and cron wrappers."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_repo_dotenv(repo_root: Path | None = None, *, override: bool = False) -> bool:
    """Load ``.env`` from the repo root if present.

    Returns True when a file was found and loaded.
    """
    root = repo_root or REPO_ROOT
    env_file = root / ".env"
    if not env_file.is_file():
        return False

    from dotenv import load_dotenv

    load_dotenv(env_file, override=override)
    return True
