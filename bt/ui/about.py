"""About BookTalker: art banner, credits, keyboard shortcuts."""
import os

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..paths import resource
from . import theme as T
from .i18n import tr
from .widgets import IconButton, PillButton, soft_shadow

VERSION = "1.0"
AUTHOR = "Neal Strassner"
SHORTCUTS = [("Space", "Play / pause"), ("← →", "Previous / next sentence"),
             ("Shift ← →", "Back / forward 30 s"), ("[  ]", "Slower / faster"),
             ("Click a word", "Read from there"), ("PgUp PgDn", "Turn the page"),
             ("Ctrl +  Ctrl −", "Zoom"), ("Ctrl O", "Open a file"), ("Ctrl B", "Add a bookmark")]


class _Card(QWidget):
    def __init__(self, banner, parent=None):
        super().__init__(parent)
        self.banner = banner

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 20, 20)
        p.setClipPath(path)
        p.fillRect(r, QColor(T.INK_2))
        if self.banner and not self.banner.isNull():
            bh = 230
            s = max(r.width() / self.banner.width(), bh / self.banner.height())
            w, h = self.banner.width() * s, self.banner.height() * s
            p.drawPixmap(QRectF(r.width() - w, 0, w, h), self.banner, QRectF(self.banner.rect()))
            g = QLinearGradient(0, 0, 0, bh)
            g.setColorAt(0.0, QColor(24, 29, 39, 30))
            g.setColorAt(0.6, QColor(24, 29, 39, 120))
            g.setColorAt(1.0, QColor(24, 29, 39, 255))
            p.fillRect(QRectF(0, 0, r.width(), bh), g)
            p.fillRect(QRectF(0, bh, r.width(), r.height() - bh), QColor(T.INK_2))
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 20, 20)


def _gold_links(doc):
    """Markdown links come out dark blue (unreadable on the dark page): make them gold."""
    from PySide6.QtGui import QTextCursor
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isAnchor():
                cur = QTextCursor(doc)
                cur.setPosition(frag.position())
                cur.setPosition(frag.position() + frag.length(), QTextCursor.KeepAnchor)
                fmt = frag.charFormat()
                fmt.setForeground(QColor(T.GOLD))
                cur.setCharFormat(fmt)
            it += 1
        block = block.next()


class LicenceDialog(QDialog):
    """BookTalker's licence (AGPL-3.0) and the third-party notices, shown in the app."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QTabWidget, QTextBrowser
        self.setWindowTitle(tr("Credits & licences"))
        self.resize(820, 640)
        self.setStyleSheet(f"QDialog {{ background: {T.INK_2}; }} QTextBrowser {{ background: {T.INK_1}; color: {T.TEXT};"
                           f" border: 1px solid {T.LINE}; border-radius: 8px; padding: 10px; font-size: 13px; }}"
                           f" QTabBar::tab {{ background: {T.INK_3}; color: {T.TEXT_2}; padding: 7px 16px;"
                           f" border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 3px; }}"
                           f" QTabBar::tab:selected {{ color: {T.GOLD}; }} QTabWidget::pane {{ border: none; }}")
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        for title, name, md in ((tr("Credits"), "THIRD_PARTY_NOTICES.md", True), ("AGPL-3.0", "LICENSE", False)):
            view = QTextBrowser()
            view.setOpenExternalLinks(True)
            pal = view.palette()
            pal.setColor(pal.ColorRole.Link, QColor(T.GOLD))     # (Markdown links take the palette's colour)
            view.setPalette(pal)
            try:
                text = open(resource(name), encoding="utf-8").read()
            except OSError:
                text = name + " is missing."
            if md:
                view.setMarkdown(text)
                _gold_links(view.document())
            else:
                view.setPlainText(text)
            tabs.addTab(view, title)
        lay.addWidget(tabs)
        row = QHBoxLayout()
        row.addStretch()
        ok = PillButton(tr("Close"), primary=True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)


class _UpdateSignals(QObject):
    checked = Signal(object, str)       # (version, url, bytes) or None, error
    progress = Signal(float)
    fetched = Signal(str, str)          # error, installer path


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sig = _UpdateSignals(self)
        self._sig.checked.connect(self._checked)
        self._sig.progress.connect(self._progress)
        self._sig.fetched.connect(self._fetched)
        self._offer = None
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        banner = resource("art", "about.png")
        if not os.path.exists(banner):
            banner = resource("art", "hero.png")
        card = _Card(QPixmap(banner) if os.path.exists(banner) else None, self)
        soft_shadow(card, 60, 18, 200)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 40)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(40, 18, 40, 30)
        top = QHBoxLayout()
        top.addStretch()
        close = IconButton("close", tr("Close  (Esc)"), 36, 18)
        close.clicked.connect(self.accept)
        top.addWidget(close)
        lay.addLayout(top)
        lay.addSpacing(92)
        head = QHBoxLayout()
        head.setSpacing(16)
        logo = QLabel()
        pm = QPixmap(resource("art", "logo_256.png"))
        if not pm.isNull():
            logo.setPixmap(pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        n = QLabel("BookTalker")
        n.setFont(T.font(34, QFont.DemiBold, T.DISPLAY, -0.5))
        v = QLabel(tr("Version {v}  ·  Runs entirely on this computer", v=VERSION))
        v.setFont(T.font(13))
        v.setStyleSheet(f"color: {T.TEXT_2};")
        by = QLabel(tr("Made by {name}  ·  Free for everyone", name=AUTHOR))
        by.setFont(T.font(13, QFont.DemiBold))
        by.setStyleSheet(f"color: {T.GOLD};")
        names.addWidget(n)
        names.addWidget(v)
        names.addWidget(by)
        head.addLayout(names)
        head.addStretch()
        lay.addLayout(head)
        lay.addSpacing(18)
        body = QLabel(tr("ABOUT_BODY"))
        body.setWordWrap(True)
        body.setFont(T.font(14))
        body.setStyleSheet(f"color: {T.TEXT_2}; line-height: 140%;")
        lay.addWidget(body)
        lay.addSpacing(20)

        sec = QLabel(tr("KEYBOARD"))
        sec.setFont(T.font(11, QFont.DemiBold, T.DISPLAY, 2.0))
        sec.setStyleSheet(f"color: {T.GOLD};")
        lay.addWidget(sec)
        lay.addSpacing(8)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(7)
        for i, (k, what) in enumerate(SHORTCUTS):
            key = QLabel(tr(k))
            key.setFont(T.font(12, QFont.DemiBold))
            key.setStyleSheet(f"background: {T.INK_3}; border: 1px solid {T.LINE}; border-radius: 6px;"
                              f" padding: 3px 8px; color: {T.TEXT};")
            lab = QLabel(tr(what))
            lab.setFont(T.font(13))
            lab.setStyleSheet(f"color: {T.TEXT_2};")
            grid.addWidget(key, i // 2, (i % 2) * 2, Qt.AlignLeft)
            grid.addWidget(lab, i // 2, (i % 2) * 2 + 1, Qt.AlignLeft)
        lay.addLayout(grid)
        lay.addStretch()
        cred = QLabel(tr("CREDITS"))
        cred.setWordWrap(True)
        cred.setFont(T.font(12))
        cred.setStyleSheet(f"color: {T.TEXT_3};")
        lay.addWidget(cred)
        lay.addSpacing(14)
        self.update_note = QLabel("")
        self.update_note.setWordWrap(True)
        self.update_note.setFont(T.font(12))
        self.update_note.setStyleSheet(f"color: {T.GOLD};")
        self.update_note.hide()
        lay.addWidget(self.update_note)
        lay.addSpacing(6)
        row = QHBoxLayout()
        lic = PillButton(tr("Credits & licences").replace("&", "&&"))   # (a single & marks a shortcut key)
        lic.clicked.connect(lambda: LicenceDialog(self).exec())
        row.addWidget(lic)
        self.update_btn = PillButton(tr("Check for updates"))
        self.update_btn.clicked.connect(self._update_clicked)
        row.addWidget(self.update_btn)
        row.addStretch()
        ok = PillButton(tr("Close"), primary=True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        # some languages need more room for the shortcut list: widen rather than cut
        self.setFixedSize(max(700, self.sizeHint().width()), 800)

    # ---- updates (only when asked: BookTalker never goes online by itself) ----------------
    def _note(self, text):
        self.update_note.setText(text)
        self.update_note.setVisible(bool(text))
        from .widgets import announce
        announce(self, text)

    def _update_clicked(self):
        import threading
        from .. import update
        if getattr(self, "_offer", None):             # 'Install version X': fetch it, then run it
            version, url, size = self._offer
            path = update.installer_path(version)
            self.update_btn.setEnabled(False)
            from .. import packs

            def progress(done, total):
                if total:
                    self._sig.progress.emit(done / total)
            self._dl = packs.Download([(url, path, False)], progress,
                                      lambda err: self._sig.fetched.emit(err or "", path))
            self._dl.start()
            return
        self.update_btn.setEnabled(False)
        self.update_btn.setText(tr("Checking…"))

        def work():
            try:
                self._sig.checked.emit(update.latest(), "")
            except Exception as e:      # noqa: BLE001 — shown to the reader
                self._sig.checked.emit(None, str(e) or e.__class__.__name__)
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, found, err):
        from .. import update
        self.update_btn.setEnabled(True)
        self.update_btn.setText(tr("Check for updates"))
        if err:
            self._note(tr("Couldn't check for updates: {err}", err=err))
        elif not found or not update.is_newer(found[0], VERSION):
            self._note(tr("BookTalker is up to date (version {v}).", v=VERSION))
        else:
            self._offer = found
            mb = round(found[2] / 1e6) if found[2] else 0
            self.update_btn.setText(tr("Install version {v}", v=found[0]) + (f"  ({mb} MB)" if mb else ""))
            self._note(tr("Version {v} is available. Your books, bookmarks and voices stay as they are.", v=found[0]))

    def _progress(self, fraction):
        self.update_btn.setText(tr("Downloading the update — {pct}%", pct=round(100 * fraction)))

    def _fetched(self, err, path):
        from .. import update
        if err:
            self.update_btn.setEnabled(True)
            self.update_btn.setText(tr("Check for updates"))
            self._offer = None
            self._note(tr("Update failed: {err}", err=err))
            return
        update.run_installer(path)
        from PySide6.QtWidgets import QApplication
        QApplication.quit()                           # (the installer replaces the program's files)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(e)
