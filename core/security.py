"""
FlipaRender v9 — Security helpers

v9 changes:
  - ALLOWED_EXTENSIONS: أضفنا .tif / .tiff
"""

import re
from pathlib import Path

# ── v9: أضفنا tif / tiff ──────────────────────────────────────────────────────
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
})


# ── Natural sort ──────────────────────────────────────────────────────────────

def _natural_key(text: str) -> list:
    """Split 'frame10' → ['frame', 10] so files sort numerically."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", text)
    ]


# ── Path helpers ──────────────────────────────────────────────────────────────

def safe_path(path: str, base: Path | None = None) -> Path:
    resolved = Path(path).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    if base is not None:
        try:
            resolved.relative_to(base.resolve())
        except ValueError:
            raise ValueError(f"Path escapes allowed directory: {path}")

    return resolved


# ── File list helpers ─────────────────────────────────────────────────────────

def validate_files(
    files: list[str],
    allowed: frozenset[str] = ALLOWED_EXTENSIONS,
) -> list[str]:
    """
    Return only paths that:
      - exist on disk
      - are regular files (not directories or symlinks)
      - have an extension in *allowed*

    v9: يقبل الآن TIFF بالإضافة إلى PNG / JPG / WebP.
    يُطبّع الامتداد بـ lower() فلا فرق بين .TIF و .tif.
    """
    valid = []
    for f in files:
        p = Path(f)
        if (
            p.suffix.lower() in allowed
            and p.is_file()
            and not p.is_symlink()
        ):
            valid.append(f)

    return sorted(valid, key=lambda p: _natural_key(Path(p).name))


# Keep old name as alias
validate_pngs = validate_files
