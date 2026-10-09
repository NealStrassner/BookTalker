"""Comic pages: every word is read (balloons sit inside the pictures), grouped into balloons,
in comic reading order: panel rows top to bottom, panels left to right in a row, and inside a
panel the balloons from the top down (side by side: left first). Japanese manga runs the other
way: panels and balloons right to left, and the vertical text columns right to left.

Panels are the large picture boxes the layout model finds. Balloons come from the page image:
the light paper inside one inked outline is one connected patch, so lines on the same patch are
one balloon and lines split by ink are not. Text printed straight on the art (no outline) is
grouped by how close its lines sit.

Comic pages are recognised by the file they came from (comic archives) or by the page itself
(a scanned PDF): vertical Japanese text, or most of the text sitting inside big pictures.
"""
import re

PANEL_LABELS = {"Picture", "Figure"}
MIN_PANEL = 0.03                  # a panel covers at least this share of the page
CJK = re.compile(r"[　-ヿ㐀-䶿一-鿿豈-﫿가-힯＀-￯]")
KANA = re.compile(r"[぀-ヿ]")


def _rect(ws):
    return min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws)


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _gap(a, b):
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return (dx * dx + dy * dy) ** 0.5


def _is_vertical(ws):
    """A column of vertical Japanese/Chinese text."""
    r = _rect(ws)
    return (r[3] - r[1]) > 1.5 * (r[2] - r[0]) and any(CJK.search(w[4]) for w in ws)


def _lines(words):
    """word tuples -> text lines (OCR's own lines), each in reading order."""
    lines = {}
    for w in words:
        lines.setdefault((w[5], w[6]), []).append(w)
    out = []
    for ws in lines.values():
        out.append(sorted(ws, key=lambda w: w[1] if _is_vertical(ws) else w[0]))
    return out


def looks_like(page, boxes, words):
    """A scanned page that reads like a comic: vertical Japanese text (manga), or most of the
    words inside big pictures (balloons in panels)."""
    words = [w for w in words if w[4].strip()]
    if not words:
        return False
    lines = _lines(words)
    cjk_lines = [ws for ws in lines if any(CJK.search(w[4]) for w in ws)]
    if len(cjk_lines) >= 2 and sum(_is_vertical(ws) for ws in cjk_lines) >= 0.5 * len(cjk_lines):
        return True
    area = page.rect.width * page.rect.height
    panels = [b for b in boxes if b[4] in PANEL_LABELS and (b[2] - b[0]) * (b[3] - b[1]) >= MIN_PANEL * area]
    if len(panels) < 2:
        return False
    inside = sum(1 for w in words if any(p[0] <= (w[0] + w[2]) / 2 <= p[2] and p[1] <= (w[1] + w[3]) / 2 <= p[3]
                                         for p in panels))
    return inside >= 0.3 * len(words)


def _patches(page):
    """-> (label image, pixels per point, which patches are open page): connected patches of
    light paper on the page."""
    import cv2
    import numpy as np
    import pymupdf
    zoom = 1500 / max(page.rect.width, page.rect.height)
    pm = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width)
    n, labels, stats, _ = cv2.connectedComponentsWithStats((gray > 170).astype(np.uint8), connectivity=4)
    open_area = 0.2 * gray.size                 # the page's open paper/art, not inside an outline
    big = stats[:, cv2.CC_STAT_AREA] > open_area
    return labels, zoom, big


def _patch_of(line_box, patches):
    """The paper patch a text line sits on (None: open page or art, no outline around it)."""
    import numpy as np
    labels, zoom, big = patches
    x0, y0, x1, y1 = (int(round(v * zoom)) for v in line_box)
    sub = labels[max(0, y0):max(0, y1) + 1, max(0, x0):max(0, x1) + 1].ravel()
    sub = sub[sub > 0]
    if not sub.size:
        return None
    k = int(np.bincount(sub).argmax())
    return None if big[k] else k


def _near(a, b, vertical):
    """Two text lines without an outline around them: the same block of text?"""
    if vertical:                                   # columns side by side
        a, b = (a[1], a[0], a[3], a[2]), (b[1], b[0], b[3], b[2])
    h = min(a[3] - a[1], b[3] - b[1])
    gap = max(a[1], b[1]) - min(a[3], b[3])
    side = min(a[2], b[2]) - max(a[0], b[0])
    along = max(a[0], b[0]) - min(a[2], b[2])
    same_block = gap < 0.5 * h and side > 0.25 * min(a[2] - a[0], b[2] - b[0])
    split_line = gap < -0.5 * h and along < 1.5 * h          # one text line OCR'd in two pieces
    return same_block or split_line


def _balloons(words, patches=None, rtl=False):
    """words -> lists of words, one per balloon, each in reading order."""
    lines = _lines(words)
    boxes = [_rect(ws) for ws in lines]
    vert = [_is_vertical(ws) for ws in lines]
    parent = list(range(len(lines)))
    patch = [_patch_of(b, patches) for b in boxes] if patches is not None else [None] * len(lines)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            if patch[i] is not None or patch[j] is not None:      # inside outlines: the ink decides
                if patch[i] == patch[j]:
                    parent[find(i)] = find(j)
                continue
            if vert[i] == vert[j] and _near(a, boxes[j], vert[i]):
                parent[find(i)] = find(j)
    groups = {}
    for i, ws in enumerate(lines):
        groups.setdefault(find(i), []).append(ws)
    out = []
    for ls in groups.values():
        if sum(_is_vertical(ws) for ws in ls) * 2 > len(ls):
            ls = _columns(ls, _rect)                      # vertical text: columns right to left
        else:
            ls = _rows(ls, _rect)                         # lines top to bottom (left to right inside)
        out.append([w for ws in ls for w in ws])
    return out


_ZH = None


def _zh_words():
    """Chinese 2-character words (wordfreq's list, Simplified) + its Traditional->Simplified map."""
    global _ZH
    if _ZH is None:
        import gzip
        import msgpack
        from wordfreq import get_frequency_dict
        from wordfreq.util import data_path
        simp = msgpack.load(gzip.open(data_path("_chinese_mapping.msgpack.gz")), raw=False, strict_map_key=False)
        _ZH = ({w for w in get_frequency_dict("zh") if len(w) == 2}, simp)
    return _ZH


class _Balloon(list):
    columns = False


def _chinese_order(ws):
    """Old Chinese comics write in columns, right to left, each top to bottom, packed so tight
    that OCR reads across their tops as lines ('三王子拿了木盒來見沙皇' comes out '來盒木了拿子王三...').
    Both orders are tried; the one with more real 2-character words is kept."""
    chars = [w for w in ws if len(w[4]) == 1 and CJK.match(w[4])]
    if len(chars) < 4:
        return ws
    words, simp = _zh_words()
    score = lambda seq: sum(1 for a, b in zip(seq, seq[1:]) if (a[4] + b[4]).translate(simp) in words)
    size = sorted(w[2] - w[0] for w in chars)[len(chars) // 2]
    cols = []                                          # characters stacked under one another
    for w in sorted(ws, key=lambda w: -(w[0] + w[2]) / 2):
        cx = (w[0] + w[2]) / 2
        for col in cols:
            if abs(col[0] - cx) < 0.5 * size:
                col[1].append(w)
                break
        else:
            cols.append([cx, [w]])
    vertical = [w for _cx, col in cols for w in sorted(col, key=lambda w: w[1])]
    now, down = score(ws), score(vertical)
    if down >= now + 2 and down >= 1.3 * max(1, now):
        out = _Balloon(vertical)
        out.columns = True
        return out
    return ws


def _rows(items, rect, rtl=False):
    """Top-to-bottom bands of side-by-side items, each band left to right (right to left)."""
    rows = []
    for it in sorted(items, key=lambda it: rect(it)[1]):
        r = rect(it)
        row = rows[-1] if rows else None
        if row:
            top, bottom = row[1], row[2]
            if min(bottom, r[3]) - max(top, r[1]) > 0.5 * min(bottom - top, r[3] - r[1]):
                row[0].append(it)
                continue
        rows.append([[it], r[1], r[3]])
    side = (lambda it: -rect(it)[2]) if rtl else (lambda it: rect(it)[0])
    return [it for row in rows for it in sorted(row[0], key=side)]


def _columns(items, rect):
    """Vertical text: columns right to left, each top to bottom."""
    cols = []
    for it in sorted(items, key=lambda it: -rect(it)[2]):
        r = rect(it)
        col = cols[-1] if cols else None
        if col and min(col[2], r[2]) - max(col[1], r[0]) > 0.5 * min(col[2] - col[1], r[2] - r[0]):
            col[0].append(it)
            continue
        cols.append([[it], r[0], r[2]])
    return [it for col in cols for it in sorted(col[0], key=lambda it: rect(it)[1])]


def _xycut(items, rect, slack, rtl=False):
    """Panels in reading order: cut the page along gutters, rows first (top to bottom), then
    columns (left to right; manga right to left), and again inside each piece ('XY-cut')."""
    if len(items) <= 1:
        return list(items)
    for lo, hi in ((1, 3), (0, 2)):                              # horizontal gutters, then vertical
        items = sorted(items, key=lambda it: rect(it)[lo])
        groups, cur, end = [], [items[0]], rect(items[0])[hi]
        for it in items[1:]:
            r = rect(it)
            if r[lo] >= end - slack:
                groups.append(cur)
                cur = [it]
            else:
                cur.append(it)
            end = max(end, r[hi])
        groups.append(cur)
        if len(groups) > 1:
            if lo == 0 and rtl:
                groups.reverse()
            return [x for g in groups for x in _xycut(g, rect, slack, rtl)]
    return sorted(items, key=lambda it: (rect(it)[1], -rect(it)[2] if rtl else rect(it)[0]))


def _panel_for(r, panels):
    """The panel a balloon belongs to: the one under its middle; else the nearest one straight
    below or above its middle (below preferred); else the one it overlaps most / lies nearest."""
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    for k, p in enumerate(panels):
        if p[0] <= cx <= p[2] and p[1] <= cy <= p[3]:
            return k
    column = [k for k, p in enumerate(panels) if p[0] <= cx <= p[2]]
    if column:              # balloons poke out of the TOP of their panel far more than the bottom
        return min(column, key=lambda k: max(panels[k][1] - cy, 3 * (cy - panels[k][3]), 0))
    return max(range(len(panels)), key=lambda k: (_overlap(r, panels[k]), -_gap(r, panels[k])))


def _open_bands(panels, balloons, rect):
    """A splash picture the layout model didn't box: a tall stretch of the page with no panel
    but with balloons in it becomes one full-width panel."""
    if not panels:
        return []
    spans = sorted((p[1], p[3]) for p in panels)
    gaps, y = [], rect.y0
    for top, bottom in spans:
        if top > y:
            gaps.append((y, top))
        y = max(y, bottom)
    gaps.append((y, rect.y1))
    out = []
    for top, bottom in gaps:
        if bottom - top >= 0.12 * rect.height and any(top <= (_rect(ws)[1] + _rect(ws)[3]) / 2 <= bottom for ws in balloons):
            out.append((rect.x0, top, rect.x1, bottom))
    return out


def build(page, boxes, words):
    """boxes: layout regions in PDF points [(x0, y0, x1, y1, label, conf)]; words: word tuples
    (x0, y0, x1, y1, text, block, line, n). -> a page dict like layout.build_page's."""
    from .layout import split_cjk
    area = page.rect.width * page.rect.height
    panels = [b[:4] for b in boxes if b[4] in PANEL_LABELS and (b[2] - b[0]) * (b[3] - b[1]) >= MIN_PANEL * area]
    pieces = []
    for w in words:
        if w[4].strip():
            for k, (x0, y0, x1, y1, t) in enumerate(split_cjk(w)):    # one box per Chinese/Japanese character
                pieces.append((x0, y0, x1, y1, t, w[5], w[6], w[7] * 100 + k))
    text = "".join(w[4] for w in pieces)
    rtl = len(KANA.findall(text)) >= max(3, 0.05 * len(text))         # Japanese: manga reads right to left
    # vertical Chinese (Traditional comics, lianhuanhua) reads right to left too: columns and panels
    tall = [w for w in words if len(w[4]) >= 2 and CJK.search(w[4])]
    if tall and sum((w[3] - w[1]) > 1.5 * (w[2] - w[0]) for w in tall) >= 0.5 * len(tall):
        rtl = True
    try:
        patches = _patches(page)
    except Exception:
        patches = None
    balloons = [ws for ws in _balloons(pieces, patches, rtl)
                if sum(c.isalpha() for w in ws for c in w[4]) >= 2]      # drop specks and lone page numbers
    if not KANA.search(text):
        balloons = [_chinese_order(ws) for ws in balloons]
        chinese = [ws for ws in balloons if sum(1 for w in ws if CJK.match(w[4])) >= 4]
        if sum(1 for ws in chinese if getattr(ws, "columns", False)) * 2 > len(chinese) > 0:
            rtl = True              # written in columns: panels run right to left too
    panels += _open_bands(panels, balloons, page.rect)
    order = _xycut(panels, lambda p: p, 0.02 * page.rect.height, rtl)
    inside = {k: [] for k in range(len(order))}
    loose = []
    for ws in balloons:
        if order:
            inside[_panel_for(_rect(ws), order)].append(ws)
        else:
            loose.append(ws)
    ordered = []
    for k in range(len(order)):
        ordered += _rows(inside[k], _rect, rtl)
    ordered += _rows(loose, _rect, rtl)
    blocks = []
    for bi, ws in enumerate(ordered):
        r = _rect(ws)
        blocks.append({"label": "Text", "top": r[1], "bottom": r[3],
                       "words": [[round(w[0], 2), round(w[1], 2), round(w[2], 2), round(w[3], 2),
                                  w[4], bi * 10000 + w[6], w[7]] for w in ws]})
    return {"blocks": blocks, "extra": [], "height": page.rect.height, "comic": True, "rtl": rtl}
