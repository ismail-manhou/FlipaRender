"""
FlipaRender v10 — Logging System  (utils/logger.py)

نظام سجلات احترافي:
  - يسجّل كل عملية رندر في ملف مستقل تحت logs/
  - مستويات: INFO / WARNING / ERROR
  - يطبع رسائل مختصرة وملوّنة في الطرفية + يحفظ التفاصيل الكاملة في الملف
  - استخدام:

      from utils.logger import get_logger
      log = get_logger("render")
      log.info("بدء الرندر")
      log.warning("الطبقات غير متساوية الطول")
      log.error("فشل ffmpeg", exc=exception_obj)
"""

from __future__ import annotations

import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs")

_LEVEL_COLOR = {
    "INFO":    "\033[96m",   # cyan
    "WARNING": "\033[93m",   # yellow
    "ERROR":   "\033[91m",   # red
}
_RESET = "\033[0m"


class FlipaLogger:
    """
    لوغر مستقل لكل عملية تشغيل (run).
    كل استدعاء لـ get_logger() بنفس session_id يستخدم نفس الملف.
    """

    def __init__(self, name: str, session_id: str, verbose: bool = False) -> None:
        self.name       = name
        self.session_id = session_id
        self.verbose    = verbose   # لو True يطبع تفاصيل INFO أيضاً في الطرفية

        LOG_DIR.mkdir(exist_ok=True)
        self.log_path = LOG_DIR / f"{session_id}.log"

        # رأس الملف عند أول إنشاء
        if not self.log_path.exists():
            with self.log_path.open("w", encoding="utf-8") as f:
                f.write(f"FlipaRender Log — Session {session_id}\n")
                f.write(f"Started: {datetime.now().isoformat()}\n")
                f.write("=" * 60 + "\n\n")

    # ── internal ──────────────────────────────────────────────────────────────

    def _write(self, level: str, msg: str, exc: BaseException | None = None) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level:<7}] [{self.name}] {msg}"

        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            if exc is not None:
                f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                f.write("\n")

        # طرفية: الأخطاء والتحذيرات دائماً، INFO فقط لو verbose
        if level == "INFO" and not self.verbose:
            return

        color = _LEVEL_COLOR.get(level, "")
        print(f"{color}[{level}]{_RESET} {msg}", file=sys.stderr if level == "ERROR" else sys.stdout)

    # ── public API ────────────────────────────────────────────────────────────

    def info(self, msg: str) -> None:
        self._write("INFO", msg)

    def warning(self, msg: str) -> None:
        self._write("WARNING", msg)

    def error(self, msg: str, exc: BaseException | None = None) -> None:
        self._write("ERROR", msg, exc=exc)

    def stage(self, stage_name: str) -> None:
        """تسجيل بداية مرحلة جديدة من الرندر — يفصلها بصرياً في الملف."""
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {stage_name} " + "-" * max(1, 40 - len(stage_name)) + "\n")
        self.info(f"المرحلة: {stage_name}")


# ── Session management ───────────────────────────────────────────────────────

_active_loggers: dict[str, FlipaLogger] = {}
_session_id: str | None = None


def new_session() -> str:
    """يُستدعى مرة واحدة عند بدء main.py — يولّد session_id فريد لهذا التشغيل."""
    global _session_id
    _session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    _active_loggers.clear()
    return _session_id


def get_logger(name: str, verbose: bool = False) -> FlipaLogger:
    """
    يرجع logger باسم معيّن (مثل 'render', 'ai', 'scanner') يكتب كلهم
    في نفس ملف الـ session الحالي.
    """
    global _session_id
    if _session_id is None:
        _session_id = new_session()

    key = f"{_session_id}:{name}"
    if key not in _active_loggers:
        _active_loggers[key] = FlipaLogger(name, _session_id, verbose=verbose)
    return _active_loggers[key]


def current_log_path() -> Path | None:
    global _session_id
    if _session_id is None:
        return None
    return LOG_DIR / f"{_session_id}.log"


def cleanup_old_logs(keep_last: int = 20) -> None:
    """يحتفظ فقط بآخر keep_last ملف سجل، يحذف الباقي."""
    if not LOG_DIR.exists():
        return
    logs = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old_log in logs[keep_last:]:
        try:
            old_log.unlink()
        except OSError:
            pass
