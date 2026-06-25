"""
FlipaRender v10 — Smart FPS Detection  (core/fps_advisor.py)

يحلّل الـ Exposure Sheet (نتيجة core/xsheet.py) لكل مشهد ويقترح FPS مناسب:

  - Holds كثيرة (كل فريم يتكرر مرات عديدة)  → حركة بطيئة تقليدية → يقترح 12
  - Holds قليلة (كل فريم يظهر مرة أو مرتين)  → حركة سريعة وسلسة   → يقترح 24 أو أعلى
  - حالة متوسطة                              → يقترح 18

المنطق يعتمد على "متوسط الـ hold" عبر كل فريمات الـ Exposure Sheet:

    avg_hold = مجموع (hold لكل فريم) / عدد الفريمات

    avg_hold >= 3   → حركة "on twos/threes" تقليدية → 12 fps
    avg_hold ~= 2   → حركة متوسطة                    → 18 fps
    avg_hold <= 1.3 → حركة سريعة "on ones"            → 24 fps
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.xsheet import load_xsheet


@dataclass
class FPSSuggestion:
    fps:         int
    avg_hold:    float
    reason:      str
    confidence:  str   # "low" | "medium" | "high"


# عتبات القرار — قابلة للتعديل بسهولة
_THRESHOLD_SLOW   = 2.6   # avg_hold أعلى من هذا → 12fps
_THRESHOLD_MEDIUM = 1.6   # avg_hold بين هذا والسابق → 18fps
                            # أقل من هذا → 24fps


def analyze_scene(scene_path: str, pngs: list[str], default_hold: int = 1) -> FPSSuggestion:
    """
    يحلّل مشهداً واحداً ويرجع اقتراح FPS له.
    """
    xsheet = load_xsheet(scene_path, pngs, default_hold)

    if not xsheet.entries:
        return FPSSuggestion(
            fps=12, avg_hold=1.0,
            reason="لا توجد بيانات توقيت — استخدام الإعداد الافتراضي.",
            confidence="low",
        )

    holds = [e.hold for e in xsheet.entries]
    avg_hold = sum(holds) / len(holds)

    if avg_hold >= _THRESHOLD_SLOW:
        fps    = 12
        reason = f"متوسط التكرار {avg_hold:.1f} فريم — حركة تقليدية بطيئة (Holds كثيرة)."
    elif avg_hold >= _THRESHOLD_MEDIUM:
        fps    = 18
        reason = f"متوسط التكرار {avg_hold:.1f} فريم — حركة متوسطة السرعة."
    else:
        fps    = 24
        reason = f"متوسط التكرار {avg_hold:.1f} فريم — حركة سريعة وسلسة (Holds قليلة)."

    # الثقة بالاقتراح تعتمد على وجود timing.txt حقيقي (وليس auto)
    confidence = "high" if "auto" not in xsheet.source else "medium"

    return FPSSuggestion(fps=fps, avg_hold=avg_hold, reason=reason, confidence=confidence)


def analyze_batch(jobs: list[dict], default_hold: int = 1) -> FPSSuggestion:
    """
    يحلّل عدة مشاهد معاً (دفعة كاملة) ويرجع اقتراحاً موحّداً.
    يأخذ متوسط الـ avg_hold عبر كل المشاهد، مرجّحاً بعدد فريمات كل مشهد.
    """
    if not jobs:
        return FPSSuggestion(fps=12, avg_hold=1.0, reason="لا توجد مشاهد.", confidence="low")

    total_weighted_hold = 0.0
    total_frames        = 0
    any_manual           = False

    for job in jobs:
        xsheet = load_xsheet(job["path"], job["pngs"], default_hold)
        if not xsheet.entries:
            continue
        holds = [e.hold for e in xsheet.entries]
        total_weighted_hold += sum(holds)
        total_frames        += len(holds)
        if "auto" not in xsheet.source:
            any_manual = True

    if total_frames == 0:
        return FPSSuggestion(fps=12, avg_hold=1.0, reason="لا توجد بيانات كافية.", confidence="low")

    avg_hold = total_weighted_hold / total_frames

    if avg_hold >= _THRESHOLD_SLOW:
        fps    = 12
        reason = f"متوسط عام {avg_hold:.1f} عبر {len(jobs)} مشهد — حركة بطيئة (Holds كثيرة)."
    elif avg_hold >= _THRESHOLD_MEDIUM:
        fps    = 18
        reason = f"متوسط عام {avg_hold:.1f} عبر {len(jobs)} مشهد — حركة متوسطة."
    else:
        fps    = 24
        reason = f"متوسط عام {avg_hold:.1f} عبر {len(jobs)} مشهد — حركة سريعة وسلسة."

    confidence = "high" if any_manual else "medium"
    return FPSSuggestion(fps=fps, avg_hold=avg_hold, reason=reason, confidence=confidence)
