"""
FlipaRender — FlipaClip Project Reader  (core/flipaclip_reader.py)

يفتح ملفات مشاريع FlipaClip (.fc أو ملفات النسخ الاحتياطي .zip)
ويستخرج منها:
  - معدل الإطارات (FPS)
  - أبعاد اللوحة (Canvas Width × Height)
  - عدد الطبقات (Layers)
  - مسارات صور الفريمات — جاهزة للتمرير مباشرة إلى xsheet.py / scanner.py

بنية ملف FlipaClip الداخلية (أرشيف ZIP):
  project.db         ← قاعدة بيانات SQLite تحتوي إعدادات المشروع
  frames/            ← مجلد الصور الشفافة (PNG لكل فريم)
    layer_0/
      frame_0001.png
      frame_0002.png
      ...
    layer_1/
      ...

الاستخدام:
    from core.flipaclip_reader import open_flipaclip_project

    with open_flipaclip_project("/sdcard/Export/myAnimation.fc") as proj:
        print(proj.fps, proj.width, proj.height)
        print(proj.layers)          # [{"name": "layer_0", "frames": [...]}]
        # مرّر الفريمات لـ xsheet
        from core.xsheet import load_xsheet
        xsheet = load_xsheet(proj.layers[0]["frames"], scene_dir=None)
"""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

from .security import validate_files, ALLOWED_EXTENSIONS


# ─────────────────────────────────────────────────────────────────────────────
# بيانات المشروع المستخرجة
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FlipaClipLayer:
    """طبقة واحدة داخل مشروع FlipaClip."""
    name:   str
    frames: list[str]   # مسارات PNG مرتّبة طبيعياً

    @property
    def count(self) -> int:
        return len(self.frames)


@dataclass
class FlipaClipProject:
    """
    نتيجة قراءة ملف .fc — تُعاد من open_flipaclip_project().

    الحقول:
        fps      : معدل الإطارات (24 افتراضياً لو لم يُخزَّن في القاعدة)
        width    : عرض اللوحة بالبكسل
        height   : ارتفاع اللوحة بالبكسل
        layers   : قائمة FlipaClipLayer مرتّبة من الأسفل للأعلى
        _tmpdir  : مجلد مؤقت داخلي — يُحذف تلقائياً عند الخروج من with
    """
    fps:    int
    width:  int
    height: int
    layers: list[FlipaClipLayer] = field(default_factory=list)
    _tmpdir: tempfile.TemporaryDirectory | None = field(
        default=None, repr=False, compare=False
    )

    def cleanup(self) -> None:
        """احذف المجلد المؤقت يدوياً (يُستدعى تلقائياً من context manager)."""
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None

    @property
    def all_frames(self) -> list[str]:
        """كل فريمات الطبقة السفلى (الـ reference layer) كقائمة مباشرة."""
        if not self.layers:
            return []
        return self.layers[0].frames

    def to_scanner_jobs(self) -> list[dict]:
        """
        يحوّل المشروع إلى صيغة jobs متوافقة مع scanner.scan_jobs()
        حتى يمكن تمريره مباشرة لـ render_frames() و main.py.

        - مشروع بطبقة واحدة  → simple job
        - مشروع بطبقات متعددة → compound job
        """
        if not self.layers:
            return []

        compound = len(self.layers) > 1

        job: dict = {
            "name":     "flipaclip_import",
            "path":     str(Path(self.layers[0].frames[0]).parent) if self.layers[0].frames else "",
            "pngs":     self.layers[0].frames,
            "count":    max(lay.count for lay in self.layers),
            "compound": compound,
            "layers":   [{"name": lay.name, "count": lay.count} for lay in self.layers],
        }

        if compound:
            job["layer_pngs"] = [lay.frames for lay in self.layers]

        return [job]


# ─────────────────────────────────────────────────────────────────────────────
# قراءة قاعدة البيانات
# ─────────────────────────────────────────────────────────────────────────────

def _read_db(db_path: Path) -> dict:
    """
    يقرأ إعدادات المشروع الأساسية من قاعدة بيانات SQLite الخاصة بـ FlipaClip.

    يحاول استخراج FPS والأبعاد من جداول متعددة (project / canvas / settings)
    لأن FlipaClip غيّرت هيكل قاعدتها عبر الإصدارات.
    يعيد قاموساً بـ {fps, width, height}.
    """
    result = {"fps": 24, "width": 1080, "height": 1920}   # قيم افتراضية آمنة

    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()

        # ── اكتشف الجداول الموجودة ─────────────────────────────────────────
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0].lower() for row in cur.fetchall()}

        # ── استراتيجية 1: جدول "project" ─────────────────────────────────
        if "project" in tables:
            cur.execute("PRAGMA table_info(project)")
            cols = {row[1].lower() for row in cur.fetchall()}

            if "fps" in cols:
                row = cur.execute("SELECT fps FROM project LIMIT 1").fetchone()
                if row and row[0]:
                    result["fps"] = int(row[0])

            for w_col in ("width", "canvas_width", "canvaswidth"):
                if w_col in cols:
                    row = cur.execute(f"SELECT {w_col} FROM project LIMIT 1").fetchone()
                    if row and row[0]:
                        result["width"] = int(row[0])
                    break

            for h_col in ("height", "canvas_height", "canvasheight"):
                if h_col in cols:
                    row = cur.execute(f"SELECT {h_col} FROM project LIMIT 1").fetchone()
                    if row and row[0]:
                        result["height"] = int(row[0])
                    break

        # ── استراتيجية 2: جدول "canvas" ──────────────────────────────────
        if "canvas" in tables:
            cur.execute("PRAGMA table_info(canvas)")
            cols = {row[1].lower() for row in cur.fetchall()}
            if "width" in cols and result["width"] == 1080:
                row = cur.execute("SELECT width, height FROM canvas LIMIT 1").fetchone()
                if row:
                    result["width"], result["height"] = int(row[0]), int(row[1])

        # ── استراتيجية 3: جدول "settings" (key-value pairs) ─────────────
        if "settings" in tables:
            cur.execute("PRAGMA table_info(settings)")
            scols = {row[1].lower() for row in cur.fetchall()}
            if "key" in scols and "value" in scols:
                for row in cur.execute("SELECT key, value FROM settings"):
                    k, v = str(row[0]).lower(), row[1]
                    if k == "fps" and v:
                        result["fps"] = int(v)
                    elif k in ("width", "canvas_width") and v:
                        result["width"] = int(v)
                    elif k in ("height", "canvas_height") and v:
                        result["height"] = int(v)

        con.close()

    except sqlite3.Error:
        pass  # لو فشلت القراءة نرجع بالقيم الافتراضية

    return result


# ─────────────────────────────────────────────────────────────────────────────
# استخراج الفريمات
# ─────────────────────────────────────────────────────────────────────────────

def _extract_frames(zf: zipfile.ZipFile, tmp_path: Path) -> list[FlipaClipLayer]:
    """
    يستخرج مجلدات الصور من الأرشيف ويبني قائمة FlipaClipLayer.

    يبحث في هيكل الأرشيف عن:
      frames/layer_N/frame_NNNN.png   ← بنية FlipaClip الحديثة
      frames/frame_NNNN.png           ← بنية مبسّطة (طبقة واحدة)
      *.png في الجذر                  ← تصدير PNG مباشر
    """
    names = zf.namelist()

    # ── اكتشاف تلقائي لمجلد الصور ───────────────────────────────────────────
    img_names = [
        n for n in names
        if Path(n).suffix.lower() in ALLOWED_EXTENSIONS
        and not Path(n).name.startswith(".")
    ]

    if not img_names:
        return []

    # ── تجميع حسب المجلد الأب ───────────────────────────────────────────────
    layers_dict: dict[str, list[str]] = {}
    for img in img_names:
        parent = str(Path(img).parent)
        layers_dict.setdefault(parent, []).append(img)

    # ── فك الضغط وبناء الطبقات ──────────────────────────────────────────────
    result_layers: list[FlipaClipLayer] = []

    for layer_key in sorted(layers_dict.keys()):
        member_names = sorted(layers_dict[layer_key])
        layer_dir = tmp_path / layer_key
        layer_dir.mkdir(parents=True, exist_ok=True)

        extracted_paths: list[str] = []
        for member in member_names:
            dest = tmp_path / member
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            extracted_paths.append(str(dest))

        # تحقّق أمني من الملفات المستخرجة
        validated = validate_files(extracted_paths, ALLOWED_EXTENSIONS)
        if validated:
            layer_name = Path(layer_key).name or f"layer_{len(result_layers)}"
            result_layers.append(FlipaClipLayer(name=layer_name, frames=validated))

    return result_layers


# ─────────────────────────────────────────────────────────────────────────────
# واجهة عامة — Context Manager
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def open_flipaclip_project(
    fc_path: str | Path,
) -> Generator[FlipaClipProject, None, None]:
    """
    Context manager يفتح ملف FlipaClip (.fc أو .zip) ويعيد FlipaClipProject.

    المجلد المؤقت يُحذف تلقائياً عند الخروج من الـ with، بالتوافق مع
    وحدة memory.py — لا يتراكم شيء على القرص.

    مثال:
        with open_flipaclip_project("myAnim.fc") as proj:
            print(proj.fps, proj.width, proj.height)
            jobs = proj.to_scanner_jobs()
    """
    fc_path = Path(fc_path)

    if not fc_path.exists():
        raise FileNotFoundError(f"ملف FlipaClip غير موجود: {fc_path}")

    if not zipfile.is_zipfile(fc_path):
        raise ValueError(
            f"الملف ليس أرشيف ZIP صالح (FlipaClip يستخدم ZIP داخلياً): {fc_path}"
        )

    tmp = tempfile.TemporaryDirectory(prefix="fliparender_fc_")
    tmp_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(fc_path, "r") as zf:
            members = zf.namelist()

            # ── ابحث عن قاعدة البيانات ─────────────────────────────────────
            db_member = next(
                (m for m in members if Path(m).suffix.lower() == ".db"),
                None,
            )

            db_info: dict = {"fps": 24, "width": 1080, "height": 1920}
            if db_member:
                db_dest = tmp_path / Path(db_member).name
                zf.extract(db_member, tmp_path)
                # zipfile يحافظ على المسار الكامل عند الاستخراج
                extracted_db = tmp_path / db_member
                db_info = _read_db(extracted_db)

            # ── استخرج الفريمات ────────────────────────────────────────────
            layers = _extract_frames(zf, tmp_path)

        proj = FlipaClipProject(
            fps=db_info["fps"],
            width=db_info["width"],
            height=db_info["height"],
            layers=layers,
            _tmpdir=tmp,
        )
        yield proj

    except Exception:
        tmp.cleanup()
        raise
    else:
        proj.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# واجهة مبسّطة بدون context manager (للاستخدام الخارجي)
# ─────────────────────────────────────────────────────────────────────────────

def read_flipaclip_info(fc_path: str | Path) -> dict:
    """
    يقرأ معلومات المشروع فقط (FPS، الأبعاد، عدد الطبقات) دون استخراج الصور.
    مفيد لعرض معلومات سريعة في CLI قبل الرندر الكامل.

    يعيد:
        {
            "fps": 24,
            "width": 1080,
            "height": 1920,
            "layer_count": 3,
            "has_db": True,
        }
    """
    fc_path = Path(fc_path)

    if not fc_path.exists():
        raise FileNotFoundError(f"الملف غير موجود: {fc_path}")

    if not zipfile.is_zipfile(fc_path):
        raise ValueError(f"ليس أرشيف ZIP صالح: {fc_path}")

    with tempfile.TemporaryDirectory(prefix="fliparender_info_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(fc_path, "r") as zf:
            members = zf.namelist()
            db_member = next(
                (m for m in members if Path(m).suffix.lower() == ".db"),
                None,
            )

            db_info = {"fps": 24, "width": 1080, "height": 1920}
            has_db = False
            if db_member:
                zf.extract(db_member, tmp_path)
                db_info = _read_db(tmp_path / db_member)
                has_db = True

            # عدّ الطبقات بدون استخراج الصور
            img_parents = {
                str(Path(n).parent)
                for n in members
                if Path(n).suffix.lower() in ALLOWED_EXTENSIONS
            }
            layer_count = max(len(img_parents), 1)

    return {
        "fps":         db_info["fps"],
        "width":       db_info["width"],
        "height":      db_info["height"],
        "layer_count": layer_count,
        "has_db":      has_db,
    }
