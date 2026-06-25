"""
FlipaRender v10 — Audio Support  (core/audio.py)

اكتشاف ملف الصوت داخل مجلد المشروع ودمجه مع الفيديو النهائي عبر FFmpeg.

هيكل المجلد المتوقع::

    <project_root>/
    ├── Walk/              ← مشهد
    ├── Jump/              ← مشهد
    └── audio/
        └── soundtrack.mp3   (أو .wav / .ogg)

لو وُجد أكثر من ملف صوت واحد داخل audio/، يُعرَض للمستخدم ليختار أيّها.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

AUDIO_DIR_NAME     = "audio"
SUPPORTED_AUDIO_EXT = (".mp3", ".wav", ".ogg")


@dataclass
class AudioTrack:
    path:        Path
    duration_s:  float | None   # None لو تعذّر قياسها (ffprobe غير متاح مثلاً)
    size_mb:     float


def find_audio_dir(project_root: str | Path) -> Path | None:
    """يبحث عن مجلد audio/ داخل مجلد المشروع. يعيد المسار أو None لو غير موجود."""
    candidate = Path(project_root) / AUDIO_DIR_NAME
    return candidate if candidate.is_dir() else None


def list_audio_files(project_root: str | Path) -> list[Path]:
    """
    يرجع كل ملفات الصوت المدعومة (mp3/wav/ogg) داخل audio/ بالمشروع،
    مرتّبة أبجدياً. قائمة فاضية لو المجلد غير موجود أو لا يحتوي صوتاً مدعوماً.
    """
    audio_dir = find_audio_dir(project_root)
    if audio_dir is None:
        return []

    files = [
        p for p in sorted(audio_dir.iterdir())
        if p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_EXT
    ]
    return files


def probe_duration(path: str | Path) -> float | None:
    """
    يستخدم ffprobe لقياس مدة ملف الصوت بالثواني. يعيد None لو ffprobe
    غير متاح أو فشل القياس (لا يوقف البرنامج أبداً — الميزة اختيارية).
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError, FileNotFoundError):
        pass
    return None


def describe_audio_track(path: Path) -> AudioTrack:
    """يبني AudioTrack بمعلومات المدة والحجم لملف صوت معيّن."""
    size_mb = path.stat().st_size / (1024 * 1024)
    duration = probe_duration(path)
    return AudioTrack(path=path, duration_s=duration, size_mb=size_mb)


def format_duration(seconds: float | None) -> str:
    """تنسيق مدة بالثواني إلى mm:ss للعرض في الواجهة."""
    if seconds is None:
        return "—"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m:02d}:{s:02d}"


# ── دمج الصوت مع الفيديو عبر FFmpeg ─────────────────────────────────────────

def mux_audio(
    video_path: str | Path,
    audio_path: str | Path,
    out_path: str | Path,
    mode: str = "match_video",
) -> None:
    """
    يدمج *audio_path* مع *video_path* وينتج *out_path* عبر FFmpeg.

    *mode*:
      "match_video" : الفيديو والصوت كما هما — يتوقف الإخراج عند نهاية
                      أقصرهما (الأسرع — لا إعادة ترميز للفيديو، الافتراضي).
      "match_audio" : يمدّد الفيديو (يكرر آخر فريم) حتى نهاية الصوت كاملاً
                      (يتطلب إعادة ترميز الفيديو).
      "audio_loop"  : يكرر الصوت في حلقة حتى نهاية الفيديو كاملاً
                      (مناسب لموسيقى خلفية أقصر من الفيديو — لا إعادة ترميز).

    يرفع subprocess.CalledProcessError لو فشل FFmpeg.
    """
    video_path = Path(video_path)
    audio_path = Path(audio_path)
    out_path   = Path(out_path)

    base = ["ffmpeg", "-y", "-loglevel", "error"]

    if mode == "match_audio":
        # نمدّد آخر فريم من الفيديو حتى نهاية الصوت — يحتاج إعادة ترميز الفيديو
        cmd = base + [
            "-i", str(video_path),
            "-i", str(audio_path),
            "-vf", "tpad=stop_mode=clone:stop_duration=99999",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",   # الفيديو الممدَّد أطول من الصوت الآن، فيتوقف على طول الصوت
            str(out_path),
        ]

    elif mode == "audio_loop":
        # نكرر الصوت في حلقة لا نهائية ونوقفه عند نهاية الفيديو — بدون إعادة ترميز
        cmd = base + [
            "-i", str(video_path),
            "-stream_loop", "-1", "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",   # الصوت يتكرر بلا حدود، فيتوقف على طول الفيديو
            str(out_path),
        ]

    else:  # "match_video" — الافتراضي
        cmd = base + [
            "-i", str(video_path),
            "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",   # يتوقف عند نهاية أقصرهما (الفيديو عادة)
            str(out_path),
        ]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
