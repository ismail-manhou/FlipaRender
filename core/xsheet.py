"""
FlipaRender v9 — Exposure Sheet  (core/xsheet.py)

يقرأ ملف timing.txt من مجلد المشهد ويوسّع قائمة الفريمات بناءً على
عدد مرات تكرار كل فريم — بالضبط كما يفعل المحرك في التحريك التقليدي.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
صيغة timing.txt
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

كل سطر يمثل فريماً واحداً من الرسوم الأصلية:

    <رقم الفريم> : <عدد التكرارات>   # تعليق اختياري

أمثلة:

    1 : 3          # فريم 1 يُعرض 3 مرات (ثابت / hold)
    2 : 1          # فريم 2 يُعرض مرة واحدة (حركة سريعة)
    3 : 2
    4 : 2
    5 : 1          # لحظة تأثير قوية
    6 : 4          # توقف / pause

قواعد:
  - الأرقام تبدأ من 1 (لا من 0)
  - أي سطر يبدأ بـ # يُتجاهل (تعليق)
  - السطور الفارغة تُتجاهل
  - لو الفريم المذكور يتجاوز عدد الصور الموجودة → تحذير ويُتجاهل
  - لو timing.txt غير موجود → كل فريم يُكرر مرة واحدة (سلوك افتراضي)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from pathlib import Path


# ── نموذج بيانات ─────────────────────────────────────────────────────────────

class XSheetEntry:
    """سطر واحد من Exposure Sheet."""
    __slots__ = ("frame_index", "hold", "label")

    def __init__(self, frame_index: int, hold: int, label: str = "") -> None:
        self.frame_index = frame_index   # 0-based index في قائمة pngs
        self.hold        = hold          # عدد مرات التكرار
        self.label       = label         # تعليق / اسم الحركة (اختياري)

    def __repr__(self) -> str:
        s = f"XSheetEntry(frame={self.frame_index + 1}, hold={self.hold}"
        if self.label:
            s += f", label={self.label!r}"
        return s + ")"


class XSheet:
    """جدول Exposure Sheet كامل لمشهد واحد."""

    def __init__(self, entries: list[XSheetEntry], source: str = "") -> None:
        self.entries = entries
        self.source  = source   # مسار timing.txt أو "auto"

    # ── حساب المدة الكلية ─────────────────────────────────────────────────────

    @property
    def total_output_frames(self) -> int:
        """إجمالي الفريمات في الفيديو النهائي (بعد التكرار)."""
        return sum(e.hold for e in self.entries)

    # ── توسيع القائمة ─────────────────────────────────────────────────────────

    def expand(self, pngs: list[str]) -> list[str]:
        """
        أعِد قائمة pngs موسّعة بناءً على جدول التوقيت.

        مثال:
            pngs    = [A, B, C]
            entries = [hold=3, hold=1, hold=2]
            result  = [A, A, A, B, C, C]
        """
        result: list[str] = []
        for entry in self.entries:
            idx = entry.frame_index
            if idx >= len(pngs):
                continue   # فريم غير موجود — يُتجاهل
            for _ in range(entry.hold):
                result.append(pngs[idx])
        return result

    # ── عرض الجدول ────────────────────────────────────────────────────────────

    def summary(self, fps: int) -> str:
        """نص قصير يعرض محتوى الجدول — يُطبع في CLI."""
        lines = [f"  Exposure Sheet  ({len(self.entries)} drawings → "
                 f"{self.total_output_frames} output frames)"]

        if fps > 0:
            dur = self.total_output_frames / fps
            lines[0] += f"  [{dur:.2f}s @ {fps}fps]"

        lines.append(f"  Source: {self.source}")
        lines.append("")

        COL = 6
        for i, entry in enumerate(self.entries):
            bar   = "█" * min(entry.hold, 12) + ("+" if entry.hold > 12 else "")
            label = f"  ← {entry.label}" if entry.label else ""
            lines.append(
                f"    Frame {entry.frame_index + 1:>3}  "
                f"hold={entry.hold:<3}  {bar:<14}{label}"
            )
            if i >= COL - 1 and len(self.entries) > COL + 1:
                remaining = len(self.entries) - COL
                lines.append(f"    ... and {remaining} more drawing(s)")
                break

        return "\n".join(lines)


# ── Parser ────────────────────────────────────────────────────────────────────

_LINE_RE = re.compile(
    r"^\s*(\d+)\s*:\s*(\d+)\s*(?:#\s*(.*))?$"
)


def parse_timing_file(path: Path, total_pngs: int) -> XSheet:
    """
    اقرأ timing.txt وأعِد XSheet.

    السطور المقبولة:
        1 : 3
        2 : 1          # تعليق
        # سطر تعليق كامل

    الأخطاء:
        - رقم فريم = 0 → يُتجاهل مع تحذير
        - رقم فريم > total_pngs → يُتجاهل مع تحذير
        - hold = 0 → يُتجاهل مع تحذير
    """
    entries: list[XSheetEntry] = []
    warnings: list[str] = []

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        m = _LINE_RE.match(line)
        if not m:
            warnings.append(f"  Line {lineno}: unrecognised format → '{line}'")
            continue

        frame_1based = int(m.group(1))
        hold         = int(m.group(2))
        label        = (m.group(3) or "").strip()

        if frame_1based < 1:
            warnings.append(f"  Line {lineno}: frame number must be ≥ 1 — skipped")
            continue

        frame_0based = frame_1based - 1

        if frame_0based >= total_pngs:
            warnings.append(
                f"  Line {lineno}: frame {frame_1based} exceeds "
                f"available drawings ({total_pngs}) — skipped"
            )
            continue

        if hold < 1:
            warnings.append(f"  Line {lineno}: hold must be ≥ 1 — skipped")
            continue

        entries.append(XSheetEntry(frame_0based, hold, label))

    for w in warnings:
        print(f"\033[33m{w}\033[0m")   # طباعة تحذيرات بالأصفر مباشرة

    return XSheet(entries, source=str(path))


# ── Auto-generate ─────────────────────────────────────────────────────────────

def auto_xsheet(pngs: list[str], default_hold: int = 1) -> XSheet:
    """
    أنشئ XSheet تلقائياً: كل فريم يُكرر *default_hold* مرة.
    يُستخدم عندما لا يوجد timing.txt.
    """
    entries = [
        XSheetEntry(i, default_hold)
        for i in range(len(pngs))
    ]
    return XSheet(entries, source=f"auto (hold={default_hold})")


# ── واجهة رئيسية ──────────────────────────────────────────────────────────────

def load_xsheet(
    scene_dir: str | Path,
    pngs: list[str],
    default_hold: int = 1,
) -> XSheet:
    """
    حاول تحميل timing.txt من *scene_dir*.
    لو لم يوجد → أنشئ XSheet تلقائياً.

    الاستخدام:
        xsheet = load_xsheet(job["path"], job["pngs"], cfg.get("default_hold", 1))
        expanded_pngs = xsheet.expand(job["pngs"])
    """
    timing_file = Path(scene_dir) / "timing.txt"

    if timing_file.exists():
        return parse_timing_file(timing_file, total_pngs=len(pngs))

    return auto_xsheet(pngs, default_hold)


# ── مولّد timing.txt تجريبي ───────────────────────────────────────────────────

def generate_sample_timing(scene_dir: str | Path, pngs: list[str]) -> Path:
    """
    اكتب timing.txt نموذجياً في *scene_dir* بناءً على عدد الفريمات الموجودة.
    كل فريم له hold=2 افتراضياً (twos — التحريك على اثنين).

    لا يُنفَّذ تلقائياً — يُستدعى فقط لو طلب المستخدم نموذجاً.
    """
    out = Path(scene_dir) / "timing.txt"
    lines = [
        "# timing.txt — FlipaRender Exposure Sheet",
        "# Format:  <frame_number> : <hold_frames>  # optional label",
        "# Example: 1 : 3  means drawing 1 shows for 3 video frames",
        "#",
        "# Twos (every drawing holds for 2 frames — classic animation standard)",
        "",
    ]
    for i in range(1, len(pngs) + 1):
        lines.append(f"{i} : 2")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out
