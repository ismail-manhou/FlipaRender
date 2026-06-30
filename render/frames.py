"""
FlipaRender v10 — Frame Renderer

v10 changes:
  - Chunk Rendering (Memory Optimizer) : الفريمات تُعالَج على دفعات بحجم
    RENDER_CHUNK_SIZE بدل المرور الكامل دفعة واحدة. يحرّر الذاكرة (gc) بعد
    كل دفعة عبر utils.memory.MemoryGuard — مهم جداً للمشاريع الكبيرة على الهاتف.
  - Motion Blur : تمويه اختياري بين الفريمات المتتالية عبر render.motion_blur،
    يعمل بسلاسة عبر حدود الدفعات (chunk) وعبر استئناف الرندر (resume).
  - Logging : كل مرحلة (xsheet expansion / AI / compositing / resume) تُسجَّل
    عبر utils.logger بدل الاعتماد فقط على progress_cb.
  - السلوك الوظيفي (resume, AI, compound scenes, exposure sheet) لم يتغيّر إطلاقاً —
    فقط أعيدت هيكلته ليعمل على دفعات.

v9 changes (محفوظة بالكامل):
  - Exposure Sheet : يستدعي core/xsheet.py قبل الرندر
  - cfg["default_hold"] : قيمة hold الافتراضية لو لا يوجد timing.txt
"""

from pathlib import Path
from typing import Callable

from PIL import Image

from .grading import apply_grade
from .motion_blur import MotionBlurState
from utils.memory import chunked, RENDER_CHUNK_SIZE, MemoryGuard, warn_if_large_project
from utils.logger import get_logger

log = get_logger("render")


# ── Preview (بدون تغيير) ───────────────────────────────────────────────────────

def preview_frame(
    image_path: str,
    cfg: dict,
    frame_index: int = 0,
    layer_paths: list[str] | None = None,
) -> Image.Image:
    """
    أعِد فريماً واحداً معالجاً جاهزاً للعرض — بدون حفظ على القرص.
    """
    w, h  = cfg["w"], cfg["h"]
    grade = cfg["grade"]

    if layer_paths:
        img = _composite_layers(layer_paths, (w, h))
    else:
        img = Image.open(image_path).resize((w, h), Image.LANCZOS)

    img = apply_grade(img, grade)
    return img.convert("RGB")


# ── Internal: layer composite (بدون تغيير) ─────────────────────────────────────

def _composite_layers(paths: list[str], size: tuple[int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    for path in paths:
        layer = Image.open(path).resize((w, h), Image.LANCZOS).convert("RGBA")
        base  = Image.alpha_composite(base, layer)

    return base


# ── Resume helper (بدون تغيير) ──────────────────────────────────────────────────

def _resume_start(out_dir: Path) -> int:
    """
    أعِد رقم الفريم الذي يجب أن نبدأ منه.

    يبحث عن آخر frame_NNNNN.png محفوظ في out_dir.
    لو المجلد فارغ أو غير موجود → يعيد 0 (بداية من الأول).
    """
    existing = sorted(out_dir.glob("frame_?????.png"))
    if not existing:
        return 0
    last_name = existing[-1].stem
    last_idx  = int(last_name.split("_")[1])
    return last_idx + 1


# ── v10: تهيئة ذاكرة Motion Blur عند الاستئناف ──────────────────────────────────

def _seed_blur_from_last_frame(out_dir: Path, blur: MotionBlurState) -> None:
    """
    عند استئناف رندر متوقَّف (resume)، الفريمات السابقة موجودة على القرص لكن
    غير معروفة لكائن MotionBlurState الجديد. نحمّل آخر فريم محفوظ كنقطة بداية
    حتى لا ينقطع تأثير البلر على حدود الاستئناف.
    """
    existing = sorted(out_dir.glob("frame_?????.png"))
    if not existing:
        return
    try:
        last_img = Image.open(existing[-1]).convert("RGB")
        blur._prev_frame = last_img
    except Exception:
        pass


# ── Exposure Sheet helper (بدون تغيير) ──────────────────────────────────────────

def _apply_xsheet(
    pngs: list[str],
    scene_dir: str | None,
    default_hold: int,
) -> tuple[list[str], object]:
    """
    حمّل XSheet من *scene_dir* (لو موجود) ووسّع *pngs*.
    يعيد (expanded_pngs, xsheet_object).
    """
    from core.xsheet import load_xsheet

    if scene_dir is None:
        from core.xsheet import auto_xsheet
        xsheet = auto_xsheet(pngs, default_hold)
    else:
        xsheet = load_xsheet(scene_dir, pngs, default_hold)

    return xsheet.expand(pngs), xsheet


# ── v10: معالجة فريم واحد (يُستخدم داخل كل دفعة) ────────────────────────────────

def _apply_image_filters(img: Image.Image, image_filters: list) -> Image.Image:
    """
    يُطبّق قائمة ImageFilterPlugin (إن وُجدت) بالترتيب على *img*، بعد
    Color Grading وMotion Blur الأصليين مباشرة — آخر معالجة قبل الحفظ.
    خطأ في إضافة واحدة لا يوقف الرندر؛ يُسجَّل تحذيراً ويُكمل بالصورة كما هي.
    """
    if not image_filters:
        return img
    for plugin in image_filters:
        try:
            img = plugin.apply(img, **plugin.params)
        except Exception as exc:
            log.warning(f"فلتر الإضافة '{plugin.name}' فشل وتم تجاوزه: {exc}")
    return img


def _render_single_frame(
    path: str, out_path: Path, size: tuple[int, int], grade: dict,
    blur: MotionBlurState | None = None,
    image_filters: list | None = None,
) -> None:
    img = Image.open(path).resize(size, Image.LANCZOS)
    img = apply_grade(img, grade)
    if blur is not None:
        img = blur.apply(img)
    img = _apply_image_filters(img, image_filters or [])
    img.convert("RGB").save(out_path)


def _render_single_composite(
    frame_paths: list[str], out_path: Path, size: tuple[int, int], grade: dict,
    blur: MotionBlurState | None = None,
    image_filters: list | None = None,
) -> None:
    img = _composite_layers(frame_paths, size)
    img = apply_grade(img, grade)
    if blur is not None:
        img = blur.apply(img)
    img = _apply_image_filters(img, image_filters or [])
    img.convert("RGB").save(out_path)


# ── Render ────────────────────────────────────────────────────────────────────

def render_frames(
    pngs: list[str],
    cfg: dict,
    out_dir: Path,
    progress_cb: Callable[[int, int], None] | None = None,
    layer_pngs: list[list[str]] | None = None,
    scene_dir: str | None = None,
) -> int:
    """
    اكتب فريمات معالجة إلى *out_dir*.

    v10 — Chunk Rendering:
        الفريمات (سواء scene بسيط أو compound) تُعالَج على دفعات بحجم
        cfg.get("render_chunk_size", RENDER_CHUNK_SIZE). بعد كل دفعة تُحرَّر
        الذاكرة عبر MemoryGuard. النتيجة على القرص مطابقة تماماً للسلوك القديم —
        فقط استهلاك الذاكرة أقل بكثير على المشاريع الكبيرة.

    v10 — Motion Blur:
        cfg["motion_blur_enabled"] + cfg["motion_blur_strength"] (0.0–0.8).
        يُطبَّق بعد الـ grading مباشرة، ويحافظ على استمراريته عبر الدفعات
        وعند استئناف رندر متوقَّف (resume).

    v9 — Exposure Sheet:
        قبل الرندر، إذا وُجد timing.txt في *scene_dir*، يُقرأ ويوسَّع pngs
        بناءً على عدد مرات تكرار كل فريم. بدون timing.txt يعمل كما كان.

    v8 — resume:
        لو out_dir يحتوي فريمات من جلسة سابقة، يتخطاها ويكمل من آخر فريم.

    v8 — AI cache:
        لو cfg["ai_cache"] = True، يُنشئ AICache ويمرره للـ AIInbetween.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    w, h          = cfg["w"], cfg["h"]
    grade         = cfg["grade"]
    default_hold  = int(cfg.get("default_hold", 1))
    chunk_size    = int(cfg.get("render_chunk_size", RENDER_CHUNK_SIZE))

    # v10: Motion Blur — كائن واحد يُحافظ على ذاكرة الفريم السابق عبر كل الدفعات
    blur = MotionBlurState(
        strength=float(cfg.get("motion_blur_strength", 0.0)),
        enabled=bool(cfg.get("motion_blur_enabled", False)),
    )

    # v10: Plugins — فلاتر صورة مفعّلة لهذا الرندر (بعد grading وblur، قبل الحفظ)
    image_filters = cfg.get("active_image_filters") or []
    if image_filters:
        log.info(f"فلاتر إضافات مفعّلة: {', '.join(p.name for p in image_filters)}")

    log.stage(f"بدء رندر مشهد ({out_dir.name})")
    if blur.enabled:
        log.info(f"Motion Blur مفعّل — strength={blur.strength}")

    # ── Exposure Sheet ────────────────────────────────────────────────────────
    pngs, xsheet = _apply_xsheet(pngs, scene_dir, default_hold)
    log.info(f"Exposure Sheet: {len(pngs)} فريم بعد التوسعة (source={getattr(xsheet, 'source', '?')})")

    if layer_pngs:
        expanded_layers: list[list[str]] = []
        for layer in layer_pngs:
            expanded, _ = _apply_xsheet(layer, scene_dir, default_hold)
            expanded_layers.append(expanded)
        layer_pngs = expanded_layers

    # ── AI pipeline ───────────────────────────────────────────────────────────
    if cfg.get("ai_enabled"):
        from ai.inbetween import AIInbetween, BlendMode, AICache

        log.stage("AI In-betweening")
        mode  = BlendMode(cfg.get("ai_mode", "smart"))
        cache = AICache() if cfg.get("ai_cache", False) else None
        ib    = AIInbetween(mode=mode, steps=cfg.get("ai_steps", 1), cache=cache)
        ai_tmp = out_dir / "_ai_tmp"

        if layer_pngs:
            layer_pngs = [
                ib.process_and_save(layer, ai_tmp / f"layer_{i}")
                for i, layer in enumerate(layer_pngs)
            ]
            pngs = layer_pngs[0]
        else:
            pngs = ib.process_and_save(pngs, ai_tmp)
        log.info(f"AI: توليد فريمات وسيطة اكتمل — وضع {mode.value}")

    # تحذير استهلاك الذاكرة (إعلامي فقط، لا يوقف الرندر)
    mem_warning = warn_if_large_project(len(pngs), w, h, chunk_size)
    if mem_warning:
        log.warning(mem_warning)

    # ── Compound scene (chunked) ─────────────────────────────────────────────
    if layer_pngs:
        total     = max(len(layer) for layer in layer_pngs)
        resume_at = _resume_start(out_dir)

        if resume_at > 0:
            log.info(f"استئناف من الفريم {resume_at}")
            if blur.enabled:
                _seed_blur_from_last_frame(out_dir, blur)
            if progress_cb:
                progress_cb(resume_at, total)

        indices = list(range(resume_at, total))
        for chunk in chunked(indices, chunk_size):
            with MemoryGuard():
                for i in chunk:
                    frame_paths = [layer[min(i, len(layer) - 1)] for layer in layer_pngs]
                    out_path = out_dir / f"frame_{i:05d}.png"
                    if not out_path.exists():
                        _render_single_composite(frame_paths, out_path, (w, h), grade,
                                                  blur=blur, image_filters=image_filters)
                    if progress_cb:
                        progress_cb(i + 1, total)

        log.info(f"اكتمل المشهد المركّب: {total} فريم")
        return total

    # ── Simple scene (chunked) ───────────────────────────────────────────────
    else:
        total     = len(pngs)
        resume_at = _resume_start(out_dir)

        if resume_at > 0:
            log.info(f"استئناف من الفريم {resume_at}")
            if blur.enabled:
                _seed_blur_from_last_frame(out_dir, blur)
            if progress_cb:
                progress_cb(resume_at, total)

        remaining = list(enumerate(pngs))[resume_at:]
        for chunk in chunked(remaining, chunk_size):
            with MemoryGuard():
                for i, path in chunk:
                    out_path = out_dir / f"frame_{i:05d}.png"
                    if not out_path.exists():
                        _render_single_frame(path, out_path, (w, h), grade,
                                              blur=blur, image_filters=image_filters)
                    if progress_cb:
                        progress_cb(i + 1, total)

        log.info(f"اكتمل المشهد: {total} فريم")
        return total
