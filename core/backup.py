"""
FlipaRender v10 — Auto Backup  (core/backup.py)

نسخة احتياطية واحدة لكل مشروع (تُستبدل كل مرة) تحتوي:
  • إعدادات آخر تشغيل (project.flipa) — تُحفَظ *قبل* بدء الرندر، لا بعده فقط،
    حتى لو حدث انقطاع مفاجئ تبقى آخر الإعدادات المستخدمة محفوظة.
  • نسخة من مجلدات tmp_* الموجودة وقت الحفظ (فريمات مرندرة جزئياً) — تُستخدم
    لاكتشاف رندر متوقَّف من تشغيل سابق والسؤال عن استعادته بوضوح.

هيكل التخزين::

    backups/<project_name>/
    ├── project.flipa          (نسخة من إعدادات آخر تشغيل قبل الرندر)
    ├── meta.json              (وقت الحفظ + اسم مجلد المصدر)
    └── tmp/
        ├── _tmp_fliparender_Walk/
        └── _tmp_fliparender_Jump/
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import TMP_PREFIX

BACKUPS_DIR = "backups"


@dataclass
class BackupInfo:
    project_name: str
    saved_at:     str
    tmp_scenes:   list[str]   # أسماء مجلدات tmp_* الموجودة داخل النسخة الاحتياطية


def _backup_root() -> Path:
    root = Path(BACKUPS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _backup_dir(project_name: str) -> Path:
    return _backup_root() / project_name


def find_pending_tmp_dirs(search_root: Path = Path(".")) -> list[Path]:
    """
    يبحث في *search_root* عن مجلدات tmp_* متبقية من تشغيل سابق منقطع
    (لم تُحذف عبر _cleanup الطبيعي). تُستخدم هذه القائمة لتنبيه المستخدم
    عند بدء تشغيل جديد بأن هناك رندراً متوقَّفاً يمكن استئنافه.
    """
    return sorted(p for p in search_root.glob(f"{TMP_PREFIX}*") if p.is_dir())


def save_backup(project_name: str, project_data: dict, live_tmp_dirs: list[Path]) -> Path:
    """
    يحفظ نسخة احتياطية كاملة (إعدادات + نسخ من tmp_dirs الحالية) لمشروع
    *project_name*، ويستبدل أي نسخة سابقة محفوظة له بالكامل.

    *project_data*  : dict إعدادات المشروع (نفس شكل project.flipa)
    *live_tmp_dirs* : مسارات مجلدات tmp_* الموجودة فعلياً على القرص الآن
                      (قبل بدء الرندر — عادة فاضية أو من تشغيل سابق منقطع)
    """
    bdir = _backup_dir(project_name)

    # نستبدل النسخة القديمة بالكامل — نسخة واحدة فقط محفوظة في كل وقت
    if bdir.exists():
        shutil.rmtree(bdir, ignore_errors=True)
    bdir.mkdir(parents=True, exist_ok=True)

    # 1) إعدادات المشروع
    (bdir / "project.flipa").write_text(
        json.dumps(project_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 2) نسخ مجلدات tmp_* الحالية (لو موجودة) — رندر متوقَّف من قبل
    tmp_backup_dir = bdir / "tmp"
    tmp_backup_dir.mkdir(parents=True, exist_ok=True)
    copied_names = []
    for src in live_tmp_dirs:
        if src.is_dir() and any(src.iterdir()):
            dest = tmp_backup_dir / src.name
            shutil.copytree(src, dest, dirs_exist_ok=True)
            copied_names.append(src.name)

    # 3) meta.json
    meta = {
        "project_name": project_name,
        "saved_at":     datetime.now().isoformat(timespec="seconds"),
        "tmp_scenes":   copied_names,
    }
    (bdir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return bdir


def has_backup(project_name: str) -> bool:
    return (_backup_dir(project_name) / "meta.json").exists()


def load_backup_info(project_name: str) -> BackupInfo | None:
    """يقرأ meta.json لنسخة احتياطية موجودة. يعيد None لو غير موجودة أو تالفة."""
    meta_path = _backup_dir(project_name) / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return BackupInfo(
        project_name=meta.get("project_name", project_name),
        saved_at=meta.get("saved_at", "—"),
        tmp_scenes=meta.get("tmp_scenes", []),
    )


def load_backup_project_data(project_name: str) -> dict | None:
    """يقرأ project.flipa المحفوظ داخل النسخة الاحتياطية. None لو غير موجود/تالف."""
    path = _backup_dir(project_name) / "project.flipa"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def restore_tmp_dirs(project_name: str, dest_root: Path = Path(".")) -> list[str]:
    """
    يستعيد مجلدات tmp_* المحفوظة في النسخة الاحتياطية إلى *dest_root*
    (المسار الذي يبدأ منه main.py عادة)، حتى يستأنف الرندر منها طبيعياً
    عبر آلية Resume الموجودة (_resume_start تتعرف عليها تلقائياً).

    يعيد قائمة أسماء المجلدات المُستعادة فعلياً.
    """
    tmp_backup_dir = _backup_dir(project_name) / "tmp"
    if not tmp_backup_dir.is_dir():
        return []

    restored = []
    for src in tmp_backup_dir.iterdir():
        if not src.is_dir():
            continue
        dest = dest_root / src.name
        if dest.exists():
            # لا نستبدل مجلد tmp حالي فعلاً موجود — أكثر أماناً
            continue
        shutil.copytree(src, dest)
        restored.append(src.name)

    return restored


def clear_backup(project_name: str) -> bool:
    """يحذف النسخة الاحتياطية بالكامل (تُستخدم بعد رندر ناجح كامل بلا مقاطعة)."""
    bdir = _backup_dir(project_name)
    if bdir.exists():
        shutil.rmtree(bdir, ignore_errors=True)
        return True
    return False
