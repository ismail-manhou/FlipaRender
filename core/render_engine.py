"""
FlipaRender v10 — Render Engine موحَّد  (core/render_engine.py)

هذا الملف هو **نقطة التنفيذ الوحيدة** للرندر الفعلي في FlipaRender.

الفكرة: كل منطق "ماذا يحدث بعد أن يصبح cfg جاهزاً" (حلقة رندر المشاهد،
الدمج، الصوت، الإحصائيات، الحفظ التلقائي، النسخة الاحتياطية) يعيش هنا
مرة واحدة فقط. أي ميزة جديدة تُضاف هنا تعمل تلقائياً في:

  • main.py        — الرندر اليدوي (تفاعلي، يبني cfg بالأسئلة ثم يستدعي run_render)
  • watch_mode.py  — الرندر التلقائي (يبني cfg من project.flipa ثم يستدعي run_render)

أي وضع رندر جديد لاحقاً (API، واجهة رسومية، إلخ) يحتاج فقط بناء cfg
الصحيح واستدعاء run_render — بدون أي تكرار لمنطق الرندر نفسه.

*cfg* يجب أن يكون **جاهزاً بالكامل** عند الوصول لهذا الملف — لا يوجد هنا
أي استدعاء لـ ask/ask_int/ask_choice. فقط عرض (CLI prints) وتنفيذ.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import (
    DEFAULT_OUTPUT_DIR, TMP_PREFIX,
    PROJECT_AUTOSAVE,
    AUDIO_SYNC_FULL_VIDEO_ONLY, AUDIO_SYNC_PER_SCENE, DEFAULT_AUDIO_MIX_MODE,
)
from render.frames import render_frames, _resume_start
from render.video   import export
from core.project_file import save_project, project_name_from_path, build_project_data
from core.audio     import mux_audio
from core.backup    import find_pending_tmp_dirs, save_backup, clear_backup
from core.plugins   import discover_video_effects
from utils.stats    import RenderStats
from ui.cli import (
    section, ok, warn, err_detailed, ProgressBar,
    bold, cyan, dim, yellow,
)


# ── نتيجة الرندر ────────────────────────────────────────────────────────────────

@dataclass
class RenderResult:
    success:       int                 # عدد المشاهد التي رُندرت بنجاح
    failed:        int                 # عدد المشاهد التي فشلت
    rendered_files: list[Path] = field(default_factory=list)
    final_video:   Path | None = None   # FULL_VIDEO.mp4 أو الفيديو الوحيد (None لو GIF/فشل الكل)
    stats:         RenderStats | None = None
    project_path:  Path | None = None   # مسار project.flipa المحفوظ تلقائياً (لو حدث)

    @property
    def ok(self) -> bool:
        return self.success > 0


# ── أدوات داخلية (نفس المنطق المنقول من main.py) ───────────────────────────────

def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", name)


def _merge_videos(video_files: list[Path], out_file: Path) -> None:
    """دمج فيديوهات متعددة بـ ffmpeg concat (نسخ التيارات، بدون إعادة ترميز)."""
    import subprocess
    list_file = out_file.parent / "_concat_list.txt"
    lines = []
    for v in video_files:
        escaped = str(Path(v).resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines), encoding="utf-8")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(out_file),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)


def _cleanup(tmp_dir: Path) -> None:
    import shutil
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── المحرك الرئيسي ───────────────────────────────────────────────────────────────

def run_render(
    cfg: dict[str, Any],
    jobs: list[dict],
    root_path: Path,
    log,
    project_name: str | None = None,
    autosave: bool = True,
) -> RenderResult:
    """
    ينفّذ الرندر الكامل لدفعة *jobs* بإعدادات *cfg* جاهزة مسبقاً.

    لا يطرح أي سؤال تفاعلي — هذا مسؤولية الطبقة المستدعية (main.py في
    الرندر اليدوي، أو watch_mode.py في الرندر التلقائي). يعرض فقط
    رسائل CLI (section/ok/warn/err/progress) أثناء التنفيذ، تماماً
    كما كان يحدث سابقاً داخل main().

    *project_name* : اسم المشروع لاستخدامه في الحفظ التلقائي والنسخة
                      الاحتياطية. لو None، يُستنتج من اسم مجلد *root_path*.
    *autosave*      : لو True (الافتراضي)، يُحفَظ project.flipa تلقائياً
                      بعد أي رندر ناجح (نفس سلوك PROJECT_AUTOSAVE القديم).
    """
    fps = cfg["fps"]
    fmt = cfg["format"]

    proj_name = project_name or project_name_from_path(root_path)

    out_base = Path(DEFAULT_OUTPUT_DIR)
    out_base.mkdir(exist_ok=True)

    # ── v10: Auto Backup — حفظ الإعدادات + أي tmp_dirs موجودة *قبل* بدء الرندر
    # حتى لو حدث انقطاع مفاجئ أثناء الرندر، تبقى آخر الإعدادات المستخدمة
    # والفريمات الجزئية محفوظة لاستعادتها في التشغيل التالي.
    try:
        pre_render_tmp_dirs = find_pending_tmp_dirs()
        save_backup(
            proj_name,
            build_project_data(proj_name, str(root_path), cfg),
            pre_render_tmp_dirs,
        )
        log.info(f"تم حفظ نسخة احتياطية قبل بدء الرندر: {proj_name}")
    except OSError as exc:
        warn(f"Could not create backup: {exc}")
        log.warning(f"فشل إنشاء النسخة الاحتياطية: {exc}")

    section(f"Rendering batch  ({len(jobs)} scene(s))...")
    log.stage(f"بدء رندر الدفعة ({len(jobs)} مشهد)")

    stats = RenderStats()
    stats.start()

    success, failed = 0, 0
    rendered_files: list[Path] = []

    for idx, job in enumerate(jobs, 1):
        tag = yellow(" [compound]") if job["compound"] else ""
        print(f"\n  [{cyan(f'{idx}/{len(jobs)}')}]  {bold(job['name'])}{tag}")

        if job["compound"]:
            for layer in job["layers"]:
                print(f"       {dim('└─')} {layer['name']}  {dim(str(layer['count']) + ' frames')}")

        tmp_dir   = Path(f"{TMP_PREFIX}{job['name']}")
        safe_name = _safe_filename(job["name"])
        ext       = fmt
        out_file  = out_base / f"{safe_name}.{ext}"

        resumed_at = _resume_start(tmp_dir)
        if resumed_at > 0:
            print(f"  {cyan('↺')}  Resuming from frame {resumed_at}...")

        try:
            frame_t0 = stats.frame_start()
            # v10: ProgressBar حقيقي بنسبة% + سرعة + ETA. نسجّل scene_start_time
            # *قبل* استدعاء render_frames (قبل أي عمل فعلي)، ونمرّره لأول
            # ProgressBar يُنشأ — حتى لو الإنشاء نفسه كسول (lazy، يحدث فقط
            # عند أول استدعاء فعلي للـ callback بعد معالجة الفريم الأول)،
            # السرعة المحسوبة تبقى صحيحة لأنها تعتمد على وقت بدء العمل
            # الحقيقي، لا على وقت إنشاء الشريط نفسه.
            scene_start_time = time.monotonic()
            bar_holder: dict = {}

            def _on_progress(c: int, t: int) -> None:
                bar = bar_holder.get("bar")
                if bar is None or bar.total != max(t, 1):
                    bar = ProgressBar(total=t, label="frames", start_time=scene_start_time)
                    bar_holder["bar"] = bar
                bar.update(c)

            n_frames = render_frames(
                job["pngs"], cfg, tmp_dir,
                progress_cb=_on_progress,
                layer_pngs=job.get("layer_pngs"),
                scene_dir=job["path"],
            )
            if "bar" in bar_holder:
                bar_holder["bar"].finish()

            # نحسب وقت معالجة المشهد كمتوسط موزّع على فريماته
            stats.total_frames += max(n_frames - 1, 0)  # frame_end أدناه يضيف 1
            stats.frame_end(frame_t0, from_cache=False, ai_generated=cfg.get("ai_enabled", False))

            export(cfg, tmp_dir, str(out_file))

            # ── v10: Audio Support — دمج الصوت على كل مشهد منفرد ────────────
            if (cfg.get("audio_enabled") and fmt == "mp4"
                    and cfg.get("audio_sync_mode") == AUDIO_SYNC_PER_SCENE):
                try:
                    audio_out = out_base / f"{safe_name}_audio.{ext}"
                    mux_audio(
                        out_file, cfg["audio_file"], audio_out,
                        mode=cfg.get("audio_mix_mode", DEFAULT_AUDIO_MIX_MODE),
                    )
                    out_file.unlink(missing_ok=True)
                    audio_out.rename(out_file)
                    ok(f"Audio added: {out_file}")
                    log.info(f"تم دمج الصوت مع المشهد '{job['name']}'")
                except Exception as exc:
                    warn(f"Could not add audio to this scene: {exc}")
                    log.warning(f"فشل دمج الصوت للمشهد '{job['name']}': {exc}")

            ok(f"Saved: {out_file}")
            rendered_files.append(out_file)
            success += 1
            stats.scene_done(True)
            log.info(f"نجح رندر '{job['name']}' → {out_file}")

        except Exception as exc:
            err_detailed(exc, context=f"Scene '{job['name']}'")
            failed += 1
            stats.scene_done(False)
            log.error(f"فشل رندر '{job['name']}'", exc=exc)

        finally:
            _cleanup(tmp_dir)

    # ── دمج MP4 فقط ──────────────────────────────────────────────────────────
    final_video: Path | None = None
    if fmt == "mp4" and len(rendered_files) >= 2:
        section("Merging all scenes into one video")
        full_out = out_base / "FULL_VIDEO.mp4"
        try:
            _merge_videos(rendered_files, full_out)
            ok(f"Full video: {full_out}")
            log.info(f"تم دمج {len(rendered_files)} فيديو → {full_out}")
            final_video = full_out
        except Exception as exc:
            err_detailed(exc, context="Video merge")
            log.error("فشل دمج الفيديوهات", exc=exc)
    elif fmt == "mp4" and len(rendered_files) == 1:
        final_video = rendered_files[0]

    # ── v10: Plugins — معالجات فيديو (VideoEffectPlugin) على الفيديو النهائي،
    # بعد الدمج الكامل وقبل دمج الصوت — تماماً مثل filmgrain.py
    active_video_effects = cfg.get("active_video_effects") or []
    if active_video_effects and fmt == "mp4" and final_video and final_video.exists():
        for plugin in active_video_effects:
            try:
                effect_out = out_base / f"{final_video.stem}_fx.mp4"
                plugin.apply(final_video, effect_out, **plugin.params)
                final_video.unlink(missing_ok=True)
                effect_out.rename(final_video)
                ok(f"Video effect applied: {plugin.name}")
                log.info(f"تم تطبيق مؤثر الإضافة '{plugin.name}' على الفيديو النهائي")
            except Exception as exc:
                warn(f"Plugin '{plugin.name}' failed and was skipped: {exc}")
                log.warning(f"فشل مؤثر الإضافة '{plugin.name}' وتم تجاوزه: {exc}")

    # ── v10: Audio Support — دمج الصوت على الفيديو النهائي (full_video_only فقط) ─
    # لو sync_mode = per_scene، كل مشهد منفرد يحتوي الصوت مسبقاً من الخطوة أعلاه،
    # و _merge_videos تنسخ الـ streams (-c copy) فتحافظ عليه تلقائياً — فلا
    # حاجة لدمج إضافي هنا، بل سيُكرَّر الصوت خطأً لو فعلنا ذلك مرة ثانية.
    if (cfg.get("audio_enabled") and fmt == "mp4" and final_video and final_video.exists()
            and cfg.get("audio_sync_mode", AUDIO_SYNC_FULL_VIDEO_ONLY) == AUDIO_SYNC_FULL_VIDEO_ONLY):
        try:
            audio_final = out_base / f"{final_video.stem}_audio.mp4"
            mux_audio(
                final_video, cfg["audio_file"], audio_final,
                mode=cfg.get("audio_mix_mode", DEFAULT_AUDIO_MIX_MODE),
            )
            final_video.unlink(missing_ok=True)
            audio_final.rename(final_video)
            ok(f"Audio added to final video: {final_video}")
            log.info(f"تم دمج الصوت مع الفيديو النهائي: {final_video}")
        except Exception as exc:
            warn(f"Could not add audio to final video: {exc}")
            log.warning(f"فشل دمج الصوت مع الفيديو النهائي: {exc}")

    # ── v10: Render Statistics Report ───────────────────────────────────────────
    stats.finish()
    section("Summary")

    report_output = None
    if fmt == "mp4" and len(rendered_files) >= 2:
        candidate = out_base / "FULL_VIDEO.mp4"
        if candidate.exists():
            report_output = candidate
    elif rendered_files:
        report_output = rendered_files[0]

    res_label = f"{cfg['w']}x{cfg['h']}"
    print(stats.report(fps=fps, resolution=res_label, output_path=report_output))

    if cfg.get("audio_enabled"):
        audio_name = Path(cfg.get("audio_file", "")).name
        sync_label = ("every scene + merged" if cfg.get("audio_sync_mode") == AUDIO_SYNC_PER_SCENE
                      else "merged video only")
        print(dim(f"  🎵 Audio: {audio_name}  ({sync_label})"))

    log.info(f"تقرير الرندر النهائي: {stats.as_dict()}")

    # ── v10: Project File — حفظ تلقائي بعد رندر ناجح ──────────────────────────
    saved_project_path: Path | None = None
    if autosave and PROJECT_AUTOSAVE and success > 0:
        try:
            saved_project_path = save_project(proj_name, str(root_path), cfg)
            print()
            ok(f"Project settings saved: {saved_project_path}")
            log.info(f"تم حفظ المشروع تلقائياً: {saved_project_path}")
        except OSError as exc:
            warn(f"Could not save project file: {exc}")
            log.warning(f"فشل حفظ ملف المشروع: {exc}")

    # ── v10: Auto Backup — لو نجح الرندر بالكامل (لا فشل) نحذف النسخة الاحتياطية
    # (لا حاجة للاستعادة بعد اكتمال المشروع بنجاح كامل بلا أي انقطاع)
    if success > 0 and failed == 0:
        try:
            clear_backup(proj_name)
        except OSError:
            pass

    return RenderResult(
        success=success,
        failed=failed,
        rendered_files=rendered_files,
        final_video=final_video,
        stats=stats,
        project_path=saved_project_path,
    )
