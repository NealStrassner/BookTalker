"""Choose voices (and the AI translator): tick to download, untick a downloaded voice to remove
it. Shown on first run and from 'More voices…' / 'More languages…'. Also the one-voice DownloadPrompt."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout,
                               QWidget)

from .. import packs, voices
from . import i18n, theme as T
from .about import _Card
from .i18n import tr
from .widgets import IconButton, PillButton, soft_shadow


AI = "ai"       # the AI translator's row key
FAST = "fast"   # the fast translator's row key


def _mb(key):
    return {AI: packs.AI_SIZE_MB, FAST: packs.TRANSLATOR_SIZE_MB}.get(key) or voices.size_mb(key)


def _items(key):
    return packs.ai_items() if key == AI else packs.translator_items() if key == FAST else packs.voice_items(key)


class VoiceRow(QWidget):
    """One voice: painted gold checkbox, 'Name — description (size)', a quiet note on the right."""
    toggled = Signal()

    def __init__(self, stem, have, locked, checked, text=None, parent=None):
        super().__init__(parent)
        self.stem, self.have, self.locked, self.checked = stem, have, locked, checked
        mb = _mb(stem)
        self.text = text or f"{voices.display_name(stem)}  —  {voices.describe(stem)}" + (f"  ({mb} MB)" if mb else "")
        self.note = tr("built in") if locked and stem not in (AI, FAST) else (tr("on this computer") if have else "")
        lic = voices.license(stem) if stem not in (AI, FAST) else ""
        if lic:
            self.setToolTip(tr("Voice recordings: {lic}", lic=lic))
        elif stem == FAST:
            self.setToolTip("NLLB-200 (Meta AI) · CC BY-NC 4.0")
        self.hover = False
        self.setFixedHeight(34)
        self.setCursor(Qt.ArrowCursor if locked else Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._name_for_readers()

    def matches(self, words):
        hay = (self.text + " " + self.stem + " " + i18n.AUTONYM.get(self.stem[:2], "")).lower()
        return all(w in hay for w in words)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def _name_for_readers(self):
        state = tr("built in") if self.locked else (tr("chosen") if self.checked else tr("not chosen"))
        self.setAccessibleName(f"{self.text}, {state}")

    def _toggle(self):
        if not self.locked and self.isEnabled():
            self.checked = not self.checked
            self._name_for_readers()
            self.update()
            self.toggled.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._toggle()
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
            self._toggle()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.hover and not self.locked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.INK_3))
            p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        box = QRectF(10, (self.height() - 18) / 2, 18, 18)
        dim = self.locked or not self.isEnabled()
        if self.checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.GOLD_LO if dim else T.GOLD))
            p.drawRoundedRect(box, 5, 5)
            p.setPen(QPen(QColor(T.ON_GOLD), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline([QPointF(box.left() + 4.5, box.center().y()), QPointF(box.left() + 7.8, box.bottom() - 4.8),
                            QPointF(box.right() - 4, box.top() + 5)])
        else:
            p.setPen(QPen(QColor("#46526a"), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7), 5, 5)
        p.setFont(T.font(13))
        p.setPen(QColor(T.TEXT_3 if dim and not self.checked else T.TEXT))
        right = self.width() - 12
        if self.note:
            p.save()
            p.setFont(T.font(11))
            p.setPen(QColor(T.TEXT_3))
            nw = p.fontMetrics().horizontalAdvance(self.note)
            p.drawText(QRectF(right - nw, 0, nw, self.height()), Qt.AlignVCenter, self.note)
            p.restore()
            right -= nw + 14
        p.drawText(QRectF(40, 0, right - 40, self.height()), Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.text, Qt.ElideRight, int(right - 40)))


class VoicePicker(QDialog):
    progress = Signal(float, float)
    finished_download = Signal(str)

    def __init__(self, first_run=False, priority=(), suggest=(), parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.first_run = first_run
        self.added, self.removed, self.failed_remove = [], [], []
        self._dl = None
        card = _Card(None, self)
        soft_shadow(card, 60, 18, 200)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 40)
        outer.addWidget(card)
        self.setFixedSize(820, 800)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(40, 22, 40, 28)
        top = QHBoxLayout()
        eyebrow = QLabel(tr("VOICES"))
        eyebrow.setFont(T.font(11, QFont.DemiBold, T.DISPLAY, 2.0))
        eyebrow.setStyleSheet(f"color: {T.GOLD};")
        top.addWidget(eyebrow)
        top.addStretch()
        self.close_btn = IconButton("close", tr("Close  (Esc)"), 36, 18)
        self.close_btn.clicked.connect(self._cancel)
        top.addWidget(self.close_btn)
        lay.addLayout(top)
        title = QLabel(tr("Welcome — choose your voices") if first_run else tr("Choose your voices"))
        title.setFont(T.font(28, QFont.DemiBold, T.DISPLAY, -0.3))
        lay.addWidget(title)
        lay.addSpacing(6)
        body = QLabel(tr("BookTalker comes with one English voice. Tick any others you want for the languages "
                         "you read or listen in. You can change this any time with “More voices…” or “More languages…” in the reading menu.")
                      if first_run else
                      tr("Tick a voice to download it; untick a downloaded voice to remove it. Every voice reads on "
                         "this computer, offline."))
        body.setWordWrap(True)
        body.setFont(T.font(13))
        body.setStyleSheet(f"color: {T.TEXT_2};")
        lay.addWidget(body)
        lay.addSpacing(14)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search languages or voices"))
        self.search.setFont(T.font(13))
        self.search.setFixedHeight(36)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        lay.addSpacing(10)

        # every language, the ones this person is likely to want first
        langs = voices.languages()
        first = [c for c in dict.fromkeys(priority) if c in langs]
        rest = sorted((c for c in langs if c not in first), key=lambda c: i18n.lang_label(c).lower())
        have = voices.installed()
        self.rows, self.sections = [], []
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(0)
        # translation first: two optional downloads (nothing is imposed on the reader's disk)
        head = QLabel(tr("Translation"))
        head.setFont(T.font(12, QFont.DemiBold, T.DISPLAY, 0.6))
        head.setStyleSheet(f"color: {T.GOLD}; padding: 4px 0 4px 10px;")
        col.addWidget(head)
        fast_have = packs.translator_dir() is not None
        ai_have = packs.ai_installed()
        ai_row = VoiceRow(AI, ai_have, ai_have, ai_have,
                          tr("AI translator — best quality, needs a graphics card") + f"  ({packs.AI_SIZE_MB} MB)")
        tr_rows = [ai_row]
        if not fast_have:       # (built in: only offered if it's missing, e.g. a build made without it)
            tr_rows.insert(0, VoiceRow(FAST, False, False, False,
                                       tr("Fast translator — hear books in another language") + f"  ({packs.TRANSLATOR_SIZE_MB} MB)"))
            ai_row.setToolTip(tr("Includes the fast translator, which reads while the AI starts and on computers without a graphics card."))
        for r in tr_rows:
            r.toggled.connect(self._update_summary)
            col.addWidget(r)
            self.rows.append(r)
        self.sections.append((head, tr_rows))
        for code in first + rest:
            own, local = i18n.AUTONYM.get(code, code.upper()), i18n.lang_label(code)
            head = QLabel(own if own == local else f"{own}  ·  {local}")
            head.setFont(T.font(12, QFont.DemiBold, T.DISPLAY, 0.6))
            head.setStyleSheet(f"color: {T.GOLD}; padding: 12px 0 4px 10px;")
            col.addWidget(head)
            rows = []
            for stem, _name, _desc, inst in voices.catalog(code):
                r = VoiceRow(stem, inst, voices.bundled(stem) and inst, inst or stem in suggest)
                r.toggled.connect(self._update_summary)
                col.addWidget(r)
                rows.append(r)
            self.rows += rows
            self.sections.append((head, rows))
        col.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        lay.addWidget(scroll, 1)
        lay.addSpacing(14)

        self.bar = _Progress()
        self.bar.hide()
        lay.addWidget(self.bar)
        foot = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setFont(T.font(13))
        self.summary.setStyleSheet(f"color: {T.TEXT_2};")
        foot.addWidget(self.summary, 1)
        self.secondary = PillButton(tr("Not now") if first_run else tr("Cancel"))
        self.secondary.clicked.connect(self._cancel)
        self.primary = PillButton(tr("Done"), primary=True)
        self.primary.clicked.connect(self._apply)
        foot.addWidget(self.secondary)
        foot.addSpacing(8)
        foot.addWidget(self.primary)
        lay.addLayout(foot)
        self.progress.connect(self._on_progress)
        self.finished_download.connect(self._on_done)
        self._update_summary()

    # ---- choosing ---------------------------------------------------------------
    def _plan(self):
        add = [r.stem for r in self.rows if r.checked and not r.have]
        drop = [r.stem for r in self.rows if r.have and not r.checked and not r.locked]
        return add, drop

    def _update_summary(self):
        add, drop = self._plan()
        parts = []
        if add:
            mb = sum(_mb(s) or 0 for s in add)
            if AI in add and packs.translator_dir() is None and FAST not in add:
                mb += packs.TRANSLATOR_SIZE_MB             # (the AI brings the fast translator along)
            parts.append(tr("{n} to download · {mb} MB", n=len(add), mb=mb))
        if drop:
            parts.append(tr("{n} to remove", n=len(drop)))
        self.summary.setText("   ·   ".join(parts) if parts else tr("Nothing to change"))
        self.primary.setText(tr("Download") if add else (tr("Apply") if drop else tr("Done")))

    def _filter(self, text):
        words = text.lower().split()
        for head, rows in self.sections:
            any_shown = False
            for r in rows:
                show = r.matches(words) or (words and all(w in head.text().lower() for w in words))
                r.setVisible(bool(show))
                any_shown |= bool(show)
            head.setVisible(any_shown)

    # ---- applying ---------------------------------------------------------------
    def _apply(self):
        add, drop = self._plan()
        for stem in drop:
            try:
                voices.remove(stem)
                self.removed.append(stem)
            except OSError:
                self.failed_remove.append(stem)
        if not add:
            self.accept()
            return
        items = list(dict.fromkeys(it for s in add for it in _items(s)))     # (AI and fast share the translator)
        self._adding = add
        for r in self.rows:
            r.setEnabled(False)
        self.search.setEnabled(False)
        self.primary.hide()
        self.secondary.setText(tr("Cancel download"))
        self.bar.set_fraction(0)
        self.bar.show()
        self.summary.setText(tr("Starting the download…"))
        self._dl = packs.Download(items, lambda d, t: self.progress.emit(float(d), float(t)),
                                  lambda err: self.finished_download.emit(err or ""))
        self._dl.start()

    def _on_progress(self, done, total):
        if total > 0:
            self.bar.set_fraction(done / total)
            self.summary.setText(tr("Downloading — {pct}%  ({done} of {total} MB)",
                                    pct=f"{100 * done / total:.0f}", done=f"{done / 1e6:.0f}", total=f"{total / 1e6:.0f}"))

    def _on_done(self, err):
        self._dl = None
        if not err:
            self.added = list(self._adding)
            self.accept()
            return
        self.bar.hide()
        for r in self.rows:
            r.setEnabled(True)
        self.search.setEnabled(True)
        self.primary.show()
        self.secondary.setText(tr("Not now") if self.first_run else tr("Cancel"))
        self.summary.setText(tr("Download failed: {err}", err=err) if err != "cancelled" else tr("Download cancelled"))

    def _cancel(self):
        if self._dl is not None:
            self._dl.cancelled = True
            return
        self.reject()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(e)


class _Progress(QWidget):
    """Thin gold download bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f = 0.0
        self.setFixedHeight(14)

    def set_fraction(self, f):
        self.f = max(0.0, min(1.0, f))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 4, self.width(), 5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r, 2.5, 2.5)
        if self.f > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(r.left(), r.top(), max(5.0, r.width() * self.f), r.height()), 2.5, 2.5)
            p.fillPath(path, QColor(T.GOLD))


class DownloadPrompt(QDialog):
    """A short question with one download behind it ('Read and translate in Spanish?')."""
    progress = Signal(float, float)
    finished_download = Signal(str)

    def __init__(self, title, body, line, items, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.items, self._dl = items, None
        card = _Card(None, self)
        soft_shadow(card, 60, 18, 200)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 40)
        outer.addWidget(card)
        self.setFixedWidth(680)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 26, 36, 26)
        t = QLabel(title)
        t.setFont(T.font(24, QFont.DemiBold, T.DISPLAY, -0.3))
        lay.addWidget(t)
        lay.addSpacing(8)
        b = QLabel(body)
        b.setWordWrap(True)
        b.setFont(T.font(13))
        b.setStyleSheet(f"color: {T.TEXT_2};")
        lay.addWidget(b)
        lay.addSpacing(10)
        ln = QLabel(line)
        ln.setFont(T.font(14, QFont.DemiBold))
        ln.setStyleSheet(f"background: {T.INK_3}; border: 1px solid {T.LINE}; border-radius: 10px; padding: 10px 14px;")
        lay.addWidget(ln)
        lay.addSpacing(16)
        self.bar = _Progress()
        self.bar.hide()
        lay.addWidget(self.bar)
        foot = QHBoxLayout()
        self.status = QLabel()
        self.status.setFont(T.font(13))
        self.status.setStyleSheet(f"color: {T.TEXT_2};")
        foot.addWidget(self.status, 1)
        self.secondary = PillButton(tr("Not now"))
        self.secondary.clicked.connect(self._cancel)
        self.primary = PillButton(tr("Download"), primary=True)
        self.primary.clicked.connect(self._start)
        foot.addWidget(self.secondary)
        foot.addSpacing(8)
        foot.addWidget(self.primary)
        lay.addLayout(foot)
        self.progress.connect(self._on_progress)
        self.finished_download.connect(self._on_done)
        self.adjustSize()

    def _start(self):
        self.primary.hide()
        self.secondary.setText(tr("Cancel download"))
        self.bar.set_fraction(0)
        self.bar.show()
        self.status.setText(tr("Starting the download…"))
        self._dl = packs.Download(self.items, lambda d, t: self.progress.emit(float(d), float(t)),
                                  lambda err: self.finished_download.emit(err or ""))
        self._dl.start()

    def _on_progress(self, done, total):
        if total > 0:
            self.bar.set_fraction(done / total)
            self.status.setText(tr("Downloading — {pct}%  ({done} of {total} MB)",
                                   pct=f"{100 * done / total:.0f}", done=f"{done / 1e6:.0f}", total=f"{total / 1e6:.0f}"))

    def _on_done(self, err):
        self._dl = None
        if not err:
            self.accept()
            return
        self.bar.hide()
        self.primary.show()
        self.secondary.setText(tr("Not now"))
        self.status.setText(tr("Download failed: {err}", err=err) if err != "cancelled" else tr("Download cancelled"))

    def _cancel(self):
        if self._dl is not None:
            self._dl.cancelled = True
            return
        self.reject()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(e)
