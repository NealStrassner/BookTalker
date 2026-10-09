"""Stage 1 — layout. Surya's layout model labels page regions; PyMuPDF supplies every
word with its box. Each word is assigned to the region that contains it, so every
spoken word keeps its rectangle on the page for highlighting.

Page result (JSON-able):
    {"blocks": [{"label": str, "top": float, "bottom": float,
                 "words": [[x0, y0, x1, y1, text, line_id, n], ...]}, ...],
     "height": float}
Blocks come in reading order (the PDF's own text order); n is the word's index in
PyMuPDF's natural order, used as a stable id.
"""
import hashlib
import json
import os
import re
import threading
import time
import unicodedata

import pymupdf
from PIL import Image

from .paths import resource

LAYOUT_DPI = 96
CACHE_VERSION = 13      # 2: CJK split; 3: scans OCR'd; 4: broken layers re-OCR'd; 5: scans' layers checked; 6: Greek/Arabic/Thai... readers; 7: no line flipping; 8: comic panels; 9: manga, OCR junk floor; 10: reader per page, broken fonts, Korean words; 11: Tesseract readers; 12: code kept (bt/code.py); 13: exact words of converted books
SKIP_LABELS = {"PageHeader", "PageFooter", "Picture", "Figure", "Table", "Form",
               "Equation", "ChemicalBlock", "Diagram", "TableOfContents",
               "Bibliography", "BlankPage", "Handwriting"}
MARGIN_BAND = 0.07   # top/bottom fraction of the page treated as header/footer zone
KEEP_ASIDE = {"PageHeader", "PageFooter", "TableOfContents"}   # kept in the cache, never spoken


def cache_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "BookTalker", "cache")
    os.makedirs(d, exist_ok=True)
    return d


def doc_id(path):
    st = os.stat(path)
    # realpath: one id however the path is spelled (8.3 short names, different case)
    key = f"{os.path.realpath(path).lower()}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


RELABEL = {"Caption": "Caption", "Footnote": "Footnote", "Equation-Block": "Equation",
           "List-Group": "ListGroup", "Page-Header": "PageHeader", "Page-Footer": "PageFooter",
           "Image": "Picture", "Section-Header": "SectionHeader", "Table": "Table", "Text": "Text",
           "Complex-Block": "Figure", "Code-Block": "Code", "Form": "Form",
           "Table-Of-Contents": "TableOfContents", "Figure": "Figure",
           "Chemical-Block": "ChemicalBlock", "Diagram": "Diagram",
           "Bibliography": "Bibliography", "Blank-Page": "BlankPage"}
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


class Box:
    __slots__ = ("bbox", "label", "confidence")

    def __init__(self, bbox, label, confidence):
        self.bbox, self.label, self.confidence = bbox, label, confidence


class Layout:
    __slots__ = ("bboxes",)

    def __init__(self, bboxes):
        self.bboxes = bboxes


class LayoutModel:
    """Surya's rf-detr page-layout model (exported to ONNX by tools/export_layout_onnx.py),
    run with onnxruntime. Same pre/post-processing as surya: ImageNet-normalise, resize to
    the model resolution, sigmoid top-k, threshold 0.4, merge same-label contained boxes."""

    THRESHOLD = 0.4
    CONTAIN = 0.9

    def __init__(self):
        import numpy as np
        import onnxruntime as ort
        self.np = np
        meta = json.load(open(resource("models", "layout.json"), encoding="utf-8"))
        self.res, self.num_select = meta["resolution"], meta["num_select"]
        self.labels = [RELABEL.get(l, l) for l in meta["labels"]]
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(2, (os.cpu_count() or 4) // 2)
        self.sess = ort.InferenceSession(resource("models", "layout.onnx"), opts,
                                         providers=["CPUExecutionProvider"])
        self.mean = np.array(MEAN, np.float32).reshape(3, 1, 1)
        self.std = np.array(STD, np.float32).reshape(3, 1, 1)

    def _one(self, img):
        np = self.np
        w, h = img.size
        x = np.asarray(img.convert("RGB").resize((self.res, self.res), Image.BILINEAR), np.float32) / 255.0
        x = ((x.transpose(2, 0, 1) - self.mean) / self.std)[None].astype(np.float32)
        logits, boxes = self.sess.run(None, {"image": x})
        prob = 1 / (1 + np.exp(-logits[0]))                     # [Q, C]
        flat = prob.reshape(-1)
        top = np.argpartition(-flat, self.num_select)[:self.num_select]
        top = top[np.argsort(-flat[top])]
        q, c = np.divmod(top, prob.shape[1])
        cx, cy, bw, bh = boxes[0][q].T
        bw, bh = np.clip(bw, 0, None), np.clip(bh, 0, None)
        xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], 1) * [w, h, w, h]
        out = [Box([float(v) for v in xyxy[i]], self.labels[c[i]], float(flat[top[i]]))
               for i in range(len(top)) if flat[top[i]] > self.THRESHOLD]
        return Layout(self._merge_contained(out))

    def _merge_contained(self, boxes):
        """Drop a box that lies (90%+) inside a larger box with the same label (as surya)."""
        def area(b):
            return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        keep = []
        for b in sorted(boxes, key=lambda x: area(x.bbox), reverse=True):
            a = area(b.bbox)
            absorbed = False
            for s in keep:
                if s.label != b.label or a == 0:
                    continue
                sb, bb = s.bbox, b.bbox
                ix = max(0.0, min(sb[2], bb[2]) - max(sb[0], bb[0]))
                iy = max(0.0, min(sb[3], bb[3]) - max(sb[1], bb[1]))
                if ix * iy / a >= self.CONTAIN:
                    s.bbox = [min(sb[0], bb[0]), min(sb[1], bb[1]), max(sb[2], bb[2]), max(sb[3], bb[3])]
                    absorbed = True
                    break
            if not absorbed:
                keep.append(b)
        return keep

    def detect(self, images):
        return [self._one(im) for im in images]


def _is_scan(page):
    """A page that is one big picture (a scan), whatever text layer lies over it."""
    area = page.rect.width * page.rect.height
    try:
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            if (x1 - x0) * (y1 - y0) >= 0.6 * area:
                return True
    except Exception:
        pass
    return False


def page_image(page):
    pm = page.get_pixmap(dpi=LAYOUT_DPI)
    return Image.frombytes("RGB", (pm.width, pm.height), pm.samples)


CJK_CHAR = re.compile(r"[　-ヿ㐀-䶿一-鿿豈-﫿가-힯＀-￯]")


SPLIT_CHAR = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")   # written without spaces: Chinese, Japanese


def split_cjk(word):
    """Chinese/Japanese/Korean lines arrive as one long 'word' (no spaces). Split into
    one box per character (runs of Latin letters/digits stay together), so each
    character can be highlighted and sentences can end mid-line at 。！？"""
    x0, y0, x1, y1, text = word[:5]
    if not SPLIT_CHAR.search(text) or len(text) < 2:
        return [(x0, y0, x1, y1, text)]
    tokens = re.findall(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]|[^\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]+", text)   # (Korean keeps its words)
    widths = [len(t) if CJK_CHAR.match(t) else len(t) * 0.55 for t in tokens]
    vertical = (y1 - y0) > 1.5 * (x1 - x0)            # a column of vertical Japanese/Chinese
    a0, a1 = (y0, y1) if vertical else (x0, x1)
    unit = (a1 - a0) / max(sum(widths), 1e-6)
    out, a = [], a0
    for t, wdt in zip(tokens, widths):
        na = a + wdt * unit
        if t.strip():
            out.append((x0, a, x1, na, t) if vertical else (a, y0, na, y1, t))
        a = na
    return out


KANA_ONLY = re.compile(r"^[぀-ヿー]+$")
KANJI = re.compile(r"[㐀-䶿一-鿿]")


# what a page in an old 8-bit code page turns into when read as Western European -> its script
MOJIBAKE = (("cp1251", re.compile(r"[\u0400-\u04ff]")),      # Russian, Ukrainian, Bulgarian ...
            ("cp1253", re.compile(r"[\u0370-\u03ff]")),      # Greek
            ("cp1256", re.compile(r"[\u0600-\u06ff]")))      # Arabic, Persian, Urdu


TURKISH_MAC = {"›": "ı", "¤": "ğ", "ﬂ": "ş", "‹": "İ", "ﬁ": "Ş", "⁄": "Ğ", "õ": "ı"}
TURKISH_WIN = {"ý": "ı", "þ": "ş", "ð": "ğ", "Ý": "İ", "Þ": "Ş", "Ð": "Ğ"}


def fix_turkish(words):
    """Turkish set in fonts made for Western code pages: 'say›m›zda', 'gönderece¤iniz',
    'ﬁemsiye' (Mac fonts), 'sayýmýzda' (Windows). Repaired only on a page that shows the
    pattern: › or ¤ inside words never happen in real text; ý þ ð without Icelandic's á é æ."""
    inside = lambda t, chars: any(c in chars for c in t[1:-1])
    mac = sum(1 for w in words if inside(w[4], "›¤"))
    table = None
    if mac >= 3:
        table = TURKISH_MAC
    else:
        win = sum(1 for w in words if inside(w[4], "ýþð"))
        icelandic = sum(1 for w in words for c in w[4] if c in "áéíóúæÁÉÍÓÚÆ")
        if win >= 5 and icelandic < 0.1 * win and any(c in w[4] for w in words for c in "çöüÇÖÜ"):
            table = TURKISH_WIN
    if table is None:
        return words
    fix = lambda t: "".join(table.get(c, c) if c.isalpha() or c in "›‹¤⁄" else c for c in t) \
        if any(ch.isalpha() for ch in t) else t
    out = [w[:4] + (fix(w[4]),) + tuple(w[5:]) for w in words]
    if _symbol_word_share([w[4] for w in out]) >= SYMBOL_WORDS:
        return words                        # still full of symbols: some other broken font
    return out


def fix_mojibake(words):
    """A PDF whose font maps an old code page as Western European shows Russian as
    'Íàó÷íî-äîêóìåíòàëüíàÿ'. When most letters are in the Latin-1 accented range, read the
    same bytes in each likely code page and keep the one that gives clean letters of its script."""
    words = fix_turkish(words)
    letters = [c for w in words for c in w[4] if c.isalpha()]
    if len(letters) < 20 or sum("\u00c0" <= c <= "\u00ff" for c in letters) < 0.5 * len(letters):
        return words

    def recode(t, cp):
        for src in ("cp1252", "latin-1"):
            try:
                return t.encode(src).decode(cp)
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        return None

    for cp, script in MOJIBAKE:
        out = [w[:4] + (recode(w[4], cp),) + tuple(w[5:]) for w in words]
        if any(w[4] is None for w in out):
            continue
        new = [c for w in out for c in w[4] if c.isalpha()]
        if new and len([c for c in new if script.match(c)]) >= 0.8 * len(new):
            return out
    return words


# Indic vowel signs written to the left of their consonant (Hindi, Bengali, Punjabi, Gujarati,
# Tamil, Malayalam, Sinhala, Burmese); a consonant cluster = consonant (+ nukta) (+ virama + consonant)...
PREBASE = "\u093f\u09bf\u09c7\u09c8\u0a3f\u0abf\u0bc6\u0bc7\u0bc8\u0d46\u0d47\u0d48\u0dd9\u0dda\u0ddb\u1031"
INDIC_CLUSTER = re.compile(r"([\u093f\u09bf\u09c7\u09c8\u0a3f\u0abf\u0bc6\u0bc7\u0bc8\u0d46\u0d47\u0d48\u0dd9\u0dda\u0ddb\u1031])((?:[\u0915-\u0939\u0958-\u095f\u0995-\u09b9\u09dc-\u09df\u0a15-\u0a39\u0a59-\u0a5e\u0a95-\u0ab9\u0b95-\u0bb9\u0d15-\u0d3a\u0d9a-\u0dc6\u1000-\u1021][\u093c\u09bc\u0a3c\u0abc]?[\u094d\u09cd\u0a4d\u0acd\u0bcd\u0d4d\u0dca\u1039])*[\u0915-\u0939\u0958-\u095f\u0995-\u09b9\u09dc-\u09df\u0a15-\u0a39\u0a59-\u0a5e\u0a95-\u0ab9\u0b95-\u0bb9\u0d15-\u0d3a\u0d9a-\u0dc6\u1000-\u1021][\u093c\u09bc\u0a3c\u0abc]?)")
INDIC_BASE = re.compile(r"[\u0915-\u0939\u0958-\u095f\u0995-\u09b9\u09dc-\u09df\u0a15-\u0a39\u0a59-\u0a5e\u0a95-\u0ab9\u0b95-\u0bb9\u0d15-\u0d3a\u0d9a-\u0dc6\u1000-\u1021\u093c\u09bc\u0a3c\u0abc]")


def fix_indic_order(words):
    """Some PDFs store a vowel sign where it is drawn, before its consonant: 'ਪੁੱਿਛਆ' for
    ਪੁੱਛਿਆ, 'ਿਭਕਸ਼ੂ' for ਭਿਕਸ਼ੂ. A sign that does not follow a consonant (word start, after another
    sign) is moved behind the consonant cluster after it. (Between two consonants it may
    belong to either; that is left alone.)"""
    import unicodedata
    out = []
    for w in words:
        t = w[4]
        if any(c in PREBASE for c in t):
            def move(m, t=t):
                i = m.start()
                if i > 0 and INDIC_BASE.match(t[i - 1]):
                    return m.group(0)               # after a consonant: already right
                return m.group(2) + m.group(1)
            t = unicodedata.normalize("NFC", INDIC_CLUSTER.sub(move, t))
            w = w[:4] + (t,) + tuple(w[5:])
        out.append(w)
    return out


def drop_ruby(words):
    """Japanese furigana (the small kana printed beside a kanji to show how it is said) would
    be read twice: '人参畠 にんじんばたけ'. Drop kana-only runs that are clearly smaller than
    the page's text and sit right beside kanji."""
    cjk = [w for w in words if CJK_CHAR.search(w[4])]
    if len(cjk) < 10:
        return words
    size = lambda w: min(w[2] - w[0], w[3] - w[1])         # character size, either direction
    body = sorted(size(w) for w in cjk)[len(cjk) // 2]
    kanji = [w for w in cjk if KANJI.search(w[4]) and size(w) > 0.75 * body]

    def beside(r):
        s = size(r)
        for k in kanji:
            if (abs(r[0] - k[2]) < s and min(r[3], k[3]) > max(r[1], k[1])) or                     (abs(r[3] - k[1]) < s and min(r[2], k[2]) > max(r[0], k[0])):
                return True                                  # right of a column / above a line
        return False

    return [w for w in words if not (KANA_ONLY.match(w[4].strip()) and size(w) < 0.65 * body and beside(w))]


RTL_CHAR = re.compile(r"[֐-׿؀-ۿݐ-ݿיִ-﷿ﹰ-﻿]")
LTR_CHAR = re.compile(r"[A-Za-z0-9À-ɏͰ-ϿЀ-ӿ]")
RTL_MARKS = re.compile(r"[֑-ׇؐ-ًؚ-ٰٟۖ-ۭ]")
MIRROR = str.maketrans("()[]{}<>", ")(][}{><")


def rtl_words(page, words):
    """Hebrew/Arabic: letters carrying vowel points often get zero width in the PDF, and the
    text reader then invents spaces (and loses letters) inside the word: 'ְירּו ַל ִים' for
    ירושלים. Read the page again without invented spaces; keep that unless the PDF has no
    real space characters (then the words would run together)."""
    import pymupdf
    plain = page.get_text("words", sort=False, flags=pymupdf.TEXTFLAGS_WORDS | pymupdf.TEXT_INHIBIT_SPACES)
    return plain if len(plain) >= 0.6 * len(words) else words


# A book BookTalker converted carries the exact words of the pages whose PDF text is damaged.
# MuPDF writes shaped letters with no character of their own (Thai tone marks above a vowel,
# Indic conjuncts and vowel signs, Arabic joined forms, Khmer, Myanmar, Sinhala, Tibetan ...) as
# their glyph number: 'นี้' -> 'นี2'. The typesetter knew the real letters; convert.py keeps them.
EXACT_WORDS = "booktalker-words.json"


def stext_words(tp):
    """A text page (MuPDF's own, before PDF writing) -> words in get_text("words") shape.
    MuPDF starts a new line wherever a vowel sign is drawn left of its letter ('ছ' | 'োট'),
    always on the same baseline and touching the word it belongs to: those pieces are joined
    back (the spaces are real characters). A letter drawn away from the rest of its word starts
    a word of its own, as in MuPDF's own word list (a sentence's full stop that a right-to-left
    line puts at its far end), and a line of its own too, as MuPDF numbers it in a PDF. Joiners
    (zero-width, category Cf) go with their word wherever they are drawn."""
    def near(cs, x0, x1, size):
        cs = [c for c in cs if unicodedata.category(c["c"]) != "Cf"]
        return not cs or max(x0 - max(c["bbox"][2] for c in cs), min(c["bbox"][0] for c in cs) - x1) <= 0.5 * size

    out = []
    for bno, b in enumerate(tp.extractRAWDICT()["blocks"]):
        if b.get("type") != 0:
            continue
        rows = []                                   # [baseline, chars]
        for line in b["lines"]:
            chars = [dict(c, size=s["size"] or 10) for s in line["spans"] for c in s["chars"]]
            if not chars:
                continue
            size = max(c["size"] for c in chars)
            y = chars[0]["origin"][1]
            if rows and abs(rows[-1][0] - y) < 0.2 * size:
                tail = []                           # the word the row ends in
                for c in reversed(rows[-1][1]):
                    if c["c"].isspace():
                        break
                    tail.append(c)
                if near(tail or rows[-1][1][-1:], line["bbox"][0], line["bbox"][2], size):
                    rows[-1][1].extend(chars)
                    continue
            rows.append([y, chars])
        lno = -1
        for _, chars in rows:
            word, wno, lno = [], 0, lno + 1
            for c in chars + [None]:
                gap = (c is not None and word and not c["c"].isspace() and unicodedata.category(c["c"]) != "Cf"
                       and not near(word, c["bbox"][0], c["bbox"][2], c["size"]))
                if c is None or c["c"].isspace() or gap:
                    if word:
                        boxes = [w["bbox"] for w in word if unicodedata.category(w["c"]) != "Cf"] or [word[0]["bbox"]]
                        out.append((min(b[0] for b in boxes), min(b[1] for b in boxes),
                                    max(b[2] for b in boxes), max(b[3] for b in boxes),
                                    "".join(w["c"] for w in word), bno, lno, wno))
                        wno += 1
                        word = []
                    if gap:
                        wno, lno = 0, lno + 1
                if c is not None and not c["c"].isspace():
                    word.append(c)
    return out


def exact_words(page):
    """The page's exact words when its book was converted by BookTalker and its PDF text is
    damaged, else None."""
    doc = page.parent
    kept = getattr(doc, "_bt_exact", None)
    if kept is None:
        kept = {}
        try:
            if EXACT_WORDS in doc.embfile_names():
                import json
                kept = {int(k): [tuple(w) for w in v] for k, v in json.loads(doc.embfile_get(EXACT_WORDS)).items()}
        except Exception:
            kept = {}
        doc._bt_exact = kept
    return kept.get(page.number)


WORD_FINAL = re.compile(r"([\u0629\u0649\u05da\u05dd\u05df\u05e3\u05e5])(?=[\u0621-\u064a\u05d0-\u05ea])")


def _rtl_split(text, lang=None):
    """Two words the PDF printed without a space: 'زهرةالمدائن' -> ['زهرة', 'المدائن']. Only
    where the spelling proves it: Arabic ة/ى and Hebrew final letters (ך ם ן ף ץ) end a word."""
    return WORD_FINAL.sub(r"\1 ", text).split()


def _split_box(w, parts):
    """One word box -> boxes for its parts, right to left (Hebrew/Arabic)."""
    total = sum(len(t) for t in parts) or 1
    out, x = [], w[2]
    for t in parts:
        nx = x - (w[2] - w[0]) * len(t) / total
        out.append((nx, w[1], x, w[3], t) + tuple(w[5:]))
        x = nx
    return out


HEB_FINAL = "\u05da\u05dd\u05df\u05e3\u05e5"     # final forms: they only end a word
HEB_MARKS = re.compile(r"[\u0591-\u05c7]")


def _unreverse_hebrew(words):
    """Some text layers keep each Hebrew word's letters in the order they appear on screen,
    left to right: the word then starts with a final letter ('ןֹורָג'). When more words start
    with a final letter than end with one, turn every Hebrew word around."""
    from .ocr import visual_to_logical
    heb = [HEB_MARKS.sub("", w[4]) for w in words if "\u05d0" <= HEB_MARKS.sub("", w[4])[:1] <= "\u05ea"]
    starts = sum(1 for t in heb if len(t) > 1 and t[0] in HEB_FINAL)
    ends = sum(1 for t in heb if len(t) > 1 and t[-1] in HEB_FINAL)
    if starts <= max(2, ends):
        return words
    return [w[:4] + (visual_to_logical(w[4]),) + tuple(w[5:]) for w in words]


PRESENTATION = re.compile(r"[יִ-ﭏﭐ-﷿ﹰ-﻿]")   # Hebrew/Arabic presentation forms


def fix_rtl(words):
    """Hebrew/Arabic lines: PDFs keep them in visual order, so their words can come out
    backwards, with numbers swapped and pointed words in pieces ('ִע יר'). Put each right-to-left
    line in reading order (right to left; numbers and Latin runs stay left to right), drop the
    vowel points/harakat (plain text, as most print is) and rejoin the pieces."""
    if any(PRESENTATION.search(w[4]) for w in words):
        # letters stored in their shaped forms ('ﺍﻥ ﮐﺎ'): plain letters, so translation, voice
        # and language detection know them
        import unicodedata
        words = [w[:4] + (unicodedata.normalize("NFKC", w[4]),) + tuple(w[5:]) if PRESENTATION.search(w[4]) else w
                 for w in words]
    if not any(RTL_CHAR.search(w[4]) for w in words):
        return words
    words = _unreverse_hebrew(words)
    lines, order = {}, []
    for w in words:
        key = (w[5], w[6])
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(w)
    out = []
    for key in order:
        ws = lines[key]
        text = "".join(w[4] for w in ws)
        if len(RTL_CHAR.findall(text)) <= len(LTR_CHAR.findall(text)):
            out += ws
            continue
        lang = "he" if len(re.findall(r"[\u0590-\u05ff]", text)) > len(RTL_CHAR.findall(text)) / 2 else "ar"
        clean = []
        for w in ws:
            t = re.sub(r"([\u060c\u061b])(?=\S)", r"\1 ", RTL_MARKS.sub("", w[4]).replace("\u0640", ""))   # glued commas, kashida
            parts = [q for part in t.split() for q in _rtl_split(part, lang)]
            clean += _split_box(w, parts) if len(parts) > 1 else [w[:4] + (t,) + tuple(w[5:])]
        ws = clean
        merged = sorted((w for w in ws if w[4].strip()), key=lambda w: -(w[0] + w[2]))   # right to left
        joined = []
        for w in merged:                               # a word-final letter split off by OCR
            if joined and w[4] in ("\u0629", "\u0649") and RTL_CHAR.search(joined[-1][4]):
                j = joined[-1]
                joined[-1] = (w[0], min(j[1], w[1]), j[2], max(j[3], w[3]), j[4] + w[4]) + tuple(j[5:])
                continue
            joined.append(w)
        merged = joined
        line, run = [], []
        for w in merged:                               # Latin/number runs read left to right
            if LTR_CHAR.search(w[4]) and not RTL_CHAR.search(w[4]):
                run.append(w)
                continue
            line += run[::-1]
            run = []
            line.append(w if LTR_CHAR.search(w[4]) else w[:4] + (w[4].translate(MIRROR),) + tuple(w[5:]))
        out += line + run[::-1]
    return out


HANGUL = re.compile(r"[\uac00-\ud7a3]")


def join_spaced_hangul(words):
    """Korean lettered with a space after every syllable ('스 스 로 의판단과재량', comics): on a line
    where most pieces are single syllables, pieces closer than a real word space are one word.
    MEASURED on a manhwa: letter gaps -0.2..0.24 of the letter height, word spaces 0.3..0.5."""
    if not any(HANGUL.search(w[4]) for w in words):
        return words
    lines = {}
    for i, w in enumerate(words):
        lines.setdefault((w[5], w[6]), []).append(i)
    drop, out = set(), list(words)
    for idx in lines.values():
        toks = [words[i] for i in idx]
        singles = sum(1 for w in toks if len(w[4]) == 1 and HANGUL.match(w[4]))
        if singles < 3 or singles < 0.4 * len(toks):
            continue                            # ordinary Korean: its spaces are real
        cur = idx[0]
        for i in idx[1:]:
            a, b = out[cur], words[i]
            h = max(a[3] - a[1], b[3] - b[1], 1)
            if HANGUL.search(a[4][-1:]) and HANGUL.search(b[4][:1] or "") and (b[0] - a[2]) < 0.25 * h:
                out[cur] = (a[0], min(a[1], b[1]), b[2], max(a[3], b[3]), a[4] + b[4]) + tuple(a[5:])
                drop.add(i)
            else:
                cur = i
    return [w for i, w in enumerate(out) if i not in drop]


def join_drop_caps(words):
    """Magazines and books start articles with a big first letter set apart: 'T he', 'A fter'.
    Join it to the word beside it. 'A' and 'I' are words themselves: joined only when the
    rest is not a word on its own ('A fter' -> 'After', 'A rmbian' -> 'Armbian', but
    'A release' stays)."""
    if len(words) < 20:
        return words
    from wordfreq import zipf_frequency
    heights = sorted(w[3] - w[1] for w in words)
    body = heights[len(heights) // 2]
    out, skip = [], False
    for i, w in enumerate(words):
        if skip:
            skip = False
            continue
        nxt = words[i + 1] if i + 1 < len(words) else None
        t = w[4]
        if (nxt is not None and len(t) == 1 and t.isupper() and (w[3] - w[1]) > 1.8 * body
                and nxt[4][:1].islower() and nxt[0] > w[0] and w[1] - body <= nxt[1] <= w[3]):
            core = strip_punct(nxt[4], lead=False)
            if t not in ("A", "I") or len(core) < 2 or zipf_frequency(core, "en") < 2.0:
                out.append((w[0], min(w[1], nxt[1]), nxt[2], max(w[3], nxt[3]), t + nxt[4]) + tuple(nxt[5:]))
                skip = True
                continue
        out.append(w)
    return out


def build_page(page, layout, words=None, comic=False, code=False):
    """Combine one page's layout boxes with its words (PyMuPDF's, or OCR words for scans,
    in the same (x0, y0, x1, y1, text, block, line, n) shape). code: a source file shown as
    pages, all of it code."""
    scale = 72.0 / LAYOUT_DPI
    boxes = []
    for b in layout.bboxes:
        x0, y0, x1, y1 = (v * scale for v in b.bbox)
        boxes.append((x0 - 2, y0 - 2, x1 + 2, y1 + 2, b.label, b.confidence))
    ocr = words is not None                     # OCR'd scan (no PDF text order to lean on)
    exact = False
    if words is None:
        words = exact_words(page)
        exact = words is not None
        if not exact:
            words = page.get_text("words", sort=False)
            if any(RTL_CHAR.search(w[4]) for w in words):
                words = rtl_words(page, words)
    if not ocr and not exact:
        words = fix_indic_order(fix_mojibake(words))
    words = join_spaced_hangul(join_drop_caps(fix_rtl(drop_ruby(words))))
    from . import comic as comic_order
    # panels and balloons, in comic reading order: comic files, and scanned pages that read
    # like a comic (manga's vertical Japanese, or most words inside big pictures)
    if comic or (ocr and comic_order.looks_like(page, boxes, words)):
        return comic_order.build(page, boxes, words)
    H = page.rect.height
    groups = {}          # group key -> {"label", "words"}
    order = []
    pieces = []
    for n, w in enumerate(words):
        for k, (x0, y0, x1, y1, text) in enumerate(split_cjk(w)):
            pieces.append((x0, y0, x1, y1, text, w[5], w[6], n * 100 + k))
    for x0, y0, x1, y1, text, bno, lno, n in pieces:
        text = text.replace("\xad", "").replace("　", "")
        if not text.strip():
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        best = None
        for i, (bx0, by0, bx1, by1, label, conf) in enumerate(boxes):
            if bx0 <= cx <= bx1 and by0 <= cy <= by1:
                area = (bx1 - bx0) * (by1 - by0)
                if best is None or (conf, -area) > (best[1], -best[2]):
                    best = (i, conf, area)
        if best is not None:
            key, label = ("box", best[0]), boxes[best[0]][4]
        else:
            # Word outside every region: keep it as text, except in the margin bands
            # where stray words are headers, footers or page numbers.
            key = ("loose", bno)
            label = "PageHeader" if cy < H * MARGIN_BAND else (
                "PageFooter" if cy > H * (1 - MARGIN_BAND) else "Text")
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"label": label, "words": []}
            order.append(key)
        g["words"].append([round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2),
                           text, bno * 10000 + lno, n])
    if ocr:
        order = _geometric_order(order, groups, page.rect.width)
    if code:                                    # a source file: the whole page, line by line
        allw = [w for k in order for w in groups[k]["words"]]
        allw.sort(key=lambda w: w[6])
        groups, order = {"all": {"label": "Code", "words": allw}}, ["all"] if allw else []
    blocks, extra = [], []
    for key in order:   # first-word order = the PDF's own reading order
        g = groups[key]
        ys = [w[1] for w in g["words"]] + [w[3] for w in g["words"]]
        b = {"label": g["label"], "top": min(ys), "bottom": max(ys), "words": g["words"]}
        if g["label"] in KEEP_ASIDE:            # not read aloud, but tells us chapters and page numbers
            extra.append(b)
        elif g["label"] not in SKIP_LABELS:
            blocks.append(b)
    if not code:                                # code inside a book: its own blocks (typewriter font, syntax)
        from .code import mono_words, split_code
        blocks = split_code(blocks, set() if ocr else mono_words(page, words))
    return {"blocks": blocks, "extra": extra, "height": H}


_WORDFREQ_LANGS = None
BAD_TEXT = 0.6          # below this share of real words, a page's text layer is re-read with OCR


_CJK_FAMILY = {"CJK", "HIRAGANA", "KATAKANA", "HANGUL", "IDEOGRAPHIC", "HALFWIDTH", "FULLWIDTH"}


def _mixed_script_share(texts):
    """Share of words whose letters come from different alphabets. Real words never do
    (Japanese kanji + kana count as one script); text from a PDF with an old non-Unicode
    font does: Devanagari + Latin 'सुƑज', Greek + Latin 'ϗǏŬ', Arabic + Latin 'لطȢق'."""
    import unicodedata
    toks = [t for t in texts if len(t) > 1]
    if len(toks) < 3:
        return 0.0
    bad = 0
    for t in toks:
        scripts = set()
        for c in t:
            if unicodedata.category(c)[0] in "LM":
                name = unicodedata.name(c, "").split(" ")[0]
                scripts.add("CJK" if name in _CJK_FAMILY else name)
        bad += len(scripts) > 1
    return bad / len(toks)


def strip_punct(t, lead=True):
    """A word without the punctuation/symbols around it. (Regex \\W would also strip the
    vowel signs and viramas that end Indic and Thai words.)"""
    import unicodedata
    keep = lambda c: unicodedata.category(c)[0] in "LMN"
    i, j = 0, len(t)
    while lead and i < j and not keep(t[i]):
        i += 1
    while j > i and not keep(t[j - 1]):
        j -= 1
    return t[i:j]


RELATED_WORDLIST = {"mr": "hi", "ne": "hi", "mai": "hi", "sa": "hi", "bho": "hi", "awa": "hi",
                    "mk": "bg", "be": "ru", "kk": "ru", "ky": "ru", "tg": "ru", "gl": "pt", "oc": "fr",
                    "af": "nl", "ast": "es", "an": "es", "ps": "fa", "sd": "ur", "ug": "fa"}


# the script each language is written in (Unicode name prefix), for languages judged by script
LANG_SCRIPT = {"pa": "GURMUKHI", "gu": "GUJARATI", "bn": "BENGALI", "as": "BENGALI", "or": "ORIYA",
               "ml": "MALAYALAM", "kn": "KANNADA", "te": "TELUGU", "ta": "TAMIL", "si": "SINHALA",
               "ka": "GEORGIAN", "hy": "ARMENIAN", "am": "ETHIOPIC", "ti": "ETHIOPIC", "my": "MYANMAR",
               "km": "KHMER", "lo": "LAO", "bo": "TIBETAN", "dz": "TIBETAN", "th": "THAI", "he": "HEBREW",
               "yi": "HEBREW", "dv": "THAANA", "mn": "CYRILLIC", "ba": "CYRILLIC", "tt": "CYRILLIC"}


def _script_purity(toks, lang=None):
    """For a language without a word list: the share of words written cleanly in its script
    (the page's main script when unknown; plain English words allowed). Broken fonts leave stray
    Latin-1 letters and mixed-script words ('ēਤਰ', 'Ã', 'ěീനാരായണ'), and a reader made for
    another script (Tamil letters for a Malayalam page) doesn't pass for the real thing."""
    import unicodedata

    def scripts(t):
        return {unicodedata.name(c, "?").split(" ")[0] for c in t if unicodedata.category(c)[0] in "LM"}
    counts = {}
    for t in toks:
        for sc in scripts(t):
            counts[sc] = counts.get(sc, 0) + 1
    main = LANG_SCRIPT.get(lang) or (max(counts, key=counts.get) if counts else None)
    good = 0
    for t in toks:
        sc = scripts(t)
        english = bool(sc) and sc == {"LATIN"} and t.isascii()
        good += sc == {main} or english
    return good / len(toks)


SYMBOL_WORDS = 0.12        # MEASURED: clean books <= 0.08 a page; every word flagged above was a broken font or OCR junk


def _symbol_word_share(texts):
    """Share of words with symbols inside them ('‚’È', '◊Ò¥', '∑§„U'): what an old Hindi font
    (Chanakya, Kruti Dev ...) looks like when its letters are read as Latin-1 symbols."""
    import unicodedata
    toks = [strip_punct(t) for t in texts]
    toks = [t for t in toks if len(t) > 1]
    if len(toks) < 10:
        return 0.0
    odd = set("‚„…†‡ˆ‰‹›•˜™¬÷◊∑∏∂√∞≈≠≤≥µ§¶©®°±¤¦¨¯´¸")
    # (all-ASCII words are left out: 'P=P+1' is code, and ASCII junk fails the word-list check)
    bad = sum(1 for t in toks if not t.isascii() and
              any(c in odd or unicodedata.category(c) in ("Sm", "So", "Sk") for c in t[1:-1] or t))
    return bad / len(toks)


def broken_layer(texts):
    """A text layer that is junk whatever its language: an old non-Unicode font, or symbols."""
    return len(texts) >= 10 and (_mixed_script_share(texts) >= 0.15 or _symbol_word_share(texts) >= SYMBOL_WORDS)


def text_quality(texts, lang="en"):
    """Share (0..1) of a page's words that are real words in the book's language. Catches
    broken OCR layers and garbled font encodings. Chinese/Japanese/Korean text is only
    checked for garbled characters."""
    global _WORDFREQ_LANGS
    joined = "".join(texts)
    if not joined:
        return 1.0
    garbled = sum(1 for ch in joined if ch == "�" or "" <= ch <= "" or ord(ch) < 32)
    garbled += joined.count("Ã") + joined.count("Â")
    if garbled / len(joined) > 0.05:
        return 0.0
    if _mixed_script_share(texts) >= 0.15 or _symbol_word_share(texts) >= SYMBOL_WORDS:
        return 0.0                       # an old non-Unicode font: 'सुƑज', 'ϗǏŬ', 'لطȢق', '◊Ò¥ ‚’È'
    if len(CJK_CHAR.findall(joined)) > len(joined) * 0.3:
        return 1.0
    # (invisible joiners some PDFs leave inside Indic words, 'நாள்‌', don't make a word unreal)
    toks = [strip_punct(t.replace("\u200c", "").replace("\u200d", "")).lower() for t in texts]
    toks = [t for t in toks if len(t) > 1 and not re.fullmatch(r"[\d.,:/%$-]+", t)]
    if len(toks) < 20:
        return 1.0                       # too little text to judge
    from wordfreq import available_languages, zipf_frequency
    if _WORDFREQ_LANGS is None:
        _WORDFREQ_LANGS = set(available_languages())
    # Latin-script text in a Chinese/Japanese/Korean book is checked as English (wordfreq's
    # CJK word lists need extra segmenters for these scripts anyway). A language without a word
    # list is checked against a close relative's, or, in its own script, for clean words only.
    if lang in _WORDFREQ_LANGS and lang not in ("zh", "ja", "ko"):
        wl = lang
    elif lang in RELATED_WORDLIST:
        wl = RELATED_WORDLIST[lang]
    elif sum(1 for t in toks if re.search(r"[A-Za-z]", t)) < 0.5 * len(toks):
        return _script_purity(toks, lang)
    else:
        wl = "en"
    try:
        return sum(1 for t in toks if zipf_frequency(t, wl) >= 1.0) / len(toks)
    except Exception:
        return 1.0                       # never let the check itself stop the page reader


def _geometric_order(order, groups, width):
    """Reading order for OCR'd pages (no PDF text order to lean on): full-width blocks split
    the page into bands; inside a band, the left column top-to-bottom, then the right."""
    def box(k):
        ws = groups[k]["words"]
        return min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws)
    items = sorted(order, key=lambda k: box(k)[1])
    out, band = [], []

    def flush():
        left = [k for k in band if box(k)[2] < width * 0.55]
        right = [k for k in band if box(k)[0] > width * 0.45]
        if left and right and len(left) + len(right) >= 0.8 * len(band):     # real two columns
            band.sort(key=lambda k: (0 if (box(k)[0] + box(k)[2]) / 2 < width / 2 else 1, box(k)[1]))
        else:
            band.sort(key=lambda k: box(k)[1])
        out.extend(band)
        band.clear()
    for k in items:
        x0, _, x1, _ = box(k)
        if x1 - x0 > width * 0.55:          # spans both columns: its own band
            flush()
            out.append(k)
        else:
            band.append(k)
    flush()
    return out


class LayoutCache:
    """Per-book cache of processed pages on disk, so a book is only analysed once.

    New pages are appended to a small journal (<id>.jsonl), one line per page: rewriting the
    whole cache (2+ MB of JSON) holds Python's lock for ~260 ms, measured, which starved the
    audio callback and made the voice stutter while pages were still being prepared. The full
    file is rewritten only when the book is closed (compact)."""

    def __init__(self, pdf_path, page_count):
        self.path = os.path.join(cache_dir(), doc_id(pdf_path) + ".json")
        self.journal = self.path[:-5] + ".jsonl"
        self.pages = {}
        self.meta = {}          # per-book facts, e.g. which OCR reader model fits its scans
        self.unsaved = set()    # pages processed since the last save
        self.redo = set()       # pages read by an OCR reader the book has since moved away from
        self.lock = threading.Lock()
        self.page_count = page_count
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") == CACHE_VERSION and data.get("page_count") == page_count:
                self.pages = {int(k): v for k, v in data["pages"].items()}
                self.meta = data.get("meta", {})
        except (OSError, ValueError, KeyError):
            pass
        try:
            with open(self.journal, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:              # a line cut short by a crash
                        continue
                    if rec.get("v") != CACHE_VERSION or rec.get("n") != page_count:
                        continue
                    if "meta" in rec:
                        self.meta.update(rec["meta"])
                    else:
                        self.pages[int(rec["p"])] = rec["d"]
        except OSError:
            pass

    _save_lock = threading.Lock()

    def save(self):
        """Append the pages processed since the last save — small writes, safe while reading aloud."""
        with self.lock:
            recs = [{"v": CACHE_VERSION, "n": self.page_count, "p": p, "d": self.pages[p]}
                    for p in sorted(self.unsaved) if p in self.pages]
            recs.append({"v": CACHE_VERSION, "n": self.page_count, "meta": dict(self.meta)})
            self.unsaved.clear()
        lines = [json.dumps(r) for r in recs]       # one page per dump: never a long hold
        with self._save_lock:
            with open(self.journal, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    def compact(self):
        """Fold the journal into one file (done on closing the book, when nothing is playing)."""
        with self.lock:
            if not self.unsaved and not os.path.exists(self.journal):
                return
            data = {"version": CACHE_VERSION, "page_count": self.page_count, "meta": self.meta,
                    "pages": {str(k): v for k, v in self.pages.items()}}
            self.unsaved.clear()
        with self._save_lock:                       # one writer at a time
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            for attempt in range(5):                # antivirus may hold the file briefly
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    time.sleep(0.2 * (attempt + 1))
            else:
                return
            try:
                os.remove(self.journal)
            except OSError:
                pass


class LayoutWorker(threading.Thread):
    """Processes pages in the background, starting from the page the reader needs."""

    CHUNK = 4

    def __init__(self, pdf_path, cache, get_model, on_progress, get_ocr=None, get_lang=None):
        super().__init__(daemon=True)
        self.doc = pymupdf.open(pdf_path)      # own handle: PyMuPDF is not thread-safe
        keywords = (self.doc.metadata or {}).get("keywords") or ""
        self.comic = "BookTalker comic" in keywords
        self.code = "BookTalker code" in keywords            # a source file (bt/convert.py)
        self.cache = cache
        self.get_model = get_model
        self.get_ocr = get_ocr
        self.get_lang = get_lang
        self.on_progress = on_progress
        self.target = 0
        self.wake = threading.Event()
        self.stopped = False

    def want(self, page):
        self.target = page
        self.wake.set()

    def stop(self):
        self.stopped = True
        self.wake.set()

    def next_pages(self):
        n = self.cache.page_count
        with self.cache.lock:
            if self.cache.redo:                 # pages to read again with the book's better reader
                return [self.cache.redo.pop() for _ in range(min(self.CHUNK, len(self.cache.redo)))]
        todo = []
        for p in list(range(self.target, n)) + list(range(0, self.target)):
            if p not in self.cache.pages:
                todo.append(p)
                if len(todo) == self.CHUNK:
                    break
            elif todo:
                break
        return todo

    def run(self):
        dirty, last_save = False, time.time()
        while not self.stopped:
            todo = self.next_pages()
            if dirty and (not todo or time.time() - last_save > 5):
                self.cache.save()
                dirty, last_save = False, time.time()
            if not todo:
                self.wake.wait()
                self.wake.clear()
                continue
            model = self.get_model()
            for p in todo:
                try:
                    result = self.process(p, model)
                except Exception:               # one page that can't be read never stops the book
                    import traceback
                    try:
                        d = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BookTalker")
                        with open(os.path.join(d, "error.log"), "a", encoding="utf-8") as f:
                            f.write(f"page {p + 1}: {traceback.format_exc()}\n")
                    except OSError:
                        pass
                    result = {"blocks": [], "height": self.doc[p].rect.height, "no_text": True}
                with self.cache.lock:
                    self.cache.pages[p] = result
                    self.cache.unsaved.add(p)
                if self.stopped:
                    return
            dirty = True
            self.on_progress(todo)

    def process(self, p, model):
        """One page -> its layout dict (text layer, or our OCR when the page is a scan or its
        text layer reads badly)."""
        pg = self.doc[p]
        self._replaced = False
        words = None
        exact = exact_words(pg)                           # (a book we converted, damaged text)
        layer = exact or pg.get_text("words", sort=False)
        if exact:
            pass                                          # exact letters: nothing to judge
        elif len(layer) < 3:                              # scanned page: read it with OCR
            words = self._ocr_words(pg)
        elif self.get_ocr is not None and not self.code:     # (code never reads like real words)
            lang = self.get_lang() if self.get_lang else "en"
            repaired = fix_rtl(fix_indic_order(fix_mojibake(layer)))      # judged as it will be read
            q = text_quality([w[4] for w in repaired], lang)
            # A scan carrying someone else's OCR text: ours read better on the books
            # measured (0.98-1.00 real words vs 0.80-0.95), so compare and keep the better.
            scan = _is_scan(pg)
            if scan and len(layer) < 25:
                q = 0.0         # a scan whose text layer is a stamp ('tarikhema.org'): the text is in the picture
            if q < BAD_TEXT or (scan and q < 0.99):
                broken = broken_layer([w[4] for w in repaired])
                from .ocr import script_reader
                ocr_words = self._ocr_words(pg, (script_reader([w[4] for w in repaired]) or "any") if broken else None)
                letters = lambda ws: sum(c.isalpha() for w in ws for c in w[4])
                judge = lang
                layer_script = script_reader([w[4] for w in repaired])
                ocr_script = script_reader([w[4] for w in ocr_words])
                if q < BAD_TEXT and ocr_words and (broken or layer_script is None or ocr_script == layer_script):
                    # the book's language may have been guessed from this junk ('German' for an
                    # old Hindi font, 'English' for Armenian read as Latin): judge what OCR read
                    # in its own language. (Not when a sound Cyrillic page came back from OCR as
                    # Latin junk: a Mongolian contents page, 'ганжуур' -> 'raHyyp'.)
                    from .translate import detect_language
                    judge = detect_language(" ".join(w[4] for w in ocr_words))
                # (a few junk words from a reader made for another script must not beat a page)
                if (text_quality([w[4] for w in ocr_words], judge) > q + (0.02 if scan else 0.1)
                        and (broken or letters(ocr_words) >= 0.5 * letters(layer))):   # (junk letters don't count)
                    words = ocr_words
                    self._replaced = True
        if words is not None and not words:
            return {"blocks": [], "height": pg.rect.height, "no_text": True}
        result = build_page(pg, model.detect([page_image(pg)])[0], words, self.comic, self.code)
        if words is not None:
            result["ocr"] = True
            result["reader"] = getattr(self, "_reader", None)
            if self._replaced:
                result["replaced"] = True          # our OCR read better than the text layer
        return result

    def _ocr_words(self, pg, hint=None):
        """OCR a scanned page -> words in PDF points, in PyMuPDF's word-tuple shape. hint: a reader
        the page's own (broken) text layer points to, tried as well."""
        if self.get_ocr is None:
            return []
        from .ocr import render_for_ocr
        ocr = self.get_ocr()
        img, scale = render_for_ocr(pg)
        kind = self.cache.meta.get("ocr_kind")
        if kind is None:
            kind, words, score = ocr.choose_kind(img)
            if len(words) >= 15:                # decide on a page with real text, not a cover
                self.cache.meta["ocr_kind"] = kind
            self._reader = kind
        else:
            self._reader = kind
            words, score = ocr.read(img, kind, lines=bool(self.cache.meta.get("ocr_fixed")))
            doubtful = 0.45 if kind.startswith("tess:") else 0.85   # (Tesseract scores run lower: 0.55-0.8)
            if score < doubtful and self.cache.meta.get("ocr_fixed"):
                # the reader chose the book's language: only English/Latin pages may differ
                best = ocr.best_of(img, ["ch", "latin"], (kind, words, score))
                if best[0] != kind and ocr.value(*best[1:], best[0]) > 1.5 * ocr.value(words, score, kind):
                    words, self._reader = best[1], best[0]
            elif score < doubtful:              # a page in another script (bilingual books)
                # readers that already served this book first, then all of them
                alt = self.cache.meta.setdefault("ocr_alt", [])
                best = ocr.best_of(img, ["ch"] + alt, (kind, words, score))
                if best[0] == kind:
                    best = ocr.best_any(img, best)
                if best[0] != kind and ocr.value(*best[1:], best[0]) > 1.5 * ocr.value(words, score, kind):
                    words = best[1]
                    self._reader = best[0]
                    if best[0] not in alt:
                        alt.append(best[0])
                    wins = self.cache.meta.setdefault("ocr_wins", {})
                    wins[best[0]] = wins.get(best[0], 0) + 1
                    if wins[best[0]] >= 2:          # it reads this book better: make it the book's reader
                        self.cache.meta["ocr_kind"] = best[0]
                        with self.cache.lock:       # and read again what the old one read
                            self.cache.redo |= {q for q, d in self.cache.pages.items()
                                                if d.get("ocr") and d.get("reader") != best[0]}
        if hint == "any":                      # a broken layer with no real letters left: every reader has a go
            hint = ocr.contest(img)
        if hint and hint != self._reader:
            hw, hs = ocr.read(img, hint)
            if ocr.value(hw, hs, hint) > 1.5 * ocr.value(words, score, self._reader):
                words, self._reader = hw, hint
        return [(x0 * scale, y0 * scale, x1 * scale, y1 * scale, t, 0, line, i)
                for i, (x0, y0, x1, y1, t, line) in enumerate(words)]
