"""
FlipaRender v10 — Plugin System  (core/plugins.py)

نظام إضافات يسمح بإضافة فلاتر صورة أو معالجات فيديو جديدة دون تعديل
أي كود أساسي — فقط بإضافة ملف .py جديد داخل مجلد plugins/.

نوعان من الإضافات:

  1. ImageFilterPlugin — يعمل على كل فريم (PIL.Image) قبل الحفظ، بعد
     Color Grading وMotion Blur الأصليين مباشرة (آخر معالجة على الصورة).

  2. VideoEffectPlugin — يعمل على الفيديو النهائي بعد الدمج الكامل
     (FULL_VIDEO.mp4 أو المشهد الوحيد)، قبل دمج الصوت — عبر FFmpeg.

هيكل مجلد الإضافات المتوقَّع::

    plugins/
    ├── watercolor.py     ← ImageFilterPlugin
    ├── comic.py          ← ImageFilterPlugin
    └── filmgrain.py      ← VideoEffectPlugin

كل ملف يحتوي كلاساً واحداً أو أكثر يرث من ImageFilterPlugin أو
VideoEffectPlugin، ويُعرَّف فيه name (اسم معروض)، params (قاموس
المعاملات القابلة للتخصيص مع قيمها الافتراضية)، ودالة apply.

مثال أبسط فلتر ممكن (watercolor.py)::

    from core.plugins import ImageFilterPlugin

    class Watercolor(ImageFilterPlugin):
        name = "Watercolor"
        params = {"strength": 0.5}

        def apply(self, image, **params):
            # ... معالجة PIL.Image وإرجاع نسخة معدَّلة
            return image
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from PIL import Image

PLUGINS_DIR = "plugins"


# ── الواجهات الرسمية (Base Classes) ─────────────────────────────────────────────

class ImageFilterPlugin(ABC):
    """
    فلتر يُطبَّق على كل فريم (صورة) أثناء الرندر، بعد Color Grading
    وMotion Blur الأصليين مباشرة وقبل الحفظ النهائي.

    يجب على كل فلتر تعريف:
      name   : اسم معروض للمستخدم (str)
      params : قاموس المعاملات القابلة للتخصيص مع قيمها الافتراضية
      apply  : دالة تستقبل PIL.Image وتُعيد PIL.Image معدَّلة
    """
    name: str = "Unnamed Filter"
    params: dict[str, Any] = {}
    description: str = ""

    @abstractmethod
    def apply(self, image: Image.Image, **params: Any) -> Image.Image:
        """يستقبل صورة PIL ويُعيد نسخة معدَّلة منها. لا يُعدِّل المُدخَل في مكانه."""
        raise NotImplementedError


class VideoEffectPlugin(ABC):
    """
    مؤثر يُطبَّق على الفيديو النهائي (بعد الدمج الكامل، قبل دمج الصوت)
    عبر FFmpeg.

    يجب على كل مؤثر تعريف:
      name   : اسم معروض للمستخدم (str)
      params : قاموس المعاملات القابلة للتخصيص مع قيمها الافتراضية
      apply  : دالة تستقبل (مسار فيديو دخل، مسار فيديو خرج) وتُنفّذ المعالجة
    """
    name: str = "Unnamed Effect"
    params: dict[str, Any] = {}
    description: str = ""

    @abstractmethod
    def apply(self, input_path: Path, output_path: Path, **params: Any) -> None:
        """
        يقرأ الفيديو من *input_path* ويكتب النتيجة المعالَجة في *output_path*.
        المسارين مختلفين دائماً (لا كتابة في نفس الملف المصدر).
        """
        raise NotImplementedError


# ── التحميل الديناميكي ───────────────────────────────────────────────────────────

def _load_module_from_file(path: Path):
    """يحمّل ملف .py كموديول بايثون مستقل، بدون الحاجة لإضافته لـ sys.path."""
    module_name = f"flipa_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load plugin module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def discover_plugins(plugins_dir: str | Path = PLUGINS_DIR) -> tuple[list[type], list[tuple[Path, str]]]:
    """
    يبحث في *plugins_dir* عن كل ملفات .py ويستخرج منها أي كلاس يرث من
    ImageFilterPlugin أو VideoEffectPlugin.

    يعيد (classes, errors):
      classes : قائمة الكلاسات المُكتشَفة بنجاح (غير منشأة كـ instance بعد)
      errors  : قائمة (مسار_الملف, رسالة_الخطأ) لكل ملف فشل تحميله — لا يوقف
                باقي الإضافات؛ إضافة معطوبة واحدة لا تُسقط النظام كله.
    """
    root = Path(plugins_dir)
    classes: list[type] = []
    errors: list[tuple[Path, str]] = []

    if not root.is_dir():
        return classes, errors

    for path in sorted(root.glob("*.py")):
        if path.name.startswith("_"):
            continue   # ملفات مساعدة داخلية (مثل __init__.py) تُتجاهل
        try:
            module = _load_module_from_file(path)
        except Exception as exc:   # أي خطأ في كود الإضافة نفسها — لا نوقف البرنامج
            errors.append((path, str(exc)))
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue   # كلاس مستورَد من مكان آخر (مثل ABC نفسها) — نتجاهله
            if issubclass(obj, (ImageFilterPlugin, VideoEffectPlugin)) and \
                    obj not in (ImageFilterPlugin, VideoEffectPlugin):
                classes.append(obj)

    return classes, errors


def discover_image_filters(plugins_dir: str | Path = PLUGINS_DIR) -> tuple[list[ImageFilterPlugin], list[tuple[Path, str]]]:
    """يرجع فقط instances فلاتر الصورة المُكتشَفة، جاهزة للاستخدام مباشرة."""
    classes, errors = discover_plugins(plugins_dir)
    instances = [cls() for cls in classes if issubclass(cls, ImageFilterPlugin)]
    return instances, errors


def discover_video_effects(plugins_dir: str | Path = PLUGINS_DIR) -> tuple[list[VideoEffectPlugin], list[tuple[Path, str]]]:
    """يرجع فقط instances مؤثرات الفيديو المُكتشَفة، جاهزة للاستخدام مباشرة."""
    classes, errors = discover_plugins(plugins_dir)
    instances = [cls() for cls in classes if issubclass(cls, VideoEffectPlugin)]
    return instances, errors
