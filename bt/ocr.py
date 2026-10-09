"""OCR for scanned pages (no text layer): RapidOCR / PaddleOCR models on onnxruntime.

Returns words with boxes in the same shape PyMuPDF gives, so scanned pages go through the
same layout, reading and highlighting as born-digital ones.

Reader models (models/ocr):
    ch      PP-OCRv6  Chinese (simplified + traditional), English, Japanese
    latin   PP-OCRv5  French, Spanish, German, Italian, Portuguese ... (accents)
    eslav   PP-OCRv5  Russian, Ukrainian, Bulgarian ... (Cyrillic)
    korean  PP-OCRv5  Korean
    el      PP-OCRv5  Greek
    cyrillic PP-OCRv5 Cyrillic beyond the East-Slavic set (Serbian, Kazakh, Mongolian ...)
    arabic  PP-OCRv5  Arabic, Persian, Urdu
    devanagari PP-OCRv5 Hindi, Marathi, Nepali, Sanskrit
    th      PP-OCRv5  Thai
    ta / te PP-OCRv5  Tamil / Telugu
    tess:*  Tesseract (bt/tess.py) for the scripts above don't cover: Bengali, Punjabi, Gujarati,
            Malayalam, Kannada, Sinhala, Burmese, Khmer, Lao, Tibetan, Georgian, Armenian,
            Amharic, Hebrew, Yiddish
The reader is chosen per book: the one that reads the most confident letters of its own script.
"""
import os
import re
import threading

import numpy as np

from .paths import resource

REC = {"ch": "PP-OCRv6_rec_small.onnx", "latin": "latin_PP-OCRv5_rec_mobile.onnx",
       "eslav": "eslav_PP-OCRv5_rec_mobile.onnx", "korean": "korean_PP-OCRv5_rec_mobile.onnx",
       "el": "el_PP-OCRv5_rec_mobile.onnx", "cyrillic": "cyrillic_PP-OCRv5_rec_mobile.onnx",
       "arabic": "arabic_PP-OCRv5_rec_mobile.onnx", "devanagari": "devanagari_PP-OCRv5_rec_mobile.onnx",
       "th": "th_PP-OCRv5_rec_mobile.onnx", "ta": "ta_PP-OCRv5_rec_mobile.onnx", "te": "te_PP-OCRv5_rec_mobile.onnx"}
# the script each specialised reader exists for (the Chinese/English and Latin readers read anything)
OWN_SCRIPT = {
    "eslav": re.compile(r"[\u0400-\u04ff]"), "cyrillic": re.compile(r"[\u0400-\u04ff]"),
    "korean": re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]"),
    "el": re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]"),
    "arabic": re.compile(r"[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]"),
    "devanagari": re.compile(r"[\u0900-\u097f]"),
    "th": re.compile(r"[\u0e00-\u0e7f]"),
    "ta": re.compile(r"[\u0b80-\u0bff]"),
    "te": re.compile(r"[\u0c00-\u0c7f]"),
}
# Tesseract's readers for scripts PaddleOCR has no model for (bt/tess.py)
# the reader for a book whose language is known (the reader chose it under 'Book language'):
# scripts that one reader covers
LANG_READER = {"bn": "tess:ben", "as": "tess:ben", "pa": "tess:pan", "gu": "tess:guj", "ml": "tess:mal",
               "kn": "tess:kan", "si": "tess:sin", "my": "tess:mya", "km": "tess:khm", "lo": "tess:lao",
               "bo": "tess:bod", "ka": "tess:kat", "hy": "tess:hye", "am": "tess:amh", "ti": "tess:amh",
               "he": "tess:heb", "yi": "tess:yid", "hi": "devanagari", "mr": "devanagari", "ne": "devanagari",
               "sa": "devanagari", "ta": "ta", "te": "te", "th": "th", "ar": "arabic", "fa": "arabic",
               "ur": "arabic", "ps": "arabic", "el": "el", "ru": "eslav", "uk": "eslav", "be": "eslav",
               "bg": "cyrillic", "sr": "cyrillic", "mk": "cyrillic", "kk": "cyrillic", "ky": "cyrillic",
               "mn": "cyrillic", "ko": "korean", "zh": "ch", "ja": "ch"}
OWN_SCRIPT["tess:ben"] = re.compile(r"[\u0980-\u09ff]")
OWN_SCRIPT["tess:pan"] = re.compile(r"[\u0a00-\u0a7f]")
OWN_SCRIPT["tess:guj"] = re.compile(r"[\u0a80-\u0aff]")
OWN_SCRIPT["tess:mal"] = re.compile(r"[\u0d00-\u0d7f]")
OWN_SCRIPT["tess:kan"] = re.compile(r"[\u0c80-\u0cff]")
OWN_SCRIPT["tess:sin"] = re.compile(r"[\u0d80-\u0dff]")
OWN_SCRIPT["tess:mya"] = re.compile(r"[\u1000-\u109f]")
OWN_SCRIPT["tess:khm"] = re.compile(r"[\u1780-\u17ff]")
OWN_SCRIPT["tess:lao"] = re.compile(r"[\u0e80-\u0eff]")
OWN_SCRIPT["tess:bod"] = re.compile(r"[\u0f00-\u0fff]")
OWN_SCRIPT["tess:kat"] = re.compile(r"[\u10a0-\u10ff]")
OWN_SCRIPT["tess:hye"] = re.compile(r"[\u0530-\u058f]")
OWN_SCRIPT["tess:amh"] = re.compile(r"[\u1200-\u139f]")
OWN_SCRIPT["tess:heb"] = re.compile(r"[\u0590-\u05ff]")
OWN_SCRIPT["tess:yid"] = re.compile(r"[\u0590-\u05ff]")
# languages written in the Latin alphabet (read again with the Latin reader for the accents)
LATIN_LANGS = {"fr", "es", "de", "it", "pt", "nl", "pl", "cs", "sk", "hu", "ro", "hr", "sv",
               "no", "nb", "da", "fi", "ca", "tr", "vi", "la", "id", "ms", "tl", "sw"}
# Tesseract script-detector names of scripts PaddleOCR's readers cover
# (not Devanagari: it calls Gurmukhi pages 'Devanagari', 31 sure)
PADDLE_SCRIPTS = {"Latin", "Cyrillic", "Arabic", "Han", "HanS", "HanT", "Japanese", "Katakana", "Hiragana",
                  "Hangul", "Korean", "Greek", "Thai", "Tamil", "Telugu"}
OCR_DPI_LONG_SIDE = 2000       # render scans so the long side is ~2000 px


def script_reader(texts):
    """The reader for the script most of these letters are in (a broken text layer still holds
    real Telugu or Bengali letters among its junk), or None."""
    counts = {}
    letters = [c for t in texts for c in t if c.isalpha()]
    for kind, pat in OWN_SCRIPT.items():
        if kind != "tess:yid" and kind != "cyrillic":
            counts[kind] = sum(1 for c in letters if pat.match(c))
    if not counts:
        return None
    kind = max(counts, key=counts.get)
    return kind if counts[kind] >= 20 and counts[kind] >= 0.3 * len(letters) else None


RTL_TEXT = re.compile(r"[\u0590-\u05ff\u0600-\u06ff\u0750-\u077f\ufb1d-\ufdff\ufe70-\ufeff]")
LTR_RUN = re.compile(r"[0-9A-Za-z.,:%/\-]+")


def visual_to_logical(text):
    """The Arabic reader returns letters left to right as they look; reading order is right to
    left. Reverse, but keep runs of digits/Latin left to right ('2009' stays 2009)."""
    if not RTL_TEXT.search(text):
        return text
    return LTR_RUN.sub(lambda m: m.group(0)[::-1], text[::-1])


class OCR:
    def __init__(self):
        self._engines = {}
        self._lock = threading.Lock()
        self._tess = None

    def _tesseract(self):
        if self._tess is None:
            from . import tess
            self._tess = tess.Tess() if tess.available() else False
        return self._tess or None

    def _engine(self, kind):
        if kind not in self._engines:
            from rapidocr import RapidOCR
            d = resource("models", "ocr")
            self._engines[kind] = RapidOCR(params={
                "Global.log_level": "error",
                # the line-angle classifier turns good lines upside down on old typewritten scans
                # ('WHAT DO THEY WANT?' -> '„NV VM,'); measured: off reads more, and better
                "Global.use_cls": False,
                # lines read with less confidence than this were all junk on the books measured
                # (manga sound effects 'Ti7', specks 'MI', '1'); real text starts around 0.75
                "Global.text_score": 0.7,
                "Det.model_path": os.path.join(d, "PP-OCRv6_det_small.onnx"),
                "Cls.model_path": os.path.join(d, "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
                "Rec.model_path": os.path.join(d, REC[kind]),
            })
        return self._engines[kind]

    def read(self, img, kind="ch", lines=False):
        """img: HxWx3 uint8 array -> ([(x0, y0, x1, y1, text, line)], mean score). lines: Tesseract
        may read line by line where it finds no lines itself (only for a reader the user chose:
        in a contest it lets every script's model 'read' every line as junk)"""
        if kind.startswith("tess:"):
            return self._read_tess(img, kind[5:], lines=lines)
        with self._lock:
            r = self._engine(kind)(img, return_word_box=True)
        if not r.txts:
            return [], 0.0
        words = []
        wr = getattr(r, "word_results", None) or []
        for line, (box, text) in enumerate(zip(r.boxes, r.txts)):
            parts = wr[line] if line < len(wr) and wr[line] else None
            if parts:
                for w in parts:
                    t, quad = w[0], np.asarray(w[2], float).reshape(-1, 2)
                    if t.strip():
                        words.append((quad[:, 0].min(), quad[:, 1].min(), quad[:, 0].max(), quad[:, 1].max(), t, line))
            else:   # no word boxes: split the line box by character count
                quad = np.asarray(box, float).reshape(-1, 2)
                x0, y0, x1, y1 = quad[:, 0].min(), quad[:, 1].min(), quad[:, 0].max(), quad[:, 1].max()
                toks = text.split()
                total = sum(len(t) + 1 for t in toks) or 1
                x = x0
                for t in toks:
                    nx = x + (x1 - x0) * (len(t) + 1) / total
                    words.append((x, y0, nx - (x1 - x0) / total, y1, t, line))
                    x = nx
        if kind == "arabic":                     # Arabic/Persian/Urdu: letters come out mirrored
            words = [w[:4] + (visual_to_logical(w[4]),) + w[5:] for w in words]
        return words, float(np.mean(r.scores))

    @staticmethod
    def confident(words, score, kind="ch"):
        """How much text a reader is sure of: characters x mean confidence. On pages of a known
        script the right reader wins by far (Tamil 1306 vs 41, Thai 875 vs 207, Russian 1657
        vs 100), and a wrong reader can't win by being sure of a single character. A reader
        made for one script is credited only with that script: on a Latin or Cyrillic page the
        Tamil reader's Latin-looking guesses count for nothing."""
        import unicodedata
        own = OWN_SCRIPT.get(kind)
        if own is None:                     # letters only: digits and dots say nothing about the script
            return sum(unicodedata.category(c)[0] in "LM" for w in words for c in w[4]) * score
        return sum(len(own.findall(w[4])) for w in words) * score

    @classmethod
    def value(cls, words, score, kind="ch"):
        """What a reader's result is worth: its confident letters, weighed by how much of it is
        real words in the language it looks like (script purity where there is no word list).
        A reader made for a look-alike script (Hindi on a Bengali page, Tamil on Malayalam)
        is sure of many letters that make no words."""
        return cls.value_q(words, score, kind)[0]

    @classmethod
    def value_q(cls, words, score, kind="ch"):
        """-> (value, real-word share) — see value()."""
        c = cls.confident(words, score, kind)
        if c <= 0:
            return 0.0, 0.0
        from .layout import text_quality
        from .translate import detect_language
        texts = [w[4] for w in words]
        q = text_quality(texts, detect_language(" ".join(texts)))
        return c * max(0.15, q), q

    def best_of(self, img, kinds, best=None):
        """-> (kind, words, score) of the reader among `kinds` with the most confident text."""
        for kind in kinds:
            if best is not None and kind == best[0]:
                continue
            w, s = self.read(img, kind)
            if best is None or self.value(w, s, kind) > self.value(best[1], best[2], best[0]):
                best = (kind, w, s)
        return best

    def _read_tess(self, img, model, scale=1.5, lines=False):
        """Tesseract read at 1.5x (small print reads much better: Hebrew newspaper 0.62 -> 0.79)."""
        from PIL import Image
        t = self._tesseract()
        if t is None:
            return [], 0.0
        im = img if isinstance(img, Image.Image) else Image.fromarray(img)
        if scale != 1:
            im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        words, score = t.read(im, model)
        words = [(x0 / scale, y0 / scale, x1 / scale, y1 / scale, txt, line) for x0, y0, x1, y1, txt, line in words]
        if len(words) < 3 and not isinstance(img, Image.Image):
            # a coloured frame round the page makes Tesseract take it all for one picture (a
            # Punjabi novel: 0 words; inside the frame: 120): read just where the text is
            box = self._text_area(img)
            if box is not None:
                x0, y0, x1, y1 = box
                im2 = Image.fromarray(np.ascontiguousarray(img[y0:y1, x0:x1]))
                if scale != 1:
                    im2 = im2.resize((int(im2.width * scale), int(im2.height * scale)), Image.LANCZOS)
                w2, s2 = t.read(im2, model)
                if len(w2) > len(words):
                    words = [(x0 + a / scale, y0 + b / scale, x0 + c / scale, y0 + d / scale, txt, line)
                             for a, b, c, d, txt, line in w2]
                    score = s2
        if lines and len(words) < 3 and not isinstance(img, Image.Image):
            # Tesseract finds no lines on pictures (comics): PaddleOCR's line finder does, and
            # Tesseract reads each line it found
            lw, ls = self._tess_lines(img, model)
            if len(lw) > len(words):
                words, score = lw, ls
        if model in ("heb", "yid"):            # its word-by-word output comes in visual order
            words = [w[:4] + (visual_to_logical(w[4]),) + w[5:] for w in words]
        return words, score

    def _text_area(self, img):
        """(x0, y0, x1, y1) around the text lines PaddleOCR's detector finds, when that is clearly
        smaller than the image; None otherwise. Remembered for the last image (every Tesseract
        model of a contest asks about the same one)."""
        key = (id(img), img.shape, int(img[::97, ::89].sum()))
        if getattr(self, "_area_key", None) == key:
            return self._area
        with self._lock:
            det = self._engine("ch").text_det(img)
        area = None
        if det.boxes is not None and len(det.boxes):
            q = np.asarray(det.boxes, float).reshape(-1, 2)
            h, w = img.shape[:2]
            pad = 12
            x0, y0 = max(0, int(q[:, 0].min()) - pad), max(0, int(q[:, 1].min()) - pad)
            x1, y1 = min(w, int(q[:, 0].max()) + pad), min(h, int(q[:, 1].max()) + pad)
            if (x1 - x0) * (y1 - y0) < 0.9 * w * h and x1 - x0 > 20 and y1 - y0 > 20:
                area = (x0, y0, x1, y1)
        self._area_key, self._area = key, area
        return area

    def _tess_lines(self, img, model, scale=2.0):
        """Tesseract line by line, on the text lines PaddleOCR's detector finds."""
        from PIL import Image
        t = self._tesseract()
        with self._lock:
            det = self._engine("ch").text_det(img)
        if t is None or det.boxes is None:
            return [], 0.0
        words, confs = [], []
        for line, quad in enumerate(det.boxes):
            q = np.asarray(quad, float).reshape(-1, 2)
            x0, y0 = max(0, int(q[:, 0].min()) - 2), max(0, int(q[:, 1].min()) - 2)
            x1, y1 = int(q[:, 0].max()) + 2, int(q[:, 1].max()) + 2
            crop = Image.fromarray(np.ascontiguousarray(img[y0:y1, x0:x1]))
            if crop.width < 4 or crop.height < 4:
                continue
            crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.LANCZOS)
            ws, c = t.read_line(crop, model)
            for a0, b0, a1, b1, txt in ws:
                words.append((x0 + a0 / scale, y0 + b0 / scale, x0 + a1 / scale, y0 + b1 / scale, txt, line))
            if ws:
                confs.append(c)
        return words, (sum(confs) / len(confs) if confs else 0.0)

    def _tess_contest(self, img, band, scan=True):
        """-> (value on the band, 'tess:<model>', detector sure) for the page's script, or None:
        Tesseract's script detector when it is sure (Bengali, Malayalam), otherwise every model
        on the band (most confident letters of its own script wins; right on Bengali, Georgian,
        Malayalam, Hebrew, Burmese, Kannada)."""
        from PIL import Image
        from . import tess
        t = self._tesseract()
        if t is None:
            return None
        name, conf = t.script(Image.fromarray(img))
        if conf >= 20 and name in PADDLE_SCRIPTS:      # (a Burmese page was "Latin" at 4.4: only far surer counts)
            return None         # sure it is a script PaddleOCR reads (an Arabic kids' page: 132 sure)
        sure = tess.SCRIPT_MODEL.get(name) if conf >= 2.0 else None
        if sure:
            w, s = self._read_tess(band, sure, scale=1.0, lines=False)
            c = self.value(w, s, "tess:" + sure)
            # trusted only when its model reads the page with confidence: the detector once took
            # a Sinhala page for Kannada (3.5 sure), and the Kannada model read it at 0.28
            if c > 0 and s >= 0.6:
                return c, "tess:" + sure, True
            scan = True
        if not scan:
            return None
        h = band.shape[0]                    # a thinner strip is enough to tell the scripts apart
        strip = np.ascontiguousarray(band[int(h * 0.3):int(h * 0.7)]) if h > 300 else band
        results = []
        for m in sorted(set(tess.SCRIPT_MODEL.values())):
            w, s = self._read_tess(strip, m, scale=1.0, lines=False)
            results.append((self.value(w, s, "tess:" + m), "tess:" + m, False, s))
        results.sort(reverse=True)
        # a clear winner only: MEASURED real pages 63-691, 1.44x+ the next model, read at 0.41-0.91;
        # junk (a handwritten Persian manuscript, an Arabic picture page) <= 38, read at 0.26-0.34
        if results[0][0] < 30 or results[0][0] < 1.25 * results[1][0] or results[0][3] < 0.38:
            return None
        # read on a strip, compared with PaddleOCR readers that read the whole band: scale up
        return results[0][0] * h / max(1, strip.shape[0]), results[0][1], False

    def _paddle_scores(self, area):
        """{reader: (value, real-word share, mean confidence)} for every PaddleOCR reader on `area`.
        The text lines are found once and each reader only recognises them (finding lines is
        most of a read and doesn't depend on the script): ~5 s instead of ~33 s for 11 readers."""
        from rapidocr.ch_ppocr_rec import TextRecInput
        from rapidocr.utils.process_img import get_rotate_crop_image
        import copy
        with self._lock:
            det = self._engine("ch").text_det(area)
        if det.boxes is None or not len(det.boxes):
            return {}
        crops = [get_rotate_crop_image(area, copy.deepcopy(b)) for b in det.boxes]
        out = {}
        for kind in REC:
            with self._lock:
                r = self._engine(kind).text_rec(TextRecInput(img=crops, return_word_box=False))
            pairs = [(t, s) for t, s in zip(r.txts or (), r.scores or ()) if s >= 0.7]   # as a real read keeps
            words = [(0, 0, 0, 0, tok, 0) for t, _ in pairs for tok in t.split()]
            mean = sum(s for _, s in pairs) / len(pairs) if pairs else 0.0
            if kind == "arabic":
                words = [w[:4] + (visual_to_logical(w[4]),) + w[5:] for w in words]
            out[kind] = self.value_q(words, mean, kind) + (mean,)
        return out

    def contest(self, img):
        """The reader for this page: every reader reads a band from the middle of the page, the
        most confident letters of its own script win (Tesseract's readers join in unless a
        PaddleOCR reader read the band clearly). A page with little text in that band is judged
        whole."""
        h = img.shape[0]
        for area in (np.ascontiguousarray(img[int(h * 0.3):int(h * 0.6)]), img):
            best = None
            for kind, (c, q, s) in self._paddle_scores(area).items():
                if best is None or c > best[0]:
                    best = (c, kind, s, q)
            if best is None:
                continue
            # Tesseract's script detector always has its say, and when it is sure of a script only
            # Tesseract reads, it decides (the Hindi reader 'reads' Bengali confidently, as junk);
            # all Tesseract models try the band only when no PaddleOCR reader read it well
            clear = best[2] >= 0.9 and best[0] >= 50 and best[3] >= 0.5
            fair = best[1] not in ("ch", "latin") and best[2] >= 0.75 and best[0] >= 50 and best[3] >= 0.5
            # (the Hindi reader reads its neighbours Bengali, Gurmukhi, Gujarati "confidently" as
            # junk: its wins are always checked against Tesseract)
            t = self._tess_contest(img, area, scan=not (clear or fair) or best[1] == "devanagari")
            if t and (t[2] or t[0] > best[0]):
                best = (t[0], t[1], 0, 1)
            if best[0] >= 20:
                break
        return best[1] if best is not None else "ch"      # no text lines anywhere (a picture page)

    def best_any(self, img, best=None):
        """Every reader (PaddleOCR's and Tesseract's): the contest's winner read in full, or
        `best` when that read more."""
        kind = self.contest(img)
        if best is not None and kind == best[0]:
            return best
        w, s = self.read(img, kind)
        if best is None or self.value(w, s, kind) > self.value(best[1], best[2], best[0]):
            return kind, w, s
        return best

    def choose_kind(self, img):
        """Pick the reader model for a document from one of its scanned pages.
        -> (kind, that page's words read with it, mean confidence)"""
        from .layout import CJK_CHAR, text_quality
        from .translate import detect_language
        words, score = self.read(img, "ch")
        text = "".join(w[4] for w in words)
        # the Chinese/English reader read it well: Chinese/Japanese text, or real words in a
        # Latin-alphabet language (read again with the Latin reader for the accents)
        if score >= 0.85 and len(text) >= 30:
            if len(CJK_CHAR.findall(text)) > 0.3 * len(text):
                return "ch", words, score
            lang = detect_language(" ".join(w[4] for w in words))
            if (lang == "en" or lang in LATIN_LANGS) and text_quality([w[4] for w in words], lang) >= 0.7:
                return (("latin",) + self.read(img, "latin")) if lang in LATIN_LANGS else ("ch", words, score)
        # otherwise every reader has a go (PaddleOCR's and Tesseract's); the most confident wins
        return self.best_any(img, ("ch", words, score))


def render_for_ocr(page):
    """-> (HxWx3 uint8 image, points-per-pixel scale)"""
    import pymupdf
    long_pts = max(page.rect.width, page.rect.height)
    zoom = OCR_DPI_LONG_SIDE / long_pts
    pm = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    img = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)[:, :, :3]
    return np.ascontiguousarray(img), 1.0 / zoom
