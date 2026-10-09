"""Readers for the scripts PaddleOCR has no model for, using Tesseract's LSTM engine (bundled
library, Apache 2.0) with its 'fast' trained models in models/tessdata:

    Bengali  Gurmukhi (Punjabi)  Gujarati  Malayalam  Kannada  Sinhala  Burmese  Khmer  Lao
    Tibetan  Georgian  Armenian  Ethiopic (Amharic)  Hebrew  Yiddish

Tesseract's script detector (osd) names the script of a page in a fraction of a second, so the
right model is tried only when it can help. Words come back in reading order with their boxes.
"""
import os
import threading

from .paths import resource

# Tesseract's script name (from osd) -> its trained model
SCRIPT_MODEL = {"Bengali": "ben", "Gurmukhi": "pan", "Gujarati": "guj", "Malayalam": "mal",
                "Kannada": "kan", "Sinhala": "sin", "Myanmar": "mya", "Khmer": "khm", "Lao": "lao",
                "Tibetan": "bod", "Georgian": "kat", "Armenian": "hye", "Ethiopic": "amh", "Hebrew": "heb"}
# model -> book language that selects it over its script's default (Yiddish is written in Hebrew letters)
LANG_MODEL = {"yi": "yid"}
MODELS = set(SCRIPT_MODEL.values()) | set(LANG_MODEL.values())


def tessdata():
    return resource("models", "tessdata")


def preload():
    """Import the Tesseract library now, on the main thread: on import it sets up signal
    handlers, which Python allows only there (imported first from the page-reading thread, it
    fails with 'signal only works in main thread')."""
    try:
        import tesserocr  # noqa: F401
    except Exception:
        _log("Tesseract readers unavailable")


def available():
    try:
        import tesserocr  # noqa: F401
    except Exception:
        _log("Tesseract readers unavailable")
        return False
    if not os.path.exists(os.path.join(tessdata(), "osd.traineddata")):
        _log("Tesseract models missing in " + tessdata(), trace=False)
        return False
    return True


def _log(what, trace=True):
    """Note in error.log why the extra readers are off (the app carries on without them)."""
    import time
    import traceback
    try:
        d = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BookTalker")
        with open(os.path.join(d, "error.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {what}\n{traceback.format_exc() if trace else ''}\n")
    except OSError:
        pass


class Tess:
    """One Tesseract engine per model, made on first use and reused (calls are serialised)."""

    def __init__(self):
        self._apis = {}
        self._lock = threading.Lock()

    def _api(self, model, psm=None):
        import tesserocr
        key = (model, psm)
        if key not in self._apis:
            kw = {"path": tessdata(), "lang": model}
            if psm is not None:
                kw["psm"] = psm
            self._apis[key] = tesserocr.PyTessBaseAPI(**kw)
        return self._apis[key]

    def script(self, img):
        """-> (Tesseract script name, confidence 0..100) for a page image (PIL), or (None, 0)."""
        import tesserocr
        with self._lock:
            try:
                api = self._api("osd", tesserocr.PSM.OSD_ONLY)
                api.SetImage(img)
                osd = api.DetectOrientationScript()
            except Exception:
                return None, 0
        if not osd:
            return None, 0
        return osd.get("script_name"), osd.get("script_conf", 0)

    def read_line(self, img, model):
        """One line of text (PIL image) -> ([(x0, y0, x1, y1, text)], mean confidence 0..1)."""
        import tesserocr
        from tesserocr import RIL, iterate_level
        with self._lock:
            api = self._api(model, tesserocr.PSM.SINGLE_LINE)
            api.SetImage(img)
            api.Recognize()
            ri = api.GetIterator()
            words, confs = [], []
            if ri is not None:
                for r in iterate_level(ri, RIL.WORD):
                    try:
                        text = r.GetUTF8Text(RIL.WORD)
                    except RuntimeError:
                        continue
                    box = r.BoundingBox(RIL.WORD)
                    if text and text.strip() and box:
                        words.append((box[0], box[1], box[2], box[3], text.strip()))
                        confs.append(r.Confidence(RIL.WORD))
        return words, (sum(confs) / len(confs) / 100.0 if confs else 0.0)

    def read(self, img, model):
        """img: PIL image -> ([(x0, y0, x1, y1, text, line)], mean confidence 0..1) in image pixels."""
        import tesserocr
        from tesserocr import RIL, iterate_level
        with self._lock:
            api = self._api(model)
            api.SetImage(img)
            api.Recognize()
            ri = api.GetIterator()
            words, confs, line = [], [], -1
            if ri is not None:
                for r in iterate_level(ri, RIL.WORD):
                    try:
                        text = r.GetUTF8Text(RIL.WORD)
                    except RuntimeError:             # an empty word: Tesseract raises rather than return ''
                        continue
                    if not text or not text.strip():
                        continue
                    if r.IsAtBeginningOf(RIL.TEXTLINE):
                        line += 1
                    box = r.BoundingBox(RIL.WORD)
                    if not box:
                        continue
                    conf = r.Confidence(RIL.WORD)
                    words.append((box[0], box[1], box[2], box[3], text.strip(), max(line, 0)))
                    confs.append(conf)
        if not words:
            return [], 0.0
        return words, sum(confs) / len(confs) / 100.0
