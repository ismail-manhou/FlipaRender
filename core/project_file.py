"""
FlipaRender v10 — Project File System  (core/project_file.py)

ملف مشروع رسمي بصيغة JSON بامتداد .flipa، يحفظ إعدادات الرندر الكاملة
لمشروع معيّن حتى يمكن إعادة فتحه بنفس الإعدادات دون إعادة الإجابة على
كل الأسئلة من جديد.

مكان التخزين:
    projects/<اسم_المشروع>.flipa   (بجانب FlipaRender، مستقل عن مجلد الفريمات)

محتوى الملف (مثال):
    {
      "project_name": "MyAnimation",
      "source_path": "/sdcard/flipa_project/frames",
      "saved_at": "2026-06-21T10:30:00",
      "fps": 24,
      "resolution": "fhd",
      "grading": "anime",
      "ai_mode": "hybrid",
      ...
    }

استخدام:

    from core.project_file import (
        save_project, load_project, list_projects,
        export_project, import_project, project_name_from_path,
    )

    save_project("MyAnimation", root_path, cfg)
    data = load_project("MyAnimation")
    names = list_projects()
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config import PROJECTS_DIR, PROJECT_FILE_EXT

# ── المفاتيح من cfg التي تُحفَظ داخل ملف المشروع ─────────────────────────────────
# (نتجنّب حفظ كائنات معقّدة مثل dict الـ grade الكامل أو jobs — فقط القيم
#  القابلة للتسلسل JSON والتي يمكن إعادة بنائها بسهولة عند التحميل)
_SAVED_KEYS = [
    "fps", "crf", "w", "h", "resolution_key", "grade_key", "format",
    "ai_enabled", "ai_steps", "ai_mode", "ai_cache",
    "render_chunk_size",
    "motion_blur_enabled", "motion_blur_strength",
    "gif_colors", "gif_max_width", "gif_loop",
    "metadata",
    "audio_enabled", "audio_file", "audio_sync_mode", "audio_mix_mode",
]


@dataclass
class ProjectInfo:
    """نتيجة بحث سريعة عن مشروع محفوظ — تُستخدم في قوائم الاختيار."""
    name:      str
    path:      Path
    saved_at:  str
    source:    str


# ── مسارات ────────────────────────────────────────────────────────────────────

def _projects_root() -> Path:
    root = Path(PROJECTS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _project_path(name: str) -> Path:
    return _projects_root() / f"{name}{PROJECT_FILE_EXT}"


def project_name_from_path(source_path: str | Path) -> str:
    """
    يستخرج اسم مشروع آمن (لاستخدامه كاسم ملف) من مسار مجلد الفريمات.
    مثال: /sdcard/flipa_project/frames → "frames"
    """
    raw = Path(source_path).name or "project"
    safe = re.sub(r"[^\w\-]", "_", raw)
    return safe or "project"


# ── حفظ ────────────────────────────────────────────────────────────────────────

def build_project_data(project_name: str, source_path: str, cfg: dict) -> dict:
    """
    يبني dict جاهز للحفظ من *cfg* الحالي — يأخذ فقط المفاتيح القابلة
    للتسلسل ويتجاهل الباقي (jobs، كائنات PIL، إلخ).
    """
    data: dict[str, Any] = {
        "project_name": project_name,
        "source_path":  str(source_path),
        "saved_at":      datetime.now().isoformat(timespec="seconds"),
        "app_version":  __import__("config").APP_VERSION,
    }
    for key in _SAVED_KEYS:
        if key in cfg:
            data[key] = cfg[key]
    return data


def save_project(project_name: str, source_path: str, cfg: dict) -> Path:
    """
    يحفظ إعدادات المشروع الحالية إلى projects/<project_name>.flipa
    ويعيد المسار الكامل للملف المحفوظ.
    """
    data = build_project_data(project_name, source_path, cfg)
    path = _project_path(project_name)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ── تحميل ──────────────────────────────────────────────────────────────────────

def load_project(project_name: str) -> dict:
    """
    يحمّل ملف مشروع موجود ويعيد محتواه كـ dict.
    يرفع FileNotFoundError لو الملف غير موجود، و ValueError لو JSON تالف.
    """
    path = _project_path(project_name)
    if not path.exists():
        raise FileNotFoundError(f"لا يوجد مشروع محفوظ باسم: {project_name}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"ملف المشروع تالف أو غير صالح: {path}") from exc


def load_project_from_path(path: str | Path) -> dict:
    """نفس load_project لكن بمسار ملف مباشر (مفيد للاستيراد من مكان آخر)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"الملف غير موجود: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"ملف المشروع تالف أو غير صالح: {path}") from exc


# ── قائمة المشاريع المحفوظة ────────────────────────────────────────────────────

def list_projects() -> list[ProjectInfo]:
    """
    يرجع قائمة كل ملفات .flipa الموجودة في projects/، مرتّبة من الأحدث للأقدم.
    """
    root = _projects_root()
    infos: list[ProjectInfo] = []

    for path in sorted(root.glob(f"*{PROJECT_FILE_EXT}"),
                        key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        infos.append(ProjectInfo(
            name=data.get("project_name", path.stem),
            path=path,
            saved_at=data.get("saved_at", "—"),
            source=data.get("source_path", "—"),
        ))
    return infos


# ── استيراد / تصدير ────────────────────────────────────────────────────────────

def export_project(project_name: str, dest_dir: str | Path) -> Path:
    """
    ينسخ ملف المشروع المحفوظ إلى مجلد *dest_dir* (مثلاً لمشاركته أو نسخه
    إلى جهاز آخر). يعيد المسار النهائي للنسخة المُصدَّرة.
    """
    src = _project_path(project_name)
    if not src.exists():
        raise FileNotFoundError(f"لا يوجد مشروع محفوظ باسم: {project_name}")

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def import_project(file_path: str | Path) -> str:
    """
    يستورد ملف .flipa من مسار خارجي إلى projects/ (بالاسم المخزَّن داخل
    JSON إن وُجد، وإلا باسم الملف نفسه). يعيد اسم المشروع بعد الاستيراد.
    """
    src = Path(file_path)
    data = load_project_from_path(src)

    name = data.get("project_name") or src.stem
    dest = _project_path(name)
    dest.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return name


def delete_project(project_name: str) -> bool:
    """يحذف ملف مشروع محفوظ. يعيد True لو تم الحذف، False لو لم يكن موجوداً."""
    path = _project_path(project_name)
    if path.exists():
        path.unlink()
        return True
    return False


# ── تطبيق بيانات مشروع محمَّل على cfg جديد ──────────────────────────────────────

def apply_project_to_cfg(data: dict, cfg: dict) -> dict:
    """
    يدمج القيم المحفوظة في *data* داخل *cfg* الحالي (يستبدل الموجود فقط).
    يستخدم نفس مفاتيح _SAVED_KEYS — لا يلمس jobs أو مسارات الملفات الحالية.
    """
    for key in _SAVED_KEYS:
        if key in data:
            cfg[key] = data[key]
    return cfg


# ── v10: Watch Mode — إعدادات افتراضية كاملة بدون أي أسئلة ─────────────────────

def build_default_cfg() -> dict:
    """
    يبني cfg كامل وجاهز للرندر مباشرة، باستخدام القيم الافتراضية الثابتة
    من config.py فقط — بدون أي تفاعل مع المستخدم.

    يُستخدم في Watch Mode عندما لا يوجد ملف project.flipa محفوظ مسبقاً
    لمشروع معيّن: نحتاج إعدادات معقولة فوراً لنبدأ الرندر التلقائي، دون
    إيقاف المراقبة لانتظار إجابات لا أحد سيقدّمها (لا يوجد مستخدم تفاعلي
    في وضع المراقبة المستمرة).

    الميزات الاختيارية (AI / Motion Blur / Audio) معطّلة افتراضياً — أكثر
    أماناً وأسرع للرندر التلقائي المتكرر؛ المستخدم يمكنه حفظ project.flipa
    مرة عبر الرندر اليدوي العادي لو احتاج إعدادات مخصّصة في Watch Mode.
    """
    from config import (
        DEFAULT_FPS, DEFAULT_CRF, DEFAULT_GRADE, DEFAULT_RESOLUTION,
        DEFAULT_OUTPUT_FORMAT, RENDER_CHUNK_SIZE, RESOLUTIONS, GRADES,
        METADATA_DEFAULTS,
    )

    w, h, _ = RESOLUTIONS[DEFAULT_RESOLUTION]
    grade   = GRADES[DEFAULT_GRADE]

    return {
        "fps":                  DEFAULT_FPS,
        "crf":                  DEFAULT_CRF,
        "w":                    w,
        "h":                    h,
        "resolution_key":       DEFAULT_RESOLUTION,
        "grade":                grade,
        "grade_key":            DEFAULT_GRADE,
        "format":               DEFAULT_OUTPUT_FORMAT,
        "metadata":             dict(METADATA_DEFAULTS),
        "ai_enabled":           False,
        "ai_steps":             1,
        "ai_mode":              "smart",
        "ai_cache":             False,
        "render_chunk_size":    RENDER_CHUNK_SIZE,
        "motion_blur_enabled":  False,
        "motion_blur_strength": 0.0,
        "audio_enabled":        False,
    }
