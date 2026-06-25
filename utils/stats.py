"""
FlipaRender v10 — Render Statistics  (utils/stats.py)

يجمع إحصائيات أثناء الرندر ويطبع تقريراً نهائياً منسّقاً.

استخدام:

    from utils.stats import RenderStats

    stats = RenderStats()
    stats.start()

    for frame in frames:
        t0 = stats.frame_start()
        ... process frame ...
        stats.frame_end(t0, from_cache=False, ai_generated=False)

    stats.finish(output_path)
    print(stats.report(fps=12, resolution="1920x1080"))
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RenderStats:
    total_frames:        int = 0
    ai_generated_frames: int = 0
    cache_hits:          int = 0
    scenes_rendered:     int = 0
    scenes_failed:       int = 0

    _t_start:        float = field(default=0.0, repr=False)
    _t_end:          float = field(default=0.0, repr=False)
    _frame_times:    list  = field(default_factory=list, repr=False)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._t_start = time.monotonic()

    def finish(self) -> None:
        self._t_end = time.monotonic()

    # ── per-frame tracking ───────────────────────────────────────────────────

    def frame_start(self) -> float:
        return time.monotonic()

    def frame_end(self, t0: float, from_cache: bool = False, ai_generated: bool = False) -> None:
        elapsed = time.monotonic() - t0
        self._frame_times.append(elapsed)
        self.total_frames += 1
        if from_cache:
            self.cache_hits += 1
        if ai_generated:
            self.ai_generated_frames += 1

    # ── scene tracking ───────────────────────────────────────────────────────

    def scene_done(self, success: bool) -> None:
        if success:
            self.scenes_rendered += 1
        else:
            self.scenes_failed += 1

    # ── derived metrics ──────────────────────────────────────────────────────

    @property
    def elapsed_seconds(self) -> float:
        end = self._t_end if self._t_end else time.monotonic()
        return end - self._t_start

    @property
    def avg_frame_time(self) -> float:
        if not self._frame_times:
            return 0.0
        return sum(self._frame_times) / len(self._frame_times)

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def _fmt_size(path: Path) -> str:
        if not path.exists():
            return "—"
        size_mb = path.stat().st_size / (1024 * 1024)
        return f"{size_mb:.1f} MB"

    # ── report ────────────────────────────────────────────────────────────────

    def report(
        self,
        fps: int,
        resolution: str,
        output_path: Path | None = None,
        video_duration_seconds: float | None = None,
    ) -> str:
        """
        يبني تقرير نصي جاهز للطباعة في الطرفية.
        """
        lines = []
        lines.append("═" * 38)
        lines.append("   Render Complete")
        lines.append("═" * 38)
        lines.append(f"  Frames        : {self.total_frames}")
        lines.append(f"  Scenes        : {self.scenes_rendered}"
                      + (f"  (failed: {self.scenes_failed})" if self.scenes_failed else ""))
        if video_duration_seconds is not None:
            lines.append(f"  Duration      : {video_duration_seconds:.1f} sec")
        lines.append(f"  FPS           : {fps}")
        lines.append(f"  Resolution    : {resolution}")
        if output_path is not None:
            lines.append(f"  Output Size   : {self._fmt_size(output_path)}")
        lines.append(f"  Time Taken    : {self._fmt_duration(self.elapsed_seconds)}")
        lines.append("-" * 38)
        lines.append(f"  Avg/Frame     : {self.avg_frame_time*1000:.0f} ms")
        if self.ai_generated_frames:
            lines.append(f"  AI Frames     : {self.ai_generated_frames}")
        if self.cache_hits:
            lines.append(f"  Cache Hits    : {self.cache_hits}")
        lines.append("═" * 38)
        return "\n".join(lines)

    def as_dict(self) -> dict:
        """نسخة قابلة للتسلسل (JSON) — مفيدة للّوغ أو project file لاحقاً."""
        return {
            "total_frames":        self.total_frames,
            "ai_generated_frames": self.ai_generated_frames,
            "cache_hits":          self.cache_hits,
            "scenes_rendered":     self.scenes_rendered,
            "scenes_failed":       self.scenes_failed,
            "elapsed_seconds":     round(self.elapsed_seconds, 2),
            "avg_frame_time_ms":   round(self.avg_frame_time * 1000, 1),
        }
