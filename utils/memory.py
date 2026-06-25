"""
FlipaRender v10 — Memory Optimizer  (utils/memory.py)

الهدف: رندر آلاف الفريمات على أجهزة بذاكرة محدودة (هواتف) بدون
تحميل كل الصور في الذاكرة دفعة واحدة.

الفكرة:
  - render_frames() (في render/frames.py) كانت تمرّ على قائمة الفريمات
    دفعة واحدة. الآن نقسمها إلى "دفعات" (chunks) بحجم RENDER_CHUNK_SIZE.
  - كل دفعة تُعالَج وتُكتب على القرص ثم تُحرَّر من الذاكرة (gc) قبل
    الانتقال للدفعة التالية.
  - حجم الدفعة قابل للتخصيص من config.py أو من واجهة CLI.

استخدام:

    from utils.memory import chunked, RENDER_CHUNK_SIZE, MemoryGuard

    for chunk in chunked(frame_list, RENDER_CHUNK_SIZE):
        process(chunk)
"""

from __future__ import annotations

import gc
from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")

# ── الإعداد الافتراضي — قابل للتغيير من config.py ──────────────────────────────
RENDER_CHUNK_SIZE = 50

# حدود مقترحة حسب ذاكرة الجهاز (تُستخدم في auto_chunk_size)
_CHUNK_PRESETS = {
    "low":    20,    # هواتف بذاكرة 2-3GB
    "medium": 50,    # هواتف متوسطة 4-6GB
    "high":   150,   # أجهزة قوية / حواسيب
}


def chunked(items: list[T], size: int = RENDER_CHUNK_SIZE) -> Iterator[list[T]]:
    """
    يقسّم قائمة إلى دفعات بحجم *size*.

    مثال:
        list(chunked([1,2,3,4,5], 2)) == [[1,2],[3,4],[5]]
    """
    if size <= 0:
        size = RENDER_CHUNK_SIZE
    for i in range(0, len(items), size):
        yield items[i:i + size]


def auto_chunk_size(total_frames: int, ram_profile: str = "medium") -> int:
    """
    يقترح حجم دفعة مناسب حسب عدد الفريمات الكلي ومستوى ذاكرة الجهاز.

    ram_profile: "low" | "medium" | "high"
    """
    base = _CHUNK_PRESETS.get(ram_profile, RENDER_CHUNK_SIZE)
    # لو المشروع صغير أصلاً، لا داعي لتقسيمه كثيراً
    if total_frames <= base:
        return total_frames
    return base


def detect_ram_profile() -> str:
    """
    يحاول اكتشاف مستوى ذاكرة الجهاز تلقائياً.
    يعمل بدون مكتبات خارجية إضافية (يحاول psutil إن وجدت، وإلا يفترض medium).
    """
    try:
        import psutil  # قد لا تكون مثبّتة على Termux افتراضياً
        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        if total_gb <= 3:
            return "low"
        if total_gb <= 6:
            return "medium"
        return "high"
    except ImportError:
        return "medium"


class MemoryGuard:
    """
    Context manager بسيط يُستخدم حول معالجة كل دفعة (chunk) لضمان
    تحرير الذاكرة فوراً بعد الانتهاء منها.

    استخدام:
        with MemoryGuard():
            process_chunk(chunk)
    """

    def __enter__(self) -> "MemoryGuard":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        gc.collect()
        # لا نمنع انتشار الاستثناء
        return None


def estimate_memory_per_frame(width: int, height: int, channels: int = 4) -> int:
    """
    تقدير تقريبي لحجم فريم واحد في الذاكرة بالبايت (RGBA غير مضغوط).
    يُستخدم لإعطاء تحذير للمستخدم قبل الرندر إن كان المشروع كبيراً جداً.
    """
    return width * height * channels


def warn_if_large_project(total_frames: int, width: int, height: int, chunk_size: int) -> str | None:
    """
    يرجع رسالة تحذير نصية إن كان المشروع كبيراً جداً بالنسبة للدفعة المختارة،
    أو None إن كان كل شيء ضمن المعقول.
    """
    bytes_per_frame = estimate_memory_per_frame(width, height)
    chunk_mb = (bytes_per_frame * chunk_size) / (1024 ** 2)

    if chunk_mb > 500:
        return (
            f"⚠ حجم الدفعة الحالي ({chunk_size} فريم) قد يستهلك "
            f"~{chunk_mb:.0f}MB من الذاكرة دفعة واحدة. يُفضّل تقليله."
        )
    return None
