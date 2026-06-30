# FlipaRender v6

تحويل مجلدات صور PNG إلى فيديو MP4 مع تصحيح الألوان.

## المتطلبات

```
pip install Pillow
pkg install ffmpeg   # Termux
```

## التشغيل

```
python main.py
```

## الملفات

```
FlipaRender_v6/
├── main.py              # نقطة الدخول
├── config.py            # الإعدادات (دقة، فريمات، ألوان)
├── core/
│   ├── scanner.py       # البحث عن مشاريع PNG
│   └── security.py      # التحقق من المسارات
├── render/
│   ├── frames.py        # معالجة الصور
│   ├── grading.py       # تصحيح الألوان
│   └── video.py         # تصدير MP4 عبر ffmpeg
├── ai/
│   └── inbetween.py     # توليد فريمات وسيطة (AI)
└── ui/
    └── cli.py           # واجهة الأوامر (ألوان، شريط تقدم)
```

## درجات الألوان المتوفرة

| المفتاح    | الاسم        |
|------------|--------------|
| `none`     | Original     |
| `anime`    | Anime        |
| `cinematic`| Cinematic    |
| `noir`     | Noir         |
| `warm`     | Warm Glow    |
| `cold`     | Cold Steel   |
| `vintage`  | Vintage      |

## دقة الإخراج

| المفتاح | الوصف         |
|---------|---------------|
| `hd`    | HD 720p       |
| `fhd`   | Full HD 1080p |
| `4k`    | 4K UHD        |
| `sq`    | مربع 1:1      |
| `vt`    | عمودي 9:16    |
