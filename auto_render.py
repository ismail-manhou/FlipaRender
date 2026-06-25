"""
FlipaRender v10 — الرندر التلقائي  (auto_render.py)
════════════════════════════════════════════════════════

يراقب مجلد تصدير FlipaClip في الخلفية ويُرندر تلقائياً بمجرد
اكتشاف ملف جديد (.zip أو .fc) — بدون أي تدخل يدوي.

التشغيل:
    python auto_render.py                   ← يقرأ auto_render.json
    python auto_render.py my_config.json    ← ملف إعدادات مخصص

المتطلبات:
    pip install watchdog          ← المراقبة التلقائية
    pkg install termux-api        ← الإشعارات (Termux فقط)
"""

from __future__ import annotations

import gc
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ── إضافة مجلد FlipaRender لمسار الاستيراد ──────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# الإصدار والثوابت
# ══════════════════════════════════════════════════════════════════════════════

APP_VERSION  = "10.0"
CONFIG_FILE  = ROOT / "auto_render.json"
BANNER_WIDTH = 50


# ══════════════════════════════════════════════════════════════════════════════
# 1. تحميل الإعدادات والتحقق منها
# ══════════════════════════════════════════════════════════════════════════════

_REQUIRED_KEYS = ("watch_folder", "output_folder")

_SCHEMA: dict[str, tuple[type, Any]] = {
    # مفتاح          : (النوع، القيمة الافتراضية)
    "fps":                  (int,   12),
    "resolution":           (str,   "hd"),
    "format":               (str,   "mp4"),
    "crf":                  (int,   23),
    "x264_preset":          (str,   "slow"),
    "grading":              (str,   "none"),
    "motion_blur":          (bool,  False),
    "motion_blur_strength": (float, 0.4),
    "ai_enabled":           (bool,  False),
    "ai_steps":             (int,   1),
    "ai_mode":              (str,   "smart"),  # كانت "blend" — غير موجودة في BlendMode أصلاً
    "ai_cache":             (bool,  True),
    "render_chunk_size":    (int,   30),
    "ram_profile":          (str,   "medium"),
    "gif_colors":           (int,   256),
    "gif_max_width":        (int,   1080),
    "gif_loop":             (int,   0),
    "notify":               (bool,  True),
    "notify_sound":         (bool,  True),
    "notify_vibrate":       (bool,  True),
    "settle_delay":         (float, 3.0),
    "watch_recursive":      (bool,  False),
    "watched_extensions":   (list,  [".zip", ".fc"]),
    "log_verbose":          (bool,  False),
    "keep_logs":            (int,   20),
}

_VALID_AI_MODES    = {"linear", "smart", "hybrid", "optical_flow"}
# ↑ تم تصحيحها: كانت تحتوي "blend" غير الموجودة فعلياً في ai.inbetween.BlendMode
#   (تتسبب لاحقاً في ValueError عند BlendMode(cfg["ai_mode"]) وتُسقط الرندر كله)
#   وكانت تستبعد "smart" رغم أنها وضع صالح ومفيد للحركة المعتدلة. راجع ai/inbetween.py
_VALID_FORMATS     = {"mp4", "gif"}
_VALID_RAM_PROFILES= {"low", "medium", "high"}
_VALID_X264_PRESETS= {"ultrafast", "superfast", "veryfast", "faster", "fast",
                       "medium", "slow", "slower", "veryslow"}


def _load_config(path: Path) -> dict:
    """يقرأ ملف JSON ويُنظّف مفاتيح التعليق ويتحقق من الإعدادات."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _die(f"خطأ في تنسيق {path.name}: {exc}")

    # احذف مفاتيح التعليق (تبدأ بـ _ أو ══ أو ╔ أو ═)
    settings = {
        k: v for k, v in raw.items()
        if not k.startswith(("_", "══", "╔", "╚", "═"))
    }

    # تحقق من المفاتيح الإلزامية
    for key in _REQUIRED_KEYS:
        if key not in settings:
            _die(f"المفتاح الإلزامي '{key}' غير موجود في {path.name}")

    # أضف القيم الافتراضية للمفاتيح الناقصة وتحقق من الأنواع
    for key, (typ, default) in _SCHEMA.items():
        if key not in settings:
            settings[key] = default
        else:
            val = settings[key]
            if not isinstance(val, typ):
                try:
                    settings[key] = typ(val)
                except (ValueError, TypeError):
                    _die(
                        f"قيمة خاطئة للمفتاح '{key}': "
                        f"المتوقع {typ.__name__}، الموجود {type(val).__name__}"
                    )

    # تحقق من القيم المسموح بها
    _validate_enum(settings, "format",   _VALID_FORMATS,     path.name)
    _validate_enum(settings, "ai_mode",  _VALID_AI_MODES,    path.name)
    _validate_enum(settings, "ram_profile", _VALID_RAM_PROFILES, path.name)
    _validate_enum(settings, "x264_preset", _VALID_X264_PRESETS, path.name)

    # تحقق من النطاقات العددية
    _validate_range(settings, "crf",                  0,    51,  path.name)
    _validate_range(settings, "fps",                  1,    120, path.name)
    _validate_range(settings, "motion_blur_strength", 0.01, 1.0, path.name)
    _validate_range(settings, "ai_steps",             1,    3,   path.name)
    _validate_range(settings, "render_chunk_size",    1,    200, path.name)
    _validate_range(settings, "settle_delay",         0.5,  30,  path.name)

    # تطبيع الامتدادات
    settings["watched_extensions"] = [
        (e if e.startswith(".") else f".{e}").lower()
        for e in settings["watched_extensions"]
    ]

    return settings


def _validate_enum(s: dict, key: str, valid: set, fname: str) -> None:
    if s[key] not in valid:
        _die(f"قيمة غير صالحة للمفتاح '{key}': '{s[key]}' — المقبول: {valid} | ملف: {fname}")


def _validate_range(s: dict, key: str, lo: float, hi: float, fname: str) -> None:
    val = s[key]
    if not (lo <= val <= hi):
        _die(f"قيمة '{key}' خارج النطاق [{lo}–{hi}]: {val} | ملف: {fname}")


def _die(msg: str) -> None:
    print(f"\n  ✘  {msg}\n")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# 2. بناء cfg الكامل من الإعدادات
# ══════════════════════════════════════════════════════════════════════════════

def _build_cfg(settings: dict) -> dict:
    """يحوّل إعدادات auto_render.json إلى cfg متوافق مع render_frames() و export()."""
    from config import GRADES, RESOLUTIONS

    res_key   = settings["resolution"]
    grade_key = settings["grading"]

    if res_key not in RESOLUTIONS:
        _die(f"دقة غير معروفة: '{res_key}' — المقبول: {list(RESOLUTIONS)}")
    if grade_key not in GRADES:
        _die(f"فلتر ألوان غير معروف: '{grade_key}' — المقبول: {list(GRADES)}")

    w, h, _  = RESOLUTIONS[res_key]
    grade    = GRADES[grade_key]

    return {
        # أساسيات
        "fps":             settings["fps"],
        "crf":             settings["crf"],
        "x264_preset":     settings["x264_preset"],
        "w":               w,
        "h":               h,
        "resolution_key":  res_key,
        "grade":           grade,
        "grade_key":       grade_key,
        "format":          settings["format"].lower(),

        # Motion Blur
        "motion_blur_enabled":  settings["motion_blur"],
        "motion_blur_strength": settings["motion_blur_strength"],

        # AI Inbetweening
        "ai_enabled": settings["ai_enabled"],
        "ai_steps":   settings["ai_steps"],
        "ai_mode":    settings["ai_mode"],
        "ai_cache":   settings["ai_cache"],

        # الذاكرة
        "render_chunk_size": settings["render_chunk_size"],
        "default_hold":      1,

        # GIF
        "gif_colors":    settings["gif_colors"],
        "gif_max_width": settings["gif_max_width"],
        "gif_loop":      settings["gif_loop"],

        # Metadata
        "metadata": settings.get("metadata", {
            "title":   "",
            "artist":  "",
            "comment": f"FlipaRender v{APP_VERSION}",
        }),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. الإشعارات
# ══════════════════════════════════════════════════════════════════════════════

_HAS_TERMUX: bool | None = None   # كاش للتحقق من توفر Termux:API


def _termux_available() -> bool:
    global _HAS_TERMUX
    if _HAS_TERMUX is None:
        _HAS_TERMUX = bool(shutil.which("termux-notification"))
    return _HAS_TERMUX


def _notify(
    title:    str,
    message:  str,
    sound:    bool = True,
    vibrate:  bool = True,
    priority: str  = "default",
    ongoing:  bool = False,
    notif_id: str  = "fliparender_main",
) -> None:
    """يُرسل إشعار Termux ويطبع في الطرفية دائماً."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n  🔔  [{ts}]  {title}")
    print(f"      {message}")

    if not _termux_available():
        return

    cmd = [
        "termux-notification",
        "--title",    title,
        "--content",  message,
        "--priority", priority,
        "--id",       notif_id,
        "--ongoing",  "true" if ongoing else "false",
    ]
    if sound:
        cmd += ["--sound"]
    if vibrate:
        cmd += ["--vibrate", "300,150,300"]

    try:
        subprocess.run(cmd, timeout=5, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


def _notify_progress(message: str, pct: int = -1) -> None:
    """إشعار تقدّم مستمر — بدون صوت أو اهتزاز."""
    label = f"FlipaRender 🎬" + (f"  {pct}%" if pct >= 0 else "")
    _notify(
        title    = label,
        message  = message,
        sound    = False,
        vibrate  = False,
        priority = "low",
        ongoing  = True,
        notif_id = "fliparender_progress",
    )


def _clear_progress_notify() -> None:
    """يحذف إشعار التقدم المستمر."""
    if not _termux_available():
        return
    try:
        subprocess.run(
            ["termux-notification-remove", "fliparender_progress"],
            timeout=5, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# 4. أدوات الطرفية
# ══════════════════════════════════════════════════════════════════════════════

def _bar(current: int, total: int, width: int = 28) -> str:
    pct  = current / max(total, 1)
    done = int(pct * width)
    return f"[{'█' * done}{'░' * (width - done)}] {current}/{total} ({pct*100:.0f}%)"


def _hr(char: str = "─", width: int = BANNER_WIDTH) -> str:
    return f"  {char * width}"


def _section(title: str) -> None:
    pad  = max(0, BANNER_WIDTH - len(title) - 4)
    left = pad // 2
    right= pad - left
    print(f"\n  ╔{'═' * (BANNER_WIDTH - 2)}╗")
    print(f"  ║{' ' * left}  {title}  {' ' * right}║")
    print(f"  ╚{'═' * (BANNER_WIDTH - 2)}╝")


# ══════════════════════════════════════════════════════════════════════════════
# 5. منطق الرندر
# ══════════════════════════════════════════════════════════════════════════════

def _render_job(
    job:        dict,
    cfg:        dict,
    output_dir: Path,
    settings:   dict,
    scene_dir:  str | None = None,
) -> Path | None:
    """يُرندر مشهداً واحداً ويعيد مسار الفيديو، أو None لو فشل."""
    from render.frames import render_frames
    from render.video  import export

    job_name     = job["name"]
    fmt          = cfg["format"]
    ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file     = str(output_dir / f"{job_name}_{ts}.{fmt}")
    total_frames = job["count"]

    log.info(f"بدء رندر: {job_name}  ({total_frames} فريم)")

    # ── سطر المشهد ────────────────────────────────────────────────────────
    blur_tag = (
        f"blur={cfg['motion_blur_strength']}"
        if cfg["motion_blur_enabled"] else "no-blur"
    )
    ai_tag = (
        f"AI×{cfg['ai_steps']} [{cfg['ai_mode']}]"
        if cfg["ai_enabled"] else "no-AI"
    )
    print(f"\n  {'─'*BANNER_WIDTH}")
    print(f"  🎞  {job_name}  ·  {total_frames} فريم  ·  {blur_tag}  ·  {ai_tag}")
    print(f"  {'─'*BANNER_WIDTH}")

    _notify_progress(f"رندر {job_name}… 0%", 0)

    with tempfile.TemporaryDirectory(prefix="fliparender_frames_") as tmp:
        frame_dir = Path(tmp)
        last_pct  = [-1]

        def _progress(current: int, total: int) -> None:
            pct = int(current / max(total, 1) * 100)
            if pct != last_pct[0]:
                last_pct[0] = pct
                print(f"\r  {_bar(current, total)}", end="", flush=True)
                if pct in (25, 50, 75):
                    _notify_progress(f"رندر {job_name}… {pct}%", pct)

        try:
            rendered = render_frames(
                pngs       = job["pngs"],
                cfg        = cfg,
                out_dir    = frame_dir,
                progress_cb= _progress,
                layer_pngs = job.get("layer_pngs"),
                scene_dir  = scene_dir or job.get("path"),
            )
            print()   # سطر جديد بعد progress bar
        except Exception as exc:
            print()
            log.error(f"✘ فشل render_frames: {job_name}: {exc}")
            return None

        if rendered == 0:
            log.warning(f"⚠ لا فريمات مُرندَرة: {job_name}")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            export(cfg, frame_dir, out_file)
        except Exception as exc:
            log.error(f"✘ فشل التصدير: {job_name}: {exc}")
            return None

        gc.collect()

    log.info(f"✔ تم: {out_file}")
    return Path(out_file)


def _process_zip(zip_path: Path, cfg: dict, output_dir: Path, settings: dict) -> None:
    """يعالج ملف ZIP: يفك الضغط ← scan ← render."""
    from core.scanner import scan_zip

    log.info(f"ZIP: {zip_path.name}")
    print(f"\n  📦  {zip_path.name}")
    _notify_progress(f"تحليل {zip_path.name}…")

    t_start = time.perf_counter()
    videos: list[Path] = []

    try:
        with scan_zip(zip_path) as result:
            jobs = result.jobs
            if not jobs:
                msg = f"لم يُعثر على مشاهد داخل {zip_path.name}"
                log.warning(f"⚠ {msg}")
                _notify("⚠ FlipaRender", msg,
                        sound=settings["notify_sound"], vibrate=False)
                return

            log.info(f"مشاهد مكتشفة: {len(jobs)}")
            print(f"  📂  {len(jobs)} مشهد مكتشف")

            for i, job in enumerate(jobs, 1):
                print(f"\n  ── {i}/{len(jobs)}: {job['name']} ({job['count']} فريم)")
                out = _render_job(job, cfg, output_dir, settings)
                if out:
                    videos.append(out)

    except (FileNotFoundError, ValueError) as exc:
        log.error(f"✘ خطأ ZIP: {exc}")
        _notify("✘ FlipaRender — خطأ", str(exc),
                sound=settings["notify_sound"],
                vibrate=settings["notify_vibrate"])
        return

    _finish_render(zip_path.name, videos, time.perf_counter() - t_start, settings)


def _process_fc(fc_path: Path, cfg: dict, output_dir: Path, settings: dict) -> None:
    """يعالج ملف FlipaClip .fc."""
    from core.flipaclip_reader import open_flipaclip_project, read_flipaclip_info

    log.info(f".fc: {fc_path.name}")

    try:
        info = read_flipaclip_info(fc_path)
        print(f"\n  🎨  {fc_path.name}")
        print(f"      FPS={info['fps']}  {info['width']}×{info['height']}  "
              f"طبقات={info['layer_count']}")
        if settings.get("fps") is None:
            cfg["fps"] = info["fps"]
            log.info(f"FPS من ملف .fc: {info['fps']}")
    except Exception as exc:
        log.warning(f"⚠ تعذّرت قراءة معلومات .fc: {exc}")

    _notify_progress(f"رندر {fc_path.name}…")
    t_start = time.perf_counter()
    videos: list[Path] = []

    try:
        with open_flipaclip_project(fc_path) as proj:
            jobs = proj.to_scanner_jobs()
            if not jobs:
                log.warning(f"⚠ لا فريمات في {fc_path.name}")
                return
            for i, job in enumerate(jobs, 1):
                print(f"\n  ── {i}/{len(jobs)}: {job['name']} ({job['count']} فريم)")
                out = _render_job(job, cfg, output_dir, settings)
                if out:
                    videos.append(out)
    except Exception as exc:
        log.error(f"✘ خطأ .fc: {exc}")
        _notify("✘ FlipaRender — خطأ", str(exc),
                sound=settings["notify_sound"],
                vibrate=settings["notify_vibrate"])
        return

    _finish_render(fc_path.name, videos, time.perf_counter() - t_start, settings)


def _finish_render(
    source_name: str,
    videos:      list[Path],
    elapsed:     float,
    settings:    dict,
) -> None:
    """يطبع ملخص الرندر ويُرسل الإشعار النهائي."""
    _clear_progress_notify()

    mins     = int(elapsed // 60)
    secs     = int(elapsed % 60)
    time_str = f"{mins}د {secs}ث" if mins else f"{secs}ث"

    print(f"\n  {_hr()}")

    if videos:
        print(f"  ✔  اكتمل الرندر — {len(videos)} فيديو في {time_str}")
        for v in videos:
            print(f"     • {v.name}")
        log.info(f"اكتمل: {len(videos)} فيديو من [{source_name}] في {time_str}")

        if settings["notify"]:
            _notify(
                title    = "✔ FlipaRender — اكتمل الرندر 🎬",
                message  = f"{len(videos)} فيديو جاهز | {time_str}\n{videos[0].name}",
                sound    = settings["notify_sound"],
                vibrate  = settings["notify_vibrate"],
                priority = "high",
            )
    else:
        msg = f"لم يُنتَج أي فيديو من [{source_name}]"
        print(f"  ✘  {msg}")
        log.warning(msg)
        if settings["notify"]:
            _notify(
                title    = "✘ FlipaRender — فشل الرندر",
                message  = msg,
                sound    = settings["notify_sound"],
                vibrate  = settings["notify_vibrate"],
                priority = "high",
            )

    print(f"  {_hr()}\n")


# ══════════════════════════════════════════════════════════════════════════════
# 6. Watchdog Handler
# ══════════════════════════════════════════════════════════════════════════════

def _make_watchdog_handler(cfg: dict, output_dir: Path, settings: dict):
    try:
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        _die("مكتبة watchdog غير مثبّتة.\nثبّتها بالأمر:  pip install watchdog")

    watched_exts = frozenset(settings["watched_extensions"])
    settle_delay = settings["settle_delay"]
    processed:   set[str] = set()

    class _Handler(FileSystemEventHandler):

        def on_created(self, event):
            if not event.is_directory:
                self._handle(Path(event.src_path))

        def on_moved(self, event):
            dest = getattr(event, "dest_path", None)
            if dest:
                self._handle(Path(dest))

        def _handle(self, path: Path) -> None:
            if path.suffix.lower() not in watched_exts:
                return

            key = str(path.resolve())
            if key in processed:
                log.debug(f"تجاهل (مُعالَج): {path.name}")
                return

            # انتظر اكتمال الكتابة
            time.sleep(settle_delay)
            if not path.exists():
                return

            processed.add(key)
            _announce_file(path)

            ext = path.suffix.lower()
            if ext == ".zip":
                _process_zip(path, cfg, output_dir, settings)
            elif ext == ".fc":
                _process_fc(path, cfg, output_dir, settings)

    return _Handler()


def _announce_file(path: Path) -> None:
    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    print(f"\n  {'═'*BANNER_WIDTH}")
    print(f"  📥  ملف جديد   :  {path.name}")
    print(f"  🕐  الوقت      :  {ts}")
    print(f"  {'═'*BANNER_WIDTH}")


# ══════════════════════════════════════════════════════════════════════════════
# 7. اللوغ
# ══════════════════════════════════════════════════════════════════════════════

log: logging.Logger = logging.getLogger("auto_render")


def _setup_logging(verbose: bool, log_dir: Path, keep: int) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"auto_{ts}.log"

    handlers: list[logging.Handler] = [
        logging.FileHandler(log_file, encoding="utf-8")
    ]
    if verbose:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level   = logging.DEBUG if verbose else logging.INFO,
        format  = "%(asctime)s  [%(levelname)-7s]  %(message)s",
        datefmt = "%H:%M:%S",
        handlers= handlers,
        force   = True,
    )

    # احتفظ بآخر N ملفات فقط
    old_logs = sorted(log_dir.glob("auto_*.log"))[:-max(keep, 1)]
    for f in old_logs:
        try:
            f.unlink()
        except OSError:
            pass

    return logging.getLogger("auto_render")


# ══════════════════════════════════════════════════════════════════════════════
# 8. طباعة ملخص الإعدادات
# ══════════════════════════════════════════════════════════════════════════════

def _print_banner(cfg: dict, settings: dict, watch_folder: Path, output_dir: Path) -> None:
    grade_name = cfg["grade"].get("name", cfg["grade_key"])
    blur_info  = (
        f"✔  قوة={cfg['motion_blur_strength']}"
        if cfg["motion_blur_enabled"] else "✘"
    )
    ai_info    = (
        f"✔  steps={cfg['ai_steps']}  mode={cfg['ai_mode']}"
        + ("  [cache]" if cfg["ai_cache"] else "")
        if cfg["ai_enabled"] else "✘"
    )

    W = BANNER_WIDTH
    print()
    print(f"  ╔{'═'*W}╗")
    print(f"  ║{'  FlipaRender v' + APP_VERSION + ' — الرندر التلقائي  🎬':^{W}}║")
    print(f"  ╚{'═'*W}╝")
    print()
    print(f"  📁  أراقب      :  {watch_folder}")
    print(f"  💾  الإخراج    :  {output_dir}")
    print()
    print(f"  ── إعدادات الفيديو {'─'*(W-20)}")
    print(f"  🎞  FPS         :  {cfg['fps']}")
    print(f"  📐  الدقة       :  {cfg['resolution_key'].upper()}  "
          f"({cfg['w']}×{cfg['h']})")
    print(f"  🎨  الفلتر      :  {grade_name}")
    print(f"  📦  الصيغة      :  {cfg['format'].upper()}")
    print(f"  🔬  CRF         :  {cfg['crf']}  (preset={cfg['x264_preset']})")
    print()
    print(f"  ── تقنيات الجودة {'─'*(W-19)}")
    print(f"  💨  Motion Blur :  {blur_info}")
    print(f"  🤖  AI Inbetween:  {ai_info}")
    print()
    print(f"  ── الأداء {'─'*(W-12)}")
    print(f"  🧠  Chunk       :  {cfg['render_chunk_size']} فريم/دفعة")
    print(f"  💽  RAM Profile :  {settings['ram_profile']}")
    print()
    print(f"  ── المراقبة {'─'*(W-13)}")
    print(f"  🔔  إشعارات    :  {'✔' if settings['notify'] else '✘'}")
    exts = "  ".join(settings["watched_extensions"])
    print(f"  👁  امتدادات   :  {exts}")
    print(f"  ⏱  settle_delay:  {settings['settle_delay']}ث")
    print()
    print(f"  {_hr('─')}")
    print(f"  اضغط  Ctrl+C  للإيقاف")
    print(f"  {_hr('─')}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# 9. نقطة الدخول
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    global log

    # ── ملف الإعدادات ──────────────────────────────────────────────────────
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CONFIG_FILE
    if not cfg_path.exists():
        _die(
            f"ملف الإعدادات غير موجود: {cfg_path}\n"
            f"  أنشئه أولاً بجانب auto_render.py"
        )

    settings = _load_config(cfg_path)

    # ── اللوغ ──────────────────────────────────────────────────────────────
    log = _setup_logging(
        verbose = settings["log_verbose"],
        log_dir = ROOT / "logs",
        keep    = settings["keep_logs"],
    )

    # ── المسارات ───────────────────────────────────────────────────────────
    watch_folder = Path(settings["watch_folder"])
    output_dir   = Path(settings["output_folder"])

    if not watch_folder.exists():
        _die(f"مجلد المراقبة غير موجود: {watch_folder}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── بناء cfg ───────────────────────────────────────────────────────────
    cfg = _build_cfg(settings)

    # ── Banner ─────────────────────────────────────────────────────────────
    _print_banner(cfg, settings, watch_folder, output_dir)

    log.info(f"auto_render v{APP_VERSION} بدأ — مراقبة: {watch_folder}")

    if settings["notify"]:
        _notify(
            title   = "👁 FlipaRender — جاهز",
            message = f"يراقب: {watch_folder.name}",
            sound   = False,
            vibrate = False,
        )

    # ── Watchdog ────────────────────────────────────────────────────────────
    try:
        from watchdog.observers import Observer
    except ImportError:
        _die("مكتبة watchdog غير مثبّتة.\nثبّتها بالأمر:  pip install watchdog")

    handler  = _make_watchdog_handler(cfg, output_dir, settings)
    observer = Observer()
    observer.schedule(
        handler,
        str(watch_folder),
        recursive=settings["watch_recursive"],
    )
    observer.start()

    print(f"  👁  يراقب الآن…\n")

    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        _clear_progress_notify()
        print(f"\n\n  ⏹  أُوقف الرندر التلقائي.")
        log.info("auto_render أُوقف بواسطة المستخدم")


if __name__ == "__main__":
    main()
