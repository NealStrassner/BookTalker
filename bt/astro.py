"""Astrology signs read aloud: the zodiac, the planets, the nodes and the aspects ('♀' is read
'Venus', '☍' 'opposition'), in the book's language. A sign drawn by a symbol font of its own
(the PDF keeps only a private code, U+F000-F0FF) is told by its shape against Windows' Segoe UI
Symbol (MEASURED in a Word-made astrology book: its AstroMtx Venus 0.88 like Segoe's ♀, the next
sign, Pallas, 0.77; its opposition 0.91 against 0.69)."""
import os
import re

LANGS = ("en", "es", "fr", "de", "it", "pt", "ru", "zh")
_TABLE = {
    "♈": "Aries|Aries|Bélier|Widder|Ariete|Áries|Овен|白羊座",
    "♉": "Taurus|Tauro|Taureau|Stier|Toro|Touro|Телец|金牛座",
    "♊": "Gemini|Géminis|Gémeaux|Zwillinge|Gemelli|Gêmeos|Близнецы|双子座",
    "♋": "Cancer|Cáncer|Cancer|Krebs|Cancro|Câncer|Рак|巨蟹座",
    "♌": "Leo|Leo|Lion|Löwe|Leone|Leão|Лев|狮子座",
    "♍": "Virgo|Virgo|Vierge|Jungfrau|Vergine|Virgem|Дева|处女座",
    "♎": "Libra|Libra|Balance|Waage|Bilancia|Libra|Весы|天秤座",
    "♏": "Scorpio|Escorpio|Scorpion|Skorpion|Scorpione|Escorpião|Скорпион|天蝎座",
    "♐": "Sagittarius|Sagitario|Sagittaire|Schütze|Sagittario|Sagitário|Стрелец|射手座",
    "♑": "Capricorn|Capricornio|Capricorne|Steinbock|Capricorno|Capricórnio|Козерог|摩羯座",
    "♒": "Aquarius|Acuario|Verseau|Wassermann|Acquario|Aquário|Водолей|水瓶座",
    "♓": "Pisces|Piscis|Poissons|Fische|Pesci|Peixes|Рыбы|双鱼座",
    "☉": "Sun|Sol|Soleil|Sonne|Sole|Sol|Солнце|太阳",
    "☽": "Moon|Luna|Lune|Mond|Luna|Lua|Луна|月亮",
    "☾": "Moon|Luna|Lune|Mond|Luna|Lua|Луна|月亮",
    "☿": "Mercury|Mercurio|Mercure|Merkur|Mercurio|Mercúrio|Меркурий|水星",
    "♀": "Venus|Venus|Vénus|Venus|Venere|Vênus|Венера|金星",
    "♁": "Earth|Tierra|Terre|Erde|Terra|Terra|Земля|地球",
    "♂": "Mars|Marte|Mars|Mars|Marte|Marte|Марс|火星",
    "♃": "Jupiter|Júpiter|Jupiter|Jupiter|Giove|Júpiter|Юпитер|木星",
    "♄": "Saturn|Saturno|Saturne|Saturn|Saturno|Saturno|Сатурн|土星",
    "♅": "Uranus|Urano|Uranus|Uranus|Urano|Urano|Уран|天王星",
    "⛢": "Uranus|Urano|Uranus|Uranus|Urano|Urano|Уран|天王星",
    "♆": "Neptune|Neptuno|Neptune|Neptun|Nettuno|Netuno|Нептун|海王星",
    "♇": "Pluto|Plutón|Pluton|Pluto|Plutone|Plutão|Плутон|冥王星",
    "⚷": "Chiron|Quirón|Chiron|Chiron|Chirone|Quíron|Хирон|凯龙星",
    "☊": "North Node|Nodo Norte|Nœud nord|Nordknoten|Nodo Nord|Nodo Norte|Северный узел|北交点",
    "☋": "South Node|Nodo Sur|Nœud sud|Südknoten|Nodo Sud|Nodo Sul|Южный узел|南交点",
    "⯓": "Pluto|Plutón|Pluton|Pluto|Plutone|Plutão|Плутон|冥王星",
    "⯔": "Pluto|Plutón|Pluton|Pluto|Plutone|Plutão|Плутон|冥王星",
    "⯕": "Pluto|Plutón|Pluton|Pluto|Plutone|Plutão|Плутон|冥王星",
    "⯖": "Pluto|Plutón|Pluton|Pluto|Plutone|Plutão|Плутон|冥王星",
    "🜨": "Earth|Tierra|Terre|Erde|Terra|Terra|Земля|地球",
    "⚳": "Ceres|Ceres|Cérès|Ceres|Cerere|Ceres|Церера|谷神星",
    "⚴": "Pallas|Palas|Pallas|Pallas|Pallade|Palas|Паллада|智神星",
    "⚵": "Juno|Juno|Junon|Juno|Giunone|Juno|Юнона|婚神星",
    "⚶": "Vesta|Vesta|Vesta|Vesta|Vesta|Vesta|Веста|灶神星",
    "⯰": "Eris|Eris|Éris|Eris|Eris|Éris|Эрида|阋神星",
    "⯱": "Eris|Eris|Éris|Eris|Eris|Éris|Эрида|阋神星",
    "⯲": "Sedna|Sedna|Sedna|Sedna|Sedna|Sedna|Седна|赛德娜",
    "⚸": "Black Moon Lilith|Luna Negra Lilith|Lune noire Lilith|Schwarzer Mond Lilith|Luna Nera Lilith|Lua Negra Lilith|Чёрная Луна Лилит|黑月莉莉丝",
    "⛎": "Ophiuchus|Ofiuco|Ophiuchus|Schlangenträger|Ofiuco|Ofiúco|Змееносец|蛇夫座",
    "🝴": "Lot of Fortune|Parte de la Fortuna|Part de Fortune|Glückspunkt|Parte di Fortuna|Parte da Fortuna|Парс Фортуны|福点",
    "☌": "conjunction|conjunción|conjonction|Konjunktion|congiunzione|conjunção|соединение|合相",
    "☍": "opposition|oposición|opposition|Opposition|opposizione|oposição|оппозиция|对冲",
    "⚹": "sextile|sextil|sextile|Sextil|sestile|sextil|секстиль|六分相",
    "⚺": "semi-sextile|semisextil|semi-sextile|Halbsextil|semisestile|semissextil|полусекстиль|十二分相",
    "⚼": "sesquiquadrate|sesquicuadratura|sesqui-carré|Anderthalbquadrat|sesquiquadrato|sesquiquadratura|полутораквадрат|八分之三相",
    "⚻": "quincunx|quincuncio|quinconce|Quinkunx|quinconce|quincúncio|квинконс|梅花相",
    "□": "square|cuadratura|carré|Quadrat|quadratura|quadratura|квадрат|四分相",
    "△": "trine|trígono|trigone|Trigon|trigono|trígono|трин|三分相",
    "∠": "semi-square|semicuadratura|semi-carré|Halbquadrat|semiquadrato|semiquadratura|полуквадрат|八分相",
    "⬠": "quintile|quintil|quintile|Quintil|quintile|quintil|квинтиль|五分相",
    "℞": "retrograde|retrógrado|rétrograde|rückläufig|retrogrado|retrógrado|ретроградный|逆行",
}
# shapes that are also checkboxes, triangles and angles: named only where the text is about the sky
SHAPES = "□△∠⬠"
NAMES = {c: dict(zip(LANGS, v.split("|"))) for c, v in _TABLE.items()}
# ♀ and ♂ are also biology's female and male: read so outside talk of the stars
SEXES = {"♀": dict(zip(LANGS, "female|hembra|femelle|weiblich|femmina|fêmea|самка|雌".split("|"))),
         "♂": dict(zip(LANGS, "male|macho|mâle|männlich|maschio|macho|самец|雄".split("|")))}
CHARS = re.compile("[" + "".join(NAMES) + "]")
# (not words a biology or medical text uses too: Sun, Moon, Earth, Mercury, Cancer, Leo,
# conjunction, opposition, node, square)
SKY_WORDS = re.compile(r"(?i)astrolog|horoscop|zodiac|planet|retrograd|\btrine|sextile|ascendant|\b(" + "|".join(
    sorted({re.escape(n["en"].lower()) for c, n in NAMES.items()
            if c not in "☉☽☾♁🜨☿♋♌☌☍℞☊☋" + SHAPES}, key=len, reverse=True)) + r")\b")


def about_the_sky(texts):
    """A passage that talks of the stars: another sign in it, or astrology's words."""
    joined = " ".join(texts)
    return bool(re.search("[" + "".join(c for c in NAMES if c not in "♀♂" + SHAPES) + "]", joined)
                or SKY_WORDS.search(joined))


def spoken(t, lang="en", sky=True):
    """A word holding signs, with each sign named ('15°♈' -> '15° Aries')."""
    def name(m):
        c = m.group()
        if c in SHAPES and not sky:
            return c
        table = SEXES[c] if c in SEXES and not sky else NAMES[c]
        return f" {table.get(lang, table['en'])} "
    s = " ".join(CHARS.sub(name, t.replace("\ufe0e", "").replace("\ufe0f", "")).split())
    return re.sub(r"([(\[]) | ([)\]])", r"\1\2", s)          # "(Venus)", not "( Venus )"


# ---- signs drawn by a symbol font --------------------------------------------------------------
SYMBOL_CODE = re.compile("[\uf000-\uf0ff]")
_REF = None
SIZE = 48
MATCH, MARGIN = 0.85, 0.1      # the shape must be this close, and this much closer than the next


def _shape(gray):
    """A grayscale picture (0 = black) of one sign -> its ink, cropped, squared, blurred, as a unit
    vector; ink touching the edges belongs to the letters beside it and is left out."""
    import cv2
    import numpy as np
    from PIL import Image, ImageFilter
    ink = np.asarray(gray, dtype=np.uint8) < 128
    n, lab = cv2.connectedComponents(ink.astype(np.uint8), connectivity=8)
    edge = set(lab[0]) | set(lab[-1]) | set(lab[:, 0]) | set(lab[:, -1])
    inner = [k for k in range(1, n) if k not in edge]
    if inner:
        sizes = np.bincount(lab.ravel())
        biggest = max(sizes[k] for k in inner)
        ink = np.isin(lab, [k for k in inner if sizes[k] >= 0.02 * biggest])
    ys, xs = np.nonzero(ink)
    if not len(xs):
        return None
    ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = ink.shape
    side = max(h, w)
    sq = np.zeros((side, side), dtype=np.uint8)
    sq[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = ink * 255
    im = Image.fromarray(sq).resize((SIZE, SIZE), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.8))
    v = np.asarray(im, dtype=np.float32).ravel()
    return v / (float(np.linalg.norm(v)) or 1.0)


def _references():
    global _REF
    if _REF is None:
        _REF = {}
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "seguisym.ttf")
        try:
            from PIL import Image, ImageDraw, ImageFont
            font = ImageFont.truetype(path, 96)

            def draw(c):
                im = Image.new("L", (192, 192), 255)
                ImageDraw.Draw(im).text((48, 24), c, font=font, fill=0)
                return _shape(im)
            missing = draw(chr(0xE0FF))                 # (the box the font draws for a sign it lacks)
            for c in NAMES:
                v = draw(c)
                if v is not None and (missing is None or float(v @ missing) < 0.98):
                    _REF[c] = v
        except (OSError, ImportError):
            pass
    return _REF


def identify(gray):
    """A picture of one symbol-font glyph -> the sign it shows, or None."""
    ref = _references()
    v = _shape(gray) if ref else None
    if v is None:
        return None
    scores = sorted(((float(v @ r), c) for c, r in ref.items()), reverse=True)
    best, second = scores[0], scores[1] if len(scores) > 1 else (0.0, "")
    return best[1] if best[0] >= MATCH and best[0] - second[0] >= MARGIN else None


def fix_symbol_fonts(page, words):
    """get_text("words") tuples with each symbol-font glyph that is an astrology sign written as
    that sign (others stay as they are)."""
    import pymupdf
    from PIL import Image
    found = []                                  # (center x, center y, code, sign)
    seen = {}
    for b in page.get_text("rawdict")["blocks"]:
        for line in b.get("lines", []):
            for span in line["spans"]:
                for ch in span["chars"]:
                    if not SYMBOL_CODE.match(ch["c"]):
                        continue
                    r = pymupdf.Rect(ch["bbox"])
                    if r.is_empty or r.height < 2:
                        continue
                    key = (span["font"], ch["c"])
                    if key not in seen:             # (one font's code is one sign throughout)
                        pad = 0.15 * r.height
                        clip = pymupdf.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
                        dpi = int(min(600, max(150, 72 * 80 / r.height)))
                        pm = page.get_pixmap(clip=clip, dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
                        seen[key] = identify(Image.frombytes("L", (pm.width, pm.height), pm.samples))
                    if seen[key]:
                        found.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, ch["c"], seen[key]))
    if not found:
        return words
    out = []
    for w in words:
        t = w[4]
        if SYMBOL_CODE.search(t):
            mine = sorted((x, code, sign) for x, y, code, sign in found if w[0] <= x <= w[2] and w[1] <= y <= w[3])
            for _x, code, sign in mine:
                t = t.replace(code, sign, 1)
        out.append(w[:4] + (t,) + tuple(w[5:]) if t != w[4] else w)
    return out
