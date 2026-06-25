"""
FlipaRender v10 — Watch Mode  (core/watch_engine.py)

مراقبة مجلد مشروع باستمرار، واكتشاف أي تعديل (صور جديدة، صور محذوفة،
صور مُعدَّلة) في مجلدات المشاهد، وإعادة رندر الدفعة كاملة تلقائياً عبر
core.render_engine.run_render — **نفس المحرك** المستخدم في الرندر اليدوي،
فأي ميزة تُضاف للمحرك تعمل هنا تلقائياً دون أي كود إضافي.

آلية الاكتشاف: فحص دوري (polling) بسيط بدل الاعتماد على مكتبات خارجية
(watchdog وأمثالها) — أخف على الموارد وأضمن عملاً على Termux/Android
بدون تثبيت إضافي. كل دورة فحص (WATCH_POLL_INTERVAL ثانية) نبني "بصمة"
لكل ملف صورة (المسار + وقت التعديل + الحجم) ونقارنها بالبصمة السابقة؛
أي اختلاف (إضافة/حذف/تعديل) يُحدِّث رندر الدفعة بالكامل.

الإعدادات (cfg) تأتي جاهزة بالكامل قبل الدخول هنا:
  • لو يوجد project.flipa محفوظ لهذا المشروع → تُحمَّل إعداداته
  • وإلا → إعدادات افتراضية ثابتة (core.project_file.build_default_cfg)
بأي الحالتين، لا يُطرح أي سؤال تفاعلي أثناء المراقبة.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from config import WATCH_POLL_INTERVAL
from core.scanner import scan_jobs
from core.project_file import (
    load_project, project_name_from_path, build_default_cfg, apply_project_to_cfg,
)
from core.render_engine import run_render
from ui.cli import section, ok, warn, dim, cyan, bold


# ── بصمة المجلد (لاكتشاف التعديلات) ─────────────────────────────────────────────

def _build_signature(root_path: Path) -> dict[str, tuple[float, int]]:
    """
    يبني بصمة لكل ملف صورة (png/jpg/jpeg) داخل *root_path* (بحثاً متكرراً
    في كل المجلدات الفرعية — يشمل المشاهد العادية والـ Compound layers).

    البصمة: {مسار_نسبي: (وقت_التعديل, الحجم_بالبايت)}
    """
    sig: dict[str, tuple[float, int]] = {}
    if not root_path.is_dir():
        return sig

    for ext in ("*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG"):
        for f in root_path.rglob(ext):
            try:
                stat = f.stat()
                sig[str(f.relative_to(root_path))] = (stat.st_mtime, stat.st_size)
            except OSError:
                continue   # ملف حُذف بين rglob وlstat — نتجاهله بأمان

    return sig


def _diff_summary(old_sig: dict, new_sig: dict) -> str:
    """يبني وصفاً مقروءاً لما تغيّر بين بصمتين (للإشعار في الطرفية)."""
    old_keys, new_keys = set(old_sig), set(new_sig)
    added   = new_keys - old_keys
    removed = old_keys - new_keys
    changed = {
        k for k in (old_keys & new_keys)
        if old_sig[k] != new_sig[k]
    }

    parts = []
    if added:
        parts.append(f"{len(added)} new")
    if removed:
        parts.append(f"{len(removed)} removed")
    if changed:
        parts.append(f"{len(changed)} modified")

    return ", ".join(parts) if parts else "changes detected"


# ── بناء cfg جاهز بدون أسئلة ─────────────────────────────────────────────────────

def _load_or_default_cfg(root_path: Path) -> tuple[dict, bool]:
    """
    يحمّل إعدادات مشروع محفوظ (project.flipa) لو موجود، وإلا يبني إعدادات
    افتراضية ثابتة. يعيد (cfg, from_saved_project).
    """
    project_name = project_name_from_path(root_path)
    try:
        data = load_project(project_name)
        cfg = build_default_cfg()           # أساس كامل المفاتيح أولاً
        apply_project_to_cfg(data, cfg)      # ثم نطبّق المحفوظ فوقه
        return cfg, True
    except (FileNotFoundError, ValueError):
        return build_default_cfg(), False


# ── الحلقة الرئيسية ──────────────────────────────────────────────────────────────

def watch_project(
    root_path: Path,
    log,
    poll_interval: float = WATCH_POLL_INTERVAL,
    on_render_done: Callable[[object], None] | None = None,
) -> None:
    """
    يراقب *root_path* باستمرار ويعيد الرندر تلقائياً عند أي تعديل، حتى
    يوقفه المستخدم بـ Ctrl+C (KeyboardInterrupt) — لا يتوقف من تلقاء نفسه
    بعد أي رندر، فالمراقبة مستمرة دائماً.

    *on_render_done* : callback اختياري يُستدعى بنتيجة كل رندر (RenderResult)
                       — مفيد لاختبارات تلقائية بدون انتظار Ctrl+C الفعلي.
    """
    project_name = project_name_from_path(root_path)

    section("Watch Mode")
    print(f"  {cyan('👁')}  Watching: {bold(str(root_path))}")
    print(f"  {dim(f'Poll interval: {poll_interval:.0f}s — press Ctrl+C to stop')}")
    print()

    cfg, from_saved = _load_or_default_cfg(root_path)
    if from_saved:
        ok(f"Loaded saved settings for project '{project_name}'.")
    else:
        warn(f"No saved project found for '{project_name}' — using default settings.")
    print()

    log.info(f"Watch Mode بدأ على: {root_path}  (إعدادات محفوظة: {from_saved})")

    last_sig: dict[str, tuple[float, int]] = {}
    render_count = 0

    try:
        while True:
            current_sig = _build_signature(root_path)

            if current_sig and current_sig != last_sig:
                if last_sig:   # ليست أول دورة — هناك تغيير حقيقي
                    summary = _diff_summary(last_sig, current_sig)
                    print(f"  {cyan('🔔')}  Change detected ({summary}) — re-rendering...")
                    log.info(f"Watch Mode: تغيير مكتشف ({summary})")
                else:
                    print(f"  {cyan('🔔')}  Initial scan — rendering for the first time...")
                    log.info("Watch Mode: أول رندر تلقائي")

                try:
                    jobs = scan_jobs(str(root_path))
                except (FileNotFoundError, ValueError) as exc:
                    warn(f"Scan failed: {exc} — will retry next cycle.")
                    log.warning(f"Watch Mode: فشل المسح: {exc}")
                    last_sig = current_sig
                    time.sleep(poll_interval)
                    continue

                if not jobs:
                    warn("No scenes found yet — waiting for frames...")
                    last_sig = current_sig
                    time.sleep(poll_interval)
                    continue

                render_count += 1
                print()
                result = run_render(
                    cfg, jobs, root_path, log,
                    project_name=project_name,
                )
                print()
                ok(f"Auto-render #{render_count} complete  "
                   f"({result.success} succeeded, {result.failed} failed)")
                log.info(f"Watch Mode: رندر تلقائي #{render_count} اكتمل "
                          f"(success={result.success}, failed={result.failed})")

                if on_render_done:
                    on_render_done(result)

                last_sig = current_sig
                print()
                print(f"  {dim('Watching for further changes...')}")

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print()
        ok("Watch Mode stopped by user.")
        log.info(f"Watch Mode أُوقف بواسطة المستخدم — إجمالي الرندرات: {render_count}")
