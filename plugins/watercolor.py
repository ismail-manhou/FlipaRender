"""
FlipaRender Plugin — Watercolor Filter

فلتر يُحاكي مظهر الألوان المائية: تنعيم خفيف (يُذيب الحواف الحادة قليلاً)
مع رفع التشبّع اللوني — تأثير شائع في الأنيميشن المرسوم يدوياً.

مثال على بنية ImageFilterPlugin الرسمية المطلوبة من المستخدم لإضافة
فلاتر جديدة دون تعديل أي كود أساسي في FlipaRender.
"""

from PIL import Image, ImageEnhance, ImageFilter

from core.plugins import ImageFilterPlugin


class Watercolor(ImageFilterPlugin):
    name = "Watercolor"
    description = "تنعيم الحواف + رفع التشبّع اللوني، يحاكي مظهر الألوان المائية"
    params = {
        "strength": 0.5,   # 0.0 (بدون تأثير) إلى 1.0 (تأثير كامل)
    }

    def apply(self, image: Image.Image, **params) -> Image.Image:
        strength = max(0.0, min(1.0, params.get("strength", self.params["strength"])))
        if strength <= 0.0:
            return image

        work = image.convert("RGB")

        # تنعيم خفيف يُذيب الحواف الحادة (شدة البلور تتناسب مع strength)
        blur_radius = 0.5 + strength * 1.5
        blurred = work.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        # رفع التشبّع اللوني لمحاكاة كثافة الألوان المائية
        saturated = ImageEnhance.Color(blurred).enhance(1.0 + strength * 0.4)

        # دمج تدريجي بين الأصل والنتيجة المعالَجة حسب strength
        return Image.blend(work, saturated, alpha=strength)
