"""RAR archives (comic books: .cbr), read in-house: RAR 4 (the RAR 2.9/3.x 'LZ' method) and RAR 5
(WinRAR 5 and later, with its DELTA/x86/ARM filters). Every unpacked file is checked against its
stored CRC32. Passworded archives are refused; the rarely used RAR 4 PPMd text mode and VM filters
are reported as unsupported for that file.

The RAR 5 decoder and the RAR 3 filters follow libarchive (BSD-2-Clause, Tim Kientzle,
Grzegorz Antoniak and contributors): see THIRD_PARTY_NOTICES.md.
"""
import struct
import zlib

NC, DC, LDC, RC, BC = 299, 60, 17, 28, 20
LDECODE = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224]
LBITS = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5]
SDDECODE = [0, 4, 8, 16, 32, 64, 128, 192]
SDBITS = [2, 2, 3, 4, 5, 6, 6, 6]
DDECODE, DBITS = [], []
_dist = 0
for _bits, _count in enumerate([4, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 14, 0, 12]):
    for _ in range(_count):
        DDECODE.append(_dist)
        DBITS.append(_bits)
        _dist += 1 << _bits


class Unsupported(Exception):
    pass


class _Bits:
    def __init__(self, data):
        self.d = data + b"\x00" * 8
        self.pos = 0                                       # in bits

    def get16(self):
        p = self.pos >> 3
        v = (self.d[p] << 16) | (self.d[p + 1] << 8) | self.d[p + 2]
        return (v >> (8 - (self.pos & 7))) & 0xFFFF

    def add(self, n):
        self.pos += n

    def align(self):
        self.pos = (self.pos + 7) & ~7


class _Table:
    def __init__(self, lengths):
        count = [0] * 16
        for l in lengths:
            count[l & 15] += 1
        count[0] = 0
        self.dlen = [0] * 16
        self.dpos = [0] * 16
        tmp = [0] * 16
        n = 0
        for i in range(1, 16):
            n = 2 * (n + count[i])
            m = min(n << (15 - i), 0xFFFF)
            self.dlen[i] = m
            self.dpos[i] = self.dpos[i - 1] + count[i - 1]
            tmp[i] = self.dpos[i]
        self.num = [0] * len(lengths)
        for i, l in enumerate(lengths):
            if l:
                self.num[tmp[l & 15]] = i
                tmp[l & 15] += 1
        self.size = len(lengths)

    def decode(self, bits):
        f = bits.get16() & 0xFFFE
        b = 15
        for i in range(1, 16):
            if f < self.dlen[i]:
                b = i
                break
        bits.add(b)
        n = self.dpos[b] + ((f - self.dlen[b - 1]) >> (16 - b))
        if n >= self.size:
            n = 0
        return self.num[n]


class _MemBits:
    """MSB-first bit reader over a filter's parameter bytes (RAR VM numbers)."""

    def __init__(self, data):
        self.d, self.pos = data, 0

    def bits(self, n):
        v = 0
        for _ in range(n):
            byte = self.pos >> 3
            bit = (self.d[byte] >> (7 - (self.pos & 7))) & 1 if byte < len(self.d) else 0
            v = (v << 1) | bit
            self.pos += 1
        return v

    def number(self):
        kind = self.bits(2)
        if kind == 0:
            return self.bits(4)
        if kind == 1:
            v = self.bits(8)
            return v if v >= 16 else (0xFFFFFF00 | (v << 4) | self.bits(4))
        return self.bits(16) if kind == 2 else self.bits(32)


# the standard RAR 3 filters, known by their program's fingerprint (crc32 | length << 32)
FILTER_DELTA, FILTER_E8, FILTER_E8E9, FILTER_RGB, FILTER_AUDIO = (
    0x1D0E06077D, 0x35AD576887, 0x393CD7E57E, 0x951C2C5DC8, 0xD8BC85E701)


def _run_filter29(fp, data, regs, pos):
    n = len(data)
    if fp == FILTER_DELTA:
        ch = regs[0]
        if not 0 < ch <= 128:
            raise ValueError("bad delta filter")
        out, s = bytearray(n), 0
        for c in range(ch):
            last = 0
            for i in range(c, n, ch):
                last = (last - data[s]) & 0xFF
                out[i] = last
                s += 1
        return out
    if fp in (FILTER_E8, FILTER_E8E9):
        out, size, i = bytearray(data), 0x1000000, 0
        while i <= n - 5:
            if out[i] == 0xE8 or (fp == FILTER_E8E9 and out[i] == 0xE9):
                cur = (pos + i + 1) & 0xFFFFFFFF
                addr = struct.unpack_from("<i", out, i + 1)[0]
                if addr < 0 and cur >= ((~addr + 1) & 0xFFFFFFFF):
                    struct.pack_into("<I", out, i + 1, (addr + size) & 0xFFFFFFFF)
                elif 0 <= addr < size:
                    struct.pack_into("<I", out, i + 1, (addr - cur) & 0xFFFFFFFF)
                i += 4
            i += 1
        return out
    if fp == FILTER_RGB:
        stride, offset = regs[0], regs[1]
        if stride > n or n < 3 or offset > 2:
            raise ValueError("bad rgb filter")
        out, s = bytearray(n), 0
        for c in range(3):
            byte = 0
            for j in range(c, n, 3):
                pi = j - stride                         # the pixel above
                if pi >= 0:
                    a, b = out[pi + 3] if pi + 3 < n else 0, out[pi]
                    d1, d2, d3 = abs(a - b), abs(byte - b), abs(a - b + byte - b)
                    if d1 > d2 or d1 > d3:
                        byte = a if d2 <= d3 else b
                byte = (byte - data[s]) & 0xFF
                s += 1
                out[j] = byte
        for i in range(offset, n - 2, 3):
            out[i] = (out[i] + out[i + 1]) & 0xFF
            out[i + 2] = (out[i + 2] + out[i + 1]) & 0xFF
        return out
    if fp == FILTER_AUDIO:
        ch = regs[0]
        if not 0 < ch <= 128:
            raise ValueError("bad audio filter")
        out, s = bytearray(n), 0
        sb = lambda v: v - 256 if v > 127 else v
        for c in range(ch):
            lastbyte = lastdelta = count = 0
            delta, weight, error = [0, 0, 0], [0, 0, 0], [0] * 7
            for j in range(c, n, ch):
                d = sb(data[s])
                s += 1
                delta[2], delta[1], delta[0] = delta[1], lastdelta - delta[0], lastdelta
                pred = ((8 * lastbyte + weight[0] * delta[0] + weight[1] * delta[1] + weight[2] * delta[2]) >> 3) & 0xFF
                byte = (pred - d) & 0xFF
                pe = d * 8
                error[0] += abs(pe)
                error[1] += abs(pe - delta[0]); error[2] += abs(pe + delta[0])
                error[3] += abs(pe - delta[1]); error[4] += abs(pe + delta[1])
                error[5] += abs(pe - delta[2]); error[6] += abs(pe + delta[2])
                lastdelta = sb((byte - lastbyte) & 0xFF)
                out[j] = lastbyte = byte
                if not (count & 0x1F):
                    k = min(range(7), key=lambda q: (error[q], q))
                    error = [0] * 7
                    if k:
                        w, up = (k - 1) // 2, k % 2 == 0
                        if up and weight[w] < 16:
                            weight[w] += 1
                        elif not up and weight[w] >= -16:
                            weight[w] -= 1
                count += 1
        return out
    raise Unsupported("RAR VM filter")


class Unpack29:
    """RAR 2.9/3.x LZ decoder; keeps its state between files of a solid archive."""

    def __init__(self, window=0x400000):
        self.window = bytearray(window)
        self.mask = window - 1
        self.reset()

    def reset(self):
        self.old = [0, 0, 0, 0]
        self.last_len = 0
        self.ptr = 0
        self.old_table = [0] * (NC + DC + LDC + RC)
        self.tables = False
        self.prev_low = 0
        self.low_rep = 0
        self.progs = []                 # filter programs seen: [fingerprint, usage, old length]
        self.last_filter = 0
        self.filters = []               # (fingerprint, start, length, registers) for this file

    def _byte(self, b):
        v = b.get16() >> 8
        b.add(8)
        return v

    def _read_filter(self, b, out_len):
        """Symbol 257: a filter for a block of the output (libarchive read_filter/parse_filter)."""
        flags = self._byte(b)
        length = (flags & 7) + 1
        if length == 7:
            length = self._byte(b) + 7
        elif length == 8:
            length = (self._byte(b) << 8) | self._byte(b)
        br = _MemBits(bytes(self._byte(b) for _ in range(length)))
        if flags & 0x80:
            num = br.number()
            if num == 0:
                self.filters, self.progs = [], []
            else:
                num -= 1
            if num > len(self.progs):
                raise ValueError("bad RAR filter number")
            self.last_filter = num
        else:
            num = self.last_filter
        prog = self.progs[num] if num < len(self.progs) else None
        if prog:
            prog[1] += 1
        start = br.number() + out_len + (258 if flags & 0x40 else 0)
        blen = br.number() if flags & 0x20 else (prog[2] if prog else 0)
        regs = [0] * 8
        regs[4] = blen
        if flags & 0x10:
            mask = br.bits(7)
            for i in range(7):
                if mask & (1 << i):
                    regs[i] = br.number()
        if prog is None:
            n = br.number()
            if not 0 < n <= 0x10000:
                raise ValueError("bad RAR filter code")
            code = bytes(br.bits(8) for _ in range(n))
            x = 0
            for c in code[1:]:
                x ^= c
            if x != code[0]:
                raise ValueError("bad RAR filter code")
            prog = [zlib.crc32(code) | (n << 32), 0, 0]
            self.progs.append(prog)
        prog[2] = blen
        self.filters.append((prog[0], start, blen, regs))

    def _read_tables(self, b):
        b.align()
        f = b.get16()
        if f & 0x8000:
            raise Unsupported("PPMd-compressed file")
        self.prev_low, self.low_rep = 0, 0
        if not f & 0x4000:
            self.old_table = [0] * (NC + DC + LDC + RC)
        b.add(2)
        bl = [0] * BC
        i = 0
        while i < BC:
            ln = b.get16() >> 12
            b.add(4)
            if ln == 15:
                zeros = b.get16() >> 12
                b.add(4)
                if zeros == 0:
                    bl[i] = 15
                else:
                    for _ in range(zeros + 2):
                        if i < BC:
                            bl[i] = 0
                            i += 1
                    i -= 1
            else:
                bl[i] = ln
            i += 1
        bd = _Table(bl)
        size = NC + DC + LDC + RC
        table = [0] * size
        i = 0
        while i < size:
            n = bd.decode(b)
            if n < 16:
                table[i] = (n + self.old_table[i]) & 15
                i += 1
            elif n < 18:
                if n == 16:
                    cnt = (b.get16() >> 13) + 3
                    b.add(3)
                else:
                    cnt = (b.get16() >> 9) + 11
                    b.add(7)
                if i == 0:
                    raise ValueError("bad RAR tables")
                for _ in range(cnt):
                    if i < size:
                        table[i] = table[i - 1]
                        i += 1
            else:
                if n == 18:
                    cnt = (b.get16() >> 13) + 3
                    b.add(3)
                else:
                    cnt = (b.get16() >> 9) + 11
                    b.add(7)
                for _ in range(cnt):
                    if i < size:
                        table[i] = 0
                        i += 1
        self.LD = _Table(table[:NC])
        self.DD = _Table(table[NC:NC + DC])
        self.LDD = _Table(table[NC + DC:NC + DC + LDC])
        self.RD = _Table(table[NC + DC + LDC:])
        self.old_table = table
        self.tables = True

    def _copy(self, length, dist, out):
        w, m = self.window, self.mask
        src = (self.ptr - dist) & m
        for _ in range(length):
            c = w[src]
            w[self.ptr] = c
            out.append(c)
            self.ptr = (self.ptr + 1) & m
            src = (src + 1) & m

    def unpack(self, data, size, solid):
        if not solid:
            self.reset()
        b = _Bits(data)
        if not self.tables:
            self._read_tables(b)
        out = bytearray()
        w, m = self.window, self.mask
        while len(out) < size:
            n = self.LD.decode(b)
            if n < 256:
                w[self.ptr] = n
                self.ptr = (self.ptr + 1) & m
                out.append(n)
                continue
            if n >= 271:
                n -= 271
                length = LDECODE[n] + 3
                bits = LBITS[n]
                if bits:
                    length += b.get16() >> (16 - bits)
                    b.add(bits)
                dn = self.DD.decode(b)
                dist = DDECODE[dn] + 1
                bits = DBITS[dn]
                if bits:
                    if dn > 9:
                        if bits > 4:
                            dist += (b.get16() >> (20 - bits)) << 4
                            b.add(bits - 4)
                        if self.low_rep > 0:
                            self.low_rep -= 1
                            dist += self.prev_low
                        else:
                            low = self.LDD.decode(b)
                            if low == 16:
                                self.low_rep = 15
                                dist += self.prev_low
                            else:
                                dist += low
                                self.prev_low = low
                    else:
                        dist += b.get16() >> (16 - bits)
                        b.add(bits)
                if dist >= 0x2000:
                    length += 1
                    if dist >= 0x40000:
                        length += 1
                self.old = [dist] + self.old[:3]
                self.last_len = length
                self._copy(length, dist, out)
            elif n == 256:                                 # end of block: maybe new tables / end of file
                f = b.get16()
                if f & 0x8000:
                    new_table, new_file = True, False
                    b.add(1)
                else:
                    new_file, new_table = True, bool(f & 0x4000)
                    b.add(2)
                self.tables = not new_table
                if new_file:
                    break
                if new_table:
                    self._read_tables(b)
            elif n == 257:
                self._read_filter(b, len(out))
            elif n == 258:
                if self.last_len:
                    self._copy(self.last_len, self.old[0], out)
            elif n < 263:
                k = n - 259
                dist = self.old[k]
                self.old = [dist] + self.old[:k] + self.old[k + 1:]
                ln = self.RD.decode(b)
                length = LDECODE[ln] + 2
                bits = LBITS[ln]
                if bits:
                    length += b.get16() >> (16 - bits)
                    b.add(bits)
                self.last_len = length
                self._copy(length, dist, out)
            else:                                          # 263..270: short distances
                k = n - 263
                dist = SDDECODE[k] + 1
                bits = SDBITS[k]
                if bits:
                    dist += b.get16() >> (16 - bits)
                    b.add(bits)
                self.old = [dist] + self.old[:3]
                self.last_len = 2
                self._copy(2, dist, out)
        for fp, start, blen, regs in self.filters:      # filtered blocks (x86 code, images, audio)
            if start + blen > len(out):
                raise ValueError("RAR filter past the end of the file")
            out[start:start + blen] = _run_filter29(fp, bytes(out[start:start + blen]), regs, start)
        self.filters = []
        return bytes(out[:size])


# ---- RAR 5 (WinRAR 5 and later). Follows the format as read by libarchive's
# archive_read_support_format_rar5.c (BSD licence, Grzegorz Antoniak).

NC5, DC5, LDC5, RC5 = 306, 64, 16, 44


class _Bits5:
    def __init__(self, data):
        self.d = data + b"\x00" * 8
        self.pos = 0

    def get16(self):
        p = self.pos >> 3
        v = (self.d[p] << 16) | (self.d[p + 1] << 8) | self.d[p + 2]
        return (v >> (8 - (self.pos & 7))) & 0xFFFF

    def bits(self, n):                                     # n <= 16
        v = self.get16() >> (16 - n)
        self.pos += n
        return v

    def bits32(self, n):                                   # n <= 32
        p = self.pos >> 3
        v = int.from_bytes(self.d[p:p + 5], "big")
        v = (v >> (8 - (self.pos & 7))) & 0xFFFFFFFF
        self.pos += n
        return v >> (32 - n)


class _Table5:
    def __init__(self, lengths):
        size = len(lengths)
        self.size = size
        self.qbits = 10 if size == NC5 else 7
        lc = [0] * 16
        for l in lengths:
            lc[l & 15] += 1
        lc[0] = 0
        dlen, dpos = [0] * 16, [0] * 16
        upper = 0
        for i in range(1, 16):
            upper += lc[i]
            dlen[i] = upper << (16 - i)
            dpos[i] = dpos[i - 1] + lc[i - 1]
            upper <<= 1
        clone = dpos[:]
        num = [0] * size
        for i, l in enumerate(lengths):
            l &= 15
            if l:
                num[clone[l]] = i
                clone[l] += 1
        qn = 1 << self.qbits
        qlen, qnum = [0] * qn, [0] * qn
        cur = 1
        for code in range(qn):
            bf = code << (16 - self.qbits)
            while cur < 16 and bf >= dlen[cur]:
                cur += 1
            qlen[code] = cur
            pos = dpos[cur & 15] + ((bf - dlen[cur - 1]) >> (16 - cur))
            qnum[code] = num[pos] if cur < 16 and pos < size else 0
        self.dlen, self.dpos, self.num, self.qlen, self.qnum = dlen, dpos, num, qlen, qnum
        self.qlimit = dlen[self.qbits]

    def decode(self, b):
        f = b.get16() & 0xFFFE
        if f < self.qlimit:
            c = f >> (16 - self.qbits)
            b.pos += self.qlen[c]
            return self.qnum[c]
        nb = 15
        for i in range(self.qbits + 1, 15):
            if f < self.dlen[i]:
                nb = i
                break
        b.pos += nb
        pos = self.dpos[nb] + ((f - self.dlen[nb - 1]) >> (16 - nb))
        return self.num[pos] if pos < self.size else self.num[0]


def _length5(b, code):
    if code < 8:
        return 2 + code
    lbits = code // 4 - 1
    return 2 + ((4 | (code & 3)) << lbits) + b.bits(lbits)


class Unpack50:
    """RAR 5 LZ decoder. `hist` holds the unfiltered output of the whole solid stream."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.hist = bytearray()
        self.dist = [0, 0, 0, 0]
        self.last_len = 0
        self.tables = None

    def _read_tables(self, b):
        bl = []
        while len(bl) < 20:
            v = b.bits(4)
            if v == 15:
                z = b.bits(4)
                if z == 0:
                    bl.append(15)
                else:
                    bl.extend([0] * min(z + 2, 20 - len(bl)))
            else:
                bl.append(v)
        bd = _Table5(bl)
        size = NC5 + DC5 + LDC5 + RC5
        t = []
        while len(t) < size:
            n = bd.decode(b)
            if n < 16:
                t.append(n)
            elif n < 18:
                cnt = b.bits(3) + 3 if n == 16 else b.bits(7) + 11
                if not t:
                    raise ValueError("bad RAR 5 tables")
                t.extend([t[-1]] * min(cnt, size - len(t)))
            else:
                cnt = b.bits(3) + 3 if n == 18 else b.bits(7) + 11
                t.extend([0] * min(cnt, size - len(t)))
        a, c, e = NC5, NC5 + DC5, NC5 + DC5 + LDC5
        self.tables = (_Table5(t[:a]), _Table5(t[a:c]), _Table5(t[c:e]), _Table5(t[e:]))

    def _copy(self, length, dist):
        h = self.hist
        start = len(h) - dist
        if start < 0:
            raise ValueError("bad RAR 5 distance")
        if dist >= length:
            h += h[start:start + length]
        else:
            chunk = h[start:]
            while length > 0:
                piece = chunk[:length]
                h += piece
                length -= len(piece)
                chunk = h[start:]

    def unpack(self, data, size, solid):
        if not solid:
            self.reset()
        h = self.hist
        base = len(h)
        filters = []
        p = 0
        while p + 3 <= len(data):
            flags, _ck = data[p], data[p + 1]
            nb = ((flags >> 3) & 7) + 1
            bsize = int.from_bytes(data[p + 2:p + 2 + nb], "little")
            p += 2 + nb
            block = data[p:p + bsize]
            p += bsize
            b = _Bits5(block)
            if flags & 0x80:
                self._read_tables(b)
            if self.tables is None:
                raise ValueError("RAR 5 block without tables")
            ld, dd, ldd, rd = self.tables
            end = (len(block) - 1) * 8 + (flags & 7) + 1   # bit position where the block ends
            limit = base + size
            bd_, qlimit, qlen, qnum, qshift = b.d, ld.qlimit, ld.qlen, ld.qnum, 16 - ld.qbits
            append = h.append
            pos = b.pos
            while pos < end and len(h) < limit:
                q = pos >> 3                               # inlined literal-table lookup (the hot path)
                f = (((bd_[q] << 16) | (bd_[q + 1] << 8) | bd_[q + 2]) >> (8 - (pos & 7))) & 0xFFFE
                if f < qlimit:
                    c = f >> qshift
                    pos += qlen[c]
                    n = qnum[c]
                else:
                    b.pos = pos
                    n = ld.decode(b)
                    pos = b.pos
                if n < 256:
                    append(n)
                    continue
                b.pos = pos
                self._symbol(n, b, h, base, dd, ldd, rd, filters)
                pos = b.pos
            if flags & 0x40:                               # last block of this file
                break
        out = bytearray(h[base:base + size])
        for ftype, start, length, chans in filters:
            _filter5(out, h, base, ftype, start, length, chans)
        return bytes(out)

    def _symbol(self, n, b, h, base, dd, ldd, rd, filters):
        if n >= 262:
            length = _length5(b, n - 262)
            slot = dd.decode(b)
            if slot < 4:
                dist = 1 + slot
            else:
                dbits = slot // 2 - 1
                dist = 1 + ((2 | (slot & 1)) << dbits)
                if dbits >= 4:
                    if dbits > 4:
                        dist += b.bits32(dbits - 4) << 4
                    dist += ldd.decode(b)
                else:
                    dist += b.bits(dbits)
            if dist > 0x100:
                length += 1
                if dist > 0x2000:
                    length += 1
                    if dist > 0x40000:
                        length += 1
            self.dist = [dist] + self.dist[:3]
            self.last_len = length
            self._copy(length, dist)
        elif n == 256:                             # filter definition
            vals = []
            for _ in range(2):
                cnt = b.bits(2) + 1
                v = 0
                for i in range(cnt):
                    v += b.bits(8) << (8 * i)
                vals.append(v)
            ftype = b.bits(3)
            chans = b.bits(5) + 1 if ftype == 0 else 0
            filters.append((ftype, len(h) - base + vals[0], vals[1], chans))
        elif n == 257:
            if self.last_len:
                self._copy(self.last_len, self.dist[0])
        else:                                      # 258..261: repeat a cached distance
            k = n - 258
            dist = self.dist[k]
            self.dist = [dist] + self.dist[:k] + self.dist[k + 1:]
            length = _length5(b, rd.decode(b))
            self.last_len = length
            self._copy(length, dist)


def _filter5(out, h, base, ftype, start, length, chans):
    src = h[base + start:base + start + length]
    if ftype == 0:                                         # DELTA: channel-planar differences
        res = bytearray(length)
        s = 0
        for c in range(chans):
            prev = 0
            for dpos in range(c, length, chans):
                prev = (prev - src[s]) & 0xFF
                res[dpos] = prev
                s += 1
    elif ftype in (1, 2):                                  # E8 / E8E9: x86 call/jump addresses
        res = bytearray(src)
        fsize = 0x1000000
        i = 0
        while i < length - 4:
            c = src[i]
            i += 1
            if c == 0xE8 or (ftype == 2 and c == 0xE9):
                off = (i + start) % fsize
                addr = int.from_bytes(src[i:i + 4], "little")
                if addr & 0x80000000:
                    if not ((addr + off) & 0x80000000):
                        res[i:i + 4] = ((addr + fsize) & 0xFFFFFFFF).to_bytes(4, "little")
                elif (addr - fsize) & 0x80000000:
                    res[i:i + 4] = ((addr - off) & 0xFFFFFFFF).to_bytes(4, "little")
                i += 4
    elif ftype == 3:                                       # ARM branch-with-link addresses
        res = bytearray(src)
        for i in range(0, length - 3, 4):
            if src[i + 3] == 0xEB:
                o = int.from_bytes(src[i:i + 3], "little")
                o = (o - (i + start) // 4) & 0xFFFFFF
                res[i:i + 4] = (o | 0xEB000000).to_bytes(4, "little")
    else:
        raise Unsupported("RAR 5 filter %d" % ftype)
    out[start:start + length] = res[:len(out) - start] if start + length > len(out) else res


def _vint(d, p):
    v, s = 0, 0
    while True:
        c = d[p]
        p += 1
        v |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return v, p


def _files5(d):
    p, out = 8, []
    unpacker = None
    while p + 4 < len(d):
        p0 = p
        hsize, q = _vint(d, p + 4)
        hend = q + hsize
        htype, q = _vint(d, q)
        hflags, q = _vint(d, q)
        extra = data_size = 0
        if hflags & 1:
            extra, q = _vint(d, q)
        if hflags & 2:
            data_size, q = _vint(d, q)
        if htype == 4:
            raise ValueError("this archive is password-protected")
        if htype == 5:
            break
        if htype == 2:
            fflags, q = _vint(d, q)
            unp, q = _vint(d, q)
            _attr, q = _vint(d, q)
            if fflags & 2:
                q += 4
            crc = None
            if fflags & 4:
                crc = struct.unpack_from("<I", d, q)[0]
                q += 4
            comp, q = _vint(d, q)
            _host, q = _vint(d, q)
            nlen, q = _vint(d, q)
            name = d[q:q + nlen].decode("utf-8", "replace").replace("\\", "/")
            ex = hend - extra
            while ex < hend:                                # extra records: refuse encrypted files
                rsize, r = _vint(d, ex)
                rtype, _ = _vint(d, r)
                if rtype == 1:
                    raise ValueError("this archive is password-protected")
                ex = r + rsize
            data = d[hend:hend + data_size]
            if not fflags & 1:
                method, solid = (comp >> 7) & 7, bool(comp & 0x40)
                try:
                    if method == 0:
                        body = data[:unp]
                    else:
                        if unpacker is None:
                            unpacker = Unpack50()
                        body = unpacker.unpack(data, unp, solid)
                    if crc is None or zlib.crc32(body) == crc:
                        out.append((name, body))
                except Unsupported:
                    if unpacker:
                        unpacker.reset()
        p = hend + data_size
        if p <= p0:
            break
    return out


def files(path):
    """-> [(name, bytes)] for the files in a RAR archive that could be read, in archive order."""
    d = open(path, "rb").read()
    if d[:8] == b"Rar!\x1a\x07\x01\x00":
        return _files5(d)
    if d[:7] != b"Rar!\x1a\x07\x00":
        raise ValueError("not a RAR archive")
    p, out = 7, []
    unpacker = None
    while p + 7 <= len(d):
        _crc, htype, flags, hsize = struct.unpack_from("<HBHH", d, p)
        if hsize < 7:
            break
        add = 0
        if htype == 0x73 and flags & 0x0080:
            raise ValueError("this archive is password-protected")
        if htype == 0x74:
            pack, unp, _host, fcrc, _ftime, ver, method, nsize, _attr = struct.unpack_from("<IIBIIBBHI", d, p + 7)
            q = p + 32
            if flags & 0x100:
                hp, hu = struct.unpack_from("<II", d, q)
                pack, unp = pack | (hp << 32), unp | (hu << 32)
                q += 8
            name = d[q:q + nsize].split(b"\x00")[0].decode("utf-8", "replace").replace("\\", "/")
            data = d[p + hsize:p + hsize + pack]
            add = pack
            if flags & 0x04:
                raise ValueError("this archive is password-protected")
            is_dir = (flags & 0xE0) == 0xE0
            if not is_dir:
                if method == 0x30:
                    if zlib.crc32(data[:unp]) == fcrc:
                        out.append((name, data[:unp]))
                elif ver in (29, 36):
                    if unpacker is None:
                        unpacker = Unpack29()
                    try:
                        body = unpacker.unpack(data, unp, solid=bool(flags & 0x10))
                        if zlib.crc32(body) == fcrc:
                            out.append((name, body))
                    except Unsupported:
                        unpacker.reset()
                    except Exception:
                        unpacker.reset()
        elif flags & 0x8000:
            add = struct.unpack_from("<I", d, p + 7)[0]
        if htype == 0x7B:                                  # end of archive
            break
        p += hsize + add
    return out
