"""art\\banner.png: the README's banner (and GitHub's link preview, 2:1), made from the app's own
artwork (art\\hero.png), logo and display font.

    .venv\\Scripts\\python.exe tools\\make_banner.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 2560, 1280
GOLD, TEXT, TEXT_2 = (242, 179, 61), (236, 239, 244), (163, 172, 188)
FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def font(name, size, weight=None):
    f = ImageFont.truetype(os.path.join(FONTS, name), size)
    if weight:
        try:
            f.set_variation_by_name(weight)
        except (OSError, ValueError):
            pass
    return f


def spaced(draw, xy, text, f, fill, gap):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + gap


def main():
    hero = Image.open(os.path.join(ROOT, "art", "hero.png")).convert("RGB")
    img = hero.crop((0, 320, W, 320 + H))
    # the left side darkened under the words (the threads still show through)
    shade = Image.new("L", (W, H))
    for x in range(W):
        shade.paste(int(200 * max(0.0, 1 - x / 1500) ** 1.4), (x, 0, x + 1, H))
    img = Image.composite(Image.new("RGB", (W, H), (9, 12, 22)), img, shade)

    d = ImageDraw.Draw(img)
    logo = Image.open(os.path.join(ROOT, "art", "logo_256.png")).convert("RGBA").resize((150, 150), Image.LANCZOS)
    img.paste(logo, (170, 300), logo)
    spaced(d, (350, 350), "READ ALONG  ·  ANY LANGUAGE  ·  OFFLINE", font("bahnschrift.ttf", 44, "SemiBold"), GOLD, 7)
    d.text((160, 470), "BookTalker", font=font("bahnschrift.ttf", 250, "SemiBold"), fill=TEXT)
    tag = font("segoeui.ttf", 64)
    d.text((172, 760), "Your books, read aloud — every word", font=tag, fill=TEXT_2)
    d.text((172, 842), "lit up the moment it is spoken.", font=tag, fill=TEXT_2)
    what = font("segoeuib.ttf", 50)
    d.text((174, 975), "Read aloud  ·  Translate out loud  ·  Make MP3 audiobooks", font=what, fill=TEXT)
    d.text((174, 1060), "Free  ·  Open source  ·  Windows 10 and 11", font=what, fill=GOLD)
    out = os.path.join(ROOT, "art", "banner.png")                  # drawn large, kept at 1600 wide
    img.resize((1600, 800), Image.LANCZOS).save(out, optimize=True)
    preview = os.path.join(ROOT, "release", "social-preview.png")  # GitHub's link preview: 1280x640, under 1 MB
    os.makedirs(os.path.dirname(preview), exist_ok=True)
    img.resize((1280, 640), Image.LANCZOS).save(preview, optimize=True)
    print(out, os.path.getsize(out), preview, os.path.getsize(preview))


if __name__ == "__main__":
    main()
