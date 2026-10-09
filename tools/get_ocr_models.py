"""One-time: put every OCR model BookTalker uses into models/ocr (works offline after).

    .venv\\Scripts\\python.exe tools\\get_ocr_models.py
"""
import os
import shutil

import numpy as np
import rapidocr
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "models", "ocr")
os.makedirs(OUT, exist_ok=True)
# the default det/cls/rec (PP-OCRv6 Chinese+English+Japanese) ship inside the rapidocr wheel
src = os.path.join(os.path.dirname(rapidocr.__file__), "models")
for f in os.listdir(src):
    if f.endswith(".onnx"):
        shutil.copy2(os.path.join(src, f), OUT)
blank = np.full((64, 256, 3), 255, np.uint8)
for lang in (LangRec.LATIN, LangRec.ESLAV, LangRec.KOREAN, LangRec.EL, LangRec.TH, LangRec.ARABIC,
             LangRec.DEVANAGARI, LangRec.CYRILLIC, LangRec.TA, LangRec.TE):
    RapidOCR(params={"Global.model_root_dir": OUT, "Global.log_level": "error",
                     "Rec.lang_type": lang, "Rec.ocr_version": OCRVersion.PPOCRV5,
                     "Rec.model_type": ModelType.MOBILE})(blank)
for f in sorted(os.listdir(OUT)):
    print(f"{os.path.getsize(os.path.join(OUT, f)) / 1e6:6.1f} MB  {f}")
