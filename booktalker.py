"""BookTalker — reads books aloud and highlights each word on the page as it is spoken.

Copyright (C) 2026 Neal Strassner. Free software under the GNU Affero General Public License
version 3 or later (see LICENSE); it comes with no warranty.

    booktalker.exe                      open the window
    booktalker.exe book.epub            open a book (or drag a file onto the .exe)
    booktalker.exe book.pdf --audio out.wav [--pages 10-20] [--translate]
                                        save the reading as audio (--translate: in English)
"""
import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")
if getattr(sys, "frozen", False):
    os.environ.setdefault("PYTORCH_JIT", "0")       # TorchScript needs .py sources; the .exe has none
    os.environ.setdefault("HF_HUB_OFFLINE", "1")    # models are bundled
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:              # windowed .exe has no console
            setattr(sys, name, open(os.devnull, "w"))


def export_audio(path, out, pages, translate=False, target="en"):
    import time
    import wave

    import numpy as np

    from bt import voices
    from bt.book import Book
    from bt.convert import to_pdf
    from bt.layout import LayoutModel
    from bt.llm import SmartTranslator
    from bt.ocr import OCR
    from bt.reflow import Sentence, Word
    from bt.speech import Speaker
    from bt.translate import Translator

    model, ocr = LayoutModel(), OCR()
    book = Book(to_pdf(path), lambda: model, source=path, get_ocr=lambda: ocr)
    first, last = 0, book.page_count - 1
    if pages:
        a, _, b = pages.partition("-")
        first, last = int(a) - 1, int(b or a) - 1
    book.want(first)
    while not all(book.ready(p) for p in range(first, last + 1)):
        time.sleep(0.5)
    book._check_language()
    translate = (translate or not voices.for_language(book.lang)) and book.lang != target
    voice = voices.default_for(target if translate else book.lang)
    if voice is None:
        sys.exit(f"No {target} voice installed — pick it once in the app's globe menu to download it.")
    speaker = Speaker(voices.installed()[voice]["path"])
    translator = None
    if translate:   # no deadline here: always wait for the AI translation (NLLB if no AI)
        translator = SmartTranslator(Translator())
        translator.set_target(target)
        translator.follow(book, (first, -1), book.lang, book.nllb)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(speaker.rate)
        for p in range(first, last + 1):
            for s in book.sentences_on(p):
                if s.code:              # computer code: explained in plain words
                    from bt.code import spoken_text
                    text = spoken_text(s, translator, target if translate else book.lang, wait=60)
                    s = Sentence(key=s.key, words=[Word(t, t, []) for t in text.split()], pause=s.pause)
                elif translator and not s.literal:
                    english, _ = translator.get(s, book.nllb, wait=180)
                    s = Sentence(key=s.key, words=[Word(t, t, []) for t in english.split()], pause=s.pause)
                audio, _ = speaker.speak(s)
                w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
            print(f"page {p + 1} done", flush=True)
    book.close()
    if translator:
        translator.shutdown()


def export_audiobook(path, out_root, translate=False, target="en"):
    """The whole book as an audiobook (one MP3 per chapter) in out_root, by the same recorder
    process the window's 'Save as audiobook' uses."""
    import multiprocessing
    import queue

    from bt import export, voices
    from bt.convert import to_pdf
    from bt.translate import detect_book_language
    import pymupdf
    pdf = to_pdf(path)
    doc = pymupdf.open(pdf)
    n = doc.page_count
    lang, _ = detect_book_language([doc[i].get_text() for i in sorted({round(k * (n - 1) / 11) for k in range(12)})])
    meta = doc.metadata or {}
    translate = (translate or not voices.for_language(lang)) and lang != target
    voice = voices.default_for(target if translate else lang)
    if voice is None:
        sys.exit("No voice installed for this language.")
    job = {"source": path, "pdf": pdf, "voice_path": voices.installed()[voice]["path"], "translate": translate,
           "target": target, "best": True, "code_mode": "explain", "lang": None, "out_root": out_root,
           "title": (meta.get("title") or "").strip() or os.path.splitext(os.path.basename(path))[0],
           "author": (meta.get("author") or "").strip(), "year": export.find_year(path, meta)}
    doc.close()
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=export.run_job, args=(job, q), daemon=True)
    p.start()
    while True:
        try:
            msg = q.get(timeout=1)
        except queue.Empty:
            if not p.is_alive():
                sys.exit("the recorder stopped")
            continue
        if msg[0] == "file":
            print(f"recording {msg[1]}: {msg[2]}", flush=True)
        elif msg[0] == "done":
            print(f"saved {len(msg[2])} files in {msg[1]}", flush=True)
            return
        elif msg[0] == "error":
            sys.exit(msg[1])


def main():
    ap = argparse.ArgumentParser(description="Read books aloud with word highlighting.")
    ap.add_argument("pdf", nargs="?", help="PDF, EPUB, Word, PowerPoint, text ...")
    ap.add_argument("--audio", help="save the reading to this WAV file instead of opening the window")
    ap.add_argument("--audiobook", metavar="FOLDER", help="save the whole book as an audiobook (one MP3 per chapter) in FOLDER")
    ap.add_argument("--pages", help="page range for --audio, e.g. 10-20")
    ap.add_argument("--translate", action="store_true", help="with --audio: read it translated")
    ap.add_argument("--to", default="en", help="language to translate into: en es fr de it pt ru zh")
    args = ap.parse_args()
    if args.pdf and not os.path.isfile(args.pdf):
        sys.exit(f"File not found: {args.pdf}")
    from bt import tess
    tess.preload()                          # Tesseract's library must first load on the main thread
    if args.audiobook:
        if not args.pdf:
            sys.exit("--audiobook needs a file")
        export_audiobook(os.path.abspath(args.pdf), os.path.abspath(args.audiobook), args.translate, args.to)
        return
    if args.audio:
        if not args.pdf:
            sys.exit("--audio needs a file")
        export_audio(args.pdf, args.audio, args.pages, args.translate, args.to)
        return
    from bt.app import run
    sys.exit(run(args.pdf))


def report_crash():
    """Write the error to %LOCALAPPDATA%\\BookTalker\\error.log and tell the user plainly."""
    import traceback
    base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BookTalker")
    os.makedirs(base, exist_ok=True)
    log = os.path.join(base, "error.log")
    with open(log, "a", encoding="utf-8") as f:
        f.write(traceback.format_exc() + "\n")
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "BookTalker", f"BookTalker hit a problem and has to close.\n\nDetails were saved to:\n{log}")
    except Exception:
        pass


def log_error(kind, value, tb):
    """Errors inside the running window (Qt callbacks) go to the log instead of vanishing."""
    import traceback
    base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BookTalker")
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "error.log"), "a", encoding="utf-8") as f:
        f.write("".join(traceback.format_exception(kind, value, tb)) + "\n")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()        # the voice process re-enters here in the .exe
    sys.excepthook = log_error
    import threading                        # background-thread errors are logged too
    threading.excepthook = lambda a: log_error(a.exc_type, a.exc_value, a.exc_traceback)
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        report_crash()
        sys.exit(1)
