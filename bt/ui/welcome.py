"""Welcome screen: hero art, the wordmark, open/drop, and 'Continue reading' shelf."""
import os

import pymupdf
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPen,
                           QPixmap)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..paths import resource
from . import icons, theme as T
from .i18n import tr
from .widgets import PillButton


def thumbnail(path, page, cache_dir, key):
    """Small render of the page the reader stopped on (cached)."""
    out = os.path.join(cache_dir, f"{key}_{page}.png")
    if not os.path.exists(out):
        try:
            d = pymupdf.open(path)
            pg = d[min(page, d.page_count - 1)]
            z = 300 / pg.rect.height
            pg.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False).save(out)
        except Exception:
            return None
    return QImage(out)


class BookCard(QWidget):
    """A book on the shelf: page thumbnail, title, progress; a small × (on hover) takes it off the shelf."""
    open_requested = Signal(str)
    remove_requested = Signal(str)

    W, H, TH = 176, 300, 210

    def __init__(self, entry, image, parent=None):
        super().__init__(parent)
        self.entry, self.image = entry, image
        self.hover = False
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(entry["path"])
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.TabFocus)
        title = entry.get("title") or os.path.basename(entry["path"])
        where = tr("Page {page} of {pages}", page=entry.get("page", 0) + 1, pages=entry["pages"]) if entry.get("pages") else ""
        self.setAccessibleName(title + (f", {where}" if where else ""))
        self.setAccessibleDescription(tr("Enter opens it, Delete takes it off this list"))
        self.over_x = False

    def _x_rect(self):
        return QRectF(self.W - 30, 12, 18, 18)

    def mouseMoveEvent(self, e):
        over = self._x_rect().adjusted(-3, -3, 3, 3).contains(e.position())
        if over != self.over_x:
            self.over_x = over
            self.setToolTip(tr("Remove from this list") if over else self.entry["path"])
            self.update()

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = self.over_x = False
        self.update()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.open_requested.emit(self.entry["path"])
        elif e.key() == Qt.Key_Delete:
            self.remove_requested.emit(self.entry["path"])
        else:
            super().keyPressEvent(e)

    def focusInEvent(self, e):
        self.hover = True
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.hover = False
        self.update()
        super().focusOutEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._x_rect().adjusted(-3, -3, 3, 3).contains(e.position()):
                self.remove_requested.emit(self.entry["path"])
            else:
                self.open_requested.emit(self.entry["path"])

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        lift = -4 if self.hover else 0
        card = QRectF(6, 6 + lift, self.W - 12, self.H - 12)
        p.setPen(QPen(QColor(255, 255, 255, 40 if self.hover else 18), 1))
        p.setBrush(QColor(28, 34, 46, 235) if self.hover else QColor(22, 27, 37, 220))
        p.drawRoundedRect(card, 14, 14)
        # page thumbnail, centred, with a thin shadow
        th = QRectF(card.left() + 14, card.top() + 14, card.width() - 28, self.TH - 28)
        if self.image is not None and not self.image.isNull():
            img = self.image
            s = min(th.width() / img.width(), th.height() / img.height())
            w, h = img.width() * s, img.height() * s
            r = QRectF(th.center().x() - w / 2, th.top() + (th.height() - h) / 2, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 110))
            p.drawRoundedRect(r.translated(0, 4), 3, 3)
            p.drawImage(r, img)
        # title (two lines max) and progress
        p.setPen(QColor(T.TEXT))
        p.setFont(T.font(13, QFont.DemiBold))
        fm = QFontMetrics(p.font())
        title = self.entry.get("title") or os.path.basename(self.entry["path"])
        lines, cur = [], ""
        for word in title.split():
            trial = (cur + " " + word).strip()
            if fm.horizontalAdvance(trial) <= card.width() - 28 or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
        if len(lines) > 2:
            lines = [lines[0], fm.elidedText(" ".join(lines[1:]), Qt.ElideRight, int(card.width() - 28))]
        y = card.top() + self.TH - 4
        for ln in lines:
            p.drawText(QPointF(card.left() + 14, y), ln)
            y += 18
        page, pages = self.entry.get("page", 0) + 1, max(1, self.entry.get("pages", 1))
        p.setFont(T.font(12))
        p.setPen(QColor(T.TEXT_2))
        p.drawText(QPointF(card.left() + 14, card.bottom() - 26), tr("Page {page} of {pages}", page=page, pages=pages))
        bar = QRectF(card.left() + 14, card.bottom() - 16, card.width() - 28, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 25))
        p.drawRoundedRect(bar, 1.5, 1.5)
        p.setBrush(QColor(T.GOLD))
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * page / pages, 3), 1.5, 1.5)
        if self.hover:                                   # small, quiet remove button
            x = self._x_rect().translated(0, lift)
            p.setBrush(QColor(11, 14, 20, 200) if not self.over_x else QColor(T.INK_3))
            p.setPen(QPen(QColor(255, 255, 255, 60 if self.over_x else 30), 1))
            p.drawEllipse(x)
            p.setPen(QPen(QColor(T.TEXT if self.over_x else T.TEXT_2), 1.4, Qt.SolidLine, Qt.RoundCap))
            c, d = x.center(), 3.6
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))


class Welcome(QWidget):
    open_clicked = Signal()
    about_clicked = Signal()
    book_chosen = Signal(str)
    book_removed = Signal(str)
    voices_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        hero = resource("art", "hero.png")
        self.hero = QPixmap(hero) if os.path.exists(hero) else None
        self.logo = QPixmap(resource("art", "logo_256.png"))

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        brand = QHBoxLayout()
        brand.setSpacing(12)
        mark = QLabel()
        if not self.logo.isNull():
            mark.setPixmap(self.logo.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(mark)
        self.eyebrow = QLabel()
        self.eyebrow.setFont(T.font(12, QFont.DemiBold, T.DISPLAY, 2.2))
        self.eyebrow.setStyleSheet(f"color: {T.GOLD};")
        brand.addWidget(self.eyebrow)
        brand.addStretch()
        self.corner = QHBoxLayout()          # interface-language picker goes here
        brand.addLayout(self.corner)
        col.addLayout(brand)
        col.addSpacing(22)
        title = QLabel("BookTalker")
        title.setFont(T.font(72, QFont.DemiBold, T.DISPLAY, -1.5))
        col.addWidget(title)
        col.addSpacing(6)
        self.tag = QLabel()
        self.tag.setFont(T.font(20, QFont.Light))
        self.tag.setStyleSheet(f"color: {T.TEXT_2};")
        col.addWidget(self.tag)
        col.addSpacing(34)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.b_open = PillButton("", "open", primary=True)
        self.b_open.clicked.connect(self.open_clicked)
        self.b_voices = PillButton("", "globe")
        self.b_voices.clicked.connect(self.voices_clicked)
        self.b_about = PillButton("", "info")
        self.b_about.clicked.connect(self.about_clicked)
        row.addWidget(self.b_open)
        row.addWidget(self.b_voices)
        row.addWidget(self.b_about)
        row.addStretch()
        col.addLayout(row)
        col.addSpacing(16)
        self.hint = QLabel()
        self.hint.setFont(T.font(13))
        col.addWidget(self.hint)

        self.shelf_title = QLabel()
        self.shelf_title.setFont(T.font(12, QFont.DemiBold, T.DISPLAY, 2.2))
        self.shelf_title.setStyleSheet(f"color: {T.TEXT_3};")
        self.shelf = QHBoxLayout()
        self.shelf.setSpacing(10)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(84, 70, 60, 46)
        outer.addStretch(3)
        outer.addLayout(col)
        outer.addStretch(2)
        outer.addWidget(self.shelf_title)
        outer.addSpacing(10)
        outer.addLayout(self.shelf)
        self.retranslate()

    def add_corner_widget(self, w):
        self.corner.addWidget(w)

    def retranslate(self):
        self.eyebrow.setText(tr("READ ALONG · ANY LANGUAGE · OFFLINE").replace(" ", "  "))
        self.tag.setText(tr("Your books, read aloud — every word lit up\nthe moment it is spoken."))
        self.b_open.setText(tr("Open a book"))
        self.b_voices.setText(tr("Voices"))
        self.b_about.setText(tr("About"))
        self.hint.setText(f'<span style="color:{T.TEXT_3}">'
                          + tr("PDF · EPUB · Word · PowerPoint · text · scans — drop one anywhere on this window.")
                          + "<br>" + tr("Any book can be read to you translated — into English, Spanish and more.")
                          + "</span>")
        self.shelf_title.setText(tr("CONTINUE READING").replace(" ", "  "))

    def set_recents(self, entries, thumb_dir):
        while self.shelf.count():
            it = self.shelf.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        shown = 0
        for e in entries:
            if shown == 5 or not os.path.exists(e["path"]):
                continue
            card = BookCard(e, thumbnail(e["path"], e.get("page", 0), thumb_dir, e["id"]))
            card.open_requested.connect(self.book_chosen)
            card.remove_requested.connect(self.book_removed)
            self.shelf.addWidget(card)
            shown += 1
        self.shelf.addStretch()
        self.shelf_title.setVisible(shown > 0)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(T.INK_0))
        if self.hero and not self.hero.isNull():
            # cover-fit, anchored right so the art sits behind empty space
            s = max(self.width() / self.hero.width(), self.height() / self.hero.height())
            w, h = self.hero.width() * s, self.hero.height() * s
            p.drawPixmap(QRectF(self.width() - w, (self.height() - h) / 2, w, h), self.hero,
                         QRectF(self.hero.rect()))
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0.0, QColor(11, 14, 20, 250))
        g.setColorAt(0.38, QColor(11, 14, 20, 215))
        g.setColorAt(0.75, QColor(11, 14, 20, 40))
        g.setColorAt(1.0, QColor(11, 14, 20, 10))
        p.fillRect(self.rect(), g)
        b = QLinearGradient(0, self.height() * 0.55, 0, self.height())
        b.setColorAt(0, QColor(11, 14, 20, 0))
        b.setColorAt(1, QColor(11, 14, 20, 245))
        p.fillRect(self.rect(), b)
