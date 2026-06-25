"""
FlipaRender v10 — Scene Preview Grid  (core/preview_grid.py)

يبني صوراً مصغّرة (thumbnails) لكل مشهد من المشاهد المختارة، ويعرضها كقائمة
منظَّمة في الطرفية قبل بدء الرندر — مراجعة أخيرة للمستخدم بعد اختيار الدفعة
(batch) مباشرة، قبل أي إعدادات أخرى.

الطرفية لا تعرض صوراً بصرياً، لذلك "الـ Grid" هنا هو:
  1. قائمة نصية منظَّمة (اسم / عدد فريمات / نوع) — تُطبع دائماً.
  2. صورة Contact Sheet فعلية (PNG واحدة تجمع thumbnail لكل مشهد) تُحفظ على
     القرص ويُعرض مسارها — يفتحها المستخدم يدوياً إن أراد رؤية بصرية حقيقية.

استخدام:

    from core.preview_grid import build_preview_grid, render_contact_sheet

    build_preview_grid(jobs)                      # نص في الطرفية
    path = render_contact_sheet(jobs, cfg)         # صورة PNG اختيارية
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from render.frames import preview_frame


THUMB_SIZE = (160, 120)
GRID_COLUMNS = 4
GRID_PADDING = 10
GRID_BG = (24, 24, 30)
LABEL_HEIGHT = 22


def build_preview_grid(jobs: list[dict]) -> str:
    """
    يبني نص القائمة المنظَّمة (بدون رسم) — جاهز للطباعة في الطرفية.

    مثال الإخراج:
        [1] Walk     — 24 frames  (simple)
        [2] Jump     — 18 frames  (compound, 3 layers)
        [3] Attack   — 30 frames  (simple)
    """
    lines = []
    for i, job in enumerate(jobs, 1):
        kind = "simple"
        if job.get("compound"):
            n_layers = len(job.get("layers", []))
            kind = f"compound, {n_layers} layers"
        name  = job.get("name", f"scene_{i}")
        count = job.get("count", 0)
        lines.append(f"  [{i}]  {name:<18} — {count} frames  ({kind})")
    return "\n".join(lines)


def render_contact_sheet(
    jobs: list[dict],
    cfg: dict,
    out_path: str | Path = "output_videos/_scene_preview.png",
) -> Path | None:
    """
    يبني صورة Contact Sheet واحدة تجمع thumbnail للفريم الأول من كل مشهد،
    مرتّبة في شبكة، مع اسم المشهد وعدد فريماته مكتوبَين تحت كل صورة.

    يعيد مسار الملف المحفوظ، أو None لو لم تتوفر أي مشاهد صالحة للمعاينة.
    """
    if not jobs:
        return None

    thumbs: list[tuple[Image.Image, str]] = []

    for job in jobs:
        try:
            if job.get("compound") and job.get("layer_pngs"):
                first_layers = [layer[0] for layer in job["layer_pngs"]]
                img = preview_frame(first_layers[0], cfg, layer_paths=first_layers)
            else:
                img = preview_frame(job["pngs"][0], cfg)
            thumb = img.copy()
            thumb.thumbnail(THUMB_SIZE, Image.LANCZOS)
        except Exception:
            # مشهد تعذّرت معاينته — نتخطاه بدل فشل العملية كاملة
            continue

        label = f"{job.get('name', '?')} ({job.get('count', 0)}f)"
        thumbs.append((thumb, label))

    if not thumbs:
        return None

    # ── حساب أبعاد الشبكة ────────────────────────────────────────────────────
    cols = min(GRID_COLUMNS, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols

    cell_w = THUMB_SIZE[0] + GRID_PADDING
    cell_h = THUMB_SIZE[1] + LABEL_HEIGHT + GRID_PADDING

    sheet_w = cols * cell_w + GRID_PADDING
    sheet_h = rows * cell_h + GRID_PADDING

    sheet = Image.new("RGB", (sheet_w, sheet_h), GRID_BG)

    # نحاول استخدام خط بسيط؛ لو غير متاح نتجاهل الكتابة بدل فشل العملية
    draw = None
    font = None
    try:
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 12)
        except Exception:
            font = ImageFont.load_default()
    except Exception:
        pass

    for idx, (thumb, label) in enumerate(thumbs):
        col = idx % cols
        row = idx // cols
        x = GRID_PADDING + col * cell_w
        y = GRID_PADDING + row * cell_h

        # توسيط الصورة المصغّرة داخل خليتها
        tx = x + (THUMB_SIZE[0] - thumb.width) // 2
        ty = y + (THUMB_SIZE[1] - thumb.height) // 2
        sheet.paste(thumb, (tx, ty))

        if draw is not None:
            text_y = y + THUMB_SIZE[1] + 4
            draw.text((x, text_y), label, fill=(230, 230, 240), font=font)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path
