"""Save a book as an audiobook: a folder named after the book ('Title - Author (Year)') holding one
MP3 per chapter ('01 - Chapter name.mp3'), tagged for audiobook players, read the way the
reader has it set up (original or translation, the chosen voice, code explained or read).

Runs in its own process (run()), so the window and the voice reading aloud stay smooth; it
reports progress through a queue: ("prep", share), ("start", files), ("file", i, title),
("progress", share), ("done", folder, files), ("error", text).
"""
import os
import re
import time
import zipfile

MP3_KBPS = 64               # one voice, 22 kHz: 64 kbit/s mono is clean speech (~29 MB an hour)
PAGES_PER_PART = 20         # a book without chapters is cut into parts of this many pages


def safe_name(s, limit=90):
    """A string made safe as a Windows file or folder name."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", s or "")
    s = " ".join(s.split()).strip(" .")
    return s[:limit].rstrip(" .") or "Untitled"


def find_year(source, metadata):
    """The book's year, from an EPUB's own date, else a year in the title or file name."""
    if source.lower().endswith(".epub"):
        try:
            with zipfile.ZipFile(source) as z:
                opf = next((n for n in z.namelist() if n.lower().endswith(".opf")), None)
                if opf:
                    m = re.search(rb"<dc:date[^>]*>\s*(\d{4})", z.read(opf))
                    if m:
                        return m.group(1).decode()
        except Exception:
            pass
    for text in ((metadata or {}).get("title") or "", os.path.basename(source)):
        m = re.search(r"\b(1[4-9]\d\d|20\d\d)\b", text)
        if m:
            return m.group(1)
    return ""


def folder_name(title, author, year):
    name = title
    if author:
        name += f" - {author}"
    if year:
        name += f" ({year})"
    return safe_name(name, 120)


def plan(book, titles=None):
    """-> ([(title, (page, y) where it starts)] for the whole book, index of chapter 1 in it):
    its chapters, or parts of PAGES_PER_PART pages. Text before the first chapter (a title page,
    a foreword) is a part of its own."""
    chapters = book.chapters()
    if chapters:
        names = titles if titles and len(titles) == len(chapters) else [c[1] for c in chapters]
        out = [(name, (c[2], c[3])) for name, c in zip(names, chapters)]
        if chapters[0][2] > 0 or chapters[0][3] > 80:
            out.insert(0, ("Opening", (0, 0)))
            return out, 1
        return out, 0
    n = book.page_count
    return [(f"Pages {a + 1}-{min(n, a + PAGES_PER_PART)}", (a, 0)) for a in range(0, n, PAGES_PER_PART)], 0


def _sentences(book, start, stop):
    """Sentences from the one at `start` (page, y) up to (not including) the one at `stop`."""
    first = book.first_sentence_from(*start)
    end = book.first_sentence_from(*stop) if stop else None
    end_key = end.key if hasattr(end, "key") else None
    s = first
    while hasattr(s, "key"):
        if end_key is not None and s.key == end_key:
            break
        yield s
        s = book.next_after(s.key)


def id3(tags):
    """An ID3v2.3 tag (title, album, artist, track, year, genre) for the start of an MP3."""
    frames = b""
    for fid, text in tags:
        if text:
            data = b"\x01" + str(text).encode("utf-16")          # UTF-16 with its byte-order mark
            frames += fid.encode() + len(data).to_bytes(4, "big") + b"\x00\x00" + data
    n = len(frames)
    size = bytes(((n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F))
    return b"ID3\x03\x00\x00" + size + frames


class _Mp3:
    ext = ".mp3"

    def __init__(self, path, rate, tags):
        import lameenc
        self.f = open(path, "wb")
        self.f.write(id3(tags))
        self.enc = lameenc.Encoder()
        self.enc.set_bit_rate(MP3_KBPS)
        self.enc.set_in_sample_rate(rate)
        self.enc.set_channels(1)
        self.enc.set_quality(2)

    def write(self, pcm16):
        self.f.write(self.enc.encode(pcm16))

    def close(self):
        self.f.write(self.enc.flush())
        self.f.close()


class _Wav:
    """Used only when the MP3 encoder isn't there."""
    ext = ".wav"

    def __init__(self, path, rate, tags):
        import wave
        self.w = wave.open(path, "wb")
        self.w.setnchannels(1)
        self.w.setsampwidth(2)
        self.w.setframerate(rate)

    def write(self, pcm16):
        self.w.writeframes(pcm16)

    def close(self):
        self.w.close()


def _writer():
    try:
        import lameenc  # noqa: F401
        return _Mp3
    except ImportError:
        return _Wav


def run_job(job, q):
    """job: source, pdf, out_root, voice_path, translate, target, best, code_mode, lang,
    title, author, year, titles (chapter titles as shown), first, last (indexes into the plan)."""
    try:
        _run(job, q)
    except Exception as e:
        import traceback
        q.put(("error", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}"))


def _run(job, q):
    import numpy as np
    from . import tess
    tess.preload()
    from .layout import LayoutCache, LayoutModel
    # the window's own process keeps the page cache; this one only reads it
    LayoutCache.save = lambda self: None
    LayoutCache.compact = lambda self: None
    from .book import Book
    from .code import spoken_text
    from .ocr import OCR
    from .reflow import Sentence, Word
    from .speech import Speaker

    model, ocr = LayoutModel(), OCR()
    book = Book(job["pdf"], lambda: model, source=job["source"], get_ocr=lambda: ocr,
                code_mode=job.get("code_mode", "explain"))
    if job.get("lang"):
        book.set_language(job["lang"])
    book.want(0)
    while not book.prepared():
        q.put(("prep", len(book.cache.pages) / max(1, book.page_count)))
        time.sleep(0.5)
    time.sleep(0.5)
    book._check_language()

    parts, offset = plan(book, job.get("titles"))
    first, last = 0, len(parts) - 1
    if job.get("chapter_range"):
        first, last = (offset + k for k in job["chapter_range"])
    chosen = [(i, parts[i][0], parts[i][1], parts[i + 1][1] if i + 1 < len(parts) else None)
              for i in range(first, last + 1)]
    lists = [(i, title, list(_sentences(book, start, stop))) for i, title, start, stop in chosen]
    lists = [(i, t, ss) for i, t, ss in lists if any(w.say for s in ss for w in s.words) or any(s.code for s in ss)]
    total = sum(len(ss) for _i, _t, ss in lists) or 1
    q.put(("start", len(lists)))

    speaker = Speaker(job["voice_path"])
    translator = None
    if job.get("translate"):
        from .llm import SmartTranslator
        from .translate import Translator
        translator = SmartTranslator(Translator())
        translator.best = job.get("best", True)
        translator.set_target(job["target"])
    folder = os.path.join(job["out_root"], folder_name(job["title"], job.get("author"), job.get("year")))
    os.makedirs(folder, exist_ok=True)
    Writer = _writer()
    width = max(2, len(str(len(lists))))
    done, files = 0, []
    for n, (i, title, sents) in enumerate(lists, 1):
        q.put(("file", n, title))
        name = f"{n:0{width}d} - {safe_name(title)}{Writer.ext}"
        path = os.path.join(folder, name)
        tags = [("TIT2", title), ("TALB", job["title"]), ("TPE1", job.get("author")),
                ("TRCK", f"{n}/{len(lists)}"), ("TYER", job.get("year")), ("TCON", "Audiobook")]
        out = Writer(path + ".part", speaker.rate, tags)
        if translator:
            translator.follow(book, sents[0].key, book.lang, book.nllb)
        for s in sents:
            if s.code:
                text = spoken_text(s, translator, job["target"] if translator else book.lang, wait=60)
                s = Sentence(key=s.key, words=[Word(t, t, []) for t in text.split()], pause=s.pause)
            elif translator and not s.literal:
                text, _ = translator.get(s, book.nllb, wait=120)
                s = Sentence(key=s.key, words=[Word(t, t, []) for t in text.split()], pause=s.pause)
            if any(w.say for w in s.words):
                audio, _ = speaker.speak(s)
                out.write((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
            done += 1
            q.put(("progress", done / total))
        out.close()
        os.replace(path + ".part", path)
        files.append(path)
    if translator:
        translator.shutdown()
    book.close()
    q.put(("done", folder, files))
