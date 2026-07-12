"""Single source of truth for ECOS release/build metadata."""

from functools import lru_cache
from pathlib import Path


@lru_cache
def application_version() -> str:
    """Read the repository-level application version."""
    root = Path(__file__).resolve().parents[3]
    version_file = root / "VERSION"
    if not version_file.exists():
        return "0.1.0-rc.1"
    return version_file.read_text(encoding="utf-8").strip()
