"""The book being read: layout cache + per-page sentences, filled in as pages are processed."""
import os
import re
import statistics
import threading
import unicodedata

import pymupdf

from .layout import LayoutCache, LayoutWorker, broken_layer, exact_words, strip_punct
from .reflow import build_sentences
from .translate import detect_book_language, detect_language, nllb_code

WINDOW = 3      # pages of context on each side when reflowing a page
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")   # Chinese/Japanese (Korean words are matched whole)
# headings that are numbered divisions of a book: 'Chapter 2', 'Part One', 'Capítulo II', '第三章'
DIVISION = re.compile(r"^(chapter|chap\.|part|book|cap[ií]tulo|parte|libro|chapitre|partie|livre|kapitel|teil|buch|"
                      r"capitolo|глава|часть|книга)\b|^第.{1,6}[章回节節部篇卷]", re.I)
# front and back matter: kept as chapters, but never the sign of a chaptered book on their own
MATTER = re.compile(r"^(prologue|epilogue|introduction|preface|foreword|afterword|appendix|conclusion|"
                    r"pr[oó]logo|ep[ií]logo|introducci[oó]n|prefacio|ap[eé]ndice|conclusi[oó]n|avant-propos|"
                    r"pr[eé]face|einleitung|vorwort|nachwort|introduzione|prefazione|введение|предисловие|"
                    r"пролог|эпилог|заключение)\b", re.I)
CHAPTER_WORD = re.compile(DIVISION.pattern + "|" + MATTER.pattern, re.I)
CONTENTS_LINE = re.compile(r"(\.{2,}|…)\s*\d+\s*$|\.{6,}")     # 'CHAPTER 3 ........ 59'



def _norm(word):
    """A word as search compares it: case-folded, without surrounding punctuation."""
    w = unicodedata.normalize("NFKC", word).casefold()
    return strip_punct(w)


def _tokens(query):
    out = []
    for t in query.split():
        t = _norm(t)
        out += list(t) if CJK.search(t) else ([t] if t else [])
    return out


def _page_text(page):
    """The page's text (its exact words when BookTalker converted the book and kept them)."""
    exact = exact_words(page)
    return " ".join(w[4] for w in exact) if exact is not None else page.get_text()


class Book:
    def __init__(self, path, get_model, on_update=None, source=None, get_ocr=None, code_mode="explain"):
        self.path = path                       # the PDF being shown (converted if needed)
        self.source = source or path           # the file the user opened
        self.doc = pymupdf.open(path)          # for rendering (GUI thread only)
        self.page_count = self.doc.page_count
        n = self.page_count                    # 12 pages spread through the book, not just its front
        texts = [_page_text(self.doc[i]) for i in sorted({round(k * (n - 1) / 11) for k in range(12)})] if n else []
        # pages in an old non-Unicode font are junk in any language: they don't vote (the book's
        # language then comes from the pages OCR reads)
        texts = [t for t in texts if not broken_layer(t.split())]
        self.lang, sample = detect_book_language(texts)
        self.nllb = nllb_code(self.lang, sample)
        # A scanned book has no text to detect the language from until OCR has run.
        self.lang_pending = len("".join(texts).strip()) < 200
        self.cache = LayoutCache(path, self.page_count)
        self._search_index = {}                # page -> (normalised words, rects)
        self._toc = None
        self.lock = threading.Lock()
        self.page_sents = {}                   # page -> [Sentence] (published)
        self.code_mode = code_mode             # computer code: explain | verbatim | skip (bt/code.py)
        self.has_code = False                  # code found on a page read so far
        self.on_update = on_update
        self._refresh(set(self.cache.pages))
        self._check_language()
        self.worker = LayoutWorker(path, self.cache, get_model, self._progress, get_ocr,
                                   get_lang=lambda: self.lang)
        self.worker.start()

    # ---- building --------------------------------------------------------------
    def _progress(self, pages):
        touched = set()
        for p in pages:
            touched.update(range(p - WINDOW, p + WINDOW + 1))
        self._refresh(touched)
        self._check_language()
        if self.on_update:
            self.on_update(pages)

    def set_language(self, code):
        """The reader says what language the book is in (detection can be fooled)."""
        self.lang = code
        self.nllb = nllb_code(code)
        self.lang_pending = False
        self.lang_fixed = True
        # scanned pages are read (again) with that language's own reader: a Bengali comic the
        # readers took for Hindi reads in Bengali once the reader says so
        from .ocr import LANG_READER
        reader = LANG_READER.get(code)
        if reader and self.cache.meta.get("ocr_kind") != reader:
            with self.cache.lock:
                self.cache.meta["ocr_kind"] = reader
                self.cache.meta["ocr_fixed"] = True
                self.cache.redo |= {p for p, d in self.cache.pages.items() if d.get("ocr") and d.get("reader") != reader}
            if getattr(self, "worker", None) is not None:
                self.worker.wake.set()

    def _check_language(self):
        """Scanned books: detect the language from the OCR'd text once there is enough."""
        if getattr(self, "lang_fixed", False):
            return
        if not self.lang_pending:
            # a text layer that was junk (someone's OCR of Armenian as Latin letters) gave the
            # first guess: once our OCR has replaced 3 such pages, their language decides
            if getattr(self, "_relooked", False):
                return
            with self.cache.lock:
                redone = [" ".join(w[4] for b in d["blocks"] for w in b["words"])
                          for d in self.cache.pages.values() if d.get("replaced")]
            if len(redone) < 3:
                return
            self._relooked = True
            self.lang, sample = detect_book_language(redone)
            self.nllb = nllb_code(self.lang, sample)
            return
        with self.cache.lock:
            texts = [" ".join(w[4] for b in d["blocks"] for w in b["words"]) for d in self.cache.pages.values()]
            done = len(self.cache.pages) >= self.page_count
        # a few pages of text first (one front page can be in another language); a short
        # document settles once all its pages are read, however little text it has
        if done or (len("".join(texts)) >= 200 and (sum(len(t) >= 100 for t in texts) >= 4 or len(texts) >= 10)):
            self.lang, sample = detect_book_language(texts)
            self.nllb = nllb_code(self.lang, sample)
            self.lang_pending = False

    def _refresh(self, pages):
        known = self.cache.pages
        new = {}
        for p in sorted(pages):
            if (p not in known or not (p + 1 in known or p + 1 >= self.page_count)
                    or not (p - 1 in known or p == 0)):
                continue    # publish a page once both neighbours are known (run-on text)
            # the contiguous stretch of known pages around p
            run = [p]
            for q in range(p - 1, p - WINDOW - 1, -1):
                if q not in known:
                    break
                run.insert(0, q)
            for q in range(p + 1, p + WINDOW + 1):
                if q not in known:
                    break
                run.append(q)
            with self.cache.lock:
                layout = {q: known[q] for q in run}
            if not self.has_code and any(b["label"] == "Code" for b in layout[p]["blocks"]):
                self.has_code = True
            new[p] = [s for s in build_sentences(run, layout, self.lang, self.code_mode) if s.page == p]
        with self.lock:
            self.page_sents.update(new)

    def set_code_mode(self, mode, around=0):
        """Explain / read exactly / skip the code: the pages near `around` are redone at once,
        the rest in the background."""
        if mode == self.code_mode:
            return
        self.code_mode = mode
        pages = sorted(self.cache.pages)
        near = {p for p in pages if around - WINDOW <= p <= around + 2 * WINDOW}
        self._refresh(near)
        rest = set(pages) - near
        if rest:
            threading.Thread(target=self._refresh, args=(rest,), daemon=True).start()

    # ---- queries -------------------------------------------------------------------
    def want(self, page):
        self.worker.want(max(0, page - 1))     # the page before holds the start of run-on text

    def ready(self, page):
        with self.lock:
            return page in self.page_sents

    def sentences_on(self, page):
        with self.lock:
            return list(self.page_sents.get(page, []))

    def no_text(self, page):
        d = self.cache.pages.get(page)
        return bool(d and d.get("no_text"))

    def is_scanned(self, page):
        d = self.cache.pages.get(page)
        return bool(d and d.get("ocr"))

    def get(self, key):
        """Sentence with this key, or the first one after it; 'wait' if not ready."""
        page = key[0]
        while page < self.page_count:
            with self.lock:
                sents = self.page_sents.get(page)
            if sents is None:
                self.want(page)
                return "wait"
            for s in sents:
                if page > key[0] or s.key >= key:
                    return s
            page += 1
        return None

    @staticmethod
    def _position(sents, key):
        """Index of the sentence with this key in reading order (keys are not always
        sorted: a deferred footnote is read after the paragraph it interrupts)."""
        for i, s in enumerate(sents):
            if s.key == key:
                return i, True
        for i, s in enumerate(sents):
            if s.key > key:
                return i, False
        return len(sents), False

    def next_after(self, key):
        page = key[0]
        with self.lock:
            sents = self.page_sents.get(page)
        if sents is not None:
            i, exact = self._position(sents, key)
            i += exact
            if i < len(sents):
                return sents[i]
        return self.get((page + 1, -1)) if page + 1 < self.page_count else None

    def prev_before(self, key):
        page = key[0]
        with self.lock:
            sents = self.page_sents.get(page)
        if sents:
            i = self._position(sents, key)[0] - 1
            if i >= 0:
                return sents[i]
        for p in range(page - 1, -1, -1):
            with self.lock:
                sents = self.page_sents.get(p)
            if sents is None:
                return None
            if sents:
                return sents[-1]
        return None

    def sentence_at(self, page, x, y):
        """Sentence containing the word nearest to (x, y) on the page."""
        best = None
        for s in self.sentences_on(page):
            for w in s.words:
                for (p, x0, y0, x1, y1) in w.rects:
                    if p != page:
                        continue
                    dx = max(x0 - x, 0, x - x1)
                    dy = max(y0 - y, 0, y - y1)
                    d = dx * dx + dy * dy
                    if best is None or d < best[0]:
                        best = (d, s)
        return best[1] if best and best[0] < 40 * 40 else None

    # ---- search and chapters -----------------------------------------------------
    def search(self, query):
        """-> [(page, [word rects])] for the query, over the pages prepared so far. Words must
        match in order; the last one may be the start of a word (so results come while typing)."""
        q = _tokens(query)
        if not q:
            return []
        with self.cache.lock:
            pages = sorted(self.cache.pages.items())
        out, n = [], len(q)
        for p, d in pages:
            idx = self._search_index.get(p)
            if idx is None:
                words = [w for b in d.get("blocks", []) for w in b["words"]]
                idx = ([_norm(w[4]) for w in words], [tuple(w[:4]) for w in words])
                self._search_index[p] = idx
            norm, rects = idx
            for i in range(len(norm) - n + 1):
                if norm[i + n - 1].startswith(q[-1]) and all(norm[i + k] == q[k] for k in range(n - 1)):
                    out.append((p, rects[i:i + n]))
        return out

    def prepared(self):
        return len(self.cache.pages) >= self.page_count

    def chapters(self):
        """-> [(level, title, page, y)], worked out once every page is prepared (bt/chapters.py);
        [] before that, and for books without chapters."""
        if self._toc is not None:
            return self._toc
        if not self.prepared():
            return []
        from .chapters import work_out
        with self.cache.lock:
            pages = dict(self.cache.pages)
        try:
            labels = {i: self.doc[i].get_label() for i in range(self.page_count)}
            labels = {i: l for i, l in labels.items() if l}
        except Exception:
            labels = {}
        try:
            outline = self.doc.get_toc(simple=False)
        except Exception:
            outline = []
        self._toc = work_out(outline, pages, labels, self.page_count, self.lang)
        return self._toc

    def first_sentence_from(self, page, y):
        """The first sentence that starts at or below y on this page (None if the page isn't
        ready yet; then the next sentence after it)."""
        with self.lock:
            sents = self.page_sents.get(page)
        if sents is None:
            return None
        for s in sents:
            r = next((r for w in s.words for r in w.rects if r[0] == page), None)
            if r is not None and r[2] >= y - 3:
                return s
        return self.get((page + 1, -1)) if page + 1 < self.page_count else None

    def close(self):
        self.worker.stop()
        self.worker.join(timeout=5)     # let a page in progress finish before saving
        self.cache.compact()
