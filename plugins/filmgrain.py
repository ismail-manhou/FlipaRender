"""
FlipaRender Plugin — Film Grain Effect

مؤثر يُضيف حبيبات فيلم (Film Grain) خفيفة على الفيديو النهائي — تأثير
سينمائي كلاسيكي يُستخدم غالباً مع فلتر "Cinematic" أو "Vintage" اللوني.

يُطبَّق عبر فلتر FFmpeg المدمج `noise` (لا يحتاج أي مكتبة خارجية إضافية)،
على الفيديو النهائي بعد الدمج الكامل، قبل دمج الصوت — وفق تصميم
VideoEffectPlugin في core/plugins.py.

⚠️ ملاحظة مهمة عن حجم الملف: فلتر noise يضيف عشوائية بصرية حقيقية لكل
فريم، وهذا النوع من المحتوى يصعب ضغطه بشدة (الـ compression الفيديوي
يعتمد أساساً على تشابه الفريمات المتتالية، والضوضاء العشوائية تكسر هذا
التشابه تماماً). النتيجة: حجم الملف قد يكبر بشكل ملحوظ جداً (عشرات
الأضعاف) مقارنة بالفيديو الأصلي، حتى مع -crf معقول. هذا سلوك متوقَّع
وطبيعي لفلاتر الضوضاء، وليس خللاً — لكن يُفضَّل تنبيه المستخدم به عند
استخدام شدة (intensity) مرتفعة على مشاريع طويلة.

مثال على بنية VideoEffectPlugin الرسمية لإضافة مؤثرات فيديو جديدة دون
لمس أي كود أساسي.
"""

import subprocess
from pathlib import Path

from core.plugins import VideoEffectPlugin


class FilmGrain(VideoEffectPlugin):
    name = "Film Grain"
    description = "حبيبات فيلم خفيفة على كل الفيديو — مظهر سينمائي كلاسيكي (قد يكبّر حجم الملف بشكل ملحوظ)"
    params = {
        "intensity": 12,   # شدة الحبيبات (FFmpeg noise strength)؛ 0-50 معقول، 8-20 خفيف وطبيعي
    }

    def apply(self, input_path: Path, output_path: Path, **params) -> None:
        intensity = int(params.get("intensity", self.params["intensity"]))
        intensity = max(0, min(50, intensity))

        if intensity <= 0:
            # بدون تأثير — ننسخ الملف كما هو دون إعادة ترميز
            output_path.write_bytes(Path(input_path).read_bytes())
            return

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(input_path),
            "-vf", f"noise=alls={intensity}:allf=t",
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",   # لا صوت بعد في هذه المرحلة أصلاً (يُدمَج لاحقاً)
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
