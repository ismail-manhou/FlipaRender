"""
FlipaRender v10 — Export Presets  (core/export_presets.py)

إعدادات تصدير جاهزة (YouTube, TikTok, Instagram, Telegram, 4K) بالإضافة
إلى دعم إنشاء وحفظ presets مخصصة من المستخدم.

البريسيتس الجاهزة (BUILTIN_PRESETS) مكتوبة في هذا الملف مباشرة — ثابتة،
لا تُحفظ كملفات. البريسيتس المخصصة تُحفظ في مجلد منفصل::

    presets/<اسم_البريست>.json

كل preset هو dict جزئي من مفاتيح cfg (resolution_key/w/h/fps/crf/format/
gif options) — يُطبَّق فوق cfg الحالي عبر apply_preset_to_cfg، تماماً
كما تُطبَّق إعدادات project.flipa، فلا تتكرر فلسفة الدمج في مكانين.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import RESOLUTIONS

PRESETS_DIR = "presets"

# المفاتيح القابلة للتضمين في أي preset (جزء من مفاتيح cfg فقط — وليس كل
# شيء؛ presets لا تتحكم بإعدادات خاصة بمشروع معيّن كالصوت أو AI)
_PRESET_KEYS = [
    "resolution_key", "w", "h",
    "fps", "crf", "format",
    "gif_colors", "gif_max_width", "gif_loop",
]


@dataclass
class PresetInfo:
    key:         str     # المعرّف الداخلي (مثل "youtube_1080p" أو اسم مخصص)
    name:        str     # الاسم المعروض للمستخدم
    description: str
    builtin:     bool    # True لو preset جاهز، False لو مخصص من المستخدم


# ── البريسيتس الجاهزة ────────────────────────────────────────────────────────────

def _res(key: str) -> tuple[int, int]:
    w, h, _ = RESOLUTIONS[key]
    return w, h


_yt_w, _yt_h = _res("fhd")
_tt_w, _tt_h = _res("vt")
_ig_w, _ig_h = _res("vt")
_4k_w, _4k_h = _res("4k")

BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "youtube_1080p": {
        "name":        "YouTube 1080p",
        "description": "Full HD أفقي، جودة عالية — مثالي لرفع يوتيوب",
        "resolution_key": "fhd", "w": _yt_w, "h": _yt_h,
        "fps": 30, "crf": 18, "format": "mp4",
    },
    "tiktok_vertical": {
        "name":        "TikTok Vertical",
        "description": "عمودي 9:16 — مثالي لتيك توك ورييلز",
        "resolution_key": "vt", "w": _tt_w, "h": _tt_h,
        "fps": 30, "crf": 20, "format": "mp4",
    },
    "instagram_reel": {
        "name":        "Instagram Reel",
        "description": "عمودي 9:16، جودة عالية — مثالي لإنستغرام Reels",
        "resolution_key": "vt", "w": _ig_w, "h": _ig_h,
        "fps": 30, "crf": 19, "format": "mp4",
    },
    "telegram_gif": {
        "name":        "Telegram GIF",
        "description": "GIF خفيف الحجم — مثالي للمشاركة في تيليغرام",
        "resolution_key": "hd", "w": _res("hd")[0], "h": _res("hd")[1],
        "fps": 15, "crf": 23, "format": "gif",
        "gif_colors": 128, "gif_max_width": 720, "gif_loop": 0,
    },
    "4k_uhd": {
        "name":        "4K UHD",
        "description": "أعلى دقة متاحة — للأرشفة أو العرض على شاشات كبيرة",
        "resolution_key": "4k", "w": _4k_w, "h": _4k_h,
        "fps": 30, "crf": 16, "format": "mp4",
    },
}


# ── مسارات presets المخصصة ──────────────────────────────────────────────────────

def _presets_root() -> Path:
    root = Path(PRESETS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _preset_path(key: str) -> Path:
    return _presets_root() / f"{key}.json"


def _slugify(name: str) -> str:
    """يحوّل اسم preset عادي لمعرّف ملف آمن (مثل project_name_from_path)."""
    safe = re.sub(r"[^\w\-]+", "_", name.strip())
    return safe.strip("_").lower() or "custom_preset"


# ── حفظ / تحميل presets مخصصة ────────────────────────────────────────────────────

def save_custom_preset(name: str, cfg: dict) -> Path:
    """
    يحفظ preset مخصص جديد من إعدادات *cfg* الحالية، تحت اسم *name*.
    يأخذ فقط المفاتيح المتعلقة بالتصدير (_PRESET_KEYS) — لا يحفظ AI ولا
    صوت ولا metadata، لأن preset هو قالب تصدير عام قابل لإعادة الاستخدام
    على أي مشروع.
    """
    key = _slugify(name)
    data: dict[str, Any] = {"name": name, "description": "Custom preset"}
    for k in _PRESET_KEYS:
        if k in cfg:
            data[k] = cfg[k]

    path = _preset_path(key)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_custom_preset(key: str) -> dict | None:
    path = _preset_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def delete_custom_preset(key: str) -> bool:
    path = _preset_path(key)
    if path.exists():
        path.unlink()
        return True
    return False


def list_custom_presets() -> list[PresetInfo]:
    root = _presets_root()
    infos = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        infos.append(PresetInfo(
            key=path.stem,
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            builtin=False,
        ))
    return infos


# ── قائمة موحَّدة (جاهزة + مخصصة) ────────────────────────────────────────────────

def list_all_presets() -> list[PresetInfo]:
    """يرجع كل البريسيتس (الجاهزة أولاً، ثم المخصصة) كقائمة موحَّدة للعرض."""
    builtin = [
        PresetInfo(key=k, name=v["name"], description=v["description"], builtin=True)
        for k, v in BUILTIN_PRESETS.items()
    ]
    return builtin + list_custom_presets()


def get_preset_data(key: str) -> dict | None:
    """يرجع بيانات preset (جاهز أو مخصص) بمعرّفه. None لو غير موجود."""
    if key in BUILTIN_PRESETS:
        return BUILTIN_PRESETS[key]
    return load_custom_preset(key)


# ── تطبيق preset على cfg ────────────────────────────────────────────────────────

def apply_preset_to_cfg(preset_data: dict, cfg: dict) -> dict:
    """
    يدمج قيم *preset_data* داخل *cfg* الحالي (يستبدل الموجود فقط من
    _PRESET_KEYS) — لا يلمس إعدادات AI/الصوت/الميتاداتا الحالية.
    """
    for key in _PRESET_KEYS:
        if key in preset_data:
            cfg[key] = preset_data[key]
    return cfg
