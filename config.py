"""
FlipaRender v10 — Configuration

v10 changes:
  - RENDER_CHUNK_SIZE     : حجم الدفعة الافتراضي لـ Chunk Rendering (Memory Optimizer)
  - RAM_PROFILE_DEFAULT   : مستوى الذاكرة الافتراضي المستخدم لاقتراح حجم الدفعة
  - FPS_PRESETS_SMART     : عتبات اقتراح الـ FPS الذكي (مرجع فقط — المنطق في core/fps_advisor.py)
  - LOG_KEEP_LAST         : عدد ملفات اللوغ المحتفظ بها قبل حذف الأقدم
"""

APP_NAME    = "FlipaRender"
APP_VERSION = "10.0"

# ── Output presets ─────────────────────────────────────────────────────────────
RESOLUTIONS = {
    "hd":  (1280, 720,  "HD 720p"),
    "fhd": (1920, 1080, "Full HD 1080p"),
    "4k":  (3840, 2160, "4K UHD"),
    "sq":  (1080, 1080, "Square 1:1"),
    "vt":  (1080, 1920, "Vertical 9:16"),
}

# ── صيغ الإخراج ────────────────────────────────────────────────────────────────
OUTPUT_FORMATS = {
    "mp4": "فيديو H.264 — الأفضل للمشاركة",
    "gif": "صورة متحركة — مناسبة للويب والتليغرام",
}

DEFAULT_RESOLUTION    = "hd"
DEFAULT_FPS           = 12
DEFAULT_CRF           = 23
DEFAULT_GRADE         = "none"
DEFAULT_OUTPUT_DIR    = "output_videos"
DEFAULT_OUTPUT_FORMAT = "mp4"
TMP_PREFIX            = "_tmp_fliparender_"

# ── v9: Metadata defaults ──────────────────────────────────────────────────────
METADATA_DEFAULTS = {
    "title":   "",
    "artist":  "",
    "comment": "FlipaRender v10",
}

# ── v9: GIF quality options ────────────────────────────────────────────────────
GIF_COLORS_OPTIONS = {
    "64":  "64  — حجم صغير جداً",
    "128": "128 — توازن جيد",
    "256": "256 — أعلى جودة (افتراضي)",
}
DEFAULT_GIF_COLORS = 256
DEFAULT_GIF_MAX_WIDTH = 1280

# ── v10: Memory Optimizer (Chunk Rendering) ─────────────────────────────────────
# عدد الفريمات التي تُحمَّل وتُعالَج معاً قبل تحريرها من الذاكرة.
# قيمة أصغر = استهلاك ذاكرة أقل لكن overhead أكثر قليلاً.
# قيمة أكبر = أسرع لكن يحتاج RAM أكثر.
RENDER_CHUNK_SIZE = 50

# المستوى الافتراضي لو تعذّر اكتشاف ذاكرة الجهاز تلقائياً: "low" | "medium" | "high"
RAM_PROFILE_DEFAULT = "medium"

# ── v10: Smart FPS Detection ────────────────────────────────────────────────────
# مرجع فقط — المنطق الفعلي في core/fps_advisor.py
FPS_PRESETS_SMART = {
    "slow":   12,   # avg_hold مرتفع — حركة Hold كثيرة
    "medium": 18,
    "fast":   24,   # avg_hold منخفض — حركة سريعة سلسة
}

# ── v10: Logging ────────────────────────────────────────────────────────────────
LOG_KEEP_LAST = 20   # عدد ملفات السجل المحفوظة في logs/ قبل حذف الأقدم
LOG_VERBOSE_DEFAULT = False   # لو True تُطبع رسائل INFO في الطرفية أيضاً

# ── v10: Project File System (project.flipa) ───────────────────────────────────
# مجلد منفصل بجانب FlipaRender يحفظ ملف .flipa واحد لكل مشروع (اسم المجلد = اسم المشروع)
PROJECTS_DIR        = "projects"
PROJECT_FILE_EXT    = ".flipa"
PROJECT_AUTOSAVE    = True   # حفظ تلقائي بعد كل رندر ناجح

# ── v10: Audio Support ───────────────────────────────────────────────────────
# مجلد audio/ يُبحث عنه داخل مجلد المشروع نفسه (بجانب مجلدات المشاهد)
AUDIO_SYNC_FULL_VIDEO_ONLY = "full_video_only"   # الصوت على الفيديو المدموج فقط
AUDIO_SYNC_PER_SCENE       = "per_scene"         # الصوت على كل مشهد منفرد + المدموج
DEFAULT_AUDIO_SYNC_MODE    = AUDIO_SYNC_FULL_VIDEO_ONLY
DEFAULT_AUDIO_MIX_MODE     = "match_video"  # match_video | match_audio | audio_loop

# ── v10: Auto Backup ─────────────────────────────────────────────────────────
BACKUPS_DIR = "backups"   # نسخة احتياطية واحدة لكل مشروع (تُستبدل كل مرة)

# ── v10: Watch Mode ──────────────────────────────────────────────────────────
WATCH_POLL_INTERVAL = 3.0   # ثوانٍ بين كل فحص دوري لمجلدات المشاهد

# ── Color grades ───────────────────────────────────────────────────────────────
GRADES = {
    "none": {
        "name":       "Original",
        "contrast":   1.0,
        "color":      1.0,
        "brightness": 1.0,
        "sharpness":  1.0,
        "tint":       None,
    },
    "anime": {
        "name":       "Anime",
        "contrast":   1.3,
        "color":      1.5,
        "brightness": 1.05,
        "sharpness":  1.8,
        "tint":       None,
    },
    "cinematic": {
        "name":       "Cinematic",
        "contrast":   1.2,
        "color":      0.85,
        "brightness": 0.95,
        "sharpness":  1.1,
        "tint":       (255, 220, 180, 20),
    },
    "noir": {
        "name":       "Noir",
        "contrast":   1.4,
        "color":      0.0,
        "brightness": 0.85,
        "sharpness":  1.3,
        "tint":       None,
    },
    "warm": {
        "name":       "Warm Glow",
        "contrast":   1.1,
        "color":      1.2,
        "brightness": 1.05,
        "sharpness":  1.0,
        "tint":       (255, 200, 120, 25),
    },
    "cold": {
        "name":       "Cold Steel",
        "contrast":   1.15,
        "color":      0.9,
        "brightness": 0.98,
        "sharpness":  1.2,
        "tint":       (140, 180, 255, 18),
    },
    "vintage": {
        "name":       "Vintage",
        "contrast":   1.1,
        "color":      0.75,
        "brightness": 1.0,
        "sharpness":  0.9,
        "tint":       (210, 180, 130, 35),
    },
}
