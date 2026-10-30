"""About BookTalker: art banner, credits, keyboard shortcuts."""
import os

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..packs import REPO
from ..paths import resource
from . import theme as T
from .i18n import tr
from .widgets import IconButton, PillButton, soft_shadow

VERSION = "1.0.6"
AUTHOR = "Neal Strassner"
KOFI = "https://ko-fi.com/nealstrassner"         # tips for the author (BookTalker itself stays free)
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


class LicenseDialog(QDialog):
    """BookTalker's license (AGPL-3.0) and the third-party notices, shown in the app."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QTabWidget, QTextBrowser
        self.setWindowTitle(tr("Credits & licenses"))
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
            pal.setColor(pal.ColorRole.Link, QColor(T.GOLD))     # (Markdown links take the palette's color)
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


class Notice(QDialog):
    """A short message in BookTalker's own card ('BookTalker 1.0.5 is available'): exec() is
    Accepted when the reader clicks the gold button."""

    def __init__(self, title, body, ok, cancel=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        card = _Card(None, self)
        soft_shadow(card, 60, 18, 200)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 40)
        outer.addWidget(card)
        self.setFixedWidth(600)
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
        lay.addSpacing(18)
        foot = QHBoxLayout()
        foot.addStretch()
        if cancel:
            no = PillButton(cancel)
            no.clicked.connect(self.reject)
            foot.addWidget(no)
            foot.addSpacing(8)
        yes = PillButton(ok, primary=True)
        yes.clicked.connect(self.accept)
        foot.addWidget(yes)
        lay.addLayout(foot)
        self.adjustSize()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.reject()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
        else:
            super().keyPressEvent(e)


class _UpdateSignals(QObject):
    checked = Signal(object, str)       # update.latest() plus "plan", or None; error
    progress = Signal(float)
    fetched = Signal(str, str)          # error, installer path ("" for a file-by-file update)


class AboutDialog(QDialog):
    def __init__(self, parent=None, check=False, install=False):
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
        repo = f"https://github.com/{REPO}"
        link = f"color: {T.TEXT}; text-decoration: underline;"
        web = QLabel(f"<a href='{repo}/releases' style='{link}'>{tr('What’s new')}</a>"
                     f"  ·  <a href='{repo}' style='{link}'>github.com/{REPO}</a>"
                     f"  ·  <a href='{KOFI}' style='color: {T.GOLD}; text-decoration: underline;'>"
                     f"{tr('Buy me a coffee')}</a>")
        web.setToolTip(KOFI.replace("https://", ""))
        web.setTextFormat(Qt.RichText)
        web.setOpenExternalLinks(True)
        web.setFont(T.font(12))
        web.setStyleSheet(f"color: {T.TEXT_2};")
        names.addWidget(n)
        names.addWidget(v)
        names.addWidget(by)
        names.addWidget(web)
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
        lic = PillButton(tr("Credits & licenses").replace("&", "&&"))   # (a single & marks a shortcut key)
        lic.clicked.connect(lambda: LicenseDialog(self).exec())
        row.addWidget(lic)
        self.update_btn = PillButton(tr("Check for updates"))
        self.update_btn.clicked.connect(self._update_clicked)
        row.addWidget(self.update_btn)
        from .. import update
        if update.store_app():                        # (the Microsoft Store updates it)
            self.update_btn.hide()
        row.addStretch()
        ok = PillButton(tr("Close"), primary=True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        # some languages need more room for the shortcut list: widen rather than cut
        self.setFixedSize(max(700, self.sizeHint().width()), 800)
        self._install_now = install                   # (the reader already said yes to the update)
        if check:                                     # (opened from 'a new version is out')
            QTimer.singleShot(0, self._update_clicked)

    # ---- updates (BookTalker asks GitHub's release list only; nothing downloads unasked) ---
    def _note(self, text):
        self.update_note.setText(text)
        self.update_note.setVisible(bool(text))
        from .widgets import announce
        announce(self, text)

    def _update_clicked(self):
        import threading
        from .. import update
        offer = getattr(self, "_offer", None)
        self.update_btn.setEnabled(False)
        if offer and offer["plan"]:                   # only the files that differ, then copied in
            z, changed, gone = offer["plan"]

            def fetch():
                try:
                    update.fetch(z, changed, self._sig.progress.emit)
                    if not update.install(offer["version"], update.program_dir(), gone):
                        raise RuntimeError(tr("Update canceled."))
                    self._sig.fetched.emit("", "")
                except Exception as e:  # noqa: BLE001 — shown to the reader
                    self._sig.fetched.emit(str(e) or e.__class__.__name__, "")
            threading.Thread(target=fetch, daemon=True).start()
            return
        if offer:                                     # no file list (or a development copy): the installer
            url, size = offer["installer"]
            path = update.installer_path(offer["version"])
            from .. import packs

            def progress(done, total):
                if total:
                    self._sig.progress.emit(done / total)

            def done(err):
                if not err:
                    try:
                        update.run_installer(path)    # (off the window's thread: antivirus may scan it first)
                    except OSError as e:
                        err = str(e)
                self._sig.fetched.emit(err or "", path)
            self._dl = packs.Download([(url, path, False)], progress, done)
            self._dl.start()
            return
        self.update_btn.setText(tr("Checking…"))

        def work():
            try:
                found = update.latest()
                if found and update.is_newer(found["version"], VERSION):
                    folder = update.program_dir()
                    found["plan"] = update.plan(found["files"], folder) if folder and found["files"] else None
                    if not found["plan"] and not found["installer"]:
                        found = None
                self._sig.checked.emit(found, "")
            except Exception as e:      # noqa: BLE001 — shown to the reader
                self._sig.checked.emit(None, str(e) or e.__class__.__name__)
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, found, err):
        from .. import update
        self.update_btn.setEnabled(True)
        self.update_btn.setText(tr("Check for updates"))
        if err:
            self._note(tr("Couldn't check for updates: {err}", err=err))
        elif not found or not update.is_newer(found["version"], VERSION):
            self._note(tr("BookTalker is up to date (version {v}).", v=VERSION))
        else:
            self._offer = found
            size = (sum(i.compress_size for i in found["plan"][1]) if found["plan"] else found["installer"][1])
            mb = max(1, round(size / 1e6)) if size else 0
            self.update_btn.setText(tr("Install version {v}", v=found["version"]) + (f"  ({mb} MB)" if mb else ""))
            self._note(tr("Version {v} is available. Your books, bookmarks and voices stay as they are.", v=found["version"]))
            if self._install_now:
                self._install_now = False
                self._update_clicked()

    def _progress(self, fraction):
        self.update_btn.setText(tr("Downloading the update — {pct}%", pct=round(100 * fraction)))

    def _fetched(self, err, path):
        if err:
            self.update_btn.setEnabled(True)
            self.update_btn.setText(tr("Check for updates"))
            self._offer = None
            self._note(tr("Update failed: {err}", err=err))
            return
        from PySide6.QtWidgets import QApplication
        QApplication.closeAllWindows()                # (the update replaces the program's files,
        QApplication.quit()                           #  then starts BookTalker again)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(e)
