"""Stage 2 — reflow. Turns labeled page blocks into spoken sentences.

- words hyphenated across a line end are rejoined (both halves stay highlighted)
- wrapped lines are joined into true paragraphs, also across page and column breaks
- repeating headers/footers and bare page numbers are dropped
- pauses follow structure: after headings, between paragraphs, at sentence ends
"""
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from wordfreq import zipf_frequency

PAUSE_SENTENCE = 0.12
PAUSE_PARAGRAPH = 0.45
PAUSE_HEADING = 0.7
MAX_WORDS = 55            # very long runs are split at a comma/semicolon for pacing

ABBREV = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "prof", "fig", "figs",
          "vol", "vols", "p", "pp", "ed", "eds", "e.g", "i.e", "vs", "cf", "al", "approx",
          "inc", "co", "corp", "ltd", "dept", "ch", "chap", "sec", "rev", "gen", "gov",
          "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov",
          "dec", "mt", "ft", "lb", "lbs", "oz"}
SAY = {"mr.": "Mister", "mrs.": "Missus", "dr.": "Doctor", "fig.": "Figure",
       "figs.": "Figures", "vol.": "Volume", "e.g.": "for example", "i.e.": "that is",
       "etc.": "et cetera", "vs.": "versus", "cf.": "compare", "approx.": "approximately",
       "&": "and"}
SAY_BEFORE_NUMBER = {"p.": "page", "pp.": "pages", "no.": "number", "nos.": "numbers",
                     "ch.": "chapter", "chap.": "chapter", "sec.": "section"}
CLOSERS = "\"'”’)]»」』）】》"
ENDS = (".", "!", "?", "。", "！", "？", "…", "।", "॥", "؟", "۔", "։", "።", "။")   # + Hindi, Arabic/Urdu, Armenian, Amharic, Burmese
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")   # Chinese/Japanese (written without spaces)
PAGE_NUM = re.compile(r"^[\W_]*(page\s*)?([0-9]{1,4}|[ivxlcdm]{1,7})[\W_]*$", re.I)
BULLET = re.compile(r"^([•▪◦●\-–—*]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)])$")


@dataclass
class Word:
    text: str                 # as printed (hyphen halves joined)
    say: str                  # as spoken
    rects: list               # [(page, x0, y0, x1, y1), ...]


@dataclass
class Sentence:
    key: tuple                # (page, n) of the first word — stable id
    words: list
    pause: float = PAUSE_SENTENCE
    page: int = 0
    heading: bool = False
    code: str = ""            # a piece of computer code to explain (its words are highlighted meanwhile)
    literal: bool = False     # a line of code read exactly as written (never translated)
    intro: str = ""           # said before the explanation of a block's first piece


@dataclass
class Para:
    kind: str                 # "text", "heading", "item", "side"
    words: list = field(default_factory=list)   # raw: (page, x0, y0, x1, y1, text, line, n)

    def open_end(self):
        """True when the paragraph stops mid-sentence (continues on the next column/page)."""
        if not self.words:
            return False
        last = self.words[-1][5].rstrip(CLOSERS)
        return not last.endswith(ENDS + (":", "："))


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[0-9ivxlcdm]+\b", "#", s.lower())).strip()


TIBETAN_MARKS = re.compile("[\u0f0b-\u0f14]")


def _wordlike(t):
    t = t.strip("\"'“”‘’()[]{}.,;:!?*—–-")
    while t and unicodedata.category(t[0])[0] in "PS":      # punctuation of any script ('है।')
        t = t[1:]
    while t and unicodedata.category(t[-1])[0] in "PS":
        t = t[:-1]
    if not t:
        return True
    if re.fullmatch(r"[$£€]?\d[\d,.:/%]*", t):
        return True
    if re.fullmatch(r"[A-Za-z][a-z]*(['’\-][A-Za-z]+)*", t) or re.fullmatch(r"[A-Z]+", t):
        return True
    # other alphabets (é, ж, 中, देखो, நன்றி, ขอบคุณ ...): letters only, with at most one case
    # change. Vowel signs of Indic/Thai scripts are 'marks', not letters, but part of the word.
    # (Tibetan writes a tsheg between the syllables of a word, 'བྱི་ལ', and its shad often
    # without a space after it: both are part of the run of letters)
    bare = TIBETAN_MARKS.sub("", t.replace("'", "").replace("’", "").replace("-", ""))
    letters = bool(bare) and all(unicodedata.category(c)[0] in "LM" for c in bare)
    if letters and not re.search(r"[A-Za-z]", bare):
        return True
    if letters and (bare[1:].islower() or bare.isupper()):
        return True
    return False


def _garbage(words):
    """Text scraped from inside charts/images: mostly non-word tokens."""
    if len(words) < 4:
        return False
    good = sum(1 for w in words if _wordlike(w[4]))
    return good / len(words) < 0.6


def _band_text(page_data, block):
    H = page_data["height"]
    return block["bottom"] < H * 0.1 or block["top"] > H * 0.9


def build_paragraphs(pages, layout):
    """pages: a short run of consecutive pages (about 7) whose layout is known."""
    # Running headers/footers the layout model missed: same text in the top/bottom
    # band on 2+ nearby pages (digits ignored, so "Chapter 2 — 41" matches "— 42").
    band = Counter()
    for p in pages:
        for b in layout[p]["blocks"]:
            if b["label"] == "Text" and _band_text(layout[p], b):
                band[_norm(" ".join(w[4] for w in b["words"]))] += 1
    paras, deferred = [], []

    def flush_deferred():
        paras.extend(deferred)
        deferred.clear()

    for p in pages:
        for b in layout[p]["blocks"]:
            words = b["words"]
            text = " ".join(w[4] for w in words)
            if b["label"] == "Text" and _band_text(layout[p], b):
                if PAGE_NUM.match(text) or (band[_norm(text)] >= 2 and len(text) < 120):
                    continue
            raw = [(p, *w) for w in words]
            label = b["label"]
            if label == "Code":                 # (code would look like garbage to the next check)
                flush_deferred()
                paras.append(Para("code", raw))
                continue
            if _garbage(words):
                continue
            prev = paras[-1] if paras else None
            if label == "SectionHeader":
                flush_deferred()
                paras.append(Para("heading", raw))
            elif label in ("Caption", "Footnote"):
                # Don't let a caption/footnote cut into a sentence that runs on.
                if prev and prev.kind == "text" and prev.open_end():
                    deferred.append(Para("side", raw))
                else:
                    paras.append(Para("side", raw))
            elif label == "ListGroup":
                flush_deferred()
                item = None
                last_line = None
                for w in raw:
                    if w[6] != last_line and (BULLET.match(w[5]) or item is None):
                        item = Para("item")
                        paras.append(item)
                    item.words.append(w)
                    last_line = w[6]
            else:
                first = raw[0][5]
                # CJK has no lowercase to signal "continues": only join across a page break
                cjk_runon = (CJK.match(first[:1]) and prev is not None and prev.words
                             and CJK.match(prev.words[-1][5][-1:]) and prev.words[-1][0] != p)
                last = prev.words[-1][5] if prev and prev.words else ""
                hyphen = len(last) > 1 and last[-1] == "-" and last[-2].isalpha()     # 'speci-', not a dash 'CAVE--'
                if (prev and prev.kind in ("text", "item") and prev.open_end()
                        and (first[:1].islower() or hyphen or cjk_runon)):
                    prev.words.extend(raw)          # paragraph runs on across the break
                else:
                    flush_deferred()
                    paras.append(Para("text", raw))
    flush_deferred()
    return paras


URL = re.compile(r"^[(\[<\"']*(https?://|www\.|ftp://)\S+", re.I)
# an initial or a dotted capital abbreviation, read as letters: 'W.'  'U.S.'  'J.R.R.'
INITIALS = re.compile(r"^(?:[A-Z]\.){1,4}$")
# NFKC splits Thai/Lao sara am (ำ ຳ) into nikhahit + aa: put it back together
SARA_AM = re.compile("[\u0e4d\u0ecd]([\u0e48-\u0e4b\u0ec8-\u0ecb]?)([\u0e32\u0eb2])")


_WF_LANGS = None


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


def _zipf(w, lang="en"):
    return zipf_frequency(w.lower(), lang)


def _has_wordlist(lang):
    global _WF_LANGS
    if _WF_LANGS is None:
        from wordfreq import available_languages
        _WF_LANGS = set(available_languages())
    return lang in _WF_LANGS


CJK_OR_HANGUL = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힣]")
ONE_LETTER_WORDS = set("aiouyesvkzAIOUYESVKZаиявкосужбАИЯВКОСУЖБ")   # real one-letter words (en, ru, cs, pl, es ...)


def _spaced_letters(raw, i):
    """How many tokens from raw[i] form one word printed letter-spaced on one line ('Ц а р и ц а',
    German/Russian emphasis, names in plays): 3+ single letters, unless every one of them is a real
    one-letter word (Russian 'и в с') and there are fewer than 4. -> run length (1 = not spaced)."""
    def piece(t):            # 'ц', or a letter with its punctuation: 'ж.', 'а-К'
        letters = sum(c.isalpha() for c in t)
        # (Chinese/Japanese characters and Korean syllables are one 'letter' each by nature)
        return (1 <= letters <= 2 and len(t) <= 3 and t[0].isalpha() and (letters == 1 or t[1] in "-–")
                and not CJK_OR_HANGUL.match(t))
    j = i
    while j < len(raw) and piece(raw[j][5]) and raw[j][6] == raw[i][6] and raw[j][0] == raw[i][0]:
        j += 1
        if len(raw[j - 1][5]) == 2 and not raw[j - 1][5][1].isalpha():
            break                    # 'ж.' ends a spaced word; a list 'a, b, c,' never becomes one
    run = j - i
    if run < 3 or (run < 4 and all(r[5] in ONE_LETTER_WORDS for r in raw[i:j])):
        return 1
    return run


def _spaced_words(raw, i, run):
    """A letter-spaced run -> its words: the space between words is clearly wider than the
    space between letters ('З и н а и д а   М и х а й л о в н а')."""
    items = raw[i:i + run]
    gaps = [b[1] - a[3] for a, b in zip(items, items[1:])]
    med = sorted(gaps)[len(gaps) // 2] if gaps else 0
    height = max(r[4] - r[2] for r in items)
    words, cur = [], [items[0]]
    for g, r in zip(gaps, items[1:]):
        if g > max(1.6 * med, med + 0.25 * height):
            words.append(cur)
            cur = []
        cur.append(r)
    words.append(cur)
    return words


def _split_spaced(group, lang):
    """Letter-spaced text typed with the same single space between words as between letters
    ('З и н а и д а М и х а й л о в н а') keeps no word breaks: split where a capital starts a
    name, then let the word list split what is left ('Шведскийпосол' -> 'Шведский посол')."""
    parts, cur = [], [group[0]]
    for r in group[1:]:
        if r[5][:1].isupper() and cur[-1][5][-1:].islower():
            parts.append(cur)
            cur = []
        cur.append(r)
    parts.append(cur)
    if not lang:
        return parts
    from .chapters import _segment
    out = []
    for p in parts:
        text = "".join(r[5] for r in p)
        bare = strip_punct(text)
        if len(bare) >= 6 and _zipf(bare, lang) < 1.5:
            words = _segment(bare, lang)
            if len(words) > 1 and all(_zipf(w, lang) >= 2.0 for w in words):
                k, cut = 0, []
                for w in words[:-1]:                 # item where each word ends (letters counted)
                    need, got = len(w), 0
                    while k < len(p) and got < need:
                        got += sum(c.isalpha() for c in p[k][5])
                        k += 1
                    cut.append(k)
                bounds = [0] + cut + [len(p)]
                out += [p[a:b] for a, b in zip(bounds, bounds[1:]) if b > a]
                continue
        out.append(p)
    return out


def _join_hyphens(raw, lang="en"):
    """raw word tuples -> Word list, rejoining words split at line ends (judged with the
    book's language; for a language without a word list, a lowercase run-on is a soft hyphen)."""
    # (Chinese/Japanese/Korean never hyphenate, and their word lists need extra segmenters)
    known = _has_wordlist(lang) and lang not in ("zh", "ja", "ko")
    out, i = [], 0
    while i < len(raw):
        p, x0, y0, x1, y1, t, line, n = raw[i]
        rects = [(p, x0, y0, x1, y1)]
        run = _spaced_letters(raw, i)
        if run > 1:                                 # 'Ц а р и ц а' printed letter-spaced: real words
            for group in _spaced_words(raw, i, run):
                for part in _split_spaced(group, lang if known else None):
                    t = "".join(r[5] for r in part)
                    out.append((Word(t, t, [tuple(r[:5]) for r in part]), part[0][7]))
            i += run
            continue
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        line_end = nxt is not None and (nxt[6] != line or nxt[0] != p)
        if (line_end and len(t) > 1 and t[-1] in "-¬" and t[-2].isalpha()
                and nxt[5][:1].isalpha()):
            # "speci-" + "fied": drop the hyphen when the joined word is a real word,
            # keep it for true compounds ("well-known", "Anglo-Saxon").
            head, tail = t[:-1], nxt[5]
            bare = strip_punct(tail, lead=False)
            keep = (not tail[:1].islower()) or (known and _zipf(head.split("-")[-1] + bare, lang) < 2.0)
            t = head + ("-" if keep else "") + tail
            rects.append(tuple(nxt[:5]))
            i += 1
        elif (nxt is not None and not line_end and t[-1:] in "’'" and len(t) > 1
              and strip_punct(nxt[5], lead=False).lower() in ("m", "s", "t", "d", "re", "ll", "ve")):
            # "I’" + "m": a contraction the PDF split in two
            t = t + nxt[5]
            rects.append(tuple(nxt[:5]))
            i += 1
        elif known and line_end and t.isalpha() and nxt[5][:1].islower():
            # Scans that lost the hyphen: "speci" / "fied" on two lines.
            bare = strip_punct(nxt[5], lead=False)
            if (bare.isalpha() and _zipf(t + bare, lang) >= 3.0
                    and min(_zipf(t, lang), _zipf(bare, lang)) < 2.5):
                t = t + nxt[5]
                rects.append(tuple(nxt[:5]))
                i += 1
        out.append((Word(t, t, rects), n))
        i += 1
    return out


def _spoken(pairs, lang="en"):
    """Fill in Word.say: expand abbreviations, symbols and dashes for the voice. Web addresses
    are shown and highlighted but not read out (one that wraps onto the next line carries on
    in pieces with '/' in them). Astrology signs are named (bt/astro.py)."""
    from . import astro
    url = False
    sky = None
    for i, (w, _) in enumerate(pairs):
        t = unicodedata.normalize("NFKC", w.text)      # ligatures (ﬀ ﬁ) -> plain letters
        t = SARA_AM.sub(lambda m: m.group(1) + ("ำ" if m.group(2) == "า" else "ຳ"), t)
        low = t.lower().strip(CLOSERS + "(")
        nxt = pairs[i + 1][0].text if i + 1 < len(pairs) else ""
        url = bool(URL.match(t)) or (url and ("/" in t or "_" in t))
        if url:
            w.say = ""
            continue
        if astro.CHARS.search(t):
            if sky is None:
                sky = astro.about_the_sky([p[0].text for p in pairs])
            s = astro.spoken(t, lang, sky)
            before = strip_punct(pairs[i - 1][0].text).lower() if i else ""
            if before and s.strip(CLOSERS + ".,;:!?(").lower() == before:
                s = ""                                   # 'Mars ♂': the name, said once
        elif low in SAY:
            s = SAY[low]
        elif low in SAY_BEFORE_NUMBER and nxt[:1].isdigit():
            s = SAY_BEFORE_NUMBER[low]
        elif nxt and INITIALS.match(t):
            # 'W. D. Gann': the voice ends a sentence at each full stop, and a one-letter
            # sentence comes out garbled (MEASURED: Ryan said 'W. Then dance'; 'W D Gann' is
            # read right by every voice)
            s = " ".join(c for c in t if c.isalpha())
        else:
            s = re.sub(r"^([A-Za-z]{2,}[.,;:!?][\"”’']?)\d{1,3}$", r"\1", t)   # "cost.1" footnote mark
            s = s.replace("—", ", ").replace("–", "-" if re.search(r"\d–\d", s) else ", ")
            s = s.replace("…", "...").replace("|", " ")
        if not re.search(r"[^\W_]", s):
            # bare punctuation (any script): not spoken or highlighted itself, but its
            # pause/intonation is kept by attaching it to the word before
            mark = next((PUNCT[c] for c in t if c in PUNCT), "")
            if mark and i > 0 and pairs[i - 1][0].say and not pairs[i - 1][0].say.endswith(tuple(PUNCT.values())):
                pairs[i - 1][0].say += mark
            s = ""
        w.say = s.strip()
    return pairs


PUNCT = {",": ",", ";": ";", ":": ":", ".": ".", "!": "!", "?": "?", "—": ",", "–": ",",
         "，": ",", "、": ",", "；": ";", "：": ":", "。": ".", "！": "!", "？": "?", "…": "...", "।": ".", "॥": ".", "؟": "?", "۔": ".", "։": ".", "።": ".", "။": ".", "،": ",", "؛": ";", "၊": ","}


def _ends_sentence(w, nxt, prev=None):
    t = w.text
    if t and prev is not None and all(c in CLOSERS for c in t):
        t = prev.text + t           # a lone closing quote after 。 ends the sentence
    t = t.rstrip(CLOSERS)
    if not t.endswith(ENDS):
        return False
    if t.endswith(("!", "?", "。", "！", "？")):
        if nxt is not None and nxt.text[:1] in CLOSERS:
            return False        # 。” — the closing quote belongs to this sentence
        return True
    stem = t[:-1].lstrip("(\"'“‘").lower()
    if stem in ABBREV or re.fullmatch(r"[a-z]", stem) or re.fullmatch(r"([a-z]\.)+[a-z]", stem):
        return False
    if nxt is None:
        return True
    f = nxt.text.lstrip("(\"'“‘[")
    if stem in ("no", "nos") and f[:1].isdigit():
        return False
    return not f[:1].islower()


# Letters a PDF's font left without their meaning: a ligature drawn as one glyph that the font
# maps to nothing (MuPDF then gives the glyph's code: 'fi' read as '\u00eb', 'fl' as '\u00ec'), or to a
# private-use code of its own ('Th' as U+E053). MEASURED in a 259-page book: 2,243 words such as
# 'first', 'significant', 'The', 'Threshold' printed this way; the voices skipped the letters ('irst').
LIGATURES = ("fi", "fl", "ff", "ffi", "ffl", "Th", "ft", "st", "ct", "f", "fj")
# (not U+F000-F0FF: a symbol font's own signs, Symbol, Wingdings, an astrology font's planets; not
# U+F8E5-F8FF, the pieces of tall brackets; not × and ÷)
SUSPECT = re.compile("[\ue000-\uefff\uf100-\uf8e4\ufffd\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff]")
SMALL_CAPS = re.compile("[\uf721-\uf7ff]")      # Adobe's small capitals: U+F761 is a small 'a'


def _private(c):
    return "\ue000" <= c <= "\uf8ff" or c == "\ufffd"


def _fix_glyphs(raw, lang="en", learned=None):
    """raw word tuples with each lost letter put back: Adobe's small capitals as their letters,
    and any other unknown letter as the ligature that makes a known word of it. learned: {letter:
    Counter of ligatures, counted once a word} kept for the whole book, so a word that could be
    read two ways follows the rest ('\u00ecat' is 'flat' in a book whose '\u00ec' is 'fl' everywhere, not
    'That'). An accented letter is put back only once 3 different words of the book agree on it
    ('\u00ebrst', '\u00ebnancial', 'signi\u00ebcant' ...: 'fi'), and only where the word as printed is unknown
    ('No\u00ebl' stays); a lone lucky match never does (a Chinese name 'ti\u00e9n' is not 'tiffin')."""
    if not any(SUSPECT.search(r[5]) for r in raw):
        return raw
    known = _has_wordlist(lang) and lang not in ("zh", "ja", "ko")
    # an accented letter is a lost one only in an English book, and only where it makes a common word:
    # MEASURED over 150 books of other languages, real words changed ('çokları' -> 'stokları')
    accents = lang == "en"
    learned = {} if learned is None else learned
    ok = lambda c: unicodedata.category(c)[0] in "LMN" or SUSPECT.match(c)
    out = []
    for r in raw:
        t = SMALL_CAPS.sub(lambda m: chr(ord(m.group()) - 0xF700), r[5])
        if known and SUSPECT.search(t):
            i, j = 0, len(t)
            while i < j and not ok(t[i]):
                i += 1
            while j > i and not ok(t[j - 1]):
                j -= 1
            core = t[i:j]
            # (the end of a word hyphenated on the line before: 'signi-' + '\u00ebcantly')
            head = out[-1][5][:-1] if out and out[-1][5].endswith("-") and not i else ""
            head = head if head[-1:].isalpha() else ""
            for c in dict.fromkeys(ch for ch in core if SUSPECT.match(ch)):
                if not _private(c) and (not accents or _zipf(head + core, lang) >= 1.0):
                    continue                        # a real accented word
                cap = lambda lig: lig if (head + core).startswith(c) else lig.lower()
                votes = learned.get(c)
                usual = votes.most_common(1)[0] if votes else None
                agreed = usual and usual[1] >= 3 and usual[1] >= 0.8 * sum(votes.values())
                if agreed and (_private(c) or _zipf(head + core.replace(c, cap(usual[0])), lang) >= 1.0):
                    core = core.replace(c, cap(usual[0]))   # this book's own reading of it
                    continue
                best, score = None, 1.0 if _private(c) else 3.0
                for lig in LIGATURES:
                    word = head + core.replace(c, cap(lig))
                    z = _zipf(word, lang)
                    if z > score and (_private(c) or (word.isalpha() and len(word) >= 4)):
                        best, score = lig, z
                if best:
                    seen = learned.setdefault((c, "words"), set())
                    if head + core not in seen:
                        seen.add(head + core)
                        learned.setdefault(c, Counter())[best] += 1
                    if _private(c):
                        core = core.replace(c, cap(best))
            t = t[:i] + core + t[j:]
        out.append(r[:5] + (t,) + r[6:] if t != r[5] else r)
    return out


# a letter that text recognition read as a bar, by language: Latvian 'ļ' (MEASURED: all 14 bars inside
# words of a Latvian book were ļ: 'Kora|ļu', '|audis', 'gu|būvju'), which the translators misread
BAR_LETTER = {"lv": "ļ"}


def _fix_bars(raw, lang):
    c = BAR_LETTER.get(lang)
    if not c or not any("|" in r[5] for r in raw):
        return raw
    fix = lambda t: re.sub(r"(?<=[^\W\d_])\||\|(?=[^\W\d_])", c, t) if re.search(r"[^\W\d_]", t) else t
    return [r[:5] + (fix(r[5]),) + r[6:] for r in raw]


# Curly quotes a Word font shifted to the next codes along (MEASURED in a Word 2010 PDF: 78 quotes
# as '―expert‖', 'Let‘s', '‗The Hebrew'): the voice took '‖' for no closing quote, so
# 'die.‖' ran on into the next sentence
SHIFTED_QUOTES = [(re.compile(r"^([(\[]?)\u2015(?=\w)"), "\\1\u201c"),           # opening double
                  (re.compile(r"(?<=[\w.,;:!?)\]])\u2016"), "\u201d"),              # closing double
                  (re.compile(r"^([(\[]?)\u2017(?=\w)"), "\\1\u2018"),           # opening single
                  (re.compile(r"(?<=\w)\u2018(?=\w|$|[.,;:!?\u201d])"), "\u2019")]   # apostrophe / closing single


def _fix_quotes(raw):
    if not any(c in r[5] for r in raw for c in "\u2015\u2016\u2017\u2018"):
        return raw
    out = []
    for r in raw:
        t = r[5]
        for pat, rep in SHIFTED_QUOTES:
            t = pat.sub(rep, t)
        out.append(r[:5] + (t,) + r[6:] if t != r[5] else r)
    return out


def split_sentences(para, lang="en", learned=None):
    words = _spoken(_join_hyphens(_fix_glyphs(_fix_bars(_fix_quotes(para.words), lang), lang, learned), lang), lang)
    if para.kind == "heading":
        groups = [words]
    else:
        groups, cur = [], []
        # CJK text arrives one character per 'word': allow ~3x as many before splitting
        cjk = sum(1 for w, _ in words[:40] if CJK.match(w.text[:1])) > 10
        limit, soft = (MAX_WORDS * 3, 90) if cjk else (MAX_WORDS, 30)
        for i, (w, n) in enumerate(words):
            cur.append((w, n))
            nxt = words[i + 1][0] if i + 1 < len(words) else None
            if len(cur) == 1 and BULLET.match(w.text):
                continue            # "1." list marker stays with its item
            too_long = len(cur) >= limit or (len(cur) >= soft and w.text.endswith((",", ";", ":", "，", "；", "：", "،", "؛", "、")))
            prev = words[i - 1][0] if i > 0 else None
            if _ends_sentence(w, nxt, prev) or (too_long and nxt is not None):
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)
    out = []
    for gi, g in enumerate(groups):
        first_page = g[0][0].rects[0][0]
        s = Sentence(key=(first_page, g[0][1]), words=[w for w, _ in g], page=first_page,
                     heading=para.kind == "heading")
        if gi == len(groups) - 1:
            s.pause = PAUSE_HEADING if s.heading else PAUSE_PARAGRAPH
        out.append(s)
    return out


def code_sentences(para, mode):
    """A block of code -> sentences: pieces of a few lines to explain, or one line at a time
    read exactly as written (bt/code.py); none when code is skipped."""
    from . import code
    if mode == "skip":
        return []
    lines = code.code_lines(para.words)
    out = []
    if mode == "verbatim":
        for text, ws in lines:
            words = [Word(w[5], code.say_verbatim(w[5]), [tuple(w[:5])]) for w in ws]
            if any(w.say for w in words):
                out.append(Sentence(key=(ws[0][0], ws[0][7]), words=words, page=ws[0][0], literal=True))
    else:
        pieces = code.chunks(lines)
        whole = "\n".join(t for t, _ in lines)
        for i, piece in enumerate(pieces):
            ws = [w for _, line in piece for w in line]
            text = "\n".join(t for t, _ in piece)
            words = [Word(w[5], "", [tuple(w[:5])]) for w in ws]
            out.append(Sentence(key=(ws[0][0], ws[0][7]), words=words, page=ws[0][0], code=text,
                                intro=code.intro(whole, len(lines)) if i == 0 and len(lines) >= 3 else ""))
    if out:
        out[-1].pause = PAUSE_PARAGRAPH
    return out


def build_sentences(pages, layout, lang="en", code_mode="explain", learned=None):
    out = []
    for para in build_paragraphs(pages, layout):
        if para.kind == "code":
            out.extend(code_sentences(para, code_mode))
            continue
        out.extend(s for s in split_sentences(para, lang, learned) if any(w.say for w in s.words))
    return out
