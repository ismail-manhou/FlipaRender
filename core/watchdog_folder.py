"""
FlipaRender — Watchdog Folder  (core/watchdog_folder.py)

يراقب مجلداً محدداً في الخلفية وينطلق تلقائياً عند اكتشاف ملف ZIP
أو مشروع FlipaClip جديد (.fc) — مثل "خادم صامت" للرندر التلقائي.

التثبيت المطلوب مرة واحدة:
    pip install watchdog

الاستخدام من CLI:
    python -m core.watchdog_folder /sdcard/FlipaClip/Export

الاستخدام البرمجي:
    from core.watchdog_folder import start_watcher, RenderCallback

    def my_render(zip_path):
        print(f"رندر تلقائي: {zip_path}")
        # ← ضع هنا منطق الرندر

    start_watcher("/sdcard/FlipaClip/Export", callback=my_render)

ما يراقبه:
    - ملفات .zip  ← يُمرَّر لـ scan_zip() → render
    - ملفات .fc   ← يُمرَّر لـ open_flipaclip_project() → render
    - يتجاهل أي صيغة أخرى
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger("fliparender.watchdog")

# الامتدادات التي تُطلق الرندر التلقائي
WATCHED_EXTENSIONS = frozenset({".zip", ".fc"})

# ثوانٍ ننتظرها بعد اكتشاف الملف قبل معالجته
# (نضمن انتهاء الكتابة على القرص قبل الفتح)
SETTLE_DELAY = 2.0

RenderCallback = Callable[[Path], None]


# ─────────────────────────────────────────────────────────────────────────────
# Handler
# ─────────────────────────────────────────────────────────────────────────────

def _make_handler(callback: RenderCallback, processed: set[Path]):
    """
    يبني FileSystemEventHandler يستدعي callback عند اكتشاف ملف جديد.
    processed: مجموعة مشتركة لتجنّب معالجة نفس الملف مرتين.
    """
    try:
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        raise ImportError(
            "مكتبة watchdog غير مثبّتة.\n"
            "ثبّتها بالأمر:  pip install watchdog"
        )

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            self._handle(event)

        def on_moved(self, event):
            # عند نقل ملف إلى المجلد المراقب (مثلاً من مجلد Download)
            dest = getattr(event, "dest_path", None)
            if dest:
                self._handle_path(Path(dest))

        def _handle(self, event):
            if event.is_directory:
                return
            self._handle_path(Path(event.src_path))

        def _handle_path(self, path: Path):
            if path.suffix.lower() not in WATCHED_EXTENSIONS:
                return
            if path in processed:
                return

            # انتظر حتى يكتمل الكتابة
            time.sleep(SETTLE_DELAY)

            # تحقّق أن الملف لا يزال موجوداً (ربما حُذف بسرعة)
            if not path.exists():
                return

            processed.add(path)
            logger.info(f"[watchdog] ملف جديد: {path.name}")

            try:
                callback(path)
            except Exception as exc:
                logger.error(f"[watchdog] خطأ أثناء معالجة {path.name}: {exc}")

    return _Handler()


# ─────────────────────────────────────────────────────────────────────────────
# واجهة عامة
# ─────────────────────────────────────────────────────────────────────────────

def start_watcher(
    watch_dir:  str | Path,
    callback:   RenderCallback,
    recursive:  bool = False,
    block:      bool = True,
) -> None:
    """
    يبدأ مراقبة المجلد watch_dir ويستدعي callback(path) لكل ملف جديد.

    المعاملات:
        watch_dir  : المجلد المراد مراقبته (يجب أن يكون موجوداً)
        callback   : دالة تُستدعى بمسار الملف الجديد (Path)
        recursive  : راقب المجلدات الفرعية أيضاً (False افتراضياً)
        block      : أبقِ البرنامج مشغولاً (True للاستخدام من CLI)

    يرفع:
        ImportError       — لو watchdog غير مثبّتة
        FileNotFoundError — لو المجلد غير موجود
    """
    try:
        from watchdog.observers import Observer
    except ImportError:
        raise ImportError(
            "مكتبة watchdog غير مثبّتة.\n"
            "ثبّتها بالأمر:  pip install watchdog"
        )

    watch_dir = Path(watch_dir)
    if not watch_dir.exists():
        raise FileNotFoundError(f"المجلد غير موجود: {watch_dir}")
    if not watch_dir.is_dir():
        raise ValueError(f"المسار ليس مجلداً: {watch_dir}")

    processed: set[Path] = set()
    handler  = _make_handler(callback, processed)
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=recursive)
    observer.start()

    logger.info(f"[watchdog] يراقب: {watch_dir}  (recursive={recursive})")
    print(f"\n  👁  يراقب المجلد: {watch_dir}")
    print(f"      الامتدادات:    {', '.join(sorted(WATCHED_EXTENSIONS))}")
    print(f"      اضغط Ctrl+C للإيقاف.\n")

    if not block:
        return  # يُعيد فوراً (Observer يعمل في thread خلفي)

    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        print("\n  ⏹  المراقبة أُوقفت.")


# ─────────────────────────────────────────────────────────────────────────────
# Default callback — يستخدم scan_zip + يطبع النتيجة
# (يمكن استبداله بمنطق رندر حقيقي في main.py)
# ─────────────────────────────────────────────────────────────────────────────

def _default_callback(path: Path) -> None:
    """
    Callback افتراضي يُعيّن عند تشغيل الوحدة مباشرة من CLI.
    يُجري scan فقط ويطبع المشاهد المكتشفة دون رندر حقيقي.
    """
    ext = path.suffix.lower()
    print(f"\n  ▶  ملف جديد: {path.name}")

    if ext == ".zip":
        try:
            from core.scanner import scan_zip
            with scan_zip(path) as result:
                print(f"     مشاهد مكتشفة: {len(result.jobs)}")
                for job in result.jobs:
                    print(f"       • {job['name']}  ({job['count']} فريم)")
        except Exception as exc:
            print(f"     ✘ فشل scan: {exc}")

    elif ext == ".fc":
        try:
            from core.flipaclip_reader import read_flipaclip_info
            info = read_flipaclip_info(path)
            print(
                f"     FPS={info['fps']}  "
                f"{info['width']}×{info['height']}  "
                f"طبقات={info['layer_count']}"
            )
        except Exception as exc:
            print(f"     ✘ فشل قراءة .fc: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# تشغيل مباشر:  python -m core.watchdog_folder <مجلد>
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) < 2:
        print("الاستخدام:  python -m core.watchdog_folder <مجلد_المراقبة>")
        sys.exit(1)

    folder = sys.argv[1]
    start_watcher(folder, callback=_default_callback, block=True)
