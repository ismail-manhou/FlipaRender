"""
FlipaRender v6 — Color Grading
"""

from PIL import Image, ImageEnhance


def apply_grade(img: Image.Image, grade: dict) -> Image.Image:
    """
    Apply color-grading parameters from *grade* to *img*.

    Expected keys: brightness, contrast, color, sharpness, tint.
    When grade["name"] == "Original" the image is returned untouched.

    FIX #5: الدالة تعمل على نسخة RGB داخلياً وتُعيد RGBA فقط عند وجود tint،
    مما يتجنب دورتَي تحويل عند استدعائها من render_frames.
    المتصل مسؤول عن .convert("RGB") النهائي عند الحفظ.
    """
    if grade.get("name") == "Original":
        return img

    # العمليات الأربع تعمل على RGB فقط
    work = img.convert("RGB")
    work = ImageEnhance.Brightness(work).enhance(grade["brightness"])
    work = ImageEnhance.Contrast(work).enhance(grade["contrast"])
    work = ImageEnhance.Color(work).enhance(grade["color"])
    work = ImageEnhance.Sharpness(work).enhance(grade["sharpness"])

    tint = grade.get("tint")
    if tint:
        # Blend a colored overlay for warm/cool tint effects
        # النتيجة تبقى RGBA — المتصل يُحوّلها لـ RGB عند الحفظ
        overlay = Image.new("RGBA", work.size, tint)
        work = Image.alpha_composite(work.convert("RGBA"), overlay)

    return work
