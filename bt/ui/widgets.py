"""Custom-painted widgets: page canvas, buttons, scrubber, floating bars, toast."""
import pymupdf
from PIL import Image, ImageDraw, ImageFilter
from PySide6.QtCore import (Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize,
                            Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen, QRadialGradient)
from PySide6.QtWidgets import (QComboBox, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QSizePolicy, QToolButton, QWidget)

from . import icons, theme as T
from .i18n import tr


def soft_shadow(widget, blur=36, dy=10, alpha=150):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)


# ---------------------------------------------------------------- buttons
class IconButton(QToolButton):
    """Flat round-cornered icon button; gold when checked."""

    def __init__(self, name, tip, size=40, icon_size=20, checkable=False, parent=None):
        super().__init__(parent)
        self.name = name
        self.setIcon(icons.icon(name, T.TEXT_2, icon_size, active_color=T.GOLD))
        self.setIconSize(QSize(icon_size, icon_size))
        self.setFixedSize(size, size)
        self.setCheckable(checkable)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)          # Tab reaches it; a click doesn't take focus (Space stays Play)
        r = size // 2 - 4
        self.setStyleSheet(f"""
            QToolButton {{ border: none; border-radius: {r}px; background: transparent; }}
            QToolButton:hover {{ background: {T.INK_3}; }}
            QToolButton:pressed {{ background: {T.LINE}; }}
            QToolButton:checked {{ background: rgba(242,179,61,0.13); }}
            QToolButton:focus {{ border: 2px solid {T.GOLD}; }}
        """)

    def enterEvent(self, e):
        if not self.isChecked():
            self.setIcon(icons.icon(self.name, T.TEXT, self.iconSize().width(), active_color=T.GOLD))
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setIcon(icons.icon(self.name, T.TEXT_2, self.iconSize().width(), active_color=T.GOLD))
        super().leaveEvent(e)


class PillButton(QToolButton):
    """Text button. primary=True -> gold fill."""

    def __init__(self, text, icon_name=None, primary=False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if icon_name else Qt.ToolButtonTextOnly)
        fg = T.ON_GOLD if primary else T.TEXT
        if icon_name:
            self.setIcon(icons.icon(icon_name, fg, 18))
            self.setIconSize(QSize(18, 18))
        self.setFont(T.font(14, QFont.DemiBold))
        if primary:
            css = f"""QToolButton {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {T.GOLD_HI}, stop:1 {T.GOLD});
                        color: {T.ON_GOLD}; border: none; border-radius: 22px; padding: 0 24px; }}
                      QToolButton:hover {{ background: {T.GOLD_HI}; }}
                      QToolButton:pressed {{ background: {T.GOLD_LO}; }}"""
        else:
            css = f"""QToolButton {{ background: rgba(255,255,255,0.06); color: {T.TEXT};
                        border: 1px solid rgba(255,255,255,0.12); border-radius: 22px; padding: 0 22px; }}
                      QToolButton:hover {{ background: rgba(255,255,255,0.11); }}"""
        self.setStyleSheet(css + f" QToolButton:focus {{ border: 2px solid {T.GOLD}; }}")
        self.setFixedHeight(44)


class PageBox(QComboBox):
    """Editable page-number box with a small painted chevron, so it reads as a list."""

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(T.TEXT_2), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cx, cy = self.width() - 12, self.height() / 2 + 1
        p.drawPolyline([QPointF(cx - 3.5, cy - 2), QPointF(cx, cy + 1.5), QPointF(cx + 3.5, cy - 2)])


class Spinner(QWidget):
    """Small spinning gold ring: something is still being worked on."""

    def __init__(self, size=14, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._turn)

    def _turn(self):
        self.angle = (self.angle + 12) % 360
        self.update()

    def setVisible(self, on):
        super().setVisible(on)
        (self.timer.start(30) if on else self.timer.stop())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setPen(QPen(QColor(255, 255, 255, 40), 2))
        p.drawEllipse(r)
        p.setPen(QPen(QColor(T.GOLD), 2, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, int(-self.angle * 16), 100 * 16)


class PlayButton(QToolButton):
    """The hero control: a gold disc with a soft glow (a real button, so screen readers and the
    keyboard know it)."""

    def __init__(self, size=58, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.TabFocus)
        self.d = size
        self.setFixedSize(size + 24, size + 24)
        self.playing = False
        self.hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Play / Pause  (Space)")
        self._icons = {k: icons.pixmap(k, T.ON_GOLD, 26) for k in ("play", "pause")}

    def set_playing(self, on):
        if on != self.playing:
            self.playing = on
            self.update()

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.hasFocus():
            p.setPen(QPen(QColor(T.GOLD), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self.rect().adjusted(3, 3, -3, -3))
        c = QPointF(self.width() / 2, self.height() / 2)
        r = self.d / 2
        glow = QRadialGradient(c, r + 12)
        a = 120 if (self.hover or self.playing) else 70
        glow.setColorAt(0.65, QColor(242, 179, 61, a))
        glow.setColorAt(1.0, QColor(242, 179, 61, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, r + 12, r + 12)
        g = QLinearGradient(0, c.y() - r, 0, c.y() + r)
        g.setColorAt(0, QColor(T.GOLD_HI if self.hover else "#FFC24F"))
        g.setColorAt(1, QColor(T.GOLD if self.hover else T.GOLD_LO))
        p.setBrush(g)
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, r - 0.5, r - 0.5)
        pm = self._icons["pause" if self.playing else "play"]
        w = pm.width() / pm.devicePixelRatio()
        dx = 0 if self.playing else 2       # optical centring of the triangle
        p.drawPixmap(QPointF(c.x() - w / 2 + dx, c.y() - w / 2), pm)


# ---------------------------------------------------------------- scrubber
class Scrubber(QWidget):
    """Whole-book position bar: read position (gold), prepared pages (soft), drag to jump."""
    seek = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(140)
        self.setFixedHeight(28)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.pages, self.page, self.prepared = 1, 0, set()
        self.hover_x = None
        self.dragging = False

    def set_state(self, pages, page, prepared):
        if (pages, page, len(prepared)) != (self.pages, self.page, len(self.prepared)):
            self.pages, self.page, self.prepared = max(1, pages), page, set(prepared)
            self.update()

    def _track(self):
        return QRectF(8, self.height() / 2 - 2, self.width() - 16, 4)

    def _page_at(self, x):
        t = self._track()
        f = min(max((x - t.left()) / t.width(), 0), 1)
        return min(self.pages - 1, int(f * self.pages))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._track()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(t, 2, 2)
        # prepared pages as soft segments
        if self.prepared and self.pages > 1:
            p.setBrush(QColor(255, 255, 255, 46))
            w = t.width() / self.pages
            run = None
            for q in sorted(self.prepared) + [None]:
                if run and (q is None or q != run[1] + 1):
                    p.drawRoundedRect(QRectF(t.left() + run[0] * w, t.top(), (run[1] - run[0] + 1) * w, t.height()), 2, 2)
                    run = None
                if q is not None:
                    run = [q, q] if run is None else [run[0], q]
        x = t.left() + t.width() * (self.page + 0.5) / self.pages
        g = QLinearGradient(t.left(), 0, x, 0)
        g.setColorAt(0, QColor(T.GOLD_LO))
        g.setColorAt(1, QColor(T.GOLD_HI))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(t.left(), t.top(), x - t.left(), t.height()), 2, 2)
        hot = self.hover_x is not None or self.dragging
        p.setBrush(QColor(T.GOLD_HI))
        p.setPen(QPen(QColor(T.INK_1), 2))
        rad = 7 if hot else 5.5
        p.drawEllipse(QPointF(x, t.center().y()), rad, rad)
        if self.hover_x is not None and not self.dragging:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 90))
            p.drawEllipse(QPointF(self.hover_x, t.center().y()), 3, 3)

    def mousePressEvent(self, e):
        self.dragging = True
        self.page = self._page_at(e.position().x())
        self.update()

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self.dragging:
            self.page = self._page_at(x)
        else:
            self.hover_x = x
        self.setToolTip(tr("Page {n}", n=self._page_at(x) + 1))
        self.update()

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.seek.emit(self._page_at(e.position().x()))

    def leaveEvent(self, e):
        self.hover_x = None
        self.update()


# ---------------------------------------------------------------- page canvas
def _shadow_image(w, h, blur=22, spread=6):
    pad = blur * 3
    im = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    ImageDraw.Draw(im).rectangle([pad - spread, pad - spread + 8, pad + w + spread, pad + h + spread + 8], fill=150)
    im = im.filter(ImageFilter.GaussianBlur(blur))
    rgba = Image.new("RGBA", im.size, (0, 0, 0, 0))
    rgba.putalpha(im)
    qi = QImage(rgba.tobytes(), rgba.width, rgba.height, QImage.Format_RGBA8888).copy()
    return qi, pad


class PageCanvas(QWidget):
    """One PDF page floating on the dark canvas, with the read-along highlight."""
    clicked = Signal(float, float)
    MARGIN = 40
    BOTTOM = 140        # room to scroll the last lines above the floating transport bar

    def __init__(self):
        super().__init__()
        self.img = None
        self.shadow = None
        self.zoom = 1.0
        self.sentence_bars, self.word_boxes = [], []
        self.marks, self.current_mark = [], ()          # search matches on this page; the current one
        self.setCursor(Qt.IBeamCursor)

    def show_page(self, page, zoom):
        dpr = self.devicePixelRatioF()
        pm = page.get_pixmap(matrix=pymupdf.Matrix(zoom * dpr, zoom * dpr), alpha=False)
        img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
        img.setDevicePixelRatio(dpr)
        self.img, self.zoom = img, zoom
        w, h = round(pm.width / dpr), round(pm.height / dpr)
        if self.shadow is None or self.shadow[2] != (w, h):
            qi, pad = _shadow_image(w, h)
            self.shadow = (qi, pad, (w, h))
        self.setFixedSize(w + 2 * self.MARGIN, h + self.MARGIN + self.BOTTOM)
        self.update()

    def page_rect(self):
        w, h = self.shadow[2]
        return QRectF(self.MARGIN, self.MARGIN, w, h)

    def set_highlight(self, sentence_bars, word_boxes):
        if (sentence_bars, word_boxes) != (self.sentence_bars, self.word_boxes):
            self.sentence_bars, self.word_boxes = sentence_bars, word_boxes
            self.update()

    def set_marks(self, marks, current=()):
        if (marks, current) != (self.marks, self.current_mark):
            self.marks, self.current_mark = marks, current
            self.update()

    def screen_rect(self, r, pad=1.5):
        x0, y0, x1, y1 = r
        z, m = self.zoom, self.MARGIN
        return QRectF(m + (x0 - pad) * z, m + (y0 - pad) * z, (x1 - x0 + 2 * pad) * z, (y1 - y0 + 2 * pad) * z)

    def paintEvent(self, _e):
        if self.img is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        qi, pad, _ = self.shadow
        p.drawImage(QPointF(self.MARGIN - pad, self.MARGIN - pad), qi)
        pr = self.page_rect()
        p.drawImage(pr.topLeft(), self.img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_Multiply)   # highlighter: print stays dark
        p.setPen(Qt.NoPen)
        p.setBrush(T.SENTENCE_WASH)
        for r in self.sentence_bars:
            p.drawRoundedRect(self.screen_rect(r, 2.5), 3, 3)
        dpr = self.img.devicePixelRatio()
        for r in self.word_boxes:
            box = self.screen_rect(r, 2)
            src = box.translated(-self.MARGIN, -self.MARGIN)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.drawImage(box, self.img, QRectF(src.x() * dpr, src.y() * dpr, src.width() * dpr, src.height() * dpr))
            p.setCompositionMode(QPainter.CompositionMode_Multiply)
            p.setBrush(T.WORD_MARK)
            p.drawRoundedRect(box, 3, 3)
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        for r in self.marks:
            p.setBrush(QColor(120, 185, 255) if r in self.current_mark else QColor(196, 222, 255))
            p.drawRoundedRect(self.screen_rect(r, 2), 3, 3)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(40, 110, 230), 1.6))
        for r in self.current_mark:
            p.drawRoundedRect(self.screen_rect(r, 3), 4, 4)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.img is not None:
            pos = e.position()
            self.clicked.emit((pos.x() - self.MARGIN) / self.zoom, (pos.y() - self.MARGIN) / self.zoom)


class Canvas(QWidget):
    """Backdrop behind the page: ink with a faint warm glow from the top."""

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.INK_0))
        g = QRadialGradient(QPointF(self.width() / 2, -self.height() * 0.15), max(self.width(), self.height()) * 0.9)
        g.setColorAt(0, QColor(40, 48, 66, 255))
        g.setColorAt(1, QColor(11, 14, 20, 0))
        p.fillRect(self.rect(), g)


# ---------------------------------------------------------------- floating bar + toast
class FloatingBar(QWidget):
    """Rounded translucent pill that floats over the canvas."""

    def __init__(self, parent=None, radius=22):
        super().__init__(parent)
        self.radius = radius
        self.setAttribute(Qt.WA_StyledBackground, False)
        soft_shadow(self, 40, 12, 170)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(30, 36, 48))
        g.setColorAt(1, QColor(20, 24, 33))
        p.setBrush(g)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawRoundedRect(r, self.radius, self.radius)


class Divider(QWidget):
    def __init__(self, parent=None, h=28):
        super().__init__(parent)
        self.setFixedSize(17, h)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.drawLine(8, 4, 8, self.height() - 4)


class _Fade:
    """A fade the widget paints itself (QPainter.setOpacity) — QGraphicsOpacityEffect
    rendered overlays see-through in testing."""

    def __init__(self, widget, duration=320):
        from PySide6.QtCore import QVariantAnimation
        self.w = widget
        self._value = 0.0
        self.anim = QVariantAnimation(widget)
        self.anim.setDuration(duration)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(0.0)
        self.anim.valueChanged.connect(self._set)
        self.anim.finished.connect(lambda: self._value < 0.05 and widget.hide())

    def _set(self, v):
        self._value = float(v)
        self.w.update()

    def opacity(self):
        return self._value

    def fade_to(self, to):
        self.anim.stop()
        self.anim.setStartValue(self._value)
        self.anim.setEndValue(float(to))
        self.anim.start()


class LoadingCard(QWidget):
    """'Preparing your book' — live checklist + animated progress, shown on a first open
    while models load and the first pages are read."""

    W, H_BASE, ROW = 440, 168, 34

    def __init__(self, parent):
        super().__init__(parent)
        self.title = "Preparing your book"
        self.subtitle = ""
        self.steps = []                 # [(label, state, detail)] state: done | active | todo
        self.progress = 0.0
        self.shown_progress = 0.0
        self.phase = 0.0
        self.eff = _Fade(self)          # painted fade (no QGraphicsEffect: renders identically everywhere)
        self.anim = self.eff.anim
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)
        self.hide()

    def set_state(self, subtitle, steps, progress):
        self.subtitle, self.steps = subtitle, steps
        self.progress = max(0.0, min(1.0, progress))
        self.update()

    def card_rect(self):
        h = self.H_BASE + self.ROW * len(self.steps)
        return QRectF((self.width() - self.W) / 2, max(20, (self.height() - 120 - h) / 2), self.W, h)

    def appear(self):
        if not self.isVisible() or self.anim.endValue() == 0:
            self.show()
            self.raise_()
            self.timer.start(16)
            self._fade(1)

    def vanish(self):
        if self.isVisible() and self.anim.endValue() != 0:
            self._fade(0)

    def _fade(self, to):
        self.eff.fade_to(to)

    def _step(self):
        if not self.isVisible():
            self.timer.stop()
            return
        self.phase = (self.phase + 0.012) % 1.0
        self.shown_progress += (self.progress - self.shown_progress) * 0.08   # glide, never jump
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.eff.opacity())
        p.fillRect(self.rect(), QColor(8, 10, 15, 170))          # veil over the page
        card = self.card_rect()
        p.translate(card.topLeft())
        r = QRectF(0, 0, card.width(), card.height()).adjusted(1, 1, -1, -1)
        for i in range(8, 0, -1):                                 # soft shadow
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 10))
            p.drawRoundedRect(r.adjusted(-i, -i + 6, i, i + 6), 22 + i, 22 + i)
        g = QLinearGradient(0, 0, 0, card.height())
        g.setColorAt(0, QColor(31, 37, 50))
        g.setColorAt(1, QColor(21, 25, 34))
        p.setBrush(g)
        p.setPen(QPen(QColor(255, 255, 255, 24), 1))
        p.drawRoundedRect(r, 22, 22)
        x = 32
        p.setPen(QColor(T.GOLD))
        p.setFont(T.font(11, QFont.DemiBold, T.DISPLAY, 2.0))
        p.drawText(QPointF(x, 42), tr("ONE MOMENT"))
        p.setPen(QColor(T.TEXT))
        p.setFont(T.font(21, QFont.DemiBold, T.DISPLAY))
        p.drawText(QPointF(x, 72), tr(self.title))
        p.setPen(QColor(T.TEXT_2))
        p.setFont(T.font(13))
        fm = p.fontMetrics()
        p.drawText(QPointF(x, 96), fm.elidedText(self.subtitle, Qt.ElideRight, self.W - 2 * x))
        y = 128
        for label, state, detail in self.steps:
            c = QPointF(x + 9, y)
            if state == "done":
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(T.GOLD))
                p.drawEllipse(c, 9, 9)
                p.setPen(QPen(QColor(T.ON_GOLD), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                path = QPainterPath(QPointF(c.x() - 4, c.y()))
                path.lineTo(c.x() - 1, c.y() + 3.2)
                path.lineTo(c.x() + 4.5, c.y() - 3.5)
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            elif state == "active":
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 30), 2.4))
                p.drawEllipse(c, 8, 8)
                p.setPen(QPen(QColor(T.GOLD_HI), 2.4, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(QRectF(c.x() - 8, c.y() - 8, 16, 16), int(-self.phase * 360 * 16 * 3), 100 * 16)
            else:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 40), 1.6))
                p.drawEllipse(c, 8, 8)
            p.setPen(QColor(T.TEXT if state != "todo" else T.TEXT_3))
            p.setFont(T.font(14, QFont.Medium if state == "active" else QFont.Normal))
            p.drawText(QPointF(x + 30, y + 5), label)
            if detail:
                p.setPen(QColor(T.TEXT_3 if state != "active" else T.GOLD))
                p.setFont(T.font(12))
                w = p.fontMetrics().horizontalAdvance(detail)
                p.drawText(QPointF(self.W - x - w, y + 5), detail)
            y += self.ROW
        bar = QRectF(x, card.height() - 38, self.W - 2 * x, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(bar, 3, 3)
        fill = QRectF(bar.left(), bar.top(), max(6.0, bar.width() * self.shown_progress), bar.height())
        gg = QLinearGradient(fill.left(), 0, fill.right(), 0)
        gg.setColorAt(0, QColor(T.GOLD_LO))
        gg.setColorAt(1, QColor(T.GOLD_HI))
        p.setBrush(gg)
        p.drawRoundedRect(fill, 3, 3)
        # moving sheen so the bar never looks frozen
        sx = fill.left() + (fill.width() + 80) * self.phase - 40
        sheen = QLinearGradient(sx - 40, 0, sx + 40, 0)
        sheen.setColorAt(0, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.5, QColor(255, 255, 255, 110))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(sheen)
        p.setClipRect(fill)
        p.drawRoundedRect(fill, 3, 3)


def announce(widget, text):
    """Have a screen reader (Narrator, NVDA, JAWS) say this, without moving the reader's focus."""
    try:
        from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(widget, text))
    except Exception:
        pass


class Toast(QLabel):
    """Small status pill near the top of the canvas; fades in/out (painted fade)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFont(T.font(13, QFont.Medium))
        self.setContentsMargins(16, 6, 16, 6)
        self.eff = _Fade(self, 260)
        self.anim = self.eff.anim
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(lambda: self._fade(0))
        self.current = None

    def show_message(self, text, sticky=False, ms=2600):
        if text == self.current and self.eff.opacity() > 0.5:
            if not sticky:
                self.hide_timer.start(ms)
            return
        self.current = text
        self.setText(text)
        announce(self, text)
        self.adjustSize()
        self.parent().layout_overlays()
        self.show()
        self.raise_()
        self._fade(1)
        if sticky:
            self.hide_timer.stop()
        else:
            self.hide_timer.start(ms)

    def clear(self):
        if self.current is not None:
            self.current = None
            self._fade(0)

    def _fade(self, to):
        self.eff.fade_to(to)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.eff.opacity())
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(24, 29, 39))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(QColor(T.TEXT))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignCenter, self.text())
