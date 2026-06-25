"""
FlipaRender v8 — AI In-betweening

v8 changes:
  - BlendMode.HYBRID  : optical_flow في مناطق الحركة + linear في الخلفية الثابتة
  - suggest_steps()   : يقترح عدد الفريمات الوسيطة تلقائياً حسب الفرق بين الصورتين
  - AICache           : يحفظ نتائج optical_flow ويتجنب إعادة الحساب لنفس الزوج
"""

from __future__ import annotations

import hashlib
import pickle
from enum import Enum
from pathlib import Path

import numpy as np
from PIL import Image


class BlendMode(str, Enum):
    LINEAR       = "linear"
    SMART        = "smart"
    OPTICAL_FLOW = "optical_flow"
    HYBRID       = "hybrid"       # ← v8


# ── v8: AI Cache ──────────────────────────────────────────────────────────────

class AICache:
    """
    يخزن نتائج optical_flow على القرص حتى لا تُعاد عند كل تشغيل.

    المفتاح = SHA256 لمحتوى img1 + img2 معاً.

    مثال::
        cache = AICache(Path(".ai_cache"))
        flow  = cache.get(img1, img2)
        if flow is None:
            flow = _compute_flow(img1, img2)
            cache.set(img1, img2, flow)
    """

    def __init__(self, cache_dir: Path = Path(".ai_cache")) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(img1: Image.Image, img2: Image.Image) -> str:
        h = hashlib.sha256()
        h.update(img1.tobytes())
        h.update(img2.tobytes())
        return h.hexdigest()[:24]

    def get(self, img1: Image.Image, img2: Image.Image):
        path = self.cache_dir / (self._key(img1, img2) + ".pkl")
        if path.exists():
            try:
                with path.open("rb") as f:
                    return pickle.load(f)
            except Exception:
                path.unlink(missing_ok=True)
        return None

    def set(self, img1: Image.Image, img2: Image.Image, value) -> None:
        path = self.cache_dir / (self._key(img1, img2) + ".pkl")
        try:
            with path.open("wb") as f:
                pickle.dump(value, f)
        except Exception:
            pass  # الكاش اختياري — لا نوقف البرنامج لو فشل

    def clear(self) -> int:
        """احذف كل ملفات الكاش. يُعيد عدد الملفات المحذوفة."""
        count = 0
        for f in self.cache_dir.glob("*.pkl"):
            f.unlink(missing_ok=True)
            count += 1
        return count


# ── v8: Auto-suggest steps ────────────────────────────────────────────────────

def suggest_steps(img1: Image.Image, img2: Image.Image) -> int:
    """
    اقترح عدد الفريمات الوسيطة بناءً على متوسط الفرق بين الصورتين.

    الفرق المنخفض  (< 20) → حركة بسيطة  → 1 فريم وسيط
    الفرق المتوسط  (< 50) → حركة متوسطة → 2 فريمات
    الفرق العالي   (≥ 50) → حركة كبيرة  → 3 فريمات

    يعمل على نسخة مصغّرة (160×120) لأنه مجرد تقدير سريع.
    """
    thumb_size = (160, 120)
    a = np.array(img1.convert("RGB").resize(thumb_size), dtype=np.float32)
    b = np.array(img2.convert("RGB").resize(thumb_size), dtype=np.float32)
    diff = float(np.abs(a - b).mean())

    if diff < 20:
        return 1
    if diff < 50:
        return 2
    return 3


# ── v10: AI Auto Mode ──────────────────────────────────────────────────────────

class ModeSuggestion:
    """نتيجة تحليل AI Auto Mode — وضع مقترح + شرح بالعربية لسبب الاختيار."""

    __slots__ = ("mode", "reason", "motion_intensity", "motion_coverage")

    def __init__(self, mode: str, reason: str, motion_intensity: float, motion_coverage: float):
        self.mode             = mode               # قيمة من BlendMode (str)
        self.reason           = reason              # شرح مقروء يُعرض للمستخدم
        self.motion_intensity = motion_intensity    # متوسط شدة الفرق بين البكسلات (0-255)
        self.motion_coverage  = motion_coverage     # نسبة مساحة الكادر التي تغيّرت بشكل ملحوظ (0.0-1.0)

    def __repr__(self) -> str:  # debugging فقط
        return (f"ModeSuggestion(mode={self.mode!r}, intensity={self.motion_intensity:.1f}, "
                f"coverage={self.motion_coverage:.2f})")


def _frame_motion_metrics(img1: Image.Image, img2: Image.Image) -> tuple[float, float]:
    """
    يحلّل زوج فريمات ويعيد (شدة الحركة، نسبة مساحة الحركة).

    شدة الحركة      : متوسط |a-b| محسوب فقط على البكسلات المتأثرة فعلاً
                       (وليس على كامل الكادر) — هذا يميّز حركة قوية في منطقة
                       صغيرة عن حركة خفيفة منتشرة، رغم أن متوسطهما الكلي قد يتشابه.
    نسبة مساحة الحركة: نسبة البكسلات التي تجاوز فرقها عتبة 18 (حركة "محسوسة" لا ضوضاء)

    يعمل على نسخة مصغّرة (160×120) لسرعة المعالجة — تقدير وليس قياساً دقيقاً للبكسل.
    """
    thumb_size = (160, 120)
    a = np.array(img1.convert("L").resize(thumb_size), dtype=np.float32)
    b = np.array(img2.convert("L").resize(thumb_size), dtype=np.float32)
    diff = np.abs(a - b)

    moved_mask = diff > 18
    coverage   = float(moved_mask.mean())

    if moved_mask.any():
        intensity = float(diff[moved_mask].mean())
    else:
        intensity = float(diff.mean())  # لا حركة محسوسة — متوسط عام (سيكون صغيراً جداً)

    return intensity, coverage


def suggest_mode(frames: list[Image.Image] | list[list[Image.Image]]) -> ModeSuggestion:
    """
    AI Auto Mode — يحلّل فريمات ويقترح أفضل BlendMode تلقائياً مع توضيح السبب.

    يقبل أحد الشكلين:
      • قائمة فريمات مفردة لمشهد واحد:      [img1, img2, img3, ...]
      • قائمة مجموعات (مشاهد متعددة):       [[img1, img2, ...], [img1, img2, ...]]

    في حالة المجموعات، تُحلَّل الأزواج المتتالية *داخل* كل مجموعة فقط — لا تتم
    أبداً مقارنة آخر فريم من مشهد بأول فريم من مشهد آخر (قفزة وهمية لا تمثّل
    حركة حقيقية)، ثم تُدمَج كل النتائج بمتوسط واحد يمثّل الدفعة كاملة.

    المنطق:
      • حركة شبه معدومة (coverage منخفضة جداً)
            → linear   (بسيطة وسريعة، لا حاجة لمعالجة أثقل)
      • حركة معتدلة محصورة في جزء من الكادر
            → smart    (يكتشف منطقة الحركة فقط ويعالجها بدقة)
      • حركة قوية محصورة في جزء من الكادر بينما الباقي شبه ثابت
            → hybrid   (optical_flow على الحركة + linear على الخلفية الثابتة)
      • حركة كبيرة ومنتشرة على معظم الكادر
            → optical_flow  (أفضل جودة لحركة شاملة ومنتظمة)
    """
    # ── توحيد الشكل: نحوّل لقائمة مجموعات دائماً ─────────────────────────────
    if frames and isinstance(frames[0], (list, tuple)):
        sequences = [seq for seq in frames if len(seq) >= 2]
    else:
        sequences = [frames] if len(frames) >= 2 else []

    if not sequences:
        return ModeSuggestion(
            "linear",
            "فريم واحد فقط متاح للتحليل — تم اختيار linear كخيار آمن وسريع.",
            0.0, 0.0,
        )

    # نحلّل أزواجاً متتالية *داخل كل مجموعة على حدة* (حتى 6 أزواج لكل مشهد)
    intensities, coverages = [], []
    n_pairs_total = 0
    for seq in sequences:
        pairs = list(zip(seq, seq[1:]))[:6]
        for img1, img2 in pairs:
            i, c = _frame_motion_metrics(img1, img2)
            intensities.append(i)
            coverages.append(c)
            n_pairs_total += 1

    avg_intensity = sum(intensities) / len(intensities)
    avg_coverage  = sum(coverages) / len(coverages)

    n_scenes = len(sequences)
    if n_scenes > 1:
        basis = f"بناءً على تحليل {n_pairs_total} زوج فريمات عبر {n_scenes} مشاهد"
    elif n_pairs_total > 1:
        basis = f"بناءً على تحليل {n_pairs_total} زوج فريمات متتالية"
    else:
        basis = "بناءً على تحليل أول فريمين"

    # ── قواعد القرار ────────────────────────────────────────────────────────
    if avg_coverage < 0.03:
        mode   = "linear"
        reason = (f"{basis}: لا توجد حركة محسوسة تقريباً "
                  f"({avg_coverage*100:.1f}% من الكادر فقط تغيّر) — "
                  f"المشهد شبه ثابت، فـ linear كافٍ وأسرع دون فقدان جودة ملحوظ.")

    elif avg_coverage < 0.20 and avg_intensity < 35:
        mode   = "smart"
        reason = (f"{basis}: حركة معتدلة بشدة {avg_intensity:.1f}/255 محصورة في "
                  f"{avg_coverage*100:.0f}% فقط من الكادر — smart يكتشف منطقة الحركة "
                  f"ويعالجها بدقة دون إهدار وقت على الخلفية الثابتة.")

    elif avg_coverage < 0.55:
        mode   = "hybrid"
        reason = (f"{basis}: حركة قوية بشدة {avg_intensity:.1f}/255 محصورة في "
                  f"{avg_coverage*100:.0f}% من الكادر بينما الباقي شبه ثابت — "
                  f"hybrid يطبّق optical_flow على منطقة الحركة القوية و linear "
                  f"على الخلفية الثابتة، فيوازن بين الجودة والسرعة.")

    else:
        mode   = "optical_flow"
        reason = (f"{basis}: حركة كبيرة ومنتشرة على {avg_coverage*100:.0f}% من الكادر "
                  f"بشدة {avg_intensity:.1f}/255 — optical_flow يعطي أفضل جودة "
                  f"لحركة شاملة ومنتظمة كهذه.")

    return ModeSuggestion(mode, reason, avg_intensity, avg_coverage)


# ── Main class ────────────────────────────────────────────────────────────────

class AIInbetween:
    """
    توليد فريمات وسيطة بين كيفريمين.

    مثال::
        ib = AIInbetween(mode=BlendMode.OPTICAL_FLOW, steps=2)
        frames = ib.interpolate_sequence(img_a, img_b)
        out_paths = ib.process_and_save(png_list, out_dir)

    v8: مرّر cache=AICache() لتسريع المعالجة المتكررة.
    """

    def __init__(
        self,
        mode:  BlendMode = BlendMode.OPTICAL_FLOW,
        steps: int = 1,
        cache: AICache | None = None,
    ) -> None:
        self.mode  = mode
        self.steps = steps
        self.cache = cache

    # ── API العام ─────────────────────────────────────────────────────────────

    def interpolate(
        self,
        img1:  Image.Image,
        img2:  Image.Image,
        alpha: float = 0.5,
    ) -> Image.Image:
        """أنتج فريماً واحداً عند موضع alpha (0.0 → 1.0)."""
        if self.mode == BlendMode.OPTICAL_FLOW:
            return self._optical_flow(img1, img2, alpha, self.cache)
        if self.mode == BlendMode.SMART:
            return self._smart_blend(img1, img2, alpha)
        if self.mode == BlendMode.HYBRID:
            return self._hybrid(img1, img2, alpha, self.cache)
        return self._linear_blend(img1, img2, alpha)

    def interpolate_sequence(
        self,
        img1: Image.Image,
        img2: Image.Image,
    ) -> list[Image.Image]:
        """
        أنتج *steps* فريمات موزعة بالتساوي بين img1 و img2.
        steps=1 → [0.5]
        steps=3 → [0.25, 0.50, 0.75]
        """
        n = self.steps + 1
        return [self.interpolate(img1, img2, i / n) for i in range(1, n)]

    def process_and_save(
        self,
        png_paths:   list[str],
        out_dir:     Path,
        start_index: int = 0,
    ) -> list[str]:
        """
        خذ قائمة صور، أدخل فريمات وسيطة بين كل زوج، واحفظ الكل.
        يدعم الاستكمال (resume) — يتخطى الفريمات المحفوظة مسبقاً.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        saved: list[str] = []
        idx = start_index

        for i, path in enumerate(png_paths):
            img = Image.open(path)

            out = out_dir / f"frame_{idx:05d}.png"
            if not out.exists():          # ← resume: تخطى المحفوظ
                img.save(out)
            saved.append(str(out))
            idx += 1

            if i + 1 < len(png_paths):
                img_next = Image.open(png_paths[i + 1])
                for mid in self.interpolate_sequence(img, img_next):
                    out = out_dir / f"frame_{idx:05d}.png"
                    if not out.exists():
                        mid.save(out)
                    saved.append(str(out))
                    idx += 1

        return saved

    # ── OPTICAL FLOW (Farneback) ──────────────────────────────────────────────

    @staticmethod
    def _compute_flow(img1: Image.Image, img2: Image.Image):
        """احسب الـ flow بين صورتين — منفصل للكاش."""
        import cv2
        size = img1.size
        a_rgb  = np.array(img1.convert("RGB").resize(size, Image.LANCZOS), dtype=np.float32)
        b_rgb  = np.array(img2.convert("RGB").resize(size, Image.LANCZOS), dtype=np.float32)
        a_gray = cv2.cvtColor(a_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        b_gray = cv2.cvtColor(b_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        return cv2.calcOpticalFlowFarneback(
            a_gray, b_gray, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )

    @classmethod
    def _optical_flow(
        cls,
        img1:  Image.Image,
        img2:  Image.Image,
        alpha: float,
        cache: AICache | None = None,
    ) -> Image.Image:
        import cv2

        has_alpha = (img1.mode == "RGBA" or img2.mode == "RGBA")
        size = img1.size

        a_rgb = np.array(img1.convert("RGB").resize(size, Image.LANCZOS), dtype=np.float32)
        b_rgb = np.array(img2.convert("RGB").resize(size, Image.LANCZOS), dtype=np.float32)

        # v8: استخدم الكاش لو متاح
        flow = cache.get(img1, img2) if cache else None
        if flow is None:
            flow = cls._compute_flow(img1, img2)
            if cache:
                cache.set(img1, img2, flow)

        H, W = flow.shape[:2]
        grid_x, grid_y = np.meshgrid(np.arange(W), np.arange(H))
        grid_x = grid_x.astype(np.float32)
        grid_y = grid_y.astype(np.float32)

        map_fwd_x = grid_x + flow[..., 0] * alpha
        map_fwd_y = grid_y + flow[..., 1] * alpha
        map_bwd_x = grid_x - flow[..., 0] * (1 - alpha)
        map_bwd_y = grid_y - flow[..., 1] * (1 - alpha)

        def remap(src, mx, my):
            return cv2.remap(src, mx, my,
                             interpolation=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)

        warped_fwd = remap(a_rgb, map_fwd_x, map_fwd_y)
        warped_bwd = remap(b_rgb, map_bwd_x, map_bwd_y)
        blended    = warped_fwd * (1 - alpha) + warped_bwd * alpha
        result     = np.clip(blended, 0, 255).astype(np.uint8)
        out        = Image.fromarray(result, "RGB")

        if has_alpha:
            a_alpha = np.array(img1.convert("RGBA").split()[3], dtype=np.float32)
            b_alpha = np.array(img2.convert("RGBA").resize(size, Image.LANCZOS).split()[3], dtype=np.float32)
            wa      = remap(a_alpha, map_fwd_x, map_fwd_y)
            wb      = remap(b_alpha, map_bwd_x, map_bwd_y)
            alpha_ch = np.clip(wa * (1 - alpha) + wb * alpha, 0, 255).astype(np.uint8)
            out = out.convert("RGBA")
            out.putalpha(Image.fromarray(alpha_ch))

        return out

    # ── v8: HYBRID ────────────────────────────────────────────────────────────

    @classmethod
    def _hybrid(
        cls,
        img1:  Image.Image,
        img2:  Image.Image,
        alpha: float,
        cache: AICache | None = None,
        motion_threshold: int = 15,
    ) -> Image.Image:
        """
        HYBRID = optical_flow في مناطق الحركة + linear في الخلفية الثابتة.

        الخوارزمية:
          1. احسب mask الحركة (مثل smart) → أين يتحرك شيء؟
          2. طبّق optical_flow على منطقة الحركة
          3. طبّق linear blend على الخلفية الثابتة
          4. ادمجهما بالـ mask

        النتيجة: جودة optical_flow بدون تشويه الخلفيات الثابتة.
        """
        size = img1.size
        a = np.array(img1.convert("RGB").resize(size, Image.LANCZOS), dtype=np.float32)
        b = np.array(img2.convert("RGB").resize(size, Image.LANCZOS), dtype=np.float32)

        # mask الحركة
        diff  = np.abs(b - a).max(axis=2)
        mask  = np.clip((diff - motion_threshold) / (255 - motion_threshold), 0, 1)
        mask  = _gaussian_blur_2d(mask, sigma=3)
        mask3 = mask[:, :, np.newaxis]

        # optical_flow للمناطق المتحركة
        of_img  = cls._optical_flow(img1, img2, alpha, cache)
        of_arr  = np.array(of_img.convert("RGB").resize(size, Image.LANCZOS), dtype=np.float32)

        # linear للخلفية
        lin_arr = a + (b - a) * alpha

        # دمج
        blended = lin_arr * (1 - mask3) + of_arr * mask3
        result  = np.clip(blended, 0, 255).astype(np.uint8)
        return Image.fromarray(result, "RGB")

    # ── LINEAR ────────────────────────────────────────────────────────────────

    @staticmethod
    def _linear_blend(img1, img2, alpha) -> Image.Image:
        mode = "RGBA" if (img1.mode == "RGBA" or img2.mode == "RGBA") else "RGB"
        a = img1.convert(mode)
        b = img2.convert(mode).resize(a.size, Image.LANCZOS)
        return Image.blend(a, b, alpha)

    # ── SMART ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _smart_blend(img1, img2, alpha, motion_threshold: int = 15) -> Image.Image:
        mode = "RGBA" if (img1.mode == "RGBA" or img2.mode == "RGBA") else "RGB"
        size = img1.size

        a = np.array(img1.convert("RGB").resize(size, Image.LANCZOS), dtype=np.float32)
        b = np.array(img2.convert("RGB").resize(size, Image.LANCZOS), dtype=np.float32)

        diff  = np.abs(b - a).max(axis=2)
        mask  = np.clip((diff - motion_threshold) / (255 - motion_threshold), 0, 1)
        mask  = _gaussian_blur_2d(mask, sigma=3)
        mask3 = mask[:, :, np.newaxis]

        blended = a + mask3 * ((b - a) * alpha)
        result  = np.clip(blended, 0, 255).astype(np.uint8)
        out     = Image.fromarray(result, "RGB")

        if mode == "RGBA":
            a_img    = img1.convert("RGBA")
            b_img    = img2.convert("RGBA").resize(size, Image.LANCZOS)
            alpha_ch = Image.blend(a_img.split()[3], b_img.split()[3], alpha)
            out      = out.convert("RGBA")
            out.putalpha(alpha_ch)

        return out


# ── Gaussian blur بدون scipy ──────────────────────────────────────────────────

def _gaussian_kernel(sigma: float) -> np.ndarray:
    radius = int(3 * sigma + 0.5)
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    return k / k.sum()


def _gaussian_blur_2d(img: np.ndarray, sigma: float) -> np.ndarray:
    from numpy import convolve
    k   = _gaussian_kernel(sigma)
    out = np.apply_along_axis(lambda r: convolve(r, k, mode="same"), axis=1, arr=img)
    out = np.apply_along_axis(lambda r: convolve(r, k, mode="same"), axis=0, arr=out)
    return out.astype(np.float32)
