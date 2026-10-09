"""BookTalker art, drawn in code: a page with one lit word, golden sound waves rising
from it, on a deep night-blue field. Writes art/hero.png and art/about.png."""
import math
import os
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = (242, 179, 61)
GOLD_HI = (255, 214, 120)


def field(w, h, glow_xy, rng):
    """Night-blue background with a warm glow and fine grain (no banding)."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.zeros((h, w, 3), np.float32)
    top = np.array([16, 21, 33], np.float32)
    bottom = np.array([9, 11, 17], np.float32)
    t = (y / h)[..., None]
    base += top * (1 - t) + bottom * t
    gx, gy = glow_xy
    d = np.sqrt(((x - gx) / w) ** 2 + ((y - gy) / h) ** 2 * 1.6)
    warm = np.clip(1 - d / 0.55, 0, 1) ** 2.2
    base += warm[..., None] * np.array([70, 48, 18], np.float32)
    cool = np.clip(1 - np.sqrt(((x - w * 0.15) / w) ** 2 + ((y + h * 0.2) / h) ** 2) / 0.9, 0, 1) ** 2
    base += cool[..., None] * np.array([14, 22, 44], np.float32)
    base += rng.normal(0, 1.6, (h, w, 1)).astype(np.float32)
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


def glow_layer(w, h, draw_fn, blurs=((0, 1.0), (6, 0.9), (24, 0.7), (70, 0.55))):
    """Draw shapes once, stack several blurs of them -> soft light."""
    sharp = Image.new("RGB", (w, h), (0, 0, 0))
    draw_fn(ImageDraw.Draw(sharp))
    out = Image.new("RGB", (w, h), (0, 0, 0))
    for r, k in blurs:
        layer = sharp.filter(ImageFilter.GaussianBlur(r)) if r else sharp
        out = ImageChops.add(out, Image.eval(layer, lambda v, k=k: int(v * k)))
    return out


def page_card(w, h, ss, line_rng):
    """A tilted page with grey text lines and one gold-highlighted word."""
    pw, ph = int(w * 0.25), int(w * 0.25 * 1.32)
    S = ss
    img = Image.new("RGBA", (pw * S, ph * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, pw * S - 1, ph * S - 1], radius=10 * S, fill=(246, 243, 236, 255))
    m = int(pw * 0.11) * S
    y = int(ph * 0.12) * S
    lh = int(ph * 0.052) * S
    hi_line = 6
    k = 0
    hl = None
    while y < ph * S - m:
        para_end = line_rng.random() < 0.11
        length = (pw * S - 2 * m) * (line_rng.uniform(0.35, 0.7) if para_end else line_rng.uniform(0.9, 1.0))
        x = m
        words = []
        while x < m + length:
            ww = line_rng.uniform(0.05, 0.16) * pw * S
            words.append((x, min(x + ww, m + length)))
            x += ww + 0.025 * pw * S
        if k == hi_line - 1:
            d.rounded_rectangle([m - 6 * S, y - lh * 0.42, m + length + 6 * S, y + lh * 0.42],
                                radius=6 * S, fill=(255, 238, 196, 255))
        for i, (a, b) in enumerate(words):
            col = (150, 156, 168, 255)
            if k == hi_line - 1 and i == 2:
                d.rounded_rectangle([a - 5 * S, y - lh * 0.40, b + 5 * S, y + lh * 0.40], radius=6 * S, fill=GOLD + (255,))
                col = (40, 34, 20, 255)
                hl = ((a + b) / 2 / S, y / S)
            d.rounded_rectangle([a, y - lh * 0.14, b, y + lh * 0.14], radius=int(lh * 0.14), fill=col)
        y += lh * (1.9 if para_end else 1.0)
        k += 1
    img = img.resize((pw, ph), Image.LANCZOS)
    return img, hl


def waves(d, w, h, origin, rng, scale=1.0):
    """Golden ribbons: sine waves fanning up-left from the lit word."""
    ox, oy = origin
    for i in range(9):
        amp = (18 + i * 9) * scale
        freq = 0.0105 / scale * (1 + i * 0.03)
        phase = rng.uniform(0, math.tau)
        rise = -0.16 - i * 0.045
        width = max(1, int((3.2 - i * 0.25) * scale))
        b = 0.95 - i * 0.085
        col = tuple(int(c * b) for c in (GOLD_HI if i < 3 else GOLD))
        pts = []
        for s in range(0, int(w * 0.95), 4):
            x = ox - s
            env = math.sin(min(1.0, s / (w * 0.85)) * math.pi) ** 0.9
            y = oy + rise * s + amp * env * math.sin(s * freq + phase)
            pts.append((x, y))
        d.line(pts, fill=col, width=width, joint="curve")


def particles(d, w, h, n, rng, region):
    x0, y0, x1, y1 = region
    for _ in range(n):
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        r = rng.choice([1, 1, 1, 2, 2, 3])
        b = rng.uniform(0.35, 1.0)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(int(c * b) for c in GOLD_HI))


def compose(w, h, page_xy, seed, name, page_scale=1.0):
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    px, py = page_xy
    img = field(w, h, (px + w * 0.08, py + h * 0.1), nrng).convert("RGBA")
    card, hl = page_card(int(w * page_scale), h, 3, random.Random(seed + 1))
    cw, ch = card.size
    card = card.rotate(-8, resample=Image.BICUBIC, expand=True)
    th = math.radians(8)            # where the lit word lands after the tilt
    dx, dy = hl[0] - cw / 2, hl[1] - ch / 2
    word = (card.width / 2 + math.cos(th) * dx - math.sin(th) * dy,
            card.height / 2 + math.sin(th) * dx + math.cos(th) * dy)
    # soft shadow under the page
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    a = card.split()[3].point(lambda v: int(v * 0.75))
    sh.paste((0, 0, 0, 255), (int(px + 18), int(py + 34)), a)
    sh = sh.filter(ImageFilter.GaussianBlur(28))
    img = Image.alpha_composite(img, sh)
    # light pooling around the page
    halo = glow_layer(w, h, lambda d: d.ellipse([px - 60, py - 40, px + card.width + 60, py + card.height + 40],
                                                fill=(60, 42, 14)), blurs=((90, 1.0),))
    img = Image.fromarray(np.clip(np.asarray(img.convert("RGB"), np.int16) + np.asarray(halo, np.int16), 0, 255).astype(np.uint8)).convert("RGBA")
    img.alpha_composite(card, (int(px), int(py)))
    # waves rise from the lit word (top-left area of the page)
    origin = (px + word[0], py + word[1])
    k = w / 2560                    # glow scales with the picture
    light = glow_layer(w, h, lambda d: (waves(d, w, h, origin, rng, scale=k),
                                        particles(d, w, h, int(160 * k + 40), rng, (w * 0.25, h * 0.02, w * 0.95, h * 0.75))),
                       blurs=((0, 1.0), (6 * k, 0.9), (24 * k, 0.7), (70 * k, 0.55)))
    base = np.asarray(img.convert("RGB"), np.float32) / 255
    li = np.asarray(light, np.float32) / 255
    out = 1 - (1 - base) * (1 - li)          # screen blend
    Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).save(os.path.join(HERE, name), optimize=True)


if __name__ == "__main__":
    compose(2560, 1720, (1720, 700), 11, "hero.png", page_scale=0.92)
    compose(1240, 470, (860, 150), 5, "about.png", page_scale=1.25)
    print("ok")
