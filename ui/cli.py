"""
FlipaRender v10 — CLI helpers

v10 changes:
  - ProgressBar: شريط تقدم حقيقي مع نسبة%، سرعة المعالجة (frames/sec)،
    والوقت المتبقي المقدَّر (ETA) — يحلّ محل progress() البسيطة القديمة
    دون كسرها (progress() لا تزال موجودة كواجهة مبسَّطة/توافق رجعي).
  - classify_error / err_detailed: تصنيف الأخطاء الشائعة (ملف مفقود،
    صلاحيات، إعداد/ملف تالف، فشل أمر خارجي كـ ffmpeg، خلل برمجي عام)
    مع رسالة مساعدة عملية بدل عرض نص الاستثناء الخام فقط.

v6 (محفوظ): الألوان، banner، section، ok/warn/err الأساسية، ask/ask_int/
ask_choice — لم يتغيّر سلوكها الوظيفي، فقط أُضيف فوقها.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time


# ── ANSI colours (auto-disabled when not a tty) ───────────────────────────────
_IS_TTY = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text

def cyan(t: str)    -> str: return _c("96", t)
def green(t: str)   -> str: return _c("92", t)
def yellow(t: str)  -> str: return _c("93", t)
def red(t: str)     -> str: return _c("91", t)
def bold(t: str)    -> str: return _c("1",  t)
def dim(t: str)     -> str: return _c("2",  t)
def magenta(t: str) -> str: return _c("95", t)   # v10: لتمييز عناوين plugins/presets


# ── Layout helpers ────────────────────────────────────────────────────────────

def banner(app: str, version: str) -> None:
    width = 44
    print()
    print(cyan("╔" + "═" * width + "╗"))
    print(cyan("║") + bold(f"  {app} v{version}".center(width)) + cyan("║"))
    print(cyan("╚" + "═" * width + "╝"))
    print()


def section(title: str) -> None:
    print()
    print(cyan("─" * 44))
    print(bold(f"  {title}"))
    print(cyan("─" * 44))


def ok(msg: str) -> None:
    print(green("  ✔  ") + msg)


def warn(msg: str) -> None:
    print(yellow("  ⚠  ") + msg)


def err(msg: str) -> None:
    print(red("  ✘  ") + msg)


# ── v10: شريط تقدم حقيقي مع ETA وسرعة المعالجة ─────────────────────────────────

def _format_eta(seconds: float) -> str:
    """ينسّق عدد ثوانٍ إلى mm:ss (أو h:mm:ss لو ساعة أو أكثر)."""
    if seconds < 0 or seconds != seconds:   # NaN أو سالب (لا يمكن تقديره بعد)
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class ProgressBar:
    """
    شريط تقدم حقيقي: نسبة%، سرعة المعالجة (frames/sec)، والوقت المتبقي
    المقدَّر (ETA) — محسوب من متوسط السرعة الفعلية منذ بداية هذا الشريط.

    استخدام:
        bar = ProgressBar(total=120, label="frames")
        for i in range(120):
            ...
            bar.update(i + 1)
        bar.finish()   # ينتقل لسطر جديد بعد الانتهاء

    أو كاختصار مباشر متوافق مع progress_cb القديمة:
        bar = ProgressBar(total=120)
        progress_cb = bar.update
    """

    def __init__(self, total: int, label: str = "frames", width: int = 30,
                 start_time: float | None = None):
        """
        *start_time* اختياري: مرّره (من time.monotonic()) لو إنشاء الشريط
        كسول (lazy — أي يحدث بعد أن العمل على أول عنصر بدأ فعلاً، كحال
        progress_cb الذي يُستدعى لأول مرة بعد معالجة الفريم الأول كاملاً).
        بدونه، الافتراض هو أن الإنشاء يحدث *قبل* أي عمل (الحالة المعتادة).
        """
        self.total = max(total, 1)   # تجنّب القسمة على صفر لمشهد فاضٍ نظرياً
        self.label = label
        self.width = width
        self.start_time = start_time if start_time is not None else time.monotonic()
        self._last_time = self.start_time
        self._last_current = 0
        self._done = False

    def update(self, current: int) -> None:
        current = min(current, self.total)
        now = time.monotonic()

        delta_frames = current - self._last_current
        delta_time   = max(now - self._last_time, 1e-6)
        speed        = delta_frames / delta_time if delta_frames > 0 else 0.0
        pct          = current / self.total

        if speed > 0:
            remaining = (self.total - current) / speed
            eta_label = _format_eta(remaining)
        else:
            eta_label = "--:--"

        done_blocks = int(pct * self.width)
        bar = "█" * done_blocks + dim("░" * (self.width - done_blocks))

        line = (
            f"\r  [{bar}] {current}/{self.total} {self.label}"
            f"  {pct*100:5.1f}%"
            f"  {dim(f'{speed:.1f} {self.label}/s')}"
            f"  {dim(f'ETA {eta_label}')}"
        )
        sys.stdout.write(cyan(line))
        sys.stdout.flush()

        self._last_time = now
        self._last_current = current

        if current >= self.total and not self._done:
            self._done = True
            sys.stdout.write("\n")

    def finish(self) -> None:
        """يضمن الانتقال لسطر جديد حتى لو لم يصل update() لـ total بدقة."""
        if not self._done:
            self._done = True
            sys.stdout.write("\n")
            sys.stdout.flush()


def progress(current: int, total: int, label: str = "frames") -> None:
    """
    واجهة مبسَّطة بدون حالة (stateless) — للتوافق الرجعي مع كود قديم
    ينادي progress(current, total) مباشرة بدون إنشاء ProgressBar. لا
    تعرض ETA/سرعة (تحتاج تتبّع زمني عبر استدعاءات متعددة)؛ الاستخدام
    الموصى به الآن هو ProgressBar مباشرة عندما يتوفر total منذ البداية.
    """
    pct   = current / max(total, 1)
    done  = int(pct * 30)
    bar   = "█" * done + dim("░" * (30 - done))
    line  = f"\r  [{bar}] {current}/{total} {label}"
    sys.stdout.write(cyan(line))
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")


# ── v10: تصنيف الأخطاء + عرض مفهوم ──────────────────────────────────────────────

# كل تصنيف: (عنوان قصير بالعربية، نص مساعد عملي بالعربية)
_ERROR_HELP = {
    "missing_file": (
        "ملف غير موجود",
        "تحقّق من المسار، أو أن الملف لم يُنقَل أو يُحذَف بعد بدء العملية.",
    ),
    "permission": (
        "صلاحيات غير كافية",
        "تحقّق من صلاحيات الكتابة/القراءة على هذا المسار (خصوصاً على Android/Termux).",
    ),
    "corrupt_data": (
        "ملف أو إعداد تالف",
        "الملف موجود لكن محتواه غير صالح (JSON تالف أو صورة معطوبة) — قد تحتاج لإعادة إنشائه.",
    ),
    "external_tool": (
        "فشل أمر خارجي (FFmpeg)",
        "تحقّق من تثبيت FFmpeg بشكل صحيح، أو أن الملف المصدر غير تالف.",
    ),
    "internal": (
        "خلل برمجي غير متوقَّع",
        "هذا قد يكون خللاً في البرنامج نفسه — يُفضَّل مراجعة ملف السجل (logs/) لتفاصيل أكثر.",
    ),
}


def classify_error(exc: BaseException) -> str:
    """
    يصنّف استثناءً إلى أحد المفاتيح في _ERROR_HELP، بالاعتماد على نوعه
    أولاً (الأدق)، ثم على نص رسالته كحل بديل لاستثناءات عامة (OSError
    مثلاً يغطي حالات متعددة حسب رسالتها الفعلية).
    """
    if isinstance(exc, FileNotFoundError):
        return "missing_file"
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return "corrupt_data"
    if isinstance(exc, subprocess.CalledProcessError):
        return "external_tool"

    # PIL.UnidentifiedImageError يرث من OSError ولا اسم نوع مستورد هنا
    # عمداً (تجنّباً لاعتماد ui/cli.py على Pillow) — نكتشفه باسم الكلاس.
    if type(exc).__name__ == "UnidentifiedImageError":
        return "corrupt_data"

    # OSError عام (لا FileNotFoundError ولا PermissionError محددة) —
    # نحاول التمييز من نص الرسالة كحل تقريبي معقول.
    if isinstance(exc, OSError):
        msg = str(exc).lower()
        if "permission" in msg or "denied" in msg:
            return "permission"
        if "no such file" in msg or "not found" in msg:
            return "missing_file"
        if "cannot identify image" in msg or "truncated" in msg or "corrupt" in msg:
            return "corrupt_data"

    return "internal"


def err_detailed(exc: BaseException, context: str = "") -> None:
    """
    يعرض خطأ مصنَّف بطريقة مفهومة: نوع الخطأ، رسالته الفعلية، ونص
    مساعد عملي — بدل عرض نص الاستثناء الخام فقط (سلوك err() القديمة).

    *context* اختياري: وصف قصير لما كان البرنامج يفعله عند حدوث الخطأ
    (مثل "رندر المشهد 'Walk'") — يُعرض في السطر الأول لو وُجد.
    """
    kind = classify_error(exc)
    title, help_text = _ERROR_HELP[kind]

    prefix = f"{context}: " if context else ""
    print(red("  ✘  ") + bold(f"{prefix}{title}"))
    print(f"      {dim(str(exc))}")
    print(f"      {dim('→ ' + help_text)}")


# ── Input helpers (بدون تغيير وظيفي) ───────────────────────────────────────────

def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    raw  = input(cyan(f"  › {prompt}{hint}: ")).strip()
    return raw or default


def ask_int(
    prompt: str,
    default: int,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            n = int(raw)
        except ValueError:
            err("Please enter a whole number.")
            continue
        if min_value is not None and n < min_value:
            err(f"Must be ≥ {min_value}.")
            continue
        if max_value is not None and n > max_value:
            err(f"Must be ≤ {max_value}.")
            continue
        return n


def ask_choice(prompt: str, choices: list[str], default: str) -> str:
    """Ask the user to pick one item from *choices*."""
    options = "  |  ".join(
        bold(c) if c == default else dim(c) for c in choices
    )
    print(f"\n  {options}\n")
    while True:
        raw = ask(prompt, default).lower()
        if raw in choices:
            return raw
        err(f"Valid options: {', '.join(choices)}")
