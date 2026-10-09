"""DjVu books (common for scanned books, e.g. archive.org and Russian libraries), read in-house.

The pages' hidden text layer (TXTz) is decoded — BZZ compression on DjVu's ZP arithmetic coder,
as published in the DjVu v3 format specification — giving every word and its box. Each page is
then shown as that text in its original place and size (the scanned picture itself is not
decoded), so reading, highlighting and search work as in any other book. Bookmarks (NAVM) become
chapters. Pages without a text layer come out blank.
"""
import os
import struct

# ZP-coder adaptation table (probability, threshold, next state up / down), from the specification
ZP_P = [
    0x8000, 0x8000, 0x8000, 0x6bbd, 0x6bbd, 0x5d45, 0x5d45, 0x51b9, 0x51b9, 0x4813, 0x4813, 0x3fd5,
    0x3fd5, 0x38b1, 0x38b1, 0x3275, 0x3275, 0x2cfd, 0x2cfd, 0x2825, 0x2825, 0x23ab, 0x23ab, 0x1f87,
    0x1f87, 0x1bbb, 0x1bbb, 0x1845, 0x1845, 0x1523, 0x1523, 0x1253, 0x1253, 0x0fcf, 0x0fcf, 0x0d95,
    0x0d95, 0x0b9d, 0x0b9d, 0x09e3, 0x09e3, 0x0861, 0x0861, 0x0711, 0x0711, 0x05f1, 0x05f1, 0x04f9,
    0x04f9, 0x0425, 0x0425, 0x0371, 0x0371, 0x02d9, 0x02d9, 0x0259, 0x0259, 0x01ed, 0x01ed, 0x0193,
    0x0193, 0x0149, 0x0149, 0x010b, 0x010b, 0x00d5, 0x00d5, 0x00a5, 0x00a5, 0x007b, 0x007b, 0x0057,
    0x0057, 0x003b, 0x003b, 0x0023, 0x0023, 0x0013, 0x0013, 0x0007, 0x0007, 0x0001, 0x0001, 0x5695,
    0x24ee, 0x8000, 0x0d30, 0x481a, 0x0481, 0x3579, 0x017a, 0x24ef, 0x007b, 0x1978, 0x0028, 0x10ca,
    0x000d, 0x0b5d, 0x0034, 0x078a, 0x00a0, 0x050f, 0x0117, 0x0358, 0x01ea, 0x0234, 0x0144, 0x0173,
    0x0234, 0x00f5, 0x0353, 0x00a1, 0x05c5, 0x011a, 0x03cf, 0x01aa, 0x0285, 0x0286, 0x01ab, 0x03d3,
    0x011a, 0x05c5, 0x00ba, 0x08ad, 0x007a, 0x0ccc, 0x01eb, 0x1302, 0x02e6, 0x1b81, 0x045e, 0x24ef,
    0x0690, 0x2865, 0x09de, 0x3987, 0x0dc8, 0x2c99, 0x10ca, 0x3b5f, 0x0b5d, 0x5695, 0x078a, 0x8000,
    0x050f, 0x24ee, 0x0358, 0x0d30, 0x0234, 0x0481, 0x0173, 0x017a, 0x00f5, 0x007b, 0x00a1, 0x0028,
    0x011a, 0x000d, 0x01aa, 0x0034, 0x0286, 0x00a0, 0x03d3, 0x0117, 0x05c5, 0x01ea, 0x08ad, 0x0144,
    0x0ccc, 0x0234, 0x1302, 0x0353, 0x1b81, 0x05c5, 0x24ef, 0x03cf, 0x2b74, 0x0285, 0x201d, 0x01ab,
    0x1715, 0x011a, 0x0fb7, 0x00ba, 0x0a67, 0x01eb, 0x06e7, 0x02e6, 0x0496, 0x045e, 0x030d, 0x0690,
    0x0206, 0x09de, 0x0155, 0x0dc8, 0x00e1, 0x2b74, 0x0094, 0x201d, 0x0188, 0x1715, 0x0252, 0x0fb7,
    0x0383, 0x0a67, 0x0547, 0x06e7, 0x07e2, 0x0496, 0x0bc0, 0x030d, 0x1178, 0x0206, 0x19da, 0x0155,
    0x24ef, 0x00e1, 0x320e, 0x0094, 0x432a, 0x0188, 0x447d, 0x0252, 0x5ece, 0x0383, 0x8000, 0x0547,
    0x481a, 0x07e2, 0x3579, 0x0bc0, 0x24ef, 0x1178, 0x1978, 0x19da, 0x2865, 0x24ef, 0x3987, 0x320e,
    0x2c99, 0x432a, 0x3b5f, 0x447d, 0x5695, 0x5ece, 0x8000, 0x8000, 0x5695, 0x481a, 0x481a]
ZP_M = [
    0x0000, 0x0000, 0x0000, 0x10a5, 0x10a5, 0x1f28, 0x1f28, 0x2bd3, 0x2bd3, 0x36e3, 0x36e3, 0x408c,
    0x408c, 0x48fd, 0x48fd, 0x505d, 0x505d, 0x56d0, 0x56d0, 0x5c71, 0x5c71, 0x615b, 0x615b, 0x65a5,
    0x65a5, 0x6962, 0x6962, 0x6ca2, 0x6ca2, 0x6f74, 0x6f74, 0x71e6, 0x71e6, 0x7404, 0x7404, 0x75d6,
    0x75d6, 0x7768, 0x7768, 0x78c2, 0x78c2, 0x79ea, 0x79ea, 0x7ae7, 0x7ae7, 0x7bbe, 0x7bbe, 0x7c75,
    0x7c75, 0x7d0f, 0x7d0f, 0x7d91, 0x7d91, 0x7dfe, 0x7dfe, 0x7e5a, 0x7e5a, 0x7ea6, 0x7ea6, 0x7ee6,
    0x7ee6, 0x7f1a, 0x7f1a, 0x7f45, 0x7f45, 0x7f6b, 0x7f6b, 0x7f8d, 0x7f8d, 0x7faa, 0x7faa, 0x7fc3,
    0x7fc3, 0x7fd7, 0x7fd7, 0x7fe7, 0x7fe7, 0x7ff2, 0x7ff2, 0x7ffa, 0x7ffa, 0x7fff, 0x7fff, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000]
ZP_UP = [
    84, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28,
    29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53,
    54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78,
    79, 80, 81, 82, 81, 82, 9, 86, 5, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 82, 99, 76, 101, 70, 103,
    66, 105, 106, 107, 66, 109, 60, 111, 56, 69, 114, 65, 116, 61, 118, 57, 120, 53, 122, 49, 124, 43,
    72, 39, 60, 33, 56, 29, 52, 23, 48, 23, 42, 137, 38, 21, 140, 15, 142, 9, 144, 141, 146, 147, 148,
    149, 150, 151, 152, 153, 154, 155, 70, 157, 66, 81, 62, 75, 58, 69, 54, 65, 50, 167, 44, 65, 40, 59,
    34, 55, 30, 175, 24, 177, 178, 179, 180, 181, 182, 183, 184, 69, 186, 59, 188, 55, 190, 51, 192, 47,
    194, 41, 196, 37, 198, 199, 72, 201, 62, 203, 58, 205, 54, 207, 50, 209, 46, 211, 40, 213, 36, 215,
    30, 217, 26, 219, 20, 71, 14, 61, 14, 57, 8, 53, 228, 49, 230, 45, 232, 39, 234, 35, 138, 29, 24,
    25, 240, 19, 22, 13, 16, 13, 10, 7, 244, 249, 10, 89, 230]
ZP_DN = [
    145, 4, 3, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
    25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49,
    50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74,
    75, 76, 77, 78, 79, 80, 85, 226, 6, 176, 143, 138, 141, 112, 135, 104, 133, 100, 129, 98, 127, 72,
    125, 102, 123, 60, 121, 110, 119, 108, 117, 54, 115, 48, 113, 134, 59, 132, 55, 130, 51, 128, 47,
    126, 41, 62, 37, 66, 31, 54, 25, 50, 131, 46, 17, 40, 15, 136, 7, 32, 139, 172, 9, 170, 85, 168,
    248, 166, 247, 164, 197, 162, 95, 160, 173, 158, 165, 156, 161, 60, 159, 56, 71, 52, 163, 48, 59,
    42, 171, 38, 169, 32, 53, 26, 47, 174, 193, 18, 191, 222, 189, 218, 187, 216, 185, 214, 61, 212, 53,
    210, 49, 208, 45, 206, 39, 204, 195, 202, 31, 200, 243, 64, 239, 56, 237, 52, 235, 48, 233, 44, 231,
    38, 229, 34, 227, 28, 225, 22, 223, 16, 221, 220, 63, 8, 55, 224, 51, 2, 47, 87, 43, 246, 37, 244,
    33, 238, 27, 236, 21, 16, 15, 8, 241, 242, 7, 10, 245, 2, 1, 83, 250, 2, 143, 246]


ZP_P += [0] * (256 - len(ZP_P))
ZP_M += [0] * (256 - len(ZP_M))
ZP_UP += [0] * (256 - len(ZP_UP))
ZP_DN += [0] * (256 - len(ZP_DN))
FFZT = [0] * 256
for _i in range(256):
    _j = _i
    while _j & 0x80:
        FFZT[_i] += 1
        _j = (_j << 1) & 0xFF


class ZP:
    """ZP-coder decoder."""

    def __init__(self, data):
        self.d, self.pos = data, 0
        self.a = 0
        self.code = (self._byte() << 8) | self._byte()
        self.delay, self.scount, self.buffer = 25, 0, 0
        self._preload()
        self.fence = min(self.code, 0x7FFF)

    def _byte(self):
        if self.pos < len(self.d):
            b = self.d[self.pos]
            self.pos += 1
            return b
        self.pos += 1
        return 0xFF

    def _preload(self):
        while self.scount <= 24:
            if self.pos >= len(self.d):
                self.delay -= 1
                if self.delay < 1:
                    raise EOFError("DjVu data ended early")
            self.buffer = ((self.buffer << 8) | self._byte()) & 0xFFFFFFFF
            self.scount += 8

    @staticmethod
    def _ffz(x):
        return FFZT[x & 0xFF] + 8 if x >= 0xFF00 else FFZT[(x >> 8) & 0xFF]

    def _lps(self, z):
        z = 0x10000 - z
        self.a += z
        self.code += z
        shift = self._ffz(self.a)
        self.scount -= shift
        self.a = (self.a << shift) & 0xFFFF
        self.code = ((self.code << shift) & 0xFFFF) | ((self.buffer >> self.scount) & ((1 << shift) - 1))
        if self.scount < 16:
            self._preload()
        self.fence = min(self.code, 0x7FFF)

    def _mps(self, z):
        self.scount -= 1
        self.a = (z << 1) & 0xFFFF
        self.code = ((self.code << 1) & 0xFFFF) | ((self.buffer >> self.scount) & 1)
        if self.scount < 16:
            self._preload()
        self.fence = min(self.code, 0x7FFF)

    def bit(self, ctx, i):
        """Decode with adaptive context ctx[i] (a list of states)."""
        s = ctx[i]
        z = self.a + ZP_P[s]
        if z <= self.fence:
            self.a = z
            return s & 1
        bit = s & 1
        d = 0x6000 + ((z + self.a) >> 2)
        if z > d:
            z = d
        if z > self.code:
            ctx[i] = ZP_DN[s]
            self._lps(z)
            return bit ^ 1
        if self.a >= ZP_M[s]:
            ctx[i] = ZP_UP[s]
        self._mps(z)
        return bit

    def raw(self):
        """Decode a bit with fixed probability 1/2."""
        z = 0x8000 + (self.a >> 1)
        if z > self.code:
            self._lps(z)
            return 1
        self._mps(z)
        return 0


def bzz(data):
    """Decompress a BZZ stream (ZP coding + move-to-front + Burrows-Wheeler)."""
    zp = ZP(data)
    out = bytearray()
    ctx = [0] * 300
    while True:
        n = 1
        while n < (1 << 24):
            n = (n << 1) | zp.raw()
        size = n - (1 << 24)
        if not size:
            break
        if size > 4096 * 1024:
            raise ValueError("bad DjVu text data")
        fshift = 0
        if zp.raw():
            fshift += 1
            if zp.raw():
                fshift += 1
        mtf = list(range(256))
        freq = [0, 0, 0, 0]
        fadd = 4
        mtfno = 3
        markerpos = -1
        block = bytearray(size)

        def binary(base, bits):
            n = 1
            while n < (1 << bits):
                n = (n << 1) | zp.bit(ctx, base + n - 1)
            return n - (1 << bits)
        for i in range(size):
            ctxid = min(2, mtfno)
            if zp.bit(ctx, ctxid):
                mtfno = 0
            elif zp.bit(ctx, 3 + ctxid):
                mtfno = 1
            else:
                base, found = 6, False
                for k in range(1, 8):                # 2+, 4+, 8+, … 128+
                    if zp.bit(ctx, base):
                        mtfno = (1 << k) + binary(base + 1, k)
                        found = True
                        break
                    base += 1 << k                  # next group: 1 decision + 2^k - 1 contexts
                if not found:
                    mtfno = 256
                    block[i] = 0
                    markerpos = i
                    continue
            c = mtf[mtfno]
            block[i] = c
            # move the symbol according to its estimated frequency
            fadd = fadd + (fadd >> fshift)
            if fadd > 0x10000000:
                fadd >>= 24
                freq = [f >> 24 for f in freq]
            fc = fadd + (freq[mtfno] if mtfno < 4 else 0)
            k = mtfno
            while k >= 4:
                mtf[k] = mtf[k - 1]
                k -= 1
            while k > 0 and fc >= freq[k - 1]:
                mtf[k] = mtf[k - 1]
                freq[k] = freq[k - 1]
                k -= 1
            mtf[k] = c
            freq[k] = fc
        if markerpos < 1 or markerpos >= size:
            raise ValueError("bad DjVu text data")
        # undo the Burrows-Wheeler sort
        count = [0] * 256
        posn = [0] * size
        for i in range(size):
            if i == markerpos:
                continue
            c = block[i]
            posn[i] = (c << 24) | (count[c] & 0xFFFFFF)
            count[c] += 1
        last = 1
        for i in range(256):
            count[i], last = last, last + count[i]
        res = bytearray(size)
        i, last = 0, size - 1
        while last > 0:
            n = posn[i]
            c = n >> 24
            last -= 1
            res[last] = c
            i = count[c] + (n & 0xFFFFFF)
        out += res[:size - 1]
    return bytes(out)


# ---- the DjVu file ------------------------------------------------------------------------------
def _chunks(d, pos, end):
    while pos + 8 <= end:
        cid = d[pos:pos + 4]
        size, = struct.unpack_from(">I", d, pos + 4)
        yield cid, pos + 8, size
        pos += 8 + size + (size & 1)


def _zones(t, maxtext):
    """TXTz zone tree -> [(type, x0, y0, x1, y1, start, length)], DjVu coordinates (y up)."""
    out = []
    pos = [0]

    def u8():
        v = t[pos[0]]
        pos[0] += 1
        return v

    def u16():
        v = (t[pos[0]] << 8) | t[pos[0] + 1]
        pos[0] += 2
        return v

    def u24():
        v = (t[pos[0]] << 16) | (t[pos[0] + 1] << 8) | t[pos[0] + 2]
        pos[0] += 3
        return v

    def zone(parent, prev, depth=0):
        ztype = u8()
        x, y, w, h = u16() - 0x8000, u16() - 0x8000, u16() - 0x8000, u16() - 0x8000
        start = u16() - 0x8000
        length = u24()
        if prev:
            if ztype in (1, 4, 5):                   # page, paragraph, line
                x += prev[1]
                y = prev[2] - (y + h)
            else:                                     # column, region, word, character
                x += prev[3]
                y += prev[2]
            start += prev[5] + prev[6]
        elif parent:
            x += parent[1]
            y = parent[4] - (y + h)
            start += parent[5]
        me = (ztype, x, y, x + w, y + h, start, length)
        out.append(me)
        kids = u24()
        if depth > 20:
            raise ValueError("bad DjVu text zones")
        p = None
        for _ in range(kids):
            p = zone(me, p, depth + 1)
        return me
    zone(None, None)
    return out


def _page_words(txt):
    """Decoded TXTz -> [(x0, y0, x1, y1, word)] in DjVu coordinates."""
    n = (txt[0] << 16) | (txt[1] << 8) | txt[2]
    text = txt[3:3 + n]
    if len(txt) <= 3 + n:
        return []
    zones = _zones(txt[4 + n:], n)
    words = [z for z in zones if z[0] == 6]
    if not words:                                     # lines only: one box per line
        words = [z for z in zones if z[0] == 5]
    out = []
    for z in words:
        w = text[z[5]:z[5] + z[6]].decode("utf-8", "replace").strip()
        if w:
            out.append((z[1], z[2], z[3], z[4], w))
    return out


def _navm(data):
    """Bookmarks -> [(level, title, page number or None)]."""
    b = bzz(data)
    pos = [0]

    def u8():
        v = b[pos[0]]
        pos[0] += 1
        return v

    def s():
        n = (b[pos[0]] << 16) | (b[pos[0] + 1] << 8) | b[pos[0] + 2]
        pos[0] += 3
        v = b[pos[0]:pos[0] + n].decode("utf-8", "replace")
        pos[0] += n
        return v
    total = (b[0] << 8) | b[1]
    pos[0] = 2
    out = []

    def one(level):
        kids = u8()
        title, url = s(), s()
        page = int(url[1:]) if url.startswith("#") and url[1:].isdigit() else None
        out.append((level, title, page))
        for _ in range(kids):
            one(level + 1)
    while len(out) < total and pos[0] < len(b):
        one(1)
    return out


def read(path):
    """-> (pages [(width_pt, height_pt, words [(x0, y0, x1, y1, text)] top-left points)], bookmarks)"""
    d = open(path, "rb").read()
    if d[:8] != b"AT&TFORM":
        raise ValueError("not a DjVu file")
    kind = d[12:16]
    pages, bookmarks = [], []

    def page(start, size):
        w = h = dpi = 0
        words = []
        for cid, p, n in _chunks(d, start, start + size):
            if cid == b"INFO":
                w, h = struct.unpack_from(">HH", d, p)
                dpi = struct.unpack_from("<H", d, p + 6)[0] if n >= 8 else 300
            elif cid in (b"TXTz", b"TXTa"):
                try:
                    txt = bzz(d[p:p + n]) if cid == b"TXTz" else d[p:p + n]
                    words = _page_words(txt)
                except Exception:
                    words = []
        dpi = dpi or 300
        k = 72.0 / dpi
        pts = [(x0 * k, (h - y1) * k, x1 * k, (h - y0) * k, t) for x0, y0, x1, y1, t in words]
        pages.append((w * k, h * k, pts))
    if kind == b"DJVU":
        page(16, len(d) - 16)
    elif kind == b"DJVM":
        for cid, p, n in _chunks(d, 16, len(d)):
            if cid == b"DIRM" and d[p] & 0x80 == 0:
                raise ValueError("this DjVu book is split over several files; open its index file's folder copy as one bundled file")
            if cid == b"NAVM":
                try:
                    bookmarks = _navm(d[p:p + n])
                except Exception:
                    bookmarks = []
            if cid == b"FORM" and d[p:p + 4] == b"DJVU":
                page(p + 4, n - 4)
    else:
        raise ValueError("not a DjVu book")
    return pages, bookmarks


def to_pdf(path, out):
    """A DjVu book as a PDF of its text, each word where it was printed (one batch per page)."""
    import pymupdf
    pages, bookmarks = read(path)
    if not pages:
        raise ValueError("no pages in this DjVu file")
    if not any(p[2] for p in pages):
        raise ValueError("this DjVu book has no text layer, so there is nothing to read aloud")
    font_file = next((f for f in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf")
                      if os.path.exists(f)), None)
    latin = pymupdf.Font(fontfile=font_file) if font_file else pymupdf.Font("helv")
    cjk_font = None
    doc = pymupdf.open()
    for w, h, words in pages:
        pg = doc.new_page(width=max(w, 72), height=max(h, 72))
        if not words:
            continue
        tw = pymupdf.TextWriter(pg.rect)
        # words on the same printed line share one size and baseline (short words like 'un'
        # have low boxes; sizing each word alone made the text jump)
        lines = []
        for wd in sorted(words, key=lambda q: (q[3], q[0])):
            x0, y0, x1, y1, t = wd
            if lines and abs(lines[-1][-1][3] - y1) < 0.45 * max(1.0, y1 - y0):
                lines[-1].append(wd)
            else:
                lines.append([wd])
        # size from the line spacing (steady through a paragraph), else from the tallest boxes
        bases = [max(q[3] for q in ln) for ln in lines]
        tall = [sorted(q[3] - q[1] for q in ln)[-1] for ln in lines]
        sizes = []
        for i, ln in enumerate(lines):
            by_height = tall[i] * 0.82
            gaps = [abs(bases[j] - bases[i]) for j in (i - 1, i + 1) if 0 <= j < len(lines)]
            gaps = [g for g in gaps if tall[i] * 0.8 < g < tall[i] * 2.2]
            sizes.append(min(min(gaps) * 0.72, by_height * 1.3) if gaps else by_height)
        for line, fs, base in zip(lines, sizes, bases):
            fs = max(4.0, min(40.0, fs))
            base -= fs * 0.2
            for x0, y0, x1, y1, t in sorted(line):
                cjk = any("\u3000" <= c <= "\u9fff" or "\uac00" <= c <= "\ud7af" for c in t)
                if cjk and cjk_font is None:
                    cjk_font = pymupdf.Font("cjk")
                font = cjk_font if cjk else latin
                size = fs
                natural = font.text_length(t, fontsize=fs)
                room = (x1 - x0) * (1.8 if len(t) <= 3 else 1.15)     # never run into the next word
                if natural > room and natural > 0:
                    size = fs * room / natural
                try:
                    tw.append((x0, base), t, font=font, fontsize=size)
                except Exception:
                    pass
        tw.write_text(pg)
    toc = [[lvl, title, p] for lvl, title, p in bookmarks if p and 1 <= p <= len(pages)]
    if toc:
        last = 0
        for e in toc:
            e[0] = max(1, min(e[0], last + 1))
            last = e[0]
        try:
            doc.set_toc(toc)
        except Exception:
            pass
    doc.subset_fonts()
    doc.save(out, garbage=3, deflate=True)
    doc.close()
