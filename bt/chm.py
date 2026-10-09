"""CHM (compiled HTML help — many older ebooks and manuals) read in-house: the ITSF container,
its file directory, and an LZX decompressor for the compressed section. -> HTML in the order
of the book's own table of contents (.hhc), each topic starting with its title as a heading.
"""
import html as htmlmod
import re
import struct
from urllib.parse import unquote

FRAME = 0x8000


# ---- LZX ---------------------------------------------------------------------------------
EXTRA_BITS, POSITION_BASE = [], []
_j = 0
for _i in range(0, 52, 2):
    EXTRA_BITS += [_j, _j]
    if _i != 0 and _j < 17:
        _j += 1
_j = 0
for _i in range(52):
    POSITION_BASE.append(_j)
    _j += 1 << EXTRA_BITS[_i]
SLOTS = {15: 30, 16: 32, 17: 34, 18: 36, 19: 38, 20: 42, 21: 50}


class _Bits:
    """LZX bit reader: 16-bit little-endian words, bits taken most-significant first."""

    def __init__(self, data, pos=0):
        self.d, self.p, self.buf, self.n = data, pos, 0, 0

    def ensure(self, k):
        d = self.d
        while self.n < k:
            lo = d[self.p] if self.p < len(d) else 0
            hi = d[self.p + 1] if self.p + 1 < len(d) else 0
            self.p += 2
            self.buf = ((self.buf << 16) | lo | (hi << 8)) & 0xFFFFFFFFFFFF
            self.n += 16

    def peek(self, k):
        self.ensure(k)
        return (self.buf >> (self.n - k)) & ((1 << k) - 1)

    def take(self, k):
        if k == 0:
            return 0
        v = self.peek(k)
        self.n -= k
        return v

    def align(self):
        """Drop bits up to the next 16-bit boundary."""
        self.n -= self.n & 15


class _Tree:
    """Canonical Huffman decoder via a 2^maxbits lookup table."""

    def __init__(self, lengths, maxbits=16):
        self.maxbits = maxbits
        size = 1 << maxbits
        table = [None] * size
        code = 0
        for ln in range(1, maxbits + 1):
            for sym, l in enumerate(lengths):
                if l == ln:
                    start = code << (maxbits - ln)
                    end = (code + 1) << (maxbits - ln)
                    if end > size:
                        raise ValueError("bad LZX code lengths")
                    table[start:end] = [(sym, ln)] * (end - start)
                    code += 1
            code <<= 1
        self.table = table

    def read(self, bits):
        e = self.table[bits.peek(self.maxbits)]
        if e is None:
            raise ValueError("bad LZX data")
        bits.n -= e[1]
        return e[0]


class LZX:
    def __init__(self, window_bits):
        self.wsize = 1 << window_bits
        self.window = bytearray(self.wsize)
        self.wpos = 0
        self.slots = SLOTS[window_bits]
        self.reset()

    def reset(self):
        self.R = [1, 1, 1]
        self.main_len = [0] * (256 + self.slots * 8)
        self.len_len = [0] * 249
        self.header = False
        self.remaining = 0
        self.btype = 0

    def _lengths(self, bits, lens, first, last):
        pre = _Tree([bits.take(4) for _ in range(20)])
        x = first
        while x < last:
            z = pre.read(bits)
            if z == 17:
                run = bits.take(4) + 4
                lens[x:x + run] = [0] * run
                x += run
            elif z == 18:
                run = bits.take(5) + 20
                lens[x:x + run] = [0] * run
                x += run
            elif z == 19:
                run = bits.take(1) + 4
                z = pre.read(bits)
                v = (lens[x] - z) % 17
                lens[x:x + run] = [v] * run
                x += run
            else:
                lens[x] = (lens[x] - z) % 17
                x += 1

    def decompress(self, bits, out_len):
        """Decode out_len bytes (a whole number of frames, except at the very end)."""
        out = bytearray()
        w, wsize = self.window, self.wsize
        while len(out) < out_len:
            frame = min(FRAME, out_len - len(out))
            if not self.header:
                if bits.take(1):
                    bits.take(16)
                    bits.take(16)                 # E8 translation size (CHM leaves it off)
                self.header = True
            done = 0
            while done < frame:
                if self.remaining == 0:
                    self.btype = bits.take(3)
                    hi = bits.take(16)
                    lo = bits.take(8)
                    self.remaining = (hi << 8) | lo
                    if self.btype == 2:
                        self.aligned = _Tree([bits.take(3) for _ in range(8)], 7)
                    if self.btype in (1, 2):
                        self._lengths(bits, self.main_len, 0, 256)
                        self._lengths(bits, self.main_len, 256, len(self.main_len))
                        self.main = _Tree(self.main_len)
                        self._lengths(bits, self.len_len, 0, 249)
                        self.length = _Tree(self.len_len) if any(self.len_len) else None
                    elif self.btype == 3:
                        bits.ensure(16)
                        if bits.n > 16:
                            bits.p -= 2
                        bits.n, bits.buf = 0, 0
                        d = bits.d
                        self.R = list(struct.unpack_from("<3L", d, bits.p))
                        bits.p += 12
                    else:
                        raise ValueError("bad LZX block")
                run = min(self.remaining, frame - done)
                if self.btype == 3:
                    chunk = bits.d[bits.p:bits.p + run]
                    bits.p += run
                    for b in chunk:
                        w[self.wpos] = b
                        self.wpos = (self.wpos + 1) & (wsize - 1)
                    out += chunk
                    self.remaining -= run
                    done += run
                    if self.remaining == 0 and (bits.p & 1):
                        bits.p += 1                     # uncompressed blocks are padded to even length
                    continue
                end = done + run
                R = self.R
                main, length = self.main, self.length
                aligned = self.btype == 2
                while done < end:
                    sym = main.read(bits)
                    if sym < 256:
                        w[self.wpos] = sym
                        self.wpos = (self.wpos + 1) & (wsize - 1)
                        out.append(sym)
                        done += 1
                        continue
                    sym -= 256
                    mlen = sym & 7
                    if mlen == 7:
                        mlen += length.read(bits)
                    mlen += 2
                    slot = sym >> 3
                    if slot > 2:
                        extra = EXTRA_BITS[slot]
                        off = POSITION_BASE[slot] - 2
                        if aligned and extra >= 3:
                            if extra > 3:
                                off += bits.take(extra - 3) << 3
                            off += self.aligned.read(bits)
                        else:
                            off += bits.take(extra)
                        R[2], R[1], R[0] = R[1], R[0], off
                    elif slot == 0:
                        off = R[0]
                    elif slot == 1:
                        off = R[1]
                        R[1], R[0] = R[0], off
                    else:
                        off = R[2]
                        R[2], R[0] = R[0], off
                    src = (self.wpos - off) & (wsize - 1)
                    for _ in range(mlen):
                        b = w[src]
                        w[self.wpos] = b
                        out.append(b)
                        src = (src + 1) & (wsize - 1)
                        self.wpos = (self.wpos + 1) & (wsize - 1)
                    done += mlen
                self.remaining -= run + (done - end)    # a match may run past the block end
            bits.align()                                # every frame ends on a 16-bit boundary
        return bytes(out[:out_len])


# ---- the CHM container --------------------------------------------------------------------
def _encint(d, p):
    v = 0
    while True:
        b = d[p]
        p += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, p


class CHM:
    def __init__(self, path):
        d = self.d = open(path, "rb").read()
        if d[:4] != b"ITSF":
            raise ValueError("not a CHM file")
        version, = struct.unpack_from("<L", d, 4)
        dir_off, dir_len = struct.unpack_from("<QQ", d, 0x48)
        self.content = struct.unpack_from("<Q", d, 0x58)[0] if version >= 3 else dir_off + dir_len
        if d[dir_off:dir_off + 4] != b"ITSP":
            raise ValueError("bad CHM directory")
        hlen, = struct.unpack_from("<L", d, dir_off + 8)
        csize, = struct.unpack_from("<L", d, dir_off + 0x10)
        first, last = struct.unpack_from("<ll", d, dir_off + 0x20)
        self.files = {}
        c = first
        seen = set()
        while 0 <= c and c not in seen:
            seen.add(c)
            base = dir_off + hlen + c * csize
            chunk = d[base:base + csize]
            if chunk[:4] != b"PMGL":
                break
            free, = struct.unpack_from("<L", chunk, 4)
            nxt, = struct.unpack_from("<l", chunk, 0x10)
            p = 0x14
            while p < csize - free:
                n, p = _encint(chunk, p)
                name = chunk[p:p + n].decode("utf-8", "replace")
                p += n
                sec, p = _encint(chunk, p)
                off, p = _encint(chunk, p)
                ln, p = _encint(chunk, p)
                self.files[name] = (sec, off, ln)
            c = nxt
        self._section1 = None

    def _raw(self, name):
        sec, off, ln = self.files[name]
        return self.d[self.content + off:self.content + off + ln]

    def read(self, name):
        if name not in self.files:
            return None
        sec, off, ln = self.files[name]
        if sec == 0:
            return self._raw(name)
        if self._section1 is None:
            self._section1 = self._decompress()
        return self._section1[off:off + ln]

    def _decompress(self):
        ms = "::DataSpace/Storage/MSCompressed/"
        ctl = self._raw(ms + "ControlData")
        version, reset, window = struct.unpack_from("<LLL", ctl, 8)
        if version == 2:
            reset *= FRAME
            window *= FRAME
        rt = self._raw(ms + "Transform/{7FC28940-9D31-11D0-9B27-00A0C91E9C7C}/InstanceData/ResetTable")
        n, esize, toff = struct.unpack_from("<LLL", rt, 4)
        ulen, clen, blen = struct.unpack_from("<QQQ", rt, 0x10)
        entries = [struct.unpack_from("<Q", rt, toff + i * esize)[0] for i in range(n)]
        data = self._raw(ms + "Content")
        lzx = LZX(window.bit_length() - 1)
        per = max(1, reset // blen)                     # frames between resets
        out = bytearray()
        for k in range(0, len(entries), per):
            lzx.reset()
            start = entries[k]
            want = min(per * blen, ulen - len(out))
            out += lzx.decompress(_Bits(data, start), want)
        return bytes(out)


def read(path):
    """-> (html, title, {image name: bytes})"""
    c = CHM(path)
    names = [n for n in c.files if not n.startswith("::") and not n.startswith("/#") and not n.startswith("/$")]
    pages = [n for n in names if n.lower().endswith((".htm", ".html"))]
    order, titles = [], {}
    hhc = next((n for n in names if n.lower().endswith(".hhc")), None)
    if hhc:
        toc = (c.read(hhc) or b"").decode("cp1252", "replace")
        for obj in re.findall(r"(?is)<object[^>]*text/sitemap[^>]*>(.*?)</object>", toc):
            name = re.search(r'(?is)<param\s+name="Name"\s+value="([^"]*)"', obj)
            local = re.search(r'(?is)<param\s+name="Local"\s+value="([^"]*)"', obj)
            if local:
                path_ = "/" + unquote(local.group(1).split("#")[0]).lstrip("/")
                match = next((p for p in pages if p.lower() == path_.lower()), None)
                if match and match not in titles:
                    order.append(match)
                    titles[match] = htmlmod.unescape(name.group(1)) if name else ""
    order += sorted(p for p in pages if p not in titles)
    images = {}
    parts = []
    for p in order:
        raw = c.read(p) or b""
        cs = re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
        text = raw.decode(cs.group(1).decode() if cs else "cp1252", "replace")
        body = re.search(r"(?is)<body[^>]*>(.*?)(</body>|$)", text)
        body = body.group(1) if body else text
        body = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", body)

        def img(m, folder=p.rsplit("/", 1)[0]):
            src = unquote(m.group(2))
            full = src if src.startswith("/") else folder + "/" + src
            data = c.read(full) if full in c.files else None
            if data:
                name = "chm" + re.sub(r"[^\w.]", "_", full)
                images[name] = data
                return f'{m.group(1)}"{name}"'
            return 'src=""'
        body = re.sub(r'(?i)(src=)"([^"]+)"', img, body)
        title = titles.get(p)
        if title and not re.search(r"(?is)<h[1-3]", body[:600]):
            body = f"<h1>{htmlmod.escape(title)}</h1>" + body
        parts.append(body)
    title = ""
    return "\n".join(parts), title, images
