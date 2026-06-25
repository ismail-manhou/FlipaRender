"""
FlipaRender v10 — Motion Blur  (render/motion_blur.py)

Motion Blur اختياري يُطبَّق بين كل فريم والفريم الذي يليه مباشرة، عبر مزج
وزن بسيط (weighted blend) بنسبة قابلة للتحكم.

الفكرة:
    blurred_frame[i] = (1 - strength) * frame[i] + strength * frame[i-1]

  - strength = 0.0  → بدون أي تأثير (الفريم كما هو)
  - strength = 0.3  → تأثير خفيف (موصى به لـ 12fps)
  - strength = 0.6  → تأثير قوي وواضح

ملاحظة تصميم مهمة:
    الـ blur يُطبَّق بعد الـ color grading مباشرة وقبل الحفظ النهائي على القرص،
    ويحتاج "ذاكرة" الفريم السابق فقط (frame[i-1]) — لذلك هو متوافق تماماً مع
    Chunk Rendering: نُمرّر آخر فريم من الدفعة السابقة كنقطة بداية للدفعة التالية.

استخدام:

    from render.motion_blur import MotionBlurState

    blur_state = MotionBlurState(strength=0.3)
    for img in frames:
        img = blur_state.apply(img)
        save(img)
"""

from __future__ import annotations

from PIL import Image, ImageChops


# حدود معقولة لشدة التأثير
MIN_STRENGTH = 0.0
MAX_STRENGTH = 0.8
DEFAULT_STRENGTH = 0.3


def clamp_strength(strength: float) -> float:
    return max(MIN_STRENGTH, min(MAX_STRENGTH, strength))


class MotionBlurState:
    """
    يحمل "ذاكرة" الفريم السابق عبر استدعاءات متتالية لـ apply().

    مصمَّم خصيصاً ليعمل عبر دفعات (chunks) — احتفظ بنفس الكائن بين الدفعات
    ولا تُعِد إنشاءه، حتى يستمر تأثير البلر بسلاسة على حدود الدفعات.
    """

    def __init__(self, strength: float = DEFAULT_STRENGTH, enabled: bool = True) -> None:
        self.strength = clamp_strength(strength)
        self.enabled  = enabled and self.strength > 0
        self._prev_frame: Image.Image | None = None

    def apply(self, img: Image.Image) -> Image.Image:
        """
        يطبّق Motion Blur على *img* بالاستناد إلى الفريم السابق المخزَّن،
        ثم يحدّث الفريم السابق ليكون *img* الأصلي (غير المموّه) — حتى لا
        يتراكم التمويه بشكل مفرط عبر فريمات كثيرة متتالية.
        """
        if not self.enabled:
            self._prev_frame = img
            return img

        work = img.convert("RGB")

        if self._prev_frame is None:
            # أول فريم في التسلسل بالكامل — لا يوجد فريم سابق لمزجه
            self._prev_frame = work
            return img

        prev = self._prev_frame
        if prev.size != work.size:
            prev = prev.resize(work.size, Image.LANCZOS)

        blended = Image.blend(work, prev, self.strength)

        # نحدّث الذاكرة بالفريم الأصلي (غير المموّه) لتفادي تراكم الضبابية
        self._prev_frame = work

        # نحافظ على القناة الشفافة الأصلية إن وُجدت
        if img.mode == "RGBA":
            blended = blended.convert("RGBA")
            blended.putalpha(img.getchannel("A"))

        return blended

    def reset(self) -> None:
        """يُستدعى عند بدء مشهد جديد كي لا يمتزج الفريم الأخير من مشهد بأول فريم في التالي."""
        self._prev_frame = None


def estimate_recommended_strength(fps: int) -> float:
    """
    اقتراح شدة افتراضية حسب الـ FPS:
      - fps منخفض (12) → الحركة "متقطّعة" أكثر، بلر أقوى يساعد على السلاسة
      - fps مرتفع (24+) → الحركة أصلاً سلسة، بلر خفيف يكفي
    """
    if fps <= 12:
        return 0.35
    if fps <= 18:
        return 0.25
    return 0.15
