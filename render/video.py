"""
FlipaRender v9 — Video / GIF Exporter

v9 changes:
  - export_video() : يكتب metadata (title, artist, comment) داخل MP4 عبر ffmpeg
  - export_gif()   : جودة أعلى — max_width رُفع، dithering، خيار عدد الألوان
  - export()       : واجهة موحدة بدون تغيير
"""

import subprocess
from pathlib import Path

from PIL import Image


# ── MP4 + Metadata ────────────────────────────────────────────────────────────

def export_video(cfg: dict, frame_dir: Path, out_file: str) -> None:
    """
    Encode PNG frames in *frame_dir* to *out_file* using libx264.
    يكتب metadata من cfg["metadata"] إذا كانت موجودة.

    cfg["metadata"] مثال:
        {"title": "My Film", "artist": "Ahmed", "comment": "FlipaRender v9"}
    """
    import os

    pattern   = str(frame_dir / "frame_%05d.png")
    log_level = "info" if os.environ.get("FLIPARENDER_DEBUG") else "error"

    cmd = [
        "ffmpeg", "-y",
        "-loglevel",  log_level,
        "-framerate", str(cfg["fps"]),
        "-i",         pattern,
        "-c:v",       "libx264",
        "-crf",       str(cfg["crf"]),
        "-preset",    "fast",
        "-pix_fmt",   "yuv420p",
    ]

    # v9: كتابة metadata
    metadata: dict = cfg.get("metadata", {})
    for key, value in metadata.items():
        if value:                          # تجاهل القيم الفارغة
            cmd += ["-metadata", f"{key}={value}"]

    cmd.append(out_file)
    subprocess.run(cmd, check=True)


# ── GIF محسّن ─────────────────────────────────────────────────────────────────

def export_gif(cfg: dict, frame_dir: Path, out_file: str) -> None:
    """
    اجمع فريمات PNG في *frame_dir* وصدّرها كـ GIF متحرك.

    v9 — تحسينات الجودة:
      - max_width رُفع إلى DEFAULT_GIF_MAX_WIDTH (1280 بدل 800)
      - خيار عدد الألوان من cfg["gif_colors"] (64 / 128 / 256)
      - FLOYDSTEINBERG dithering لتقليل التدرج والبقع
      - loop count من cfg["gif_loop"] (0 = لا نهائي، N = عدد التكرارات)
    """
    from config import DEFAULT_GIF_MAX_WIDTH, DEFAULT_GIF_COLORS

    frame_paths = sorted(frame_dir.glob("frame_*.png"))
    if not frame_paths:
        raise FileNotFoundError(f"No frames found in: {frame_dir}")

    fps      = cfg.get("fps", 12)
    duration = int(1000 / fps)
    colors   = int(cfg.get("gif_colors", DEFAULT_GIF_COLORS))
    max_w    = int(cfg.get("gif_max_width", DEFAULT_GIF_MAX_WIDTH))
    loop     = int(cfg.get("gif_loop", 0))      # 0 = لا نهائي

    frames: list[Image.Image] = []
    for path in frame_paths:
        img = Image.open(path).convert("RGB")

        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize(
                (max_w, int(img.height * ratio)),
                Image.LANCZOS,
            )

        # v9: FLOYDSTEINBERG دائماً لجودة أفضل
        img = img.quantize(
            colors=colors,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.FLOYDSTEINBERG,
        )
        frames.append(img)

    if not frames:
        raise RuntimeError("No valid frames to export.")

    frames[0].save(
        out_file,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        loop=loop,
        duration=duration,
        optimize=True,
    )


# ── واجهة موحدة ───────────────────────────────────────────────────────────────

def export(cfg: dict, frame_dir: Path, out_file: str) -> None:
    """
    اختر تلقائياً MP4 أو GIF بناءً على cfg["format"].
    """
    fmt = cfg.get("format", "mp4").lower()

    if fmt == "gif":
        export_gif(cfg, frame_dir, out_file)
    else:
        export_video(cfg, frame_dir, out_file)
