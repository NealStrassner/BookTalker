"""Kindle books without copy protection — AZW3 / KF8, AZW, MOBI, PRC and PalmDOC PDB — read
into HTML, all in-house (no outside programs).

A Kindle file is a Palm database: record 0 holds the headers, the next records the book text
(compressed with PalmDOC or HUFF/CDIC), then images. KF8 books store the text as 'skeleton'
pages with the 'fragments' of text cut out of them; the SKEL and FRAG indexes say where each
fragment goes back in. Copy-protected books are reported, never opened.
"""
import re
import struct


class ProtectedBook(Exception):
    """The book is copy-protected (DRM)."""


# ---- Palm database ---------------------------------------------------------------------
class PalmDB:
    def __init__(self, data):
        self.data = data
        self.kind = data[60:68]
        n, = struct.unpack_from(">H", data, 76)
        self.offsets = [struct.unpack_from(">L", data, 78 + 8 * i)[0] for i in range(n)] + [len(data)]

    def __len__(self):
        return len(self.offsets) - 1

    def record(self, i):
        return self.data[self.offsets[i]:self.offsets[i + 1]]


# ---- decompression ---------------------------------------------------------------------
def palmdoc(data):
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        i += 1
        if 1 <= c <= 8:
            out += data[i:i + c]
            i += c
        elif c < 0x80:
            out.append(c)
        elif c >= 0xC0:
            out += bytes((32, c ^ 0x80))
        else:
            c = (c << 8) | data[i]
            i += 1
            dist, length = (c >> 3) & 0x7FF, (c & 7) + 3
            if dist <= 0:
                continue
            for _ in range(length):
                out.append(out[-dist])
    return bytes(out)


class HuffCdic:
    """Amazon's HUFF/CDIC dictionary compression."""

    def __init__(self, huff, cdics):
        if huff[:4] != b"HUFF" or not all(c[:4] == b"CDIC" for c in cdics):
            raise ValueError("bad HUFF/CDIC records")
        off1, off2 = struct.unpack_from(">LL", huff, 8)
        self.dict1 = []
        for v in struct.unpack_from(">256L", huff, off1):
            codelen, term, maxcode = v & 0x1F, v & 0x80, v >> 8
            if codelen <= 8 and not term:
                raise ValueError("bad HUFF table")
            self.dict1.append((codelen, term, ((maxcode + 1) << (32 - codelen)) - 1))
        d2 = struct.unpack_from(">64L", huff, off2)
        self.mincode, self.maxcode = [0], [0]
        for codelen in range(1, 33):
            self.mincode.append(d2[2 * codelen - 2] << (32 - codelen))
            self.maxcode.append(((d2[2 * codelen - 1] + 1) << (32 - codelen)) - 1)
        self.dictionary = []
        for cdic in cdics:
            phrases, bits = struct.unpack_from(">LL", cdic, 8)
            n = min(1 << bits, phrases - len(self.dictionary))
            for off in struct.unpack_from(">%dH" % n, cdic, 16):
                blen, = struct.unpack_from(">H", cdic, 16 + off)
                self.dictionary.append([cdic[18 + off:18 + off + (blen & 0x7FFF)], blen & 0x8000])


def _huff_unpacker(db, r0):
    huff_rec, huff_n = struct.unpack_from(">LL", r0, 0x70)
    h = HuffCdic(db.record(huff_rec), [db.record(huff_rec + i) for i in range(1, huff_n)])
    # phrases that are themselves compressed get expanded the first time they are used

    def expand(i):
        e = h.dictionary[i]
        if not e[1]:
            e[1] = 1
            e[0] = unpack(e[0])
        return e[0]

    def unpack(data):
        bitsleft = len(data) * 8
        data = data + b"\x00" * 8
        pos, n = 0, 32
        x, = struct.unpack_from(">Q", data, pos)
        out = bytearray()
        while True:
            if n <= 0:
                pos += 4
                x, = struct.unpack_from(">Q", data, pos)
                n += 32
            code = (x >> n) & 0xFFFFFFFF
            codelen, term, maxcode = h.dict1[code >> 24]
            if not term:
                while code < h.mincode[codelen]:
                    codelen += 1
                maxcode = h.maxcode[codelen]
            n -= codelen
            bitsleft -= codelen
            if bitsleft < 0:
                break
            out += expand((maxcode - code) >> (32 - codelen))
        return bytes(out)
    return unpack


def _trailing(data, flags):
    """Strip the extra bytes Kindle appends to each text record."""
    def entry_size(d):
        num = 0
        for v in d[-4:]:
            if v & 0x80:
                num = 0
            num = (num << 7) | (v & 0x7F)
        return num
    num, size = 0, len(data)
    f = flags >> 1
    while f:
        if f & 1:
            num += entry_size(data[:size - num])
        f >>= 1
    if flags & 1:
        num += (data[size - num - 1] & 0x3) + 1
    return data[:size - num]


# ---- Kindle indexes (SKEL / FRAG) ----------------------------------------------------------
def _varint(data, pos):
    value = consumed = 0
    while True:
        v = data[pos + consumed]
        consumed += 1
        value = (value << 7) | (v & 0x7F)
        if v & 0x80:
            return consumed, value


def _index(db, idx):
    """Entries of a Kindle INDX index: [(label bytes, {tag: [values]})], plus its CNCX strings."""
    if idx in (0xFFFFFFFF, None) or idx >= len(db):
        return [], {}
    words = ("len", "nul1", "type", "gen", "start", "count", "code", "lng", "total", "ordt", "ligt", "nligt", "nctoc")

    def header(d):
        return dict(zip(words, struct.unpack_from(">%dL" % len(words), d, 4)))
    data = db.record(idx)
    hdr = header(data)
    cncx, rec_off = {}, 0
    for j in range(hdr["nctoc"]):
        c = db.record(idx + hdr["count"] + 1 + j)
        off = 0
        while off < len(c) and c[off] != 0:
            start = off
            used, n = _varint(c, off)
            off += used
            cncx[start + rec_off] = c[off:off + n]
            off += n
        rec_off += 0x10000
    tags, cbytes = [], 0
    t0 = hdr["len"]
    if data[t0:t0 + 4] == b"TAGX":
        first, cbytes = struct.unpack_from(">LL", data, t0 + 4)
        tags = [tuple(data[t0 + i:t0 + i + 4]) for i in range(12, first, 4)]
    out = []
    for i in range(idx + 1, idx + 1 + hdr["count"]):
        d = db.record(i)
        h = header(d)
        pos = [struct.unpack_from(">H", d, h["start"] + 4 + 2 * j)[0] for j in range(h["count"])] + [h["start"]]
        for j in range(h["count"]):
            s = pos[j]
            ln = d[s]
            label = d[s + 1:s + 1 + ln]
            out.append((label, _tagmap(cbytes, tags, d, s + 1 + ln)))
    return out, cncx


def _tagmap(cbytes, tags, d, start):
    found, ci, ds = [], 0, start + cbytes
    for tag, per, mask, end in tags:
        if end == 1:
            ci += 1
            continue
        value = d[start + ci] & mask
        if value:
            if value == mask and bin(mask).count("1") > 1:
                used, value = _varint(d, ds)
                ds += used
                found.append((tag, None, value, per))
            elif value == mask:
                found.append((tag, 1, None, per))
            else:
                while not mask & 1:
                    mask >>= 1
                    value >>= 1
                found.append((tag, value, None, per))
    result = {}
    for tag, count, nbytes, per in found:
        vals = []
        if count is not None:
            for _ in range(count * per):
                used, v = _varint(d, ds)
                ds += used
                vals.append(v)
        else:
            total = 0
            while total < nbytes:
                used, v = _varint(d, ds)
                ds += used
                total += used
                vals.append(v)
        result[tag] = vals
    return result


# ---- the book ------------------------------------------------------------------------------
def _image_kind(b):
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def read(path):
    """-> (html, title, {image name: bytes}) for a Kindle/Palm book."""
    data = open(path, "rb").read()
    db = PalmDB(data)
    r0 = db.record(0)
    if db.kind == b"TEXtREAd":                      # plain PalmDOC e-text
        comp, _, _, count = struct.unpack_from(">HHLH", r0, 0)
        text = b"".join(palmdoc(db.record(i)) if comp == 2 else db.record(i) for i in range(1, count + 1))
        body = text.decode("cp1252", "replace")
        from html import escape
        return "".join(f"<p>{escape(p)}</p>" for p in re.split(r"\r?\n\s*\r?\n|\r", body) if p.strip()), "", {}
    if db.kind not in (b"BOOKMOBI", b"TEXtREAd"):
        raise ValueError("not a Kindle book")
    comp, _, text_len, count, _rsize, encryption = struct.unpack_from(">HHLHHH", r0, 0)
    if encryption:
        raise ProtectedBook()
    if r0[16:20] != b"MOBI":
        raise ValueError("not a Kindle book")
    hdr_len, _type, codepage = struct.unpack_from(">LLL", r0, 20)
    version, = struct.unpack_from(">L", r0, 36)
    encoding = "utf-8" if codepage == 65001 else "cp1252"
    name_off, name_len = struct.unpack_from(">LL", r0, 0x54)
    title = r0[name_off:name_off + name_len].decode(encoding, "replace")
    first_res, = struct.unpack_from(">L", r0, 0x6C)
    extra = struct.unpack_from(">H", r0, 0xF2)[0] if hdr_len >= 0xE4 and version >= 5 else 0
    if comp == 2:
        unpack = palmdoc
    elif comp == 17480:
        unpack = _huff_unpacker(db, r0)
    elif comp == 1:
        unpack = bytes
    else:
        raise ValueError(f"unknown Kindle compression {comp}")
    raw = b"".join(unpack(_trailing(db.record(i), extra)) for i in range(1, count + 1))[:text_len]

    images = {}

    def image(i):
        rec = first_res + i - 1
        if 0 < rec < len(db):
            b = db.record(rec)
            kind = _image_kind(b)
            if kind:
                name = f"img{i:05d}.{kind}"
                images[name] = b
                return name
        return None

    if version >= 8:
        fdst, = struct.unpack_from(">L", r0, 0xC0)
        if fdst != 0xFFFFFFFF and fdst < len(db) and db.record(fdst)[:4] == b"FDST":
            f = db.record(fdst)
            n, = struct.unpack_from(">L", f, 8)
            if n:
                start, end = struct.unpack_from(">LL", f, 12)
                raw = raw[start:end]                    # flow 0 = the book's HTML (others: CSS)
        frag_idx, skel_idx = struct.unpack_from(">LL", r0, 0xF8)
        skels, _ = _index(db, skel_idx)
        frags, cncx = _index(db, frag_idx)
        parts, fp = [], 0
        for label, tags in skels:
            nfrag = tags.get(1, [0])[0]
            spos, slen = tags.get(6, [0, 0])[:2]
            base = spos + slen
            skel = raw[spos:base]
            for _ in range(nfrag):
                if fp >= len(frags):
                    break
                flabel, ftags = frags[fp]
                ins = int(flabel) - spos
                flen = ftags.get(6, [0, 0])[1]
                piece = raw[base:base + flen]
                skel = skel[:ins] + piece + skel[ins:]
                base += flen
                fp += 1
            parts.append(skel)
        html = b"".join(parts) if parts else raw
        text = html.decode(encoding, "replace")
        text = re.sub(r'src="kindle:embed:([0-9A-Va-v]{4})[^"]*"',
                      lambda m: f'src="{image(int(m.group(1), 32)) or ""}"', text)
    else:
        text = raw.decode(encoding, "replace")
        text = re.sub(r'recindex="?0*(\d+)"?', lambda m: f'src="{image(int(m.group(1))) or ""}"', text)
        text = re.sub(r"(?i)<mbp:pagebreak\s*/?>", "<!--bt:newpage-->", text)
    # whole HTML pages glued together: keep only what is inside each <body>
    bodies = re.findall(r"(?is)<body[^>]*>(.*?)</body>", text)
    if bodies:
        text = "\n".join(bodies)
    text = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", text)
    return text, title, images
