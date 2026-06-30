"""
FlipaRender Plugin — Comic Filter

فلتر يُحاكي مظهر القصص الهزلية (Comic Book): تقوية الحواف السوداء + تبسيط
الألوان لمستويات محدودة (Posterize) — تأثير شائع في الأنيميشن ذو الطابع
الكوميكسي/الكارتوني الصريح.

مثال ثانٍ على بنية ImageFilterPlugin لإضافة فلاتر جديدة دون لمس الكود
الأساسي.
"""

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from core.plugins import ImageFilterPlugin


class Comic(ImageFilterPlugin):
    name = "Comic"
    description = "حواف سوداء بارزة + تبسيط الألوان لمستويات محدودة، مظهر كوميكس"
    params = {
        "edge_strength": 0.6,   # 0.0 (بدون حواف) إلى 1.0 (حواف قوية جداً)
        "posterize_bits": 4,    # عدد البتات لكل قناة لون (2-8)؛ أقل = ألوان أبسط
    }

    def apply(self, image: Image.Image, **params) -> Image.Image:
        edge_strength = max(0.0, min(1.0, params.get("edge_strength", self.params["edge_strength"])))
        bits = int(params.get("posterize_bits", self.params["posterize_bits"]))
        bits = max(2, min(8, bits))

        work = image.convert("RGB")

        # تبسيط الألوان لمستويات محدودة (المظهر الكارتوني المسطّح)
        posterized = ImageOps.posterize(work, bits)

        if edge_strength <= 0.0:
            return posterized

        # استخراج خريطة الحواف وتحويلها لخطوط سوداء تُرسَم فوق الصورة المبسَّطة
        edges = work.convert("L").filter(ImageFilter.FIND_EDGES)
        edges = ImageEnhance.Contrast(edges).enhance(1.0 + edge_strength * 2.0)
        # عتبة: أي بكسل حافة واضح يصبح أسود تماماً، الباقي شفاف (لا تأثير)
        edge_mask = edges.point(lambda p: 255 if p > (255 - edge_strength * 180) else 0)

        black_lines = Image.new("RGB", work.size, (0, 0, 0))
        result = Image.composite(black_lines, posterized, edge_mask)

        return result
