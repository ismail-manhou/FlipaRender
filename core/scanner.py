"""
FlipaRender v6 — Job Scanner

Folder structure:

  root/
  ├── Plan1/        ← simple scene  (PNG files directly inside)
  └── Plan13/       ← compound scene (sub-layer folders)
      ├── 13-1/     ← bottom layer  (background)
      ├── 13-2/     ← middle layer
      └── 13-3/     ← top layer     (foreground)

All sub-folders in a compound scene should contain the same frame count.
Layers are merged frame-by-frame using alpha composite.
"""

import warnings
from pathlib import Path

from .security import safe_path, validate_files, _natural_key, ALLOWED_EXTENSIONS

# Minimum frames required to treat a folder as a renderable scene
MIN_FRAMES = 2


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sorted_natural(paths) -> list:
    return sorted(paths, key=lambda p: _natural_key(p.name))


def _frames_in(folder: Path) -> list[str]:
    """
    Return validated, naturally-sorted frame paths inside *folder*.
    Uses security.validate_files — skips non-files, symlinks, wrong extensions.
    """
    candidates = [str(p) for p in folder.iterdir() if not p.is_dir()]
    return validate_files(candidates, ALLOWED_EXTENSIONS)


def _check_layer_counts(layer_info: list[dict], scene_name: str) -> None:
    """
    Warn if layers have different frame counts.
    The renderer handles mismatches by freezing the shorter layer on its
    last frame, but the animator almost certainly made a mistake.
    """
    counts = {info["count"] for info in layer_info}
    if len(counts) > 1:
        detail = ", ".join(
            f"{info['name']}={info['count']}" for info in layer_info
        )
        warnings.warn(
            f"[{scene_name}] Layer frame counts differ: {detail}. "
            "Shorter layers will freeze on their last frame.",
            stacklevel=3,
        )


# ── Public API ────────────────────────────────────────────────────────────────

def scan_jobs(root: str) -> list[dict]:
    """
    Walk *root* and return a list of render jobs.

    Each job dict contains:
      name       (str)         — folder name used as output filename
      pngs       (list[str])   — reference frame list (bottom layer for compound)
      count      (int)         — number of frames in the reference layer
      compound   (bool)        — True if the scene has sub-layer folders
      layers     (list[dict])  — [{"name": str, "count": int}, ...]
      layer_pngs (list[list])  — only present when compound=True

    Raises:
      FileNotFoundError — if *root* does not exist
      ValueError        — if *root* is not a directory
    """
    root_path = safe_path(root)  # raises FileNotFoundError if missing

    if not root_path.is_dir():
        raise ValueError(f"Not a directory: {root}")

    jobs: list[dict] = []

    for plan_dir in _sorted_natural(
        p for p in root_path.iterdir() if p.is_dir()
    ):
        direct_frames = _frames_in(plan_dir)
        sub_dirs      = _sorted_natural(p for p in plan_dir.iterdir() if p.is_dir())

        # ── Simple scene ──────────────────────────────────────────────────────
        if direct_frames:
            if len(direct_frames) < MIN_FRAMES:
                warnings.warn(
                    f"[{plan_dir.name}] Only {len(direct_frames)} frame(s) found "
                    f"(need ≥ {MIN_FRAMES}) — skipping.",
                    stacklevel=2,
                )
                continue

            jobs.append({
                "name":     plan_dir.name,
                "path":     str(plan_dir),   # v9: مسار المجلد لقراءة timing.txt
                "pngs":     direct_frames,
                "count":    len(direct_frames),
                "compound": False,
                "layers":   [],
            })

        # ── Compound scene ────────────────────────────────────────────────────
        elif sub_dirs:
            layers: list[list[str]] = []
            layer_info: list[dict]  = []

            for sub in sub_dirs:
                frames = _frames_in(sub)
                if frames:
                    layers.append(frames)
                    layer_info.append({"name": sub.name, "count": len(frames)})
                else:
                    warnings.warn(
                        f"[{plan_dir.name}/{sub.name}] No valid frames found — "
                        "layer skipped.",
                        stacklevel=2,
                    )

            if not layers:
                warnings.warn(
                    f"[{plan_dir.name}] Compound scene has no valid layers — skipping.",
                    stacklevel=2,
                )
                continue

            if len(layers[0]) < MIN_FRAMES:
                warnings.warn(
                    f"[{plan_dir.name}] Bottom layer has only {len(layers[0])} "
                    f"frame(s) (need ≥ {MIN_FRAMES}) — skipping.",
                    stacklevel=2,
                )
                continue

            _check_layer_counts(layer_info, plan_dir.name)

            jobs.append({
                "name":       plan_dir.name,
                "path":       str(plan_dir),   # v9: مسار المجلد لقراءة timing.txt
                "pngs":       layers[0],       # bottom layer as frame-count reference
                "count":      max(len(l) for l in layers),
                "compound":   True,
                "layers":     layer_info,
                "layer_pngs": layers,
            })

    return jobs
