"""In-house readers for document formats PyMuPDF doesn't open, so BookTalker never needs Word,
PowerPoint or any other program installed. Each returns HTML (headings as <h1>-<h3>, so they
become chapters) for the typesetter in convert.py.

    ODT ODS ODP (OpenDocument)   content.xml
    RTF                          our own RTF parser (styles 'heading N' -> headings)
    DOC (Word 97-2003)           compound file -> the document's piece table -> text
    PPT (PowerPoint 97-2003)     compound file -> the slides' text records
    EML MHT MHTML                the e-mail / web-archive's HTML or text part
    TXTZ HTMLZ FBZ               zipped text / web page / FictionBook
    TEX                          LaTeX sections -> headings, commands stripped
"""
import email
import email.policy
import html
import re
import struct
import zipfile
import xml.etree.ElementTree as ET

esc = html.escape


# ---- OpenDocument --------------------------------------------------------------------------
_NS = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
       "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
       "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"}


def _odf_text(el):
    """The text of an ODF element: spaces (text:s), tabs and line breaks included."""
    out = [el.text or ""]
    for ch in el:
        tag = ch.tag.split("}")[-1]
        if tag == "s":
            out.append(" " * int(ch.get("{%s}c" % _NS["text"], "1")))
        elif tag in ("tab", "line-break"):
            out.append(" ")
        elif tag not in ("note", "annotation"):          # footnotes are read where they belong elsewhere
            out.append(_odf_text(ch))
        out.append(ch.tail or "")
    return "".join(out)


def odf(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    parts, slide = [], 0
    T = "{%s}" % _NS["text"]

    def walk(el):
        nonlocal slide
        for ch in el:
            tag = ch.tag
            if tag == "{%s}page" % _NS["draw"]:              # a presentation slide: its title is the heading
                slide += 1
                start = len(parts)
                walk(ch)
                if len(parts) > start and parts[start].startswith("<p>"):
                    parts[start] = "<h2>" + parts[start][3:-4] + "</h2>"
                else:
                    parts.insert(start, f"<h2>Slide {slide}</h2>")
            elif tag == T + "h":
                lvl = min(3, max(1, int(ch.get(T + "outline-level", "1"))))
                t = _odf_text(ch).strip()
                if t:
                    parts.append(f"<h{lvl}>{esc(t)}</h{lvl}>")
            elif tag == T + "p":
                t = " ".join(_odf_text(ch).split())
                if t:
                    parts.append(f"<h2>{esc(t)}</h2>" if not slide and looks_like_heading(t) else f"<p>{esc(t)}</p>")
            elif tag == "{%s}table-row" % _NS["table"]:      # spreadsheets / tables: one line per row
                cells = [" ".join(_odf_text(p).strip() for p in c.iter(T + "p")) for c in ch]
                cells = [c for c in cells if c]
                if cells:
                    parts.append("<p>" + esc("  ·  ".join(cells)) + "</p>")
            else:
                walk(ch)
    walk(root)
    return "\n".join(parts)


# ---- RTF -----------------------------------------------------------------------------------
_RTF_TOKEN = re.compile(rb"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([^\\{}\r\n]+)|[\r\n]+", re.S)
_RTF_SKIP = {b"fonttbl", b"colortbl", b"stylesheet", b"info", b"pict", b"object", b"header", b"footer",
             b"headerl", b"headerr", b"footerl", b"footerr", b"footnote", b"themedata", b"colorschememapping",
             b"latentstyles", b"datastore", b"xmlnstbl", b"listtable", b"listoverridetable", b"rsidtbl",
             b"generator", b"mmathPr", b"filetbl", b"revtbl", b"fldinst", b"bkmkstart", b"bkmkend", b"nonshppict"}


def rtf(path):
    data = open(path, "rb").read()
    codepage = int((re.search(rb"\\ansicpg(\d+)", data) or [0, b"1252"])[1])
    enc = f"cp{codepage}" if codepage not in (65001,) else "utf-8"
    # paragraph styles named 'heading N' -> heading level
    heading_style = {}
    for m in re.finditer(rb"\{[^{}]*?\\s(\d+)\b[^{}]*?\s([^;{}\\]+);\}", data):
        name = m.group(2).strip().lower()
        hm = re.match(rb"heading\s*(\d)", name)
        if hm:
            heading_style[int(m.group(1))] = min(3, int(hm.group(1)))
    paras, cur = [], []
    para_level = [0]
    stack = []                       # (skip, uc) per group
    skip, uc, pending_skip = False, 1, 0
    ignorable = False
    for m in _RTF_TOKEN.finditer(data):
        word, arg, hexc, sym, brace, text = m.groups()
        if brace == b"{":
            stack.append((skip, uc))
            ignorable = False
            continue
        if brace == b"}":
            skip, uc = stack.pop() if stack else (False, 1)
            continue
        if sym is not None:
            if sym == b"*":
                ignorable = True
                skip = True
            elif not skip and sym in (b"\\", b"{", b"}"):
                cur.append(sym.decode())
            elif not skip and sym == b"~":
                cur.append(" ")
            continue
        if word is not None:
            if word in _RTF_SKIP:
                skip = True
                continue
            if skip:
                continue
            if word == b"uc":
                uc = int(arg or 1)
            elif word == b"u":
                v = int(arg)
                cur.append(chr(v + 65536 if v < 0 else v))
                pending_skip = uc
            elif word in (b"par", b"sect", b"page"):
                paras.append((para_level[0], "".join(cur)))
                cur = []
            elif word == b"pard":
                para_level[0] = 0
            elif word == b"s" and arg is not None:
                para_level[0] = heading_style.get(int(arg), para_level[0])
            elif word == b"outlinelevel" and arg is not None:
                para_level[0] = min(3, int(arg) + 1)
            elif word in (b"line", b"tab", b"cell"):
                cur.append(" ")
            elif word == b"row":
                paras.append((0, "".join(cur)))
                cur = []
            continue
        if skip:
            continue
        if hexc is not None:
            if pending_skip:
                pending_skip -= 1
                continue
            cur.append(bytes([int(hexc, 16)]).decode(enc, "replace"))
        elif text is not None:
            t = text.decode(enc, "replace")
            if pending_skip:
                n = min(pending_skip, len(t))
                t, pending_skip = t[n:], pending_skip - n
            cur.append(t)
    if cur:
        paras.append((para_level[0], "".join(cur)))
    out = []
    for lvl, t in paras:
        t = " ".join(t.split())
        if t:
            lvl = lvl or (2 if looks_like_heading(t) else 0)
            out.append(f"<h{lvl}>{esc(t)}</h{lvl}>" if lvl else f"<p>{esc(t)}</p>")
    return "\n".join(out)


# ---- compound files (old Word / PowerPoint) -------------------------------------------------
class Compound:
    """Minimal reader for Microsoft's compound file format (what .doc and .ppt live in)."""
    FREE, END = 0xFFFFFFFF, 0xFFFFFFFE

    def __init__(self, path):
        d = self.d = open(path, "rb").read()
        if d[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError("not an Office 97-2003 file")
        self.ss = 1 << struct.unpack_from("<H", d, 30)[0]
        self.mss = 1 << struct.unpack_from("<H", d, 32)[0]
        nfat, self.dir_start, _, self.cutoff, mfat_start, nmfat, difat_start, ndifat = \
            struct.unpack_from("<LLLLLLLL", d, 44)
        difat = list(struct.unpack_from("<109L", d, 76))
        s = difat_start
        for _ in range(ndifat):
            if s >= 0xFFFFFFFA:
                break
            vals = struct.unpack_from("<%dL" % (self.ss // 4), d, self._off(s))
            difat += vals[:-1]
            s = vals[-1]
        self.fat = []
        for s in difat[:nfat]:
            self.fat += struct.unpack_from("<%dL" % (self.ss // 4), d, self._off(s))
        self.entries = {}
        dirs = self._chain(self.dir_start)
        root = None
        for i in range(0, len(dirs), 128):
            e = dirs[i:i + 128]
            nlen, = struct.unpack_from("<H", e, 64)
            name = e[:max(0, nlen - 2)].decode("utf-16-le", "replace")
            etype = e[66]
            start, size = struct.unpack_from("<LL", e, 116)
            if etype == 5:
                root = (start, size)
            elif etype == 2:
                self.entries[name] = (start, size)
        self.ministream = self._chain(root[0])[:root[1]] if root else b""
        self.minifat = []
        if nmfat:
            m = self._chain(mfat_start)
            self.minifat = list(struct.unpack_from("<%dL" % (len(m) // 4), m))

    def _off(self, s):
        return (s + 1) * self.ss

    def _chain(self, s, mini=False):
        out, seen = bytearray(), set()
        fat, size = (self.minifat, self.mss) if mini else (self.fat, self.ss)
        while s < 0xFFFFFFFA and s not in seen and s < len(fat):
            seen.add(s)
            if mini:
                out += self.ministream[s * size:(s + 1) * size]
            else:
                out += self.d[self._off(s):self._off(s) + size]
            s = fat[s]
        return bytes(out)

    def stream(self, name):
        if name not in self.entries:
            return None
        start, size = self.entries[name]
        return self._chain(start, mini=size < self.cutoff)[:size]


def looks_like_heading(p):
    """A short line naming a chapter, or set in capitals, without sentence punctuation."""
    from .book import CHAPTER_WORD
    letters = [c for c in p if c.isalpha()]
    return bool(len(p) <= 80 and p[-1:] not in ".,;:!?\"'" and letters and
                (CHAPTER_WORD.search(p) or (len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8)))


def promote_headings(body):
    """<p> lines that name a chapter ('CHAPTER 1: NAMES', 'Introduction') -> <h2>, so a book
    styled only by its (dropped) CSS still has chapters. Lines of a contents page are left alone."""
    from .book import CHAPTER_WORD, CONTENTS_LINE

    def fix(m):
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())
        if text and len(text) <= 90 and CHAPTER_WORD.search(text) and not CONTENTS_LINE.search(text) \
                and text[-1:] not in ".,;!?":
            return f"<h2>{esc(text)}</h2>"
        return m.group(0)
    body = re.sub(r"(?is)<p\b([^>]*)>(.*?)</p>", fix, body)
    # Kindle books often mark chapter titles only in bold: <b>CHAPTER 3: <br/> FIRST LETTER …</b>
    def bold(m):
        before = m.string[:m.start()].rstrip()[-1:]
        after = m.string[m.end():].lstrip()[:1]
        alone = before in ("", ">") and after in ("", "<")      # on its own line, not inside a sentence
        return fix(re.match(r"(?s)()(.*)", m.group(3))) if alone else m.group(0)
    return re.sub(r"(?is)<(b|strong)\b([^>]*)>(.*?)</\1>", bold, body)


def _paragraphs_html(paras):
    """Plain paragraphs -> HTML; short lines that look like headings become <h2>."""
    out = []
    for p in paras:
        p = " ".join(p.split())
        if p:
            out.append(f"<h2>{esc(p)}</h2>" if looks_like_heading(p) else f"<p>{esc(p)}</p>")
    return "\n".join(out)


def doc(path):
    cf = Compound(path)
    wd = cf.stream("WordDocument")
    if not wd or struct.unpack_from("<H", wd, 0)[0] != 0xA5EC:
        raise ValueError("not a Word document")
    flags, = struct.unpack_from("<H", wd, 0x0A)
    if flags & 0x0100:
        raise ValueError("this Word document is password-protected")
    table = cf.stream("1Table" if flags & 0x0200 else "0Table")
    fc_clx, lcb_clx = struct.unpack_from("<LL", wd, 0x01A2)
    clx = table[fc_clx:fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 0x01:                     # skip property runs
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise ValueError("this Word document's text table wasn't found")
    lcb, = struct.unpack_from("<L", clx, i + 1)
    plc = clx[i + 5:i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from("<%dL" % (n + 1), plc, 0)
    text = []
    for k in range(n):
        fc, = struct.unpack_from("<L", plc, 4 * (n + 1) + 8 * k + 2)
        count = cps[k + 1] - cps[k]
        if fc & 0x40000000:
            off = (fc & 0x3FFFFFFF) // 2
            text.append(wd[off:off + count].decode("cp1252", "replace"))
        else:
            text.append(wd[fc:fc + 2 * count].decode("utf-16-le", "replace"))
    t = "".join(text)
    t = re.sub(r"\x13[^\x14\x15]*\x14", "", t)                 # field codes: keep only the result
    t = re.sub(r"[\x13\x14\x15\x01\x08]", "", t)
    t = t.replace("\x07", "\r").replace("\x0c", "\r").replace("\x0b", " ")
    return _paragraphs_html(t.split("\r"))


def ppt(path):
    cf = Compound(path)
    s = cf.stream("PowerPoint Document")
    if not s:
        raise ValueError("not a PowerPoint presentation")
    slides, cur, skip_until = [], [], []

    def walk(pos, end, in_master):
        while pos + 8 <= end:
            ver_inst, rtype, rlen = struct.unpack_from("<HHL", s, pos)
            body = pos + 8
            if (ver_inst & 0xF) == 0xF:                       # a container
                if rtype in (0x03EE,) and not in_master:      # Slide
                    slides.append([])
                walk(body, min(end, body + rlen), in_master or rtype == 0x03F8)   # MainMaster: skip its text
            elif not in_master:
                if rtype == 0x03F3:                           # SlidePersistAtom (outline order)
                    slides.append([])
                elif rtype in (0x0FA0, 0x0FA8):               # TextCharsAtom / TextBytesAtom
                    raw = s[body:body + rlen]
                    t = raw.decode("utf-16-le" if rtype == 0x0FA0 else "cp1252", "replace")
                    t = " ".join(t.replace("\r", "\n").split())
                    if t and slides:
                        slides[-1].append(t)
                    elif t:
                        slides.append([t])
            pos = body + rlen
    walk(0, len(s), False)
    seen, out, n = set(), [], 0
    for texts in slides:
        texts = [t for t in texts if t not in ("*",)]
        if not texts:
            continue
        key = tuple(texts)
        if key in seen:                                       # outline + slide copies of the same text
            continue
        seen.add(key)
        n += 1
        out.append(f"<h2>{esc(texts[0])}</h2>" + "".join(f"<p>{esc(t)}</p>" for t in texts[1:]))
    return "\n".join(out)


# ---- WordPerfect ---------------------------------------------------------------------------
# WP5 fixed-length function codes (0xC0-0xCF): total length in bytes, including both code bytes
_WP5_FIXED = {0xC0: 4, 0xC1: 9, 0xC2: 11, 0xC3: 3, 0xC4: 3, 0xC5: 5, 0xC6: 6, 0xC7: 7}
# WP6 fixed-length groups (0xF0-0xFF): total length
_WP6_FIXED = {0xF0: 4, 0xF1: 5, 0xF2: 3, 0xF3: 3, 0xF4: 3, 0xF5: 4, 0xF6: 4, 0xF7: 5, 0xF8: 5,
              0xF9: 6, 0xFA: 3, 0xFB: 3, 0xFC: 3, 0xFD: 3, 0xFE: 3}
# WordPerfect character set 1 ('multinational'): the common accented letters
_WP_MULTI = dict(zip(range(23, 87), "ÇçÉéÊêËëÈèÏïÎîÌìÄäÅåÆæÖöÜüÑñÓóÒòÕõÚúÙùŸÿÃãÐđØøÕõÝýÐðÞþ" + "?" * 10))


def _wp_char(charset, char):
    if charset == 1:
        return _WP_MULTI.get(char, "?")
    if charset == 0:
        return chr(char) if 32 <= char < 127 else ""
    return ""


def wpd(path):
    """WordPerfect 4.x-X documents (DOS/Windows) and older Mac files -> HTML."""
    d = open(path, "rb").read()
    paras, cur = [], []

    def brk():
        nonlocal cur
        if cur:
            paras.append("".join(cur))
        cur = []
    if d[:4] == b"\xffWPC" and d[9] == 0x0A:                  # DOS/Windows document (Mac files differ)
        start, = struct.unpack_from("<I", d, 4)
        major = d[10]
        i = start
        if major == 0:                                        # WordPerfect 5.x
            while i < len(d):
                c = d[i]
                if 0x20 <= c <= 0x7E:
                    cur.append(chr(c)); i += 1
                elif c in (0x0A, 0x0C, 0x8C, 0x99):           # hard return / page
                    brk(); i += 1
                elif c in (0x0D, 0x80, 0xA9, 0xAA, 0xAB, 0xAC, 0xAD):   # soft return, soft space, hyphens
                    cur.append(" " if c in (0x0D, 0x80) else "-"); i += 1
                elif c == 0xC0 and i + 3 < len(d):            # extended character
                    cur.append(_wp_char(d[i + 2], d[i + 1])); i += 4
                elif c in _WP5_FIXED:
                    i += _WP5_FIXED[c]
                elif 0xD0 <= c <= 0xFE and i + 3 < len(d):    # variable length: code sub len(2) … len code
                    ln, = struct.unpack_from("<H", d, i + 2)
                    if c == 0xD0 and d[i + 1] in (0x00, 0x01, 0x02):   # hard/soft returns as groups
                        brk()
                    i += 4 + ln
                else:
                    i += 1
        else:                                                 # WordPerfect 6 and later
            while i < len(d):
                c = d[i]
                if 0x20 <= c <= 0x7F:
                    cur.append(chr(c)); i += 1
                elif 0x01 <= c <= 0x1F:
                    i += 1                                    # default extended characters: rare
                elif c in (0xCC, 0xC7, 0xD0) and c != 0xD0:
                    brk(); i += 1
                elif c == 0x80 or c == 0xCF:
                    cur.append(" "); i += 1
                elif 0x80 <= c <= 0xCF:
                    i += 1
                elif 0xD0 <= c <= 0xEF and i + 3 < len(d):    # variable-length group: code sub size(2)
                    size, = struct.unpack_from("<H", d, i + 2)
                    if c == 0xD0:                             # end-of-line group: hard returns
                        if d[i + 1] in (0x01, 0x04, 0x07, 0x09, 0x0A, 0x0B, 0x0C):
                            brk()
                        else:
                            cur.append(" ")
                    i += max(4, size)
                elif c == 0xF0 and i + 3 < len(d):            # extended character
                    cur.append(_wp_char(d[i + 2], d[i + 1])); i += 4
                elif c in _WP6_FIXED:
                    i += _WP6_FIXED[c]
                else:
                    i += 1
    else:                                                     # WordPerfect 4.x and older Mac files
        i = struct.unpack_from("<I", d, 4)[0] if d[:4] == b"\xffWPC" else 0
        if i >= len(d):
            i = 0
        while i < len(d):
            c = d[i]
            if 0x20 <= c <= 0x7E:
                cur.append(chr(c)); i += 1
            elif c in (0x0A, 0x0D, 0x8C):
                brk(); i += 1
            elif c >= 0xC0:                                   # a code wrapped in the same byte at its end
                j = d.find(bytes([c]), i + 1, i + 600)
                i = j + 1 if j > 0 else i + 1
                if cur and cur[-1] != " ":
                    cur.append(" ")                           # formatting codes sit between words
            else:
                i += 1
    brk()
    text_paras = [" ".join(p.split()) for p in paras]
    text_paras = [p for p in text_paras if len(re.sub(r"[\W_]", "", p)) >= 2]
    if not text_paras:                                        # last resort: the readable runs of text
        text_paras = [r.decode("latin-1") for r in re.findall(rb"[\x20-\x7e]{4,}", d)
                      if re.search(rb"[a-z]{2}.*\s|\s.*[a-z]{2}", r)]
    if not text_paras:
        raise ValueError("no readable text found in this WordPerfect file")
    return _paragraphs_html(text_paras)


# ---- e-mail / web archives -----------------------------------------------------------------
def eml(path):
    msg = email.message_from_bytes(open(path, "rb").read(), policy=email.policy.default)
    head = ""
    if msg["subject"]:
        head = f"<h1>{esc(str(msg['subject']))}</h1>"
        meta = [f"{k}: {msg[k]}" for k in ("From", "To", "Date") if msg[k]]
        head += "".join(f"<p>{esc(m)}</p>" for m in meta)
    part = msg.get_body(preferencelist=("html", "plain"))
    if part is None:
        return head
    content = part.get_content()
    if part.get_content_type() == "text/html":
        return head + content
    return head + "".join(f"<p>{esc(p)}</p>" for p in re.split(r"\n\s*\n", content) if p.strip())


# ---- zipped formats ------------------------------------------------------------------------
def unzip_main(path, exts):
    """The main file inside a zipped book (largest one with a matching extension) -> (name, bytes)."""
    with zipfile.ZipFile(path) as z:
        files = [i for i in z.infolist() if i.filename.lower().endswith(exts)]
        if not files:
            raise ValueError("nothing readable inside this file")
        best = max(files, key=lambda i: i.file_size)
        return best.filename, z.read(best)


# ---- LaTeX -----------------------------------------------------------------------------------
def tex(text):
    text = re.sub(r"(?<!\\)%.*", "", text)
    m = re.search(r"\\begin\{document\}(.*?)(\\end\{document\}|$)", text, re.S)
    if m:
        text = m.group(1)
    def heading(m):
        lvl = {"part": 1, "chapter": 1, "section": 2}.get(m.group(1), 3)
        return f"\n\n<h{lvl}>{esc(m.group(3))}</h{lvl}>\n\n"
    text = re.sub(r"\\(part|chapter|section|subsection|subsubsection)(\*?)\{([^{}]*)\}", heading, text)
    text = re.sub(r"\\begin\{(equation|align|figure|table|tabular)\*?\}.*?\\end\{\1\*?\}", " ", text, flags=re.S)
    text = re.sub(r"\\(textbf|textit|emph|underline|texttt|textsc)\{([^{}]*)\}", r"\2", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^{}]*\})?", " ", text)
    text = re.sub(r"\$[^$]*\$", " ", text).replace("{", "").replace("}", "").replace("~", " ")
    out = []
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if not b:
            continue
        out.append(b if b.startswith("<h") else f"<p>{esc(' '.join(b.split()))}</p>")
    return "\n".join(out)
