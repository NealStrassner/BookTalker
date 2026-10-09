"""A book's chapters, worked out once its pages are prepared.

Sources, best first:
  1. the book's own outline (PDF bookmarks / EPUB contents) — unless it is leftovers of how the
     file was made ('Ray Stoner1', 'Ray Stoner2' …, file names)
  2. the printed table of contents: its lines ('Chapter 3  The Dragon ........ 41') are read and
     the printed page numbers matched to the PDF's pages (page labels, the numbers printed in the
     page headers/footers, or where each chapter title turns up)
  3. chapter headings found on the pages ('CHAPTER 3' + the title line under it); when the front
     of the book lists the chapters ('1. "SAUCERS FROM INNER EARTH"'), a heading that came out of a
     poor scan takes its name from that list instead
Every name is tidied: broken spacing repaired ('CHAPT ER' -> 'Chapter'), capitals made normal,
and numbered chapters shown as 'Chapter 3 — The Title'. Books without chapters get none.
"""
import difflib
import re
import statistics
from collections import Counter

from .book import CHAPTER_WORD, CONTENTS_LINE, DIVISION

ROMAN = re.compile(r"^(?=[MDCLXVI])M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$", re.I)
SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with",
         "from", "into", "de", "del", "la", "las", "los", "el", "y", "e", "et", "le", "les", "du", "des",
         "der", "die", "das", "und", "von", "zu", "di", "da", "il", "lo"}
NUM_WORDS = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
             "sixteen|seventeen|eighteen|nineteen|twenty|uno|dos|tres|cuatro|cinco|un|deux|trois|eins|zwei|drei")
NUMBERED = re.compile(r"^(?P<word>chapter|chap\.?|part|book|section|cap[ií]tulo|parte|libro|chapitre|partie|"
                      r"livre|kapitel|teil|buch|capitolo|глава|часть|книга)\s+(?P<num>\d{1,3}|[ivxlcdm]{1,7}|"
                      + NUM_WORDS + r")\b[\s:.\-–—]*(?P<rest>.*)$", re.I)
CONTENTS_TITLE = re.compile(r"^\s*(table\s+of\s+)?contents?\s*$|^\s*(í|i)ndice( general)?\s*$|^\s*sommaire\s*$|"
                            r"^\s*table des mati[eè]res\s*$|^\s*inhalt(sverzeichnis)?\s*$|^\s*indice\s*$|"
                            r"^\s*содержание\s*$|^\s*оглавление\s*$|^\s*目\s*[录錄次]\s*$", re.I)


# ---- tidying names ---------------------------------------------------------------------
def _zipf(word, lang):
    try:
        from wordfreq import zipf_frequency
        return zipf_frequency(word.lower(), lang if lang in ("en", "fr", "de", "es", "it", "pt", "ru", "nl") else "en")
    except Exception:
        return 0.0


def _segment(s, lang):
    """'CHAPTERONE' -> 'CHAPTER ONE' (most likely split into real words)."""
    n = len(s)
    best = [(0.0, [])] + [(1e9, [])] * n
    for i in range(1, n + 1):
        for j in range(max(0, i - 20), i):
            w = s[j:i]
            z = _zipf(w, lang)
            cost = best[j][0] + ((8 - z) if z > 0 else 9 + 3 * len(w))
            if cost < best[i][0]:
                best[i] = (cost, best[j][1] + [w])
    return best[n][1]


def fix_spacing(text, lang="en"):
    toks = text.split()
    if len(toks) >= 4 and sum(len(t) == 1 and t.isalpha() for t in toks) >= 0.6 * len(toks):
        out, run = [], ""                                   # 'C H A P T E R  O N E'
        for t in toks + [""]:
            if len(t) == 1 and t.isalpha():
                run += t
            else:
                if run:
                    out += _segment(run, lang) if len(run) > 3 else [run]
                    run = ""
                if t:
                    out.append(t)
        toks = out
    out, i = [], 0
    while i < len(toks):                                    # 'CHAPT ER' -> 'CHAPTER'
        a = toks[i]
        if i + 1 < len(toks) and a.isalpha() and toks[i + 1].isalpha():
            b = toks[i + 1]
            if _zipf(a + b, lang) >= 3 and not (_zipf(a, lang) >= 3 and _zipf(b, lang) >= 3):
                out.append(a + b)
                i += 2
                continue
        out.append(a)
        i += 1
    return " ".join(out)


def _title_case(text):
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return text
    words = text.split()
    out = []
    for k, w in enumerate(words):
        core = w.strip("“”\"'(),.:;!?—–-")
        if ROMAN.match(core) and core.upper() == core:
            out.append(w)
        elif k and core.lower() in SMALL:
            out.append(w.lower())
        else:                                               # 'SUN-GOD'S' -> 'Sun-God's'
            out.append("-".join(x[:1].upper() + x[1:].lower() if x[:1].isalpha() else x[:2].upper() + x[2:].lower()
                                for x in w.split("-")))
    return " ".join(out)


def _unquote(t):
    """'"Colonel Fawcett's Fate"' -> 'Colonel Fawcett's Fate' (quotes around the whole name only)."""
    q = "\"“”«»„"
    if len(t) > 2 and t[0] in q and t[-1] in q and not any(c in q for c in t[1:-1]):
        return t[1:-1].strip()
    return t


def nice_title(text, lang="en"):
    t = " ".join(text.split()).strip(" .·•-–—:")
    t = re.sub(r"[\s.·…_]{3,}\s*\d+\s*$", "", t)          # leader dots + page number
    t = fix_spacing(t, lang)
    t = _title_case(t)
    t = _unquote(t)
    m = NUMBERED.match(t)
    if m:
        word = m.group("word").rstrip(".")
        word = "Chapter" if word.lower() == "chap" else word[:1].upper() + word[1:].lower()
        num = m.group("num")
        num = num.upper() if ROMAN.match(num) and not num.isdigit() else (num if num.isdigit() else num.capitalize())
        rest = _unquote(_title_case(m.group("rest").strip(" .:-–—")))
        rest = rest[:1].upper() + rest[1:]
        return f"{word} {num} — {rest}" if rest else f"{word} {num}"
    m = re.match(r"^(?P<num>[IVXLCDM]{1,6})[.):\s]+(?P<rest>[^\W\d_].*)$", t)    # 'III the Planet Venus'
    if m and ROMAN.match(m.group("num")):
        rest = _title_case(m.group("rest"))
        return f"{m.group('num')} — {rest[:1].upper() + rest[1:]}"
    return t[:1].upper() + t[1:] if t[:1].islower() else t


# ---- 1. the book's own outline -------------------------------------------------------------
def _junk(titles):
    stems = [re.sub(r"[\s_\-]*\d+$", "", t).strip().casefold() for t in titles]
    if len(titles) >= 2 and len(set(stems)) == 1 and all(re.search(r"\d$", t) for t in titles):
        return True                                         # 'Ray Stoner1', 'Ray Stoner2' …
    if sum(bool(re.search(r"\.(pdf|docx?|qxd|indd|html?)$|^\d+_\d{6,}", t, re.I)) for t in titles) > len(titles) / 2:
        return True                                         # file names
    return all(re.fullmatch(r"(?i)(page|part|section|bookmark|untitled|cover)?[\s_\-]*\d*", t.strip()) for t in titles)


def from_outline(rows, page_count):
    out = []
    for row in rows:
        lvl, title, page = row[0], row[1], row[2]
        if not title.strip() or not 1 <= page <= page_count:
            continue
        dest = row[3] if len(row) > 3 and isinstance(row[3], dict) else {}
        to = dest.get("to")
        out.append((lvl, title, page - 1, float(to.y) if to is not None else 0.0))
    if len(out) < 2 or _junk([t for _, t, _, _ in out]):
        return []
    out = [e for e in out if not re.search(r"\.(pdf|docx?|qxd|indd|html?)$", e[1], re.I)
           and not re.fullmatch(r"(?i)\s*(cover|front cover|back cover|title( page)?|copyright( page)?|half title)\s*", e[1])]
    return out if len(out) >= 2 else []


# ---- page text helpers -----------------------------------------------------------------------
def _lines(d, include_extra=True, skip=("PageHeader", "PageFooter")):
    """A prepared page as rows of text: [(y, x, text, label)] top to bottom; pieces at the same
    height (a 'Chapter 1' column beside its title) are joined into one row."""
    blocks = list(d.get("blocks", [])) + (list(d.get("extra", [])) if include_extra else [])
    pieces = {}
    for bi, b in enumerate(blocks):
        if b["label"] in skip:
            continue
        for w in b["words"]:
            ln = pieces.setdefault((bi, w[5]), [w[1], w[0], [], b["label"], w[3]])
            ln[0], ln[1], ln[4] = min(ln[0], w[1]), min(ln[1], w[0]), max(ln[4], w[3])
            ln[2].append((w[0], w[4]))
    rows = []
    for y, x, words, label, y1 in sorted(pieces.values()):
        text = " ".join(t for _, t in sorted(words))
        h = max(1.0, y1 - y)
        if rows and abs(rows[-1][0] - y) < 0.5 * h:            # same row
            r = rows[-1]
            parts = sorted([(r[1], r[2]), (x, text)])
            rank = {"TableOfContents": 0, "SectionHeader": 1}
            label = min((r[3], label), key=lambda l: rank.get(l, 2))
            rows[-1] = (min(r[0], y), parts[0][0], " ".join(t for _, t in parts), label)
        else:
            rows.append((y, x, text, label))
    return rows


def _norm(t):
    return re.sub(r"[^\w]+", "", t.casefold())


# ---- 2. the printed table of contents --------------------------------------------------------
STOP = re.compile(r"(?i)^\s*(list of )?(illustrations|figures|plates|maps|tables)\s*$|^\s*index\s*$")
COLUMN_WORDS = re.compile(r"(?i)\b(page|pages|chap\.?|chapter|pág\.?|página|seite|стр\.?)\s*$|^\s*(page|chap\.?)\b")
LEADS_NEW = re.compile(r"^\s*([IVXLCDM]{1,6}|\d{1,3})[.\s]|^\s*(chapter|part|book|chap\.)\b", re.I)
# a page number may carry one misread letter from OCR ('4r')
ENTRY = re.compile(r"^(?P<title>.*?\w.*?)[\s.·…_\-–]*\s(?P<page>\d{1,4}(?=[a-z]?\s*$)|[ivxlcdm]{1,7}\s*$)[a-z]?\s*$", re.I)


def _contents_pages(pages):
    n = max(pages) + 1 if pages else 0
    found = []
    for p, d in pages.items():
        if p > max(12, n * 0.3):
            continue
        has_toc_block = any(b["label"] == "TableOfContents" for b in d.get("extra", []))
        heads = [t for _, _, t, _ in _lines(d)[:3]]
        if has_toc_block or any(CONTENTS_TITLE.match(t) for t in heads):
            found.append(p)
    # the contents often run on to the next pages
    more = set(found)
    for p in found:
        q = p + 1
        while q in pages and sum(1 for _, _, t, _ in _lines(pages[q]) if ENTRY.match(t)) >= 4:
            more.add(q)
            q += 1
    return sorted(more)


def _printed_numbers(pages):
    """PDF page -> the page number printed on it (from headers/footers), where one is seen."""
    out = {}
    for p, d in pages.items():
        cands = [b for b in d.get("extra", []) if b["label"] in ("PageHeader", "PageFooter")]
        lines = _lines(d, include_extra=False)
        if lines:                                           # a lone number at the very top or bottom
            for y, x, t, _ in (lines[0], lines[-1]):
                if re.fullmatch(r"\d{1,4}", t.strip()):
                    out[p] = int(t)
        for b in cands:
            nums = [w[4] for w in b["words"] if re.fullmatch(r"\d{1,4}", w[4])]
            if len(nums) == 1:
                out[p] = int(nums[0])
    return out


def _roman(s):
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    s = s.lower()
    total = 0
    for i, ch in enumerate(s):
        v = vals[ch]
        total += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
    return total


def _title_key(title):
    """What to look for on the chapter's own page: the title without 'Chapter 3'."""
    m = NUMBERED.match(fix_spacing(" ".join(title.split())))
    rest = m.group("rest") if m and m.group("rest").strip() else title
    return _norm(rest)[:24]


def from_contents(pages, labels, page_count, lang="en"):
    cpages = _contents_pages(pages)
    if not cpages:
        return []
    rows, stop = [], False
    for p in cpages:
        for y, x, t, label in _lines(pages[p]):
            if STOP.match(t):                                # the list of illustrations is not chapters
                stop = True
                break
            # column headings ('CHAP.  PAGE') sometimes share a row with the first entry
            t = re.sub(r"(?i)^\s*(chap\.?|chapter)?\s*page\s+", "", t).strip()
            t = re.sub(r"\s+PAGE\b", "", t)                  # the 'PAGE' column heading inside a row
            if CONTENTS_TITLE.match(t) or COLUMN_WORDS.fullmatch(t) or re.fullmatch(r"[\divxlc\s.]+", t, re.I):
                continue
            m = ENTRY.match(t)
            if m and len(re.sub(r"[\W\d_]", "", m.group("title"))) >= 2:
                num = m.group("page")
                rows.append((m.group("title"), int(num) if num.isdigit() else -_roman(num), x))
            elif len(t) < 100 and re.search(r"[^\W\d_]{2}", t):
                rows.append((t, None, x))                    # a contents line without a page number
        if stop:
            break
    numbered_list = sum(1 for r in rows if r[1] is not None) >= 3
    entries = []
    for k, (t, printed, x) in enumerate(rows):
        if numbered_list and printed is None:
            nxt = rows[k + 1] if k + 1 < len(rows) else None
            if nxt and nxt[1] is not None and not LEADS_NEW.match(nxt[0]):
                rows[k + 1] = (t + " " + nxt[0], nxt[1], min(x, nxt[2]))    # a title wrapping onto the next line
            continue                                         # else a subtitle under an entry
        entries.append((t, printed, x))
    if len(entries) < 3:
        return []
    numbered = [e for e in entries if e[1] is not None]
    if len(numbered) >= 3:
        nums = [e[1] for e in numbered]
        if sum(1 for a, b in zip(nums, nums[1:]) if b >= a) < 0.7 * (len(nums) - 1):
            return []                                        # not a contents list after all
    last_contents = max(cpages)
    # where each title turns up as a heading after the contents, in order
    title_pages, last = {}, (last_contents, 1e9)
    for k, (title, printed, _x) in enumerate(entries):
        key = _title_key(title)
        if len(key) < 4:
            continue
        for p in range(last[0], page_count):
            d = pages.get(p)
            if not d:
                continue
            top = [(ly, _norm(t)) for ly, _lx, t, _ in _lines(d, include_extra=False)[:5]]
            # each chapter starts after the one before it (not inside the previous heading)
            hit = next((ly for ly, t in top if (p, ly) > last and (key in t or (len(t) >= 6 and t in key))), None)
            if hit is not None:
                title_pages[k] = (p, hit)
                full, end = _norm(title), hit
                for ly, t in top:                            # the rest of a heading that wraps
                    if ly > end and t and t in full:
                        end = ly
                    elif ly > end:
                        break
                last = (p, end + 1)
                break
    # printed page -> PDF page: page labels, the numbers printed on pages, or matched titles
    offsets = Counter()
    for i, lab in labels.items():
        if lab.isdigit():
            offsets[i - int(lab)] += 1
    if not offsets:
        for p, n in _printed_numbers(pages).items():
            offsets[p - n] += 1
    for k, (p, _y) in title_pages.items():
        if entries[k][1] and entries[k][1] > 0:
            offsets[p - entries[k][1]] += 2
    offset = offsets.most_common(1)[0][0] if offsets and offsets.most_common(1)[0][1] >= 2 else None
    out = []
    xs = sorted({round(e[2]) for e in entries})
    for k, (title, printed, x) in enumerate(entries):
        if k in title_pages:
            p, y = title_pages[k]
        elif printed and printed > 0 and offset is not None:
            p, y = printed + offset, 0.0
        else:
            continue
        if 0 <= p < page_count:
            out.append((1 if round(x) <= xs[0] + 12 else 2, title, p, y))
    return out if len(out) >= max(3, len(entries) // 2) else []


# ---- 3. chapter headings found on the pages ---------------------------------------------------
JUNK_HEAD = re.compile(r"(?i)copyright|all rights reserved|printing|printed (in|by)|publish|press\b|isbn|"
                       r"list of (illustrations|figures|plates|tables)")


def _merged_heads(d):
    """A page's heading blocks, with titles that wrap over two heading lines joined."""
    blocks = [b for b in d.get("blocks", []) if b["words"]]
    out = []
    for i, b in enumerate(blocks):
        if b["label"] != "SectionHeader":
            continue
        text = " ".join(w[4] for w in b["words"]).strip()
        h = statistics.median(w[3] - w[1] for w in b["words"])
        top = min(w[1] for w in b["words"])
        def caps(s):
            letters = [c for c in s if c.isalpha()]
            return bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.8
        bare = out and re.fullmatch(r"[IVXLCDM]{1,6}\.?|\d{1,3}\.?", out[-1]["text"].strip())   # 'VIII' alone
        if bare and out[-1]["i"] == i - 1 and top - out[-1]["bottom"] < 4 * h:
            out[-1]["text"] = out[-1]["text"].strip().rstrip(".") + " " + text
            out[-1]["bottom"] = max(w[3] for w in b["words"])
            out[-1]["i"] = i
            continue
        if out and out[-1]["i"] == i - 1 and top - out[-1]["bottom"] < 1.2 * h \
                and abs(h - out[-1]["size"]) < 0.15 * h and caps(text) == caps(out[-1]["text"]) \
                and not NUMBERED.match(fix_spacing(text)) and not NUMBERED.match(fix_spacing(out[-1]["text"])):
            out[-1]["text"] += " " + text                     # 'A JOURNEY TO THE EARTH FROM' + 'THE PLANET VENUS'
            out[-1]["bottom"] = max(w[3] for w in b["words"])
            out[-1]["i"] = i
            continue
        out.append({"text": text, "top": top, "bottom": max(w[3] for w in b["words"]), "size": h, "i": i,
                    "first": i == 0})
    return out, blocks


def from_headings(pages):
    heights = [w[3] - w[1] for _, d in sorted(pages.items())[:40] for b in d.get("blocks", [])
               if b["label"] == "Text" for w in b["words"]]
    if not heights:
        return []
    body = statistics.median(heights)
    heads, seen = [], Counter()
    for p, d in sorted(pages.items()):
        hs, blocks = _merged_heads(d)
        body_words = sum(len(b["words"]) for b in blocks if b["label"] == "Text")
        for k, h in enumerate(hs):
            text = h["text"]
            if len(text) > 100 or not re.search(r"\w", text) or CONTENTS_LINE.search(text) or JUNK_HEAD.search(text):
                continue
            m = NUMBERED.match(fix_spacing(text))
            if m and not m.group("rest").strip():             # 'Chapter 3' alone: find its name
                above = hs[k - 1] if k and h["top"] - hs[k - 1]["bottom"] < 4 * h["size"] else None
                nxt = blocks[h["i"] + 1] if h["i"] + 1 < len(blocks) else None
                below = " ".join(w[4] for w in nxt["words"]).strip() if nxt else ""
                if above and not NUMBERED.match(fix_spacing(above["text"])):
                    text += " — " + above["text"]             # the name printed above the number
                    if heads and heads[-1][1] == p and heads[-1][0] == above["text"]:
                        heads.pop()
                elif nxt and nxt["label"] == "SectionHeader" and 0 < len(below) <= 80:
                    text += " — " + below
            heads.append((text, p, h["top"], h["size"], h["first"], body_words))
            seen[_norm(text)] += 1
    heads = [h for h in heads if seen[_norm(h[0])] <= 2]
    if sum(1 for h in heads if DIVISION.search(fix_spacing(h[0]))) >= 2:
        return [(1, t, p, y) for t, p, y, _, _, _ in heads if CHAPTER_WORD.search(fix_spacing(t))]
    out, last = [], None
    for t, p, y, size, first, body_words in heads:
        letters = [c for c in t if c.isalpha()]
        if len(letters) < 4 or len(t) > 70 or t.rstrip()[-1:] in ",:;" or t[:1].islower() or body_words < 40:
            continue                                          # fragments, captions on picture pages
        caps = sum(c.isupper() for c in letters) / len(letters) >= 0.7
        if caps or size >= 1.25 * body or (first and len(t.split()) <= 8):
            key = _norm(t)
            if last and last[0] == key and p - last[1] <= 2:
                continue
            out.append((1, t, p, y))
            last = (key, p)
    return out if 2 <= len(out) <= 400 else []


# ---- names from a numbered list at the front ('1. "SAUCERS FROM INNER EARTH"') ----------------------
LIST_ITEM = re.compile(r"^\s*(?P<num>\d{1,3}|[IVXLC]{1,6})[.)]\s+(?P<title>[^\d\s].{2,80}?)\s*$")
QUOTES = "\"'“”‘’«»"


def _num(s):
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    if ROMAN.match(s):
        return _roman(s)
    words = NUM_WORDS.split("|")
    return words.index(s) % 20 + 1 if s in words[:20] else None


def _front_list(pages, page_count):
    """{number: title} from the first numbered list (1, 2, 3 … without page numbers) at the front."""
    for p in sorted(pages)[:max(12, page_count // 10)]:
        items = {}
        for _y, _x, text, _label in _lines(pages[p]):
            m = LIST_ITEM.match(text)
            if m and _num(m.group("num")) == len(items) + 1:
                items[len(items) + 1] = m.group("title").strip(" " + QUOTES + ".,;:")
        if len(items) >= 3:
            return items
    return {}


def _close(a, b):
    a, b = _norm(a), _norm(b)
    return bool(a and b) and difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def _named_from_list(chs, items):
    """Heading 'Chapter 5 — "THE SUN OOD 1 S SECRET"' + list item 5 'THE SUN-GOD'S SECRET' -> the list's name."""
    out = []
    for lvl, title, page, y in chs:
        m = NUMBERED.match(fix_spacing(title))
        n = _num(m.group("num")) if m else None
        rest = m.group("rest").strip(" " + QUOTES) if m else ""
        if n in items and (not rest or _close(rest, items[n])):
            title = f"{m.group('word')} {m.group('num')} — {items[n]}"
        out.append((lvl, title, page, y))
    return out


# ---- choosing ----------------------------------------------------------------------------------
def work_out(outline_rows, pages, labels, page_count, lang="en"):
    """-> [(level, nice title, page, y)]: the best source, tidied; [] for a book without chapters."""
    for name, source in (("outline", lambda: from_outline(outline_rows, page_count)),
                         ("contents", lambda: from_contents(pages, labels, page_count, lang)),
                         ("headings", lambda: from_headings(pages))):
        try:
            chs = source()
        except Exception:
            chs = []
        if len(chs) >= 2:
            break
    else:
        return []
    if name == "headings":
        items = _front_list(pages, page_count)
        if items:
            chs = _named_from_list(chs, items)
    out, prev = [], None
    for lvl, title, page, y in chs:
        t = nice_title(title, lang)
        if not t or (prev and prev[0] == t and abs(prev[1] - page) <= 1):
            continue
        out.append((lvl, t, page, y))
        prev = (t, page)
    return out
