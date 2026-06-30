"""
FlipaRender v10 — Entry point

v10 changes:
  - Logging           : جلسة سجل واحدة لكل تشغيل، عبر utils.logger
  - Memory Optimizer   : سؤال عن حجم دفعة الرندر (Chunk Size) قبل البدء
  - Smart FPS          : اقتراح FPS تلقائي بناءً على تحليل Exposure Sheet
  - Render Statistics  : تقرير كامل في نهاية الرندر (عبر utils.stats.RenderStats)
  - Motion Blur        : تمويه اختياري بين الفريمات المتتالية
  - Scene Preview Grid : قائمة منظَّمة + Contact Sheet بصري بعد اختيار الدفعة مباشرة

v9 changes (محفوظة بالكامل):
  - Scene sequencing : المستخدم يرتّب المشاهد يدوياً قبل الرندر
  - Metadata         : إدخال title / artist يُكتب داخل MP4
  - GIF options      : اختيار عدد الألوان وعرض GIF و loop count
"""

import shutil
import sys
from pathlib import Path

from config import (
    APP_NAME, APP_VERSION,
    GRADES, RESOLUTIONS, OUTPUT_FORMATS,
    DEFAULT_FPS, DEFAULT_CRF, DEFAULT_GRADE, DEFAULT_RESOLUTION,
    DEFAULT_OUTPUT_DIR, DEFAULT_OUTPUT_FORMAT,
    METADATA_DEFAULTS,
    GIF_COLORS_OPTIONS, DEFAULT_GIF_COLORS, DEFAULT_GIF_MAX_WIDTH,
    RENDER_CHUNK_SIZE, RAM_PROFILE_DEFAULT, LOG_KEEP_LAST, LOG_VERBOSE_DEFAULT,
    PROJECTS_DIR,
    AUDIO_SYNC_FULL_VIDEO_ONLY, AUDIO_SYNC_PER_SCENE,
    DEFAULT_AUDIO_SYNC_MODE, DEFAULT_AUDIO_MIX_MODE,
)
from core.scanner  import scan_jobs
from core.security import safe_path
from render.frames import preview_frame
from render.motion_blur import estimate_recommended_strength, MIN_STRENGTH, MAX_STRENGTH
from core.xsheet   import load_xsheet, generate_sample_timing
from core.fps_advisor import analyze_batch as fps_analyze_batch
from core.preview_grid import build_preview_grid, render_contact_sheet
from core.project_file import (
    load_project, list_projects, project_name_from_path,
)
from core.audio import (
    list_audio_files, describe_audio_track, format_duration,
)
from core.backup import (
    has_backup, load_backup_info, load_backup_project_data, restore_tmp_dirs,
)
from core.export_presets import (
    list_all_presets, get_preset_data, apply_preset_to_cfg,
    save_custom_preset,
)
from core.plugins import discover_image_filters, discover_video_effects
from core.render_engine import run_render
from utils.memory import auto_chunk_size, detect_ram_profile
from utils.logger  import new_session, get_logger, cleanup_old_logs, current_log_path
from ui.cli import (
    banner, section, ok, warn, err, err_detailed,
    ask, ask_int, ask_choice,
    bold, cyan, dim, yellow,
)



# ── helpers ───────────────────────────────────────────────────────────────────

def _hint(text: str) -> None:
    print(dim(f"  ℹ  {text}"))


def _pick_fps(jobs: list[dict] | None = None, saved_fps: int | None = None) -> int:
    section("Frame Rate  (FPS)")
    _hint("Number of images displayed per second of video.")
    _hint("Traditional animation: 12 — Cinema: 24 — Smooth motion: 30")
    print()
    print(f"  {dim('12')}  ← Classic animation  (smaller file size)")
    print(f"  {dim('24')}  ← Natural motion      (cinematic quality)")
    print(f"  {dim('30')}  ← High smoothness      (games / motion)")
    print()

    suggested_default = saved_fps if saved_fps is not None else DEFAULT_FPS

    # ── v10: Smart FPS Detection ──────────────────────────────────────────────
    if jobs:
        suggestion = fps_analyze_batch(jobs)
        print(f"  {cyan('🧠 اقتراح ذكي')}  {suggestion.reason}")
        print(f"     {dim(f'الثقة: {suggestion.confidence}')}")
        print()
        if ask_choice(f"استخدام الاقتراح ({suggestion.fps} fps)?", ["yes", "no"], "yes") == "yes":
            ok(f"Video speed: {suggestion.fps} frames/second (smart)")
            return suggestion.fps
        suggested_default = suggestion.fps

    fps = ask_int("Enter FPS", suggested_default, min_value=1, max_value=60)
    ok(f"Video speed: {fps} frames/second")
    return fps


def _pick_crf(default_crf: int = DEFAULT_CRF) -> int:
    section("Video Quality  (CRF)")
    _hint("The lower the number, the higher the quality and the larger the file size.")
    _hint("Ideal value for animation: between 18 and 23")
    print()
    crf = ask_int("Enter CRF", default_crf, min_value=15, max_value=35)
    ok(f"Encoding quality: {crf}")
    return crf


def _pick_resolution(default_key: str = DEFAULT_RESOLUTION) -> dict:
    section("Video Resolution")
    print()
    for key, (w, h, label) in RESOLUTIONS.items():
        marker = bold("●") if key == default_key else dim("○")
        print(f"  {marker}  {key:<4}  {label:<18} {dim(f'{w}x{h}')}")
    print()
    key = ask_choice("Choose resolution", list(RESOLUTIONS.keys()), default_key)
    w, h, label = RESOLUTIONS[key]
    ok(f"Resolution: {label}  ({w}x{h})")
    return {"w": w, "h": h, "resolution_key": key}


def _pick_grade(default_key: str = DEFAULT_GRADE) -> dict:
    section("Color Grading")
    print()
    GRADE_DESC = {
        "none":      "No adjustments",
        "anime":     "Vivid and sharp colors",
        "cinematic": "Warm cinematic tone",
        "noir":      "Black and white",
        "warm":      "Warm golden lighting",
        "cold":      "Cool silver tone",
        "vintage":   "Old-look faded colors",
    }
    for key, g in GRADES.items():
        marker = bold("●") if key == default_key else dim("○")
        print(f"  {marker}  {key:<10}  {dim(GRADE_DESC.get(key, ''))}")
    print()
    key   = ask_choice("Choose filter", list(GRADES.keys()), default_key)
    grade = GRADES[key]
    ok(f"Filter: {grade['name']}")
    return grade, key


def _pick_format() -> str:
    section("Output Format")
    _hint("MP4 = video file  |  GIF = animated image (no ffmpeg needed)")
    print()
    for key, desc in OUTPUT_FORMATS.items():
        marker = bold("●") if key == DEFAULT_OUTPUT_FORMAT else dim("○")
        print(f"  {marker}  {key:<5}  {dim(desc)}")
    print()
    fmt = ask_choice("Choose format", list(OUTPUT_FORMATS.keys()), DEFAULT_OUTPUT_FORMAT)
    ok(f"Output format: {fmt.upper()}")
    return fmt


# ── v10: Export Presets ───────────────────────────────────────────────────────

def _pick_export_preset() -> dict | None:
    """
    يعرض قائمة البريسيتس الجاهزة (YouTube/TikTok/Instagram/Telegram/4K)
    بالإضافة لأي presets مخصصة محفوظة، ويسأل المستخدم إن أراد استخدام
    أحدها مباشرة — في هذه الحالة تُطبَّق إعداداته (resolution/fps/crf/
    format) فوراً وتُتخطّى أسئلة هذه الإعدادات بالكامل.

    يعيد dict بيانات الـ preset المختار، أو None لو رفض المستخدم (في هذه
    الحالة يستمر التدفق العادي بالأسئلة اليدوية كما كان).
    """
    presets = list_all_presets()
    if not presets:
        return None

    section("Export Presets")
    _hint("Ready-made settings for popular platforms — applied instantly, no extra questions.")
    print()

    for i, p in enumerate(presets, 1):
        tag = dim("[built-in]") if p.builtin else dim("[custom]")
        print(f"  {cyan(f'{i}.')}  {bold(p.name)}  {tag}")
        if p.description:
            print(f"      {dim(p.description)}")
    print()

    use_preset = ask_choice("Use one of these presets?", ["yes", "no"], "no") == "yes"
    if not use_preset:
        return None

    idx = ask_int("Choose preset number", 1, min_value=1, max_value=len(presets))
    chosen = presets[idx - 1]
    data = get_preset_data(chosen.key)

    if data is None:
        warn(f"Preset '{chosen.name}' could not be loaded — falling back to manual settings.")
        return None

    summary = f"res={data.get('resolution_key')}  fps={data.get('fps')}  crf={data.get('crf')}  fmt={data.get('format')}"
    ok(f"Preset applied: {chosen.name}  ({summary})")
    return data


def _offer_save_as_preset(cfg: dict) -> None:
    """
    بعد اكتمال الإعدادات اليدوية، يسأل المستخدم إن أراد حفظها كـ preset
    مخصص لإعادة استخدامها لاحقاً على مشاريع أخرى دون تكرار الأسئلة.
    """
    section("Save as Custom Preset")
    save_it = ask_choice("Save these export settings as a reusable preset?", ["no", "yes"], "no") == "yes"
    if not save_it:
        return

    name = ask("Preset name", "My Preset")
    try:
        path = save_custom_preset(name, cfg)
        ok(f"Preset saved: {path}")
    except OSError as exc:
        warn(f"Could not save preset: {exc}")


# ── v10: Memory Optimizer ───────────────────────────────────────────────────────

def _pick_chunk_size(jobs: list[dict]) -> int:
    """
    يسأل المستخدم عن حجم دفعة الرندر (Chunk Size)، مع اقتراح تلقائي
    حسب عدد الفريمات الكلي ومستوى ذاكرة الجهاز المكتشف.
    """
    section("Memory Optimizer  (Render in Chunks)")
    _hint("Frames are processed in batches to avoid loading everything into RAM.")
    _hint("Larger projects on phones benefit from smaller chunk sizes.")
    print()

    total_frames = sum(job.get("count", 0) for job in jobs)
    ram_profile  = detect_ram_profile() if RAM_PROFILE_DEFAULT == "auto" else RAM_PROFILE_DEFAULT
    suggested    = auto_chunk_size(total_frames, ram_profile)

    print(f"  {dim(f'Total frames (approx): {total_frames}')}")
    print(f"  {dim(f'Detected RAM profile : {ram_profile}')}")
    print(f"  {cyan('🧠 اقتراح ذكي')}  حجم الدفعة: {suggested} فريم")
    print()

    chunk_size = ask_int("Render chunk size", suggested, min_value=5, max_value=1000)
    ok(f"Chunk size: {chunk_size} frame(s) per batch")
    return chunk_size


# ── v10: Motion Blur ─────────────────────────────────────────────────────────

def _pick_motion_blur(fps: int) -> tuple[bool, float]:
    """
    يسأل المستخدم إن أراد تفعيل Motion Blur، ويقترح شدة افتراضية حسب الـ FPS
    المختار مسبقاً (fps منخفض → بلر أقوى لتحسين السلاسة).
    """
    section("Motion Blur  (optional)")
    _hint("Blends each frame slightly with the previous one for smoother motion.")
    _hint("Recommended especially at low FPS (12).")
    print()

    enabled_raw = ask_choice("Enable motion blur?", ["no", "yes"], "no")
    if enabled_raw == "no":
        return False, 0.0

    suggested = estimate_recommended_strength(fps)
    print()
    print(f"  {cyan('🧠 اقتراح ذكي')}  Strength: {suggested:.2f}  (based on {fps} fps)")
    print(f"  {dim(f'Range: {MIN_STRENGTH:.1f} (off) — {MAX_STRENGTH:.1f} (strong)')}")
    print()

    while True:
        raw = ask("Blur strength", f"{suggested:.2f}")
        try:
            strength = float(raw)
        except ValueError:
            err("Please enter a number.")
            continue
        if not (MIN_STRENGTH <= strength <= MAX_STRENGTH):
            err(f"Must be between {MIN_STRENGTH} and {MAX_STRENGTH}.")
            continue
        break

    ok(f"Motion blur: enabled  (strength={strength:.2f})")
    return True, strength


# ── v10: Plugins ──────────────────────────────────────────────────────────────

def _pick_plugins() -> tuple[list, list]:
    """
    يكتشف كل الإضافات الموجودة في plugins/ (فلاتر صورة + معالجات فيديو)
    ويسأل المستخدم أيها يريد تفعيلها لهذا الرندر، مع إمكانية تعديل
    المعاملات (params) لكل إضافة مُفعَّلة.

    يعيد (active_image_filters, active_video_effects) — قوائم instances
    جاهزة للاستخدام المباشر، فاضية لو لا توجد إضافات أو رفضها المستخدم.
    """
    filters, filter_errors = discover_image_filters()
    effects, effect_errors = discover_video_effects()

    # كل ملف تالف يُكتشَف من كلا الاستدعاءين (الصورة والفيديو) لأن كلاهما
    # يفحص كل الملفات بحثاً عن أي نوع كلاس — نزيل التكرار قبل العرض.
    seen_paths = set()
    unique_errors = []
    for path, msg in filter_errors + effect_errors:
        if path not in seen_paths:
            seen_paths.add(path)
            unique_errors.append((path, msg))

    for path, msg in unique_errors:
        warn(f"Plugin failed to load: {path.name}  ({msg})")

    if not filters and not effects:
        return [], []

    section("Plugins")
    _hint("Extra filters and effects found in plugins/ — optional, none applied by default.")
    print()

    all_plugins = [("filter", p) for p in filters] + [("effect", p) for p in effects]
    for i, (kind, p) in enumerate(all_plugins, 1):
        tag = dim("[image filter]") if kind == "filter" else dim("[video effect]")
        print(f"  {cyan(f'{i}.')}  {bold(p.name)}  {tag}")
        if p.description:
            print(f"      {dim(p.description)}")
    print()

    use_plugins = ask_choice("Apply any plugins to this render?", ["no", "yes"], "no") == "yes"
    if not use_plugins:
        return [], []

    _hint("Enter numbers separated by commas (e.g. 1,3), or leave blank for none.")
    raw = ask("Plugin numbers", "")
    if not raw.strip():
        return [], []

    chosen_image_filters: list = []
    chosen_video_effects: list = []

    for token in raw.split(","):
        token = token.strip()
        if not token.isdigit():
            continue
        idx = int(token)
        if not (1 <= idx <= len(all_plugins)):
            warn(f"Skipping invalid plugin number: {idx}")
            continue
        kind, plugin = all_plugins[idx - 1]

        # نسأل عن تعديل المعاملات الافتراضية (اختياري، Enter للقبول كما هي)
        if plugin.params:
            print()
            print(f"  {bold(plugin.name)}  {dim('— default parameters: ' + str(plugin.params))}")
            customize = ask_choice(f"Customize '{plugin.name}' parameters?", ["no", "yes"], "no") == "yes"
            if customize:
                for key, default_val in plugin.params.items():
                    raw_val = ask(f"  {key}", str(default_val))
                    try:
                        # نحافظ على نوع القيمة الافتراضية (float/int/str)
                        plugin.params[key] = type(default_val)(raw_val)
                    except (ValueError, TypeError):
                        warn(f"Invalid value for '{key}' — keeping default ({default_val}).")

        if kind == "filter":
            chosen_image_filters.append(plugin)
        else:
            chosen_video_effects.append(plugin)

    if chosen_image_filters or chosen_video_effects:
        names = [p.name for p in chosen_image_filters + chosen_video_effects]
        ok(f"Plugins enabled: {', '.join(names)}")

    return chosen_image_filters, chosen_video_effects


# ── v10: Audio Support ────────────────────────────────────────────────────────

def _pick_audio(root_path: Path) -> dict:
    """
    يبحث عن ملفات صوت داخل audio/ بمجلد المشروع، ويسأل المستخدم عن
    الملف المطلوب (لو متعدد) وطريقة المزامنة ونطاق التطبيق.

    يعيد dict فاضي {} لو لا يوجد صوت أو المستخدم رفض استخدامه — في هذه
    الحالة لا يتغيّر أي سلوك رندر قديم.
    """
    files = list_audio_files(root_path)
    if not files:
        return {}

    section("Audio Support")
    _hint(f"Found {len(files)} audio file(s) in 'audio/'.")
    print()

    for i, f in enumerate(files, 1):
        track = describe_audio_track(f)
        print(f"  {cyan(f'{i}.')}  {bold(f.name)}  "
              f"{dim(f'({format_duration(track.duration_s)}, {track.size_mb:.1f} MB)')}")
    print()

    use_audio = ask_choice("Add audio to the rendered video?", ["yes", "no"], "yes") == "yes"
    if not use_audio:
        return {}

    if len(files) == 1:
        chosen = files[0]
    else:
        idx = ask_int("Choose audio file number", 1, min_value=1, max_value=len(files))
        chosen = files[idx - 1]

    print()
    section("Audio Sync")
    print(f"  {dim('full   ')}  ← Audio only on the final merged video")
    print(f"  {dim('scenes ')}  ← Audio on every scene video AND the merged video")
    print()
    sync_raw = ask_choice("Apply audio to", ["full", "scenes"], "full")
    sync_mode = AUDIO_SYNC_PER_SCENE if sync_raw == "scenes" else AUDIO_SYNC_FULL_VIDEO_ONLY

    print()
    section("Audio / Video Length Matching")
    print(f"  {dim('match_video')}  ← Stop at the end of the video (trims audio if longer)")
    print(f"  {dim('match_audio')}  ← Extend video (hold last frame) to match full audio length")
    print(f"  {dim('audio_loop ')}  ← Loop audio repeatedly until the video ends")
    print()
    mix_mode = ask_choice(
        "Choose matching mode",
        ["match_video", "match_audio", "audio_loop"],
        DEFAULT_AUDIO_MIX_MODE,
    )

    ok(f"Audio: {chosen.name}  |  Sync: {sync_mode}  |  Mode: {mix_mode}")
    return {
        "audio_enabled":  True,
        "audio_file":     str(chosen),
        "audio_sync_mode": sync_mode,
        "audio_mix_mode":  mix_mode,
    }


# ── v9: Metadata ──────────────────────────────────────────────────────────────

def _pick_metadata() -> dict:
    """
    يطلب من المستخدم إدخال metadata تُكتب داخل MP4.
    الحقول الفارغة تُتجاهل.
    """
    section("Film Metadata  (MP4 only)")
    _hint("This information is embedded inside the MP4 file.")
    _hint("Leave blank to skip any field.")
    print()

    title   = ask("Film title",  METADATA_DEFAULTS["title"])
    artist  = ask("Director / Artist", METADATA_DEFAULTS["artist"])
    comment = ask("Comment", METADATA_DEFAULTS["comment"])

    metadata = {
        "title":   title.strip(),
        "artist":  artist.strip(),
        "comment": comment.strip(),
    }
    ok("Metadata saved.")
    return metadata


# ── v9: GIF options ───────────────────────────────────────────────────────────

def _pick_gif_options() -> dict:
    """
    يطلب خيارات GIF الإضافية: عدد الألوان، أقصى عرض، عدد التكرارات.
    """
    section("GIF Options")
    print()

    print(f"  {'Colors':}")
    for key, desc in GIF_COLORS_OPTIONS.items():
        marker = bold("●") if int(key) == DEFAULT_GIF_COLORS else dim("○")
        print(f"    {marker}  {desc}")
    print()
    colors_key = ask_choice(
        "Number of colors",
        list(GIF_COLORS_OPTIONS.keys()),
        str(DEFAULT_GIF_COLORS),
    )
    colors = int(colors_key)

    print()
    _hint(f"Max width in pixels (default: {DEFAULT_GIF_MAX_WIDTH})")
    max_w = ask_int("Max width", DEFAULT_GIF_MAX_WIDTH, min_value=200, max_value=1920)

    print()
    _hint("Loop count: 0 = infinite loop, 1 = play once, 3 = play 3 times")
    loop = ask_int("Loop count", 0, min_value=0, max_value=100)

    ok(f"GIF: {colors} colors  |  max {max_w}px  |  loop={loop}")
    return {
        "gif_colors":    colors,
        "gif_max_width": max_w,
        "gif_loop":      loop,
    }


# ── v8: Batch jobs ────────────────────────────────────────────────────────────

def _pick_batch(jobs: list[dict]) -> list[dict]:
    section(f"Batch Selection  ({len(jobs)} scenes found)")
    _hint("Process all scenes, or pick specific ones.")
    print()

    choice = ask_choice(
        "Process which scenes?",
        ["all", "select"],
        "all",
    )

    if choice == "all":
        ok(f"All {len(jobs)} scenes queued.")
        return jobs

    print()
    print("  Enter scene numbers separated by commas  (e.g. 1,3,5)")
    for i, job in enumerate(jobs, 1):
        tag   = yellow(" [compound]") if job["compound"] else ""
        count = job['count']
        print(f"    {cyan(str(i))}.  {job['name']}  {dim(f'({count} frames)')}{tag}")
    print()

    raw = ask("Scene numbers", ",".join(str(i) for i in range(1, len(jobs) + 1)))

    selected: list[dict] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(jobs):
                selected.append(jobs[idx])

    if not selected:
        warn("No valid selection — processing all scenes.")
        return jobs

    ok(f"{len(selected)} scene(s) queued.")
    return selected


# ── v9: Scene sequencing ──────────────────────────────────────────────────────

def _pick_sequence(jobs: list[dict]) -> list[dict]:
    """
    يعرض المشاهد المختارة ويتيح للمستخدم إعادة ترتيبها.

    المستخدم يدخل أرقام المشاهد بالترتيب الذي يريده،
    مثلاً: "3,1,2" لتشغيل المشهد 3 أولاً ثم 1 ثم 2.

    الضغط على Enter بدون إدخال يبقي الترتيب الحالي.
    """
    section(f"Scene Sequence  ({len(jobs)} scenes)")
    _hint("Set the render order. Press Enter to keep the current order.")
    print()

    for i, job in enumerate(jobs, 1):
        tag   = yellow(" [compound]") if job["compound"] else ""
        count = job['count']
        print(f"    {cyan(str(i))}.  {bold(job['name'])}  {dim(f'({count} frames)')}{tag}")

    print()
    raw = ask(
        "New order (e.g. 3,1,2)",
        ",".join(str(i) for i in range(1, len(jobs) + 1)),
    )

    reordered: list[dict] = []
    seen: set[int] = set()

    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(jobs) and idx not in seen:
                reordered.append(jobs[idx])
                seen.add(idx)

    for idx, job in enumerate(jobs):
        if idx not in seen:
            reordered.append(job)
            warn(f"Scene '{job['name']}' not in sequence — appended at end.")

    if reordered != jobs:
        ok("New sequence: " + " → ".join(j["name"] for j in reordered))
    else:
        ok("Order unchanged.")

    return reordered


# ── v8: AI settings ───────────────────────────────────────────────────────────

def _pick_ai(jobs: list[dict], cfg_preview: dict) -> tuple[bool, int, str, bool]:
    section("AI In-betweening  (Generate intermediate frames)")
    _hint("Generates additional frames between each two images to smooth motion.")
    print()

    ai_raw     = ask_choice("Enable AI?", ["no", "yes"], "no")
    ai_enabled = ai_raw == "yes"

    if not ai_enabled:
        return False, 1, "smart", False

    suggested = 1
    try:
        from PIL import Image
        from ai.inbetween import suggest_steps
        job = jobs[0]
        if len(job["pngs"]) >= 2:
            img1 = Image.open(job["pngs"][0])
            img2 = Image.open(job["pngs"][1])
            suggested = suggest_steps(img1, img2)
            print()
            print(f"  {cyan('Auto-suggestion')}  based on motion detected: {bold(str(suggested))} intermediate frame(s)")
    except Exception:
        pass

    print()
    section("Number of Intermediate Frames")
    ai_steps = ask_int(
        "Number of intermediate frames",
        suggested,
        min_value=1,
        max_value=4,
    )

    print()
    section("Generation Method  (Blend Mode)")

    # ── v10: AI Auto Mode — تحليل تلقائي لاختيار أفضل وضع مع توضيح السبب ──────
    # نأخذ عينة فريمات من كل مشهد مختار (وليس أول مشهد فقط) لاقتراح أكثر تمثيلاً
    # للدفعة كاملة — كل مشهد يُحلَّل بأزواجه الداخلية فقط، فلا تُقارَن فريمات
    # من مشاهد مختلفة ببعضها (تجنّباً لقفزات وهمية بين مشاهد غير متصلة).
    auto_suggestion = None
    try:
        from PIL import Image
        from ai.inbetween import suggest_mode
        sequences = []
        for job in jobs:
            paths = job["pngs"][:4]   # حتى 4 فريمات من كل مشهد
            if len(paths) >= 2:
                sequences.append([Image.open(p) for p in paths])
        if sequences:
            auto_suggestion = suggest_mode(sequences)
    except Exception:
        auto_suggestion = None

    if auto_suggestion:
        print(f"  {cyan('🧠 AI Auto Mode')}  {bold(auto_suggestion.mode)}")
        print(f"     {dim(auto_suggestion.reason)}")
        print()
        use_auto = ask_choice(
            f"استخدام الاختيار التلقائي ({auto_suggestion.mode})?", ["yes", "no"], "yes"
        ) == "yes"
        if use_auto:
            ai_mode = auto_suggestion.mode
            ok(f"Mode: {ai_mode}  (AI Auto Mode)")
            print()
            section("AI Cache  (speed up repeated renders)")
            _hint("Saves optical_flow results to disk — skips recomputation for same frame pairs.")
            cache_raw = ask_choice("Enable AI cache?", ["yes", "no"], "yes")
            ai_cache  = cache_raw == "yes"
            ok(f"AI: {ai_steps} frame(s)  |  Mode: {ai_mode}  |  Cache: {'on' if ai_cache else 'off'}")
            return True, ai_steps, ai_mode, ai_cache
        print()

    print(f"  {dim('optical_flow')}  ← Best quality, slower")
    print(f"  {dim('hybrid     ')}  ← optical_flow for motion + linear for background")
    print(f"  {dim('smart      ')}  ← Detects motion areas only")
    print(f"  {dim('linear     ')}  ← Simple blend, fastest")
    print()
    ai_mode = ask_choice(
        "Choose method",
        ["optical_flow", "hybrid", "smart", "linear"],
        auto_suggestion.mode if auto_suggestion else "hybrid",
    )

    print()
    section("AI Cache  (speed up repeated renders)")
    _hint("Saves optical_flow results to disk — skips recomputation for same frame pairs.")
    cache_raw = ask_choice("Enable AI cache?", ["yes", "no"], "yes")
    ai_cache  = cache_raw == "yes"

    ok(f"AI: {ai_steps} frame(s)  |  Mode: {ai_mode}  |  Cache: {'on' if ai_cache else 'off'}")
    return True, ai_steps, ai_mode, ai_cache


# ── v10: Scene Preview Grid ──────────────────────────────────────────────────

def _show_preview_grid(jobs: list[dict]) -> None:
    """
    يُعرض مباشرة بعد اختيار الدفعة (batch) — قائمة منظَّمة لكل مشهد مختار
    + صورة Contact Sheet اختيارية تجمع thumbnail من كل مشهد.
    """
    section("Scene Preview Grid")
    _hint("Quick review of the scenes you selected, before configuring render settings.")
    print()
    print(build_preview_grid(jobs))
    print()

    if ask_choice("Generate a visual contact sheet image?", ["no", "yes"], "no") == "yes":
        # نستخدم إعدادات معاينة سريعة وخفيفة (دقة hd ثابتة، بدون فلتر) — لا تؤثر
        # على إعدادات الرندر الفعلية التي يختارها المستخدم لاحقاً
        from config import RESOLUTIONS, GRADES
        preview_cfg = {
            "w": RESOLUTIONS["hd"][0] // 4,
            "h": RESOLUTIONS["hd"][1] // 4,
            "grade": GRADES["none"],
        }
        try:
            path = render_contact_sheet(jobs, preview_cfg)
            if path:
                ok(f"Contact sheet saved: {path}")
                try:
                    from PIL import Image
                    Image.open(path).show()
                except Exception:
                    pass
            else:
                warn("Could not generate contact sheet for these scenes.")
        except Exception as exc:
            warn(f"Contact sheet generation failed: {exc}")


# ── Preview ───────────────────────────────────────────────────────────────────

def _do_preview(jobs: list[dict], cfg: dict) -> None:
    section("Preview  (first frame)")
    _hint("Shows the first frame with your selected grade and resolution.")
    print()

    job = jobs[0]
    if job["compound"]:
        first_layers = [layer[0] for layer in job["layer_pngs"]]
        img = preview_frame(first_layers[0], cfg, layer_paths=first_layers)
    else:
        img = preview_frame(job["pngs"][0], cfg)

    try:
        img.show()
        ok("Preview displayed — close the window to continue.")
    except Exception as exc:
        warn(f"Could not open preview: {exc}")
        fallback = Path(DEFAULT_OUTPUT_DIR) / "_preview.jpg"
        fallback.parent.mkdir(exist_ok=True)
        img.save(fallback, quality=90)
        ok(f"Preview saved to: {fallback}")


# ── v10: Auto Backup ───────────────────────────────────────────────────────────

def _check_pending_backup(root_path: Path) -> dict | None:
    """
    يفحص وجود نسخة احتياطية لرندر متوقَّف من تشغيل سابق منقطع (Crash أو
    إيقاف مفاجئ) لهذا المشروع، ويسأل المستخدم إن أراد استعادتها.

    يعيد project_data المستعادة (dict) لو وافق المستخدم على الاستعادة،
    وإلا None — في كل الأحوال لا يوقف التشغيل العادي.
    """
    project_name = project_name_from_path(root_path)
    if not has_backup(project_name):
        return None

    info = load_backup_info(project_name)
    if info is None:
        return None

    section("Pending Backup Found")
    warn(f"A backup from an interrupted session was found for '{project_name}'.")
    print(f"  {dim(f'Saved at: {info.saved_at}')}")
    if info.tmp_scenes:
        scenes_label = ", ".join(info.tmp_scenes)
        print(f"  {dim(f'Partial render data available for: {scenes_label}')}")
    print()

    if ask_choice("Restore this backup and continue?", ["yes", "no"], "yes") == "no":
        return None

    restored = restore_tmp_dirs(project_name)
    if restored:
        ok(f"Restored partial render data for: {', '.join(restored)}")
    else:
        ok("Backup settings restored (no partial render data to resume).")

    return load_backup_project_data(project_name)


# ── v10: Project File System ──────────────────────────────────────────────────

def _pick_saved_project(root_path: Path) -> tuple[dict | None, bool]:
    """
    يبحث عن مشاريع محفوظة (.flipa) ويسأل المستخدم إن أراد تحميل أحدها.

    يعيد (project_data أو None, quick_mode):
        project_data : محتوى ملف .flipa المحمَّل، أو None لو لم يُحمَّل شيء
        quick_mode   : True لو طلب المستخدم استخدام نفس الإعدادات مباشرة
                       بدون مراجعة كل سؤال من جديد
    """
    projects = list_projects()
    if not projects:
        return None, False

    section("Saved Projects")
    _hint(f"Found {len(projects)} saved project file(s) in '{PROJECTS_DIR}/'.")
    print()

    # نقترح أول من اسمه يطابق مجلد المصدر الحالي، وإلا أحدث مشروع محفوظ
    suggested_name = project_name_from_path(root_path)
    match = next((p for p in projects if p.name == suggested_name), projects[0])

    for p in projects[:8]:
        marker = bold("●") if p.name == match.name else dim("○")
        print(f"  {marker}  {p.name:<20} {dim(f'saved {p.saved_at}')}")
    print()

    if ask_choice(f"Load saved project '{match.name}'?", ["no", "yes"], "no") == "no":
        return None, False

    try:
        data = load_project(match.name)
    except (FileNotFoundError, ValueError) as exc:
        err_detailed(exc, context="Loading saved project")
        return None, False

    ok(f"Project '{match.name}' loaded  ({data.get('saved_at', '—')})")

    quick = ask_choice(
        "Use these settings directly without reviewing each step?",
        ["yes", "no"],
        "yes",
    ) == "yes"

    return data, quick


# ── helpers ───────────────────────────────────────────────────────────────────

# ملاحظة: _cleanup / _safe_filename / _merge_videos انتقلت إلى
# core/render_engine.py — فهي تُستخدم فقط داخل منطق الرندر الفعلي،
# والذي أصبح موحَّداً هناك بدل تكراره هنا.


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── v10: بدء جلسة تسجيل جديدة ─────────────────────────────────────────────
    session_id = new_session()
    log = get_logger("main", verbose=LOG_VERBOSE_DEFAULT)
    cleanup_old_logs(keep_last=LOG_KEEP_LAST)
    log.info(f"FlipaRender {APP_VERSION} — جلسة جديدة: {session_id}")

    banner(APP_NAME, APP_VERSION)

    if not shutil.which("ffmpeg"):
        warn("ffmpeg not found — MP4 export disabled. GIF export still works.")
        log.warning("ffmpeg غير موجود في PATH")

    # ── Project folder ────────────────────────────────────────────────────────
    section("Project Folder")
    _hint("Folder containing scene subfolders. Supports PNG / JPG / WebP / TIFF.")
    _hint("Accepted formats:")
    _hint("  /sdcard/Download/MyProject     (absolute)")
    _hint("  ~/Downloads/MyProject          (home shortcut ~)")
    _hint("  ./MyProject  or ../MyProject   (relative)")
    print()

    root_path = None
    while root_path is None:
        raw      = ask("Folder path", "/sdcard/flipa_project/frames")
        expanded = str(Path(raw).expanduser().resolve())

        try:
            candidate = safe_path(expanded)
        except FileNotFoundError:
            err(f"Not found: {expanded}")
            parent = Path(expanded).parent
            if parent.exists():
                siblings = [p.name for p in parent.iterdir() if p.is_dir()][:6]
                if siblings:
                    warn("Folders found nearby:")
                    for s in siblings:
                        print(f"         {dim(str(parent / s))}")
            print()
            continue
        except ValueError as e:
            err(str(e))
            print()
            continue

        if not candidate.is_dir():
            err("That path points to a file, not a folder.")
            print()
            continue

        ok(f"Found: {candidate}")
        root_path = candidate

    log.info(f"مجلد المشروع: {root_path}")

    # ── v10: Auto Backup — تحقّق من وجود رندر متوقَّف من انقطاع سابق ────────────
    backup_project = _check_pending_backup(root_path)
    if backup_project:
        log.info(f"تمت استعادة نسخة احتياطية: {backup_project.get('project_name')}")

    # ── v10: Project File — تحقّق من وجود مشروع محفوظ لهذا المجلد ──────────────
    if backup_project:
        # عُثر على نسخة احتياطية مُستعادة فعلاً — نستخدمها مباشرة بدل سؤال
        # المستخدم عن مشروع محفوظ عادي (الأولوية للانقطاع المُستعاد).
        loaded_project, quick_mode = backup_project, False
    else:
        loaded_project, quick_mode = _pick_saved_project(root_path)
        if loaded_project:
            log.info(f"تم تحميل مشروع محفوظ: {loaded_project.get('project_name')}")

    all_jobs = scan_jobs(str(root_path))

    if not all_jobs:
        warn("No scenes found.")
        log.warning("لم يتم العثور على أي مشاهد")
        sys.exit(0)

    # ── عرض المشاهد ───────────────────────────────────────────────────────────
    section(f"Scenes detected: {len(all_jobs)}")
    for i, job in enumerate(all_jobs, 1):
        tag   = yellow(" [compound]") if job["compound"] else ""
        count = job['count']
        print(f"  {cyan(f'{i:02d}.')}  {bold(job['name'])}  {dim(f'({count} frames)')}{tag}")
        for layer in job["layers"]:
            print(f"       {dim('└─')} {layer['name']}  {dim(str(layer['count']) + ' frames')}")

    log.info(f"تم اكتشاف {len(all_jobs)} مشهد")

    # ── اختيار الدفعة ─────────────────────────────────────────────────────────
    jobs = _pick_batch(all_jobs)

    # ── v10: Scene Preview Grid — مراجعة أخيرة مباشرة بعد اختيار الدفعة ────────
    _show_preview_grid(jobs)

    # ── v9: ترتيب المشاهد ─────────────────────────────────────────────────────
    if len(jobs) > 1:
        jobs = _pick_sequence(jobs)

    # ── الإعدادات ─────────────────────────────────────────────────────────────
    if loaded_project and quick_mode:
        # ── v10: Quick mode — استخدام كل القيم من ملف المشروع مباشرة ───────────
        section("Using saved project settings")
        res_key   = loaded_project.get("resolution_key", DEFAULT_RESOLUTION)
        w, h, _    = RESOLUTIONS.get(res_key, RESOLUTIONS[DEFAULT_RESOLUTION])
        grade_key = loaded_project.get("grade_key", DEFAULT_GRADE)
        grade     = GRADES.get(grade_key, GRADES[DEFAULT_GRADE])

        fps          = loaded_project.get("fps", DEFAULT_FPS)
        crf          = loaded_project.get("crf", DEFAULT_CRF)
        fmt          = loaded_project.get("format", DEFAULT_OUTPUT_FORMAT)
        metadata     = loaded_project.get("metadata", {})
        gif_opts     = {
            k: loaded_project[k]
            for k in ("gif_colors", "gif_max_width", "gif_loop")
            if k in loaded_project
        }
        ai_enabled   = loaded_project.get("ai_enabled", False)
        ai_steps     = loaded_project.get("ai_steps", 1)
        ai_mode      = loaded_project.get("ai_mode", "smart")
        ai_cache     = loaded_project.get("ai_cache", False)
        blur_enabled  = loaded_project.get("motion_blur_enabled", False)
        blur_strength = loaded_project.get("motion_blur_strength", 0.0)
        chunk_size    = loaded_project.get("render_chunk_size", RENDER_CHUNK_SIZE)

        ok(
            f"fps={fps}  crf={crf}  res={res_key}  grade={grade_key}  "
            f"fmt={fmt}  ai={ai_mode if ai_enabled else 'off'}  "
            f"blur={'on' if blur_enabled else 'off'}"
        )

        cfg = {
            "w": w, "h": h, "resolution_key": res_key,
            "fps":                  fps,
            "crf":                  crf,
            "grade":                grade,
            "grade_key":            grade_key,
            "format":               fmt,
            "metadata":             metadata,
            **gif_opts,
            "ai_enabled":           ai_enabled,
            "ai_steps":             ai_steps,
            "ai_mode":              ai_mode,
            "ai_cache":             ai_cache,
            "render_chunk_size":    chunk_size,
            "motion_blur_enabled":  blur_enabled,
            "motion_blur_strength": blur_strength,
        }

    else:
        # ── مراجعة كل إعداد يدوياً — مع اقتراحات من المشروع المحمَّل إن وُجد ────
        saved_fps = loaded_project.get("fps") if loaded_project else None
        saved_crf = loaded_project.get("crf", DEFAULT_CRF) if loaded_project else DEFAULT_CRF

        # v10: Export Presets — preset جاهز يطبّق resolution/fps/crf/format فوراً
        preset_data = _pick_export_preset()

        if preset_data:
            res_key = preset_data.get("resolution_key", DEFAULT_RESOLUTION)
            w, h, _ = RESOLUTIONS.get(res_key, RESOLUTIONS[DEFAULT_RESOLUTION])
            res = {"w": preset_data.get("w", w), "h": preset_data.get("h", h),
                   "resolution_key": res_key}
            fps = preset_data.get("fps", DEFAULT_FPS)
            crf = preset_data.get("crf", DEFAULT_CRF)
            fmt = preset_data.get("format", DEFAULT_OUTPUT_FORMAT)
            grade, grade_key = _pick_grade(DEFAULT_GRADE)
        else:
            fps   = _pick_fps(jobs, saved_fps=saved_fps)   # v10: تمرير jobs لتفعيل الاقتراح الذكي
            crf   = _pick_crf(saved_crf)
            res   = _pick_resolution(loaded_project.get("resolution_key", DEFAULT_RESOLUTION) if loaded_project else DEFAULT_RESOLUTION)
            grade, grade_key = _pick_grade(loaded_project.get("grade_key", DEFAULT_GRADE) if loaded_project else DEFAULT_GRADE)
            fmt   = _pick_format()

        # v9: metadata (MP4 فقط)
        metadata = {}
        if fmt == "mp4":
            metadata = _pick_metadata()

        # v9: GIF options — preset قد يحدد قيم GIF جاهزة (مثل Telegram GIF)
        gif_opts = {}
        if fmt == "gif":
            if preset_data and "gif_colors" in preset_data:
                gif_opts = {
                    "gif_colors":    preset_data.get("gif_colors", DEFAULT_GIF_COLORS),
                    "gif_max_width": preset_data.get("gif_max_width", DEFAULT_GIF_MAX_WIDTH),
                    "gif_loop":      preset_data.get("gif_loop", 0),
                }
                ok(f"GIF options (from preset): {gif_opts['gif_colors']} colors, "
                   f"max {gif_opts['gif_max_width']}px, loop={gif_opts['gif_loop']}")
            else:
                gif_opts = _pick_gif_options()

        ai_enabled, ai_steps, ai_mode, ai_cache = _pick_ai(jobs, {})

        # v10: Motion Blur
        blur_enabled, blur_strength = _pick_motion_blur(fps)

        # v10: Plugins — فلاتر صورة ومعالجات فيديو اختيارية
        active_image_filters, active_video_effects = _pick_plugins()

        # v10: Memory Optimizer — حجم دفعة الرندر
        chunk_size = _pick_chunk_size(jobs)

        cfg = {
            **res,
            "fps":                  fps,
            "crf":                  crf,
            "grade":                grade,
            "grade_key":            grade_key,
            "format":               fmt,
            "metadata":             metadata,
            **gif_opts,
            "ai_enabled":           ai_enabled,
            "ai_steps":             ai_steps,
            "ai_mode":              ai_mode,
            "ai_cache":             ai_cache,
            "render_chunk_size":    chunk_size,
            "motion_blur_enabled":  blur_enabled,
            "motion_blur_strength": blur_strength,
            "active_image_filters": active_image_filters,
            "active_video_effects": active_video_effects,
        }

        # v10: Export Presets — عرض حفظ الإعدادات اليدوية كـ preset مخصص
        # (فقط لو لم تُطبَّق من preset جاهز مسبقاً — لا فائدة من حفظ نسخة
        # مكررة من preset جاهز موجود أصلاً)
        if not preset_data:
            _offer_save_as_preset(cfg)

    # ── v10: Audio Support — يُسأل خارج quick/manual، فقط لو fmt = mp4 ─────────
    # (الصوت في GIF غير معتاد ولا يدعمه ffmpeg لصيغة GIF نفسها)
    if cfg.get("format") == "mp4":
        if loaded_project and quick_mode and loaded_project.get("audio_enabled"):
            # quick mode: نطبّق نفس إعدادات الصوت المحفوظة دون إعادة السؤال،
            # فقط لو الملف المحفوظ لا يزال موجوداً على القرص.
            saved_audio_path = Path(loaded_project.get("audio_file", ""))
            if saved_audio_path.exists():
                cfg.update({
                    "audio_enabled":   True,
                    "audio_file":      str(saved_audio_path),
                    "audio_sync_mode": loaded_project.get("audio_sync_mode", DEFAULT_AUDIO_SYNC_MODE),
                    "audio_mix_mode":  loaded_project.get("audio_mix_mode", DEFAULT_AUDIO_MIX_MODE),
                })
                ok(f"Audio (from saved project): {saved_audio_path.name}")
        else:
            audio_opts = _pick_audio(root_path)
            cfg.update(audio_opts)

    log.info(
        f"الإعدادات: fps={cfg['fps']} crf={cfg['crf']} res={cfg.get('resolution_key')} "
        f"grade={cfg.get('grade_key')} fmt={cfg['format']} "
        f"ai={cfg['ai_enabled']}({cfg['ai_mode']}) chunk={cfg['render_chunk_size']} "
        f"blur={cfg['motion_blur_enabled']}({cfg['motion_blur_strength']:.2f})"
    )

    # ── v9: Exposure Sheet preview ────────────────────────────────────────────
    section("Exposure Sheet  (Timing)")
    _hint("Shows timing.txt for each scene — or auto timing if none exists.")
    print()

    any_manual_xsheet = False
    for job in jobs:
        xsheet = load_xsheet(job["path"], job["pngs"], cfg.get("default_hold", 1))
        print(xsheet.summary(fps))
        if "auto" not in xsheet.source:
            any_manual_xsheet = True
        print()

    if not any_manual_xsheet:
        _hint("No timing.txt found — each drawing shows for 1 frame.")
        if ask_choice("Generate sample timing.txt to edit?", ["yes", "no"], "no") == "yes":
            for job in jobs:
                out_p = generate_sample_timing(job["path"], job["pngs"])
                ok(f"Created: {out_p}")
            warn("Edit the timing.txt files then re-run FlipaRender.")
            log.info("تم توليد timing.txt عينة — إيقاف للتعديل اليدوي")
            sys.exit(0)

    # ── Preview ───────────────────────────────────────────────────────────────
    section("Preview before rendering")
    if ask_choice("Show preview of first frame?", ["yes", "no"], "yes") == "yes":
        _do_preview(jobs, cfg)
        if ask_choice("Continue with rendering?", ["yes", "no"], "yes") == "no":
            warn("Rendering cancelled.")
            log.info("ألغى المستخدم الرندر بعد المعاينة")
            sys.exit(0)

    # ── Render ────────────────────────────────────────────────────────────────
    # كل منطق الرندر الفعلي (حلقة المشاهد، الدمج، الصوت، الإحصائيات، الحفظ
    # التلقائي، النسخة الاحتياطية) انتقل إلى core/render_engine.run_render —
    # محرك واحد يُستخدم من main.py (الرندر اليدوي) ومن watch_mode.py مستقبلاً
    # (الرندر التلقائي)، حتى لا تتكرر أي ميزة جديدة في مكانين.
    project_name = loaded_project.get("project_name") if loaded_project else None
    result = run_render(cfg, jobs, root_path, log, project_name=project_name)

    log_path = current_log_path()
    if log_path:
        print()
        print(dim(f"  📄 سجل العملية الكامل: {log_path}"))

    print()


# ── v10: Watch Mode entry point ─────────────────────────────────────────────────

def main_watch(path_arg: str | None = None) -> None:
    """
    نقطة دخول الرندر التلقائي (`python main.py --watch [path]`).

    يطرح سؤالاً واحداً فقط لمسار المجلد لو لم يُمرَّر عبر سطر الأوامر —
    لا أي سؤال آخر بعده؛ كل الإعدادات تُحمَّل تلقائياً (project.flipa لو
    موجود، وإلا قيم افتراضية ثابتة)، ثم تبدأ المراقبة المستمرة حتى Ctrl+C.
    """
    from core.watch_engine import watch_project

    session_id = new_session()
    log = get_logger("watch", verbose=LOG_VERBOSE_DEFAULT)
    cleanup_old_logs(keep_last=LOG_KEEP_LAST)
    log.info(f"FlipaRender {APP_VERSION} — جلسة Watch Mode جديدة: {session_id}")

    banner(APP_NAME, APP_VERSION)

    if not shutil.which("ffmpeg"):
        warn("ffmpeg not found — MP4 export disabled. GIF export still works.")
        log.warning("ffmpeg غير موجود في PATH")

    if path_arg:
        expanded = str(Path(path_arg).expanduser().resolve())
    else:
        section("Project Folder")
        _hint("Folder to watch continuously for changes.")
        print()
        expanded = str(Path(ask("Folder path", "/sdcard/flipa_project/frames"))
                        .expanduser().resolve())

    try:
        root_path = safe_path(expanded)
    except FileNotFoundError:
        err(f"Not found: {expanded}")
        return
    except ValueError as exc:
        err(str(exc))
        return

    if not root_path.is_dir():
        err(f"Not a directory: {root_path}")
        return

    watch_project(root_path, log)

    log_path = current_log_path()
    if log_path:
        print()
        print(dim(f"  📄 سجل العملية الكامل: {log_path}"))
    print()


if __name__ == "__main__":
    if "--watch" in sys.argv:
        idx = sys.argv.index("--watch")
        watch_path = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else None
        main_watch(watch_path)
    else:
        main()
