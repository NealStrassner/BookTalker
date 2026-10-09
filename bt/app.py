"""BookTalker window: the PDF page on screen, read aloud, with the spoken word highlighted."""
import ctypes
import html
import json
import os
import sys
import threading
import time

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QLineEdit, QMessageBox, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

from . import convert, packs, voices
from .book import Book
from .layout import LayoutModel, doc_id
from .paths import resource
from .llm import SmartTranslator
from .translate import LANGS, Translator
from .ui import i18n, icons, theme as T
from .ui.i18n import lang_values, tr
from .ui.about import AboutDialog
from .ui.tools import BookmarksDialog, ExportDialog
from .ui.voicepicker import DownloadPrompt, VoicePicker
from .ui.welcome import Welcome
from .ui.widgets import (Canvas, Divider, FloatingBar, IconButton, LoadingCard, PageBox, PageCanvas, PlayButton,
                         Scrubber, Spinner, Toast)

SPEEDS = (0.75, 0.9, 1.0, 1.15, 1.3, 1.5, 1.75)
TARGETS = ("en", "es", "fr", "de", "it", "pt", "ru", "zh")     # languages books can be translated into


def app_dir(*parts):
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "BookTalker", *parts)
    os.makedirs(d, exist_ok=True)
    return d


def log_exception(what):
    """Write the current exception to error.log (for problems the app recovers from)."""
    import traceback
    try:
        with open(os.path.join(app_dir(), "error.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {what}\n{traceback.format_exc()}\n")
    except OSError:
        pass


def load_settings():
    try:
        with open(os.path.join(app_dir(), "settings.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        with open(os.path.join(app_dir(), "settings.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def dark_title_bar(widget):
    """Windows 10/11: dark window frame to match the app."""
    try:
        hwnd = int(widget.winId())
        on = ctypes.c_int(1)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (new / pre-20H1)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
    except Exception:
        pass


class _EnterPresses(QObject):
    """Keyboard users: Enter presses the button that has the focus, or opens its menu.
    (Space can't: it is Play / Pause everywhere, and the window's shortcut takes it first.)"""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Return, Qt.Key_Enter):
            from PySide6.QtWidgets import QAbstractButton
            fw = QApplication.focusWidget()
            if isinstance(fw, QAbstractButton) and fw.isEnabled() and obj is fw:
                if isinstance(fw, QToolButton) and fw.menu() is not None:
                    fw.showMenu()
                else:
                    fw.click()
                return True
        return False


def _spoken_name(tip):
    """A button's name for screen readers: its tooltip without the keyboard hint in brackets."""
    import re
    return re.sub(r"\s*\([^)]*\)\s*$", "", tip).strip() or tip


def book_title(book):
    meta = (book.doc.metadata or {}).get("title", "").strip()
    name = os.path.splitext(os.path.basename(book.source))[0]
    return meta if 4 <= len(meta) <= 90 and not meta.lower().endswith((".doc", ".pdf")) else name


class Models:
    """Voices, layout model, OCR and translators — each loaded once and shared. The voice
    and the layout model start loading at launch, while the welcome screen is up."""

    def __init__(self, on_voice_ready):
        self.speaker = None                     # default English voice (ready = app can read)
        self._speakers = {}
        self.failed = {}                        # voice that wouldn't load -> the voice used instead
        self._speaker_lock = threading.Lock()
        self._voices = None                     # the voice process, started on first use
        self._layout = None
        self._layout_lock = threading.Lock()
        self._ocr = None
        self._ocr_lock = threading.Lock()
        self.translator = SmartTranslator(Translator())
        self.on_voice_ready = on_voice_ready
        threading.Thread(target=self._load_voice, daemon=True).start()
        threading.Thread(target=self.layout, daemon=True).start()

    def _load_voice(self):
        self.speaker = self.get_speaker(voices.DEFAULT_ENGLISH)
        self.on_voice_ready()

    def layout_ready(self):
        return self._layout is not None

    def ocr(self):
        with self._ocr_lock:
            if self._ocr is None:
                from .ocr import OCR
                self._ocr = OCR()
            return self._ocr

    def has_speaker(self, stem):
        return stem in self._speakers

    def get_speaker(self, stem):
        """Voice `stem`, loaded in the voice process (blocks the calling thread only)."""
        with self._speaker_lock:
            if self._voices is None:
                from .voiceproc import VoiceProcess
                self._voices = VoiceProcess()
            if stem not in self._speakers:
                from .voiceproc import VoiceProxy
                try:
                    have = voices.installed()
                    if stem not in have:
                        raise FileNotFoundError(f"voice {stem} not found; installed: {sorted(have)}")
                    self._voices.load(stem, have[stem]["path"])
                    self._speakers[stem] = VoiceProxy(self._voices, stem)
                except Exception:
                    # never leave the reader waiting on a voice: read with another one and say so
                    log_exception(f"loading voice {stem}")
                    others = [s for s in voices.for_language(stem[:2]) if s != stem]
                    alt = voices.DEFAULT_ENGLISH if voices.DEFAULT_ENGLISH in others or not others else others[0]
                    if alt == stem:
                        raise
                    self._voices.load(alt, voices.installed()[alt]["path"])
                    self._speakers[stem] = VoiceProxy(self._voices, alt)
                    self.failed[stem] = alt
            return self._speakers[stem]

    def shutdown(self):
        if self._voices is not None:
            self._voices.close()
        self.translator.shutdown()

    def layout(self):
        with self._layout_lock:
            if self._layout is None:
                self._layout = LayoutModel()
            return self._layout


class Signals(QObject):
    voice_ready = Signal()
    pages_done = Signal(object)
    converted = Signal(str, str, str)       # source, pdf, error
    convert_pages = Signal(str, int)        # source, pages made so far
    dl_progress = Signal(float, float)      # bytes done, bytes total (floats: files > 2 GB)
    dl_done = Signal(str)                   # error ("" = success)
    titles_ready = Signal(object)           # (book, target language, chapter titles translated)
    book_title_ready = Signal(object)       # (book, target language, the book's title translated)


def line_bars(rects, page):
    """Merge word boxes on the same line into one bar (sentence highlight)."""
    bars = []
    for (p, x0, y0, x1, y1) in rects:
        if p != page:
            continue
        if bars:
            bx0, by0, bx1, by1 = bars[-1]
            if abs((y0 + y1) / 2 - (by0 + by1) / 2) < (y1 - y0) * 0.5 and x0 >= bx0 - 2:
                bars[-1] = (bx0, min(by0, y0), max(bx1, x1), max(by1, y1))
                continue
        bars.append((x0, y0, x1, y1))
    return bars


class TopBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.INK_1))
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class Stage(Canvas):
    """The reading area: scrollable page plus floating transport and toast."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scroll = QScrollArea(self)
        self.scroll.setAlignment(Qt.AlignHCenter)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)   # width never jumps
        self.page = PageCanvas()
        self.scroll.setWidget(self.page)
        self.transport = FloatingBar(self, radius=26)
        # English subtitle while reading a translation
        self.subtitle = FloatingBar(self, radius=18)
        sub = QVBoxLayout(self.subtitle)
        sub.setContentsMargins(22, 12, 22, 14)
        sub.setSpacing(4)
        self.sub_text = QLabel()
        self.sub_text.setWordWrap(True)
        self.sub_text.setFont(T.font(17))
        self.sub_text.setTextFormat(Qt.RichText)
        sub.addWidget(self.sub_text)
        self.subtitle.hide()
        self.toast = Toast(self)
        self.loading = LoadingCard(self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.scroll.setGeometry(self.rect())
        self.layout_overlays()

    def layout_overlays(self):
        w = min(940, self.width() - 40)
        self.transport.setGeometry((self.width() - w) // 2, self.height() - 76 - 22, w, 76)
        # subtitle box hugs its text: height = the wrapped lines it really needs
        sw = min(940, self.width() - 40)
        text_w = sw - 44
        self.sub_text.setFixedWidth(text_w)
        text_h = self.sub_text.heightForWidth(text_w)
        self.sub_text.setFixedHeight(max(text_h, self.sub_text.fontMetrics().height()))
        self.subtitle.setFixedSize(sw, 12 + self.sub_text.height() + 14)
        self.subtitle.move((self.width() - sw) // 2, self.transport.y() - self.subtitle.height() - 12)
        self.toast.adjustSize()
        self.toast.move((self.width() - self.toast.width()) // 2, 18)
        if hasattr(self, "loading"):
            self.loading.setGeometry(self.rect())       # veil covers the page; card centred

    def show_subtitle(self, html_text):
        if self.sub_text.text() != html_text:
            self.sub_text.setText(html_text)
            self.layout_overlays()
        if not self.subtitle.isVisible():
            self.subtitle.show()
            self.subtitle.raise_()


class Main(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.setWindowTitle("BookTalker")
        self.resize(1320, 940)
        self.setMinimumSize(940, 660)
        self.setAcceptDrops(True)
        self._enter = _EnterPresses(self)              # keyboard users: Enter presses the focused button
        QApplication.instance().installEventFilter(self._enter)
        self.sig = Signals()
        self.sig.voice_ready.connect(self._voice_ready)
        self.sig.pages_done.connect(self._pages_done)
        self.sig.converted.connect(self._open_converted)
        self.sig.convert_pages.connect(lambda src, n: setattr(self, "_convert_pages", n) if src == self.converting else None)
        self.sig.dl_progress.connect(self._dl_progress)
        self.sig.dl_done.connect(self._dl_done)
        self.sig.titles_ready.connect(self._titles_ready)
        self.sig.book_title_ready.connect(self._book_title_ready)
        self._dl = None
        self.models = Models(self.sig.voice_ready.emit)
        self.settings = load_settings()
        # interface language: the user's choice, else Windows' display language
        i18n.set_language(self.settings.get("ui_lang") or i18n.system_language())
        self._tips, self._lang_buttons = [], []
        self._follow_pause_until = 0.0
        self._turn = {"dir": 0, "push": 0, "since": 0.0, "last": 0.0, "start": 0.0}   # scrolling past a page edge
        self.book = None
        self.player = None
        self.translate = False      # read the English translation instead of the original
        self.voice = voices.DEFAULT_ENGLISH
        self.converting = None
        self._saved_mode = {}
        self._mode_lang = None
        self._ready_at = None
        self.models.translator.best = self.settings.get("translate_best", True)
        self.target = self.settings.get("target_lang", "en")      # language to translate into
        self.models.translator.set_target(self.target)
        # if a recent book was being translated, warm the AI up while the welcome screen shows
        recent = self.settings.get("recents", [])[:3]
        if any(self.settings.get(r.get("id"), {}).get("translate") for r in recent):
            QTimer.singleShot(3000, self.models.translator.warm_up)
        self.page = 0
        self.zoom = None            # None = fit width
        self.follow = True
        self.shown = None
        self.last_word = None
        self.resume_key = None

        self.stack = QStackedWidget()
        self.welcome = Welcome()
        self.welcome.open_clicked.connect(self._open_dialog)
        self.welcome.about_clicked.connect(self._about)
        self.welcome.book_chosen.connect(self.open)
        self.welcome.book_removed.connect(self._remove_recent)
        self.welcome.voices_clicked.connect(lambda: self._open_voice_picker())
        self.welcome.add_corner_widget(self._ui_language_button(self.welcome))
        self.reader = QWidget()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.reader)
        self.setCentralWidget(self.stack)
        self._build_reader()
        self._shortcuts()
        self._refresh_welcome()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)
        if path:
            self.open(path)
        if not self.settings.get("voices_setup"):     # first run: pick voices to download
            QTimer.singleShot(500, lambda: self._open_voice_picker(first_run=True))

    # ---- layout -----------------------------------------------------------------
    def _build_reader(self):
        col = QVBoxLayout(self.reader)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        top = TopBar()
        row = QHBoxLayout(top)
        row.setContentsMargins(18, 0, 14, 0)
        row.setSpacing(4)
        home = QToolButton()
        home.setIcon(QIcon(QPixmap(resource("art", "logo_256.png"))))
        home.setIconSize(QSize(34, 34))
        home.setFixedSize(46, 46)
        self._tip(home, "Library")
        home.setCursor(Qt.PointingHandCursor)
        home.setStyleSheet(f"QToolButton {{ border: none; border-radius: 12px; }} QToolButton:hover {{ background: {T.INK_3}; }}"
                           f" QToolButton:focus {{ border: 2px solid {T.GOLD}; }}")
        home.clicked.connect(self._go_home)
        row.addWidget(home)
        row.addSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.setContentsMargins(0, 12, 0, 12)
        self.title_lbl = QLabel("")
        self.title_lbl.setFont(T.font(15, QFont.DemiBold))
        self.sub_lbl = QLabel("")
        self.sub_lbl.setFont(T.font(12))
        self.sub_lbl.setStyleSheet(f"color: {T.TEXT_2};")
        # pages still being prepared: a spinning ring and a bright count, so a stutter isn't a surprise
        titles.addWidget(self.title_lbl)
        titles.addWidget(self.sub_lbl)
        row.addLayout(titles, 1)
        # while pages are prepared: a spinning ring and the count; then chapters + search take its place
        self.prep_box = QWidget()
        prep = QHBoxLayout(self.prep_box)
        prep.setContentsMargins(14, 0, 14, 0)
        prep.setSpacing(10)
        self.prep_spin = Spinner(16)
        self.prep_lbl = QLabel("")
        self.prep_lbl.setFont(T.font(13, QFont.DemiBold))
        self.prep_lbl.setStyleSheet(f"color: {T.GOLD};")
        # MEASURED: while pages are prepared the voice waits ~10% of the time (both a light and a
        # heavy voice), so the reader is told
        self.prep_note = QLabel(tr("Reading may pause now and then until this is done"))
        self.prep_note.setFont(T.font(11))
        self.prep_note.setStyleSheet(f"color: {T.TEXT_3};")
        lines = QVBoxLayout()
        lines.setSpacing(0)
        lines.addWidget(self.prep_lbl)
        lines.addWidget(self.prep_note)
        prep.addWidget(self.prep_spin)
        prep.addLayout(lines)
        self.prep_box.setStyleSheet(f"QWidget {{ background: transparent; }}")
        self.prep_box.setVisible(False)
        row.addWidget(self.prep_box)
        # chapters of the book (its own contents, else headings found on the pages)
        self.chapter_box = QComboBox()
        self.chapter_box.setFont(T.font(13))
        self.chapter_box.setFixedWidth(175)
        self.chapter_box.setMaxVisibleItems(20)
        self.chapter_box.setFocusPolicy(Qt.TabFocus)
        self.chapter_box.setStyleSheet(f"""
            QComboBox {{ background: {T.INK_2}; border: 1px solid {T.LINE}; border-radius: 9px; padding: 5px 10px; color: {T.TEXT}; }}
            QComboBox:hover {{ border-color: #46526a; }} QComboBox:disabled {{ color: {T.TEXT_3}; }}
            QComboBox::drop-down {{ width: 18px; border: none; }}
            QComboBox QAbstractItemView {{ background: {T.INK_2}; border: 1px solid {T.LINE}; min-width: 360px;
                selection-background-color: {T.INK_3}; selection-color: {T.GOLD}; outline: none; }}""")
        self._tip(self.chapter_box, "Chapters")
        self.chapter_box.setPlaceholderText(tr("Chapters"))
        self.chapter_box.activated.connect(self._chapter_chosen)
        self._chapters = []
        self._title_cache = {}                      # (book, language) -> translated chapter titles
        self._book_title_tr = {}                    # (book, language) -> the book's title translated
        row.addWidget(self.chapter_box)
        row.addSpacing(8)
        # search the book (pages are searched as they get prepared)
        self.search_box = QLineEdit()
        self.search_box.setAccessibleName(tr("Search this book"))
        self.search_box.setFont(T.font(13))
        self.search_box.setFixedWidth(190)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setPlaceholderText(tr("Search this book"))
        self.search_box.addAction(icons.icon("search", T.TEXT_3, 16), QLineEdit.LeadingPosition).setText(tr("Search this book"))
        self.search_box.setStyleSheet(f"""QLineEdit {{ background: {T.INK_2}; border: 1px solid {T.LINE};
            border-radius: 9px; padding: 5px 8px; color: {T.TEXT}; }} QLineEdit:focus {{ border-color: {T.GOLD_LO}; }}""")
        self.search_box.textChanged.connect(lambda _t: self._search_timer.start(250))
        self.search_box.returnPressed.connect(lambda: self._search_step(-1 if QApplication.keyboardModifiers() & Qt.ShiftModifier else 1))
        self.search_box.installEventFilter(self)                     # Esc clears
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._run_search)
        self._results, self._result_i = [], -1
        self.search_count = QLabel("")
        self.search_count.setFont(T.font(11))
        self.search_count.setStyleSheet(f"color: {T.TEXT_2};")
        self.b_res_prev = self._tip(IconButton("nav_up", "", 30, 18), "Previous match  (Shift Enter)")
        self.b_res_prev.clicked.connect(lambda: self._search_step(-1))
        self.b_res_next = self._tip(IconButton("nav_down", "", 30, 18), "Next match  (Enter)")
        self.b_res_next.clicked.connect(lambda: self._search_step(1))
        row.addWidget(self.search_box)
        row.addSpacing(2)
        row.addWidget(self.b_res_prev)
        row.addWidget(self.b_res_next)
        row.addSpacing(2)
        row.addWidget(self.search_count)
        row.addSpacing(6)
        self.b_res_prev.setEnabled(False)
        self.b_res_next.setEnabled(False)
        b_out = self._tip(IconButton("zoom_out", ""), "Zoom out  (Ctrl −)")
        b_out.clicked.connect(lambda: self._zoom(1 / 1.15))
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setFont(T.font(12, QFont.DemiBold))
        self.zoom_lbl.setStyleSheet(f"color: {T.TEXT_2};")
        self.zoom_lbl.setFixedWidth(44)
        self.zoom_lbl.setAlignment(Qt.AlignCenter)
        b_in = self._tip(IconButton("zoom_in", ""), "Zoom in  (Ctrl +)")
        b_in.clicked.connect(lambda: self._zoom(1.15))
        b_fit = self._tip(IconButton("fit", ""), "Fit page width")
        b_fit.clicked.connect(self._fit)
        self.b_follow = self._tip(IconButton("follow", "", checkable=True), "Follow the voice — keep the spoken word in view")
        self.b_follow.setChecked(True)
        self.b_follow.clicked.connect(lambda on: self._set_follow(on))
        self.bm_btn = self._tip(IconButton("bookmark", ""), "Bookmarks  (Ctrl B adds one)")
        self.bm_menu = QMenu(self.bm_btn)
        self.bm_menu.aboutToShow.connect(self._build_bookmark_menu)
        self.bm_btn.setMenu(self.bm_menu)
        self.bm_btn.setPopupMode(QToolButton.InstantPopup)
        self.bm_btn.setStyleSheet(self.bm_btn.styleSheet() + "QToolButton::menu-indicator { image: none; }")
        b_export = self._tip(IconButton("headphones", ""), "Save as audiobook (MP3)")
        b_export.clicked.connect(self._export_dialog)
        b_open = self._tip(IconButton("open", ""), "Open a book or document  (Ctrl O)")
        b_open.clicked.connect(self._open_dialog)
        b_about = self._tip(IconButton("info", ""), "About BookTalker")
        b_about.clicked.connect(self._about)
        self.ui_lang_btn = self._ui_language_button()
        for w in (b_out, self.zoom_lbl, b_in, b_fit, Divider(), self.b_follow, self.bm_btn, b_export, Divider(),
                  b_open, b_about, self.ui_lang_btn):
            row.addWidget(w)
        col.addWidget(top)

        self.stage = Stage()
        self.stage.page.clicked.connect(self._clicked)
        self.stage.page.setAccessibleName(tr("Book page"))
        self.stage.scroll.viewport().installEventFilter(self)          # wheel: see eventFilter
        self.stage.scroll.verticalScrollBar().actionTriggered.connect(lambda _a: self._user_scrolled())
        col.addWidget(self.stage, 1)

        bar = QHBoxLayout(self.stage.transport)
        bar.setContentsMargins(14, 0, 18, 0)
        bar.setSpacing(2)
        b_prev = self._tip(IconButton("prev", "", 42, 20), "Previous sentence  (←)")
        b_prev.clicked.connect(self._prev_sentence)
        self.play_btn = self._tip(PlayButton(56), "Play / Pause  (Space)")
        self.play_btn.clicked.connect(self._toggle_play)
        b_next = self._tip(IconButton("next", "", 42, 20), "Next sentence  (→)")
        b_next.clicked.connect(self._next_sentence)
        b_back30 = self._tip(IconButton("back30", "", 42, 22), "Back 30 seconds  (Shift ←)")
        b_back30.clicked.connect(lambda: self._jump(-30))
        b_fwd30 = self._tip(IconButton("fwd30", "", 42, 22), "Forward 30 seconds  (Shift →)")
        b_fwd30.clicked.connect(lambda: self._jump(30))
        # page number: a drop-down (or type a number) to jump straight to a page
        self.page_box = PageBox()
        self.page_box.setEditable(True)
        self.page_box.setInsertPolicy(QComboBox.NoInsert)
        self.page_box.setMaxVisibleItems(16)
        self.page_box.setFont(T.font(13, QFont.DemiBold))
        self.page_box.setFixedWidth(76)
        self.page_box.setFocusPolicy(Qt.StrongFocus)
        self.page_box.lineEdit().setAlignment(Qt.AlignCenter)
        self.page_box.lineEdit().setAccessibleName(tr("Page number"))
        self.page_box.setStyleSheet(f"""
            QComboBox {{ background: {T.INK_3}; border: 1px solid {T.LINE}; border-radius: 9px; padding: 3px 4px; }}
            QComboBox:hover {{ border-color: #46526a; }}
            QComboBox::drop-down {{ width: 20px; border: none; }}
            QComboBox::down-arrow {{ image: none; width: 0; }}
            QComboBox QAbstractItemView {{ background: {T.INK_2}; border: 1px solid {T.LINE};
                selection-background-color: {T.INK_3}; selection-color: {T.GOLD}; outline: none; }}""")
        self._tip(self.page_box, "Go to page")
        self.page_box.activated.connect(lambda i: self._goto_page(i, manual=True))
        self.page_box.lineEdit().returnPressed.connect(self._page_typed)
        self.page_total = QLabel("/ —")
        self.page_total.setFont(T.font(13, QFont.DemiBold))
        self.page_total.setStyleSheet(f"color: {T.TEXT_2};")
        self.scrubber = Scrubber()
        self.scrubber.setAccessibleName(tr("Position in the book"))
        self.scrubber.seek.connect(lambda p: self._goto_page(p, manual=True))
        self.speed_btn = QToolButton()
        self.speed_btn.setText("1.0×")
        self.speed_btn.setIcon(icons.icon("speed", T.TEXT_2, 18))
        self.speed_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.speed_btn.setFont(T.font(13, QFont.DemiBold))
        self.speed_btn.setCursor(Qt.PointingHandCursor)
        self.speed_btn.setFocusPolicy(Qt.TabFocus)
        self.speed_btn.setPopupMode(QToolButton.InstantPopup)
        self._tip(self.speed_btn, "Reading speed")
        self.speed_btn.setStyleSheet(f"""QToolButton {{ border: none; border-radius: 14px; padding: 6px 10px; color: {T.TEXT}; }}
            QToolButton:hover {{ background: {T.INK_3}; }} QToolButton::menu-indicator {{ image: none; }}
            QToolButton:focus {{ border: 2px solid {T.GOLD}; }}""")
        menu = QMenu(self.speed_btn)
        self.speed_actions = []
        for s in SPEEDS:
            a = menu.addAction(f"{s:g}×")
            a.setCheckable(True)
            a.setChecked(s == 1.0)
            a.triggered.connect(lambda _c=False, v=s: self._set_speed(v))
            self.speed_actions.append((s, a))
        self.speed_btn.setMenu(menu)
        self.lang_btn = QToolButton()
        self.lang_btn.setText("EN")
        self.lang_btn.setIcon(icons.icon("globe", T.TEXT_2, 18))
        self.lang_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.lang_btn.setFont(T.font(13, QFont.DemiBold))
        self.lang_btn.setCursor(Qt.PointingHandCursor)
        self.lang_btn.setFocusPolicy(Qt.TabFocus)
        self.lang_btn.setPopupMode(QToolButton.InstantPopup)
        self._tip(self.lang_btn, "Language and voice")
        self.lang_btn.setStyleSheet(self.speed_btn.styleSheet())
        self.lang_menu = QMenu(self.lang_btn)
        self.lang_menu.aboutToShow.connect(self._build_lang_menu)
        self.lang_btn.setMenu(self.lang_menu)
        for w in (b_back30, b_prev, self.play_btn, b_next, b_fwd30):
            bar.addWidget(w)
        bar.addWidget(Divider(h=34))
        bar.addSpacing(6)
        bar.addWidget(self.page_box)
        bar.addSpacing(4)
        bar.addWidget(self.page_total)
        b_pprev = self._tip(IconButton("page_prev", "", 34, 18), "Previous page  (PgUp)")
        b_pprev.clicked.connect(lambda: self._goto_page(self.page - 1, manual=True))
        b_pnext = self._tip(IconButton("page_next", "", 34, 18), "Next page  (PgDn)")
        b_pnext.clicked.connect(lambda: self._goto_page(self.page + 1, manual=True))
        bar.addSpacing(6)
        bar.addWidget(b_pprev)
        bar.addWidget(self.scrubber, 1)
        bar.addWidget(b_pnext)
        bar.addWidget(Divider(h=34))
        self.sleep_btn = QToolButton()
        self.sleep_btn.setIcon(icons.icon("moon", T.TEXT_2, 18))
        self.sleep_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.sleep_btn.setFont(T.font(13, QFont.DemiBold))
        self.sleep_btn.setCursor(Qt.PointingHandCursor)
        self.sleep_btn.setFocusPolicy(Qt.TabFocus)
        self.sleep_btn.setPopupMode(QToolButton.InstantPopup)
        self.sleep_btn.setStyleSheet(self.speed_btn.styleSheet())
        self._tip(self.sleep_btn, "Sleep timer")
        self.sleep_menu = QMenu(self.sleep_btn)
        self.sleep_menu.aboutToShow.connect(self._build_sleep_menu)
        self.sleep_btn.setMenu(self.sleep_menu)
        self._sleep = None                  # {"kind": "time", "left": s} | {"kind": "chapter", "index": i}
        self._sleep_last = time.time()
        bar.addWidget(self.lang_btn)
        bar.addWidget(self.speed_btn)
        bar.addWidget(self.sleep_btn)
        self.speed = 1.0

    # ---- interface language ------------------------------------------------------------
    def _tip(self, widget, key):
        """Set a translatable tooltip and remember it for a live language switch."""
        self._tips.append((widget, key))
        widget.setToolTip(tr(key))
        widget.setAccessibleName(_spoken_name(tr(key)))     # what a screen reader announces
        return widget

    def _ui_language_button(self, parent=None):
        """Globe + the current interface language, named in itself; the menu lists every
        language in its own name so anyone can find theirs."""
        b = QToolButton(parent)
        b.setIcon(icons.icon("globe", T.TEXT_2, 18))
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setFont(T.font(13, QFont.DemiBold))
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.TabFocus)
        b.setPopupMode(QToolButton.InstantPopup)
        b.setStyleSheet(f"""QToolButton {{ border: none; border-radius: 14px; padding: 6px 10px; color: {T.TEXT_2}; }}
            QToolButton:hover {{ background: {T.INK_3}; color: {T.TEXT}; }} QToolButton::menu-indicator {{ image: none; }}""")
        menu = QMenu(b)
        for code in i18n.UI_LANGS:
            a = menu.addAction(i18n.AUTONYM[code])
            a.setCheckable(True)
            a.triggered.connect(lambda _c=False, c=code: self._set_ui_language(c))
        menu.aboutToShow.connect(lambda m=menu: [a.setChecked(i18n.UI_LANGS[k] == i18n.language())
                                                 for k, a in enumerate(m.actions())])
        b.setMenu(menu)
        b.setText(i18n.AUTONYM[i18n.language()])
        self._tip(b, "Interface language")
        self._lang_buttons.append(b)
        return b

    def _set_ui_language(self, code):
        i18n.set_language(code)
        self.settings["ui_lang"] = code
        save_settings(self.settings)
        self._retranslate()
        stem = voices.recommended(code)
        if stem and not voices.for_language(code) and not self.settings.get("offered_voice_" + code):
            self.settings["offered_voice_" + code] = True      # ask once per language
            save_settings(self.settings)
            QTimer.singleShot(150, lambda: self._offer_language(code, stem))

    def _offer_language(self, code, stem):
        """'Read and translate in Spanish?' — one voice, downloaded right here."""
        mb = voices.size_mb(stem)
        line = f"{voices.display_name(stem)}  —  {voices.describe(stem)}" + (f"  ({mb} MB)" if mb else "")
        d = DownloadPrompt(tr("Read and translate in {lang}?", **lang_values(code)),
                           tr("Download a {lang_l} voice so books can be read aloud and translated into {lang_l}:",
                              **lang_values(code)), line, packs.voice_items(stem), self)
        if d.exec() and voices.for_language(code):
            self._set_target(code)

    def _retranslate(self):
        self.prep_note.setText(tr("Reading may pause now and then until this is done"))
        for w, key in self._tips:
            w.setToolTip(tr(key))
            w.setAccessibleName(_spoken_name(tr(key)))
        for b in self._lang_buttons:
            b.setText(i18n.AUTONYM[i18n.language()])
        self.welcome.retranslate()
        self._refresh_welcome()
        self.search_box.setPlaceholderText(tr("Search this book"))
        self.chapter_box.setPlaceholderText(tr("Chapters"))
        if self.book:
            self._update_lang_button()
            self._chapters = None
            self._refresh_chapters()
            self._show_search_count()
        self.stage.loading.update()

    def _page_typed(self):
        try:
            self._goto_page(int(self.page_box.currentText()) - 1, manual=True)
        except ValueError:
            pass
        self.stage.scroll.setFocus()

    def _shortcuts(self):
        def sc(keys, slot):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(slot)
            self.addAction(a)
        sc(["Space"], self._toggle_play)
        sc(["Left"], self._prev_sentence)
        sc(["Right"], self._next_sentence)
        sc(["Shift+Left"], lambda: self._jump(-30))
        sc(["Shift+Right"], lambda: self._jump(30))
        sc(["["], lambda: self._step_speed(-1))
        sc(["]"], lambda: self._step_speed(1))
        sc(["PgUp"], lambda: self._goto_page(self.page - 1, manual=True))
        sc(["PgDown"], lambda: self._goto_page(self.page + 1, manual=True))
        sc(["Ctrl+O"], self._open_dialog)
        sc(["Ctrl+F"], self._focus_search)
        sc(["Ctrl+-"], lambda: self._zoom(1 / 1.15))
        sc(["Ctrl+=", "Ctrl++"], lambda: self._zoom(1.15))
        sc(["Ctrl+0"], self._fit)
        sc(["Ctrl+B"], lambda: self._add_bookmark(False))
        sc(["Ctrl+Shift+B"], lambda: self._add_bookmark(True))

    def showEvent(self, e):
        super().showEvent(e)
        dark_title_bar(self)

    # ---- view ----------------------------------------------------------------------
    def _set_follow(self, on=True):
        self.follow = on
        self.b_follow.setChecked(on)

    def _fit(self):
        self.zoom = None
        self._render(force=True)

    def _zoom(self, f):
        if not self.book:
            return
        self.zoom = min(max(self._effective_zoom() * f, 0.3), 6.0)
        self._render(force=True)

    def _effective_zoom(self):
        if self.zoom is not None or self.book is None:
            return self.zoom or 1.0
        # fit the width, but never wider than a comfortable reading column
        w = self.stage.scroll.width() - 2 * PageCanvas.MARGIN - 24
        return max(0.3, min(w, 940) / self.book.doc[self.page].rect.width)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.zoom is None:
            QTimer.singleShot(0, self._render)

    def _render(self, force=False):
        if self.book is None:
            return
        z = self._effective_zoom()
        if force or self.shown != (self.page, round(z, 3)):
            self.stage.page.show_page(self.book.doc[self.page], z)
            self.shown = (self.page, round(z, 3))
        self.zoom_lbl.setText(f"{round(z * 100)}%")
        self._update_labels()
        self._update_marks()

    def _goto_page(self, page, manual=False):
        if self.book is None:
            return
        page = max(0, min(page, self.book.page_count - 1))
        if manual:
            self._set_follow(False)
        if page != self.page:
            self.page = page
            self.stage.scroll.verticalScrollBar().setValue(0)
            self.book.want(page)
            self._render()

    def _update_labels(self):
        if not self.book:
            return
        n = self.book.page_count
        done = len(self.book.cache.pages)
        box = self.page_box
        if box.count() != n:                        # a new book: list every page
            box.blockSignals(True)
            box.clear()
            box.addItems([str(i) for i in range(1, n + 1)])
            box.blockSignals(False)
            self.page_total.setText(f"/ {n}")
        if not box.view().isVisible() and not box.lineEdit().hasFocus() and box.currentIndex() != self.page:
            box.blockSignals(True)
            box.setCurrentIndex(self.page)
            box.blockSignals(False)
        preparing = done < n
        if preparing:
            self.prep_lbl.setText(tr("Preparing pages {pct}%", pct=round(100 * done / n)))
        if self.prep_box.isHidden() == preparing or getattr(self, "_tools_book", None) is not self.book:
            self._tools_book = self.book                  # a new book always gets its own chapters
            self._show_ready_tools(not preparing)
        lang = i18n.lang_label(self.book.lang)
        mode = f"{lang} → {i18n.lang_label(self.target)}" if self.translate else lang
        if self.book.lang_pending:
            mode = tr("Detecting language…")
        # (left-to-right mark first: a Hebrew/Arabic language name would flip the whole line)
        self.sub_lbl.setText("‎" + f"{mode}  ·  " + tr("Page {page} of {pages}", page=self.page + 1, pages=n))
        self._show_title()
        self.scrubber.set_state(n, self.page, self.book.cache.pages.keys())
        self._sync_chapter()
        self._update_toast()

    def _update_toast(self):
        """Progress lives in the loading card; the toast only flags pages with nothing to read."""
        t = self.stage.toast
        no_text = tr("No readable text on this page")
        if self.book.no_text(self.page):
            t.show_message(no_text, sticky=True)
        elif t.current == no_text:
            t.clear()

    # ---- library ----------------------------------------------------------------------
    def _refresh_welcome(self):
        self.welcome.set_recents(self.settings.get("recents", []), app_dir("thumbs"))

    def _go_home(self):
        if self.player and not self.player.paused:
            self.player.set_paused(True)
        self._save_position()
        self._refresh_welcome()
        self.stack.setCurrentWidget(self.welcome)

    def _about(self):
        AboutDialog(self).exec()

    # ---- search -----------------------------------------------------------------------
    def _run_search(self):
        """New search text: find it in the pages prepared so far and show the first match
        from the page on screen onward. Moves the page, never the voice."""
        q = self.search_box.text().strip()
        self._results = self.book.search(q) if self.book and q else []
        self._result_i = next((i for i, (p, _) in enumerate(self._results) if p >= self.page), 0) if self._results else -1
        if self._results:
            self._show_result()
        self._update_marks()
        self._show_search_count()

    def _refresh_search(self):
        """More pages got prepared: count their matches too, staying on the current one."""
        q = self.search_box.text().strip()
        if not q or not self.book:
            return
        cur = self._results[self._result_i] if 0 <= self._result_i < len(self._results) else None
        self._results = self.book.search(q)
        self._result_i = self._results.index(cur) if cur in self._results else (-1 if not self._results else 0)
        self._show_search_count()
        self._update_marks()

    def _search_step(self, step):
        if not self._results:
            self._run_search()
            return
        self._result_i = (self._result_i + step) % len(self._results)
        self._show_result()
        self._show_search_count()

    def _show_result(self):
        page, rects = self._results[self._result_i]
        self._goto_page(page, manual=True)
        self._update_marks()
        r = self.stage.page.screen_rect(rects[0])
        self.stage.scroll.ensureVisible(int(r.center().x()), int(r.center().y()), 60, 220)

    def _show_search_count(self):
        q = self.search_box.text().strip()
        many = bool(q and self._results)
        self.b_res_prev.setEnabled(many)
        self.b_res_next.setEnabled(many)
        if not q or not self.book:
            self.search_count.setText("")
            return
        n = len(self._results)
        text = tr("{i} of {n}", i=self._result_i + 1, n=n) if n else tr("not found")
        if len(self.book.cache.pages) < self.book.page_count:
            text += "  ·  " + tr("still loading")
        self.search_count.setText(text)

    def _update_marks(self):
        here = [r for p, rects in self._results for r in rects if p == self.page]
        cur = ()
        if 0 <= self._result_i < len(self._results) and self._results[self._result_i][0] == self.page:
            cur = tuple(self._results[self._result_i][1])
        self.stage.page.set_marks(here, cur)

    def _focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    # ---- chapters ---------------------------------------------------------------------
    def _show_ready_tools(self, ready):
        """Pages ready: the progress gives way to search (and chapters, when the book has some)."""
        self.prep_box.setVisible(not ready)
        self.prep_spin.setVisible(not ready)
        for w in (self.search_box, self.b_res_prev, self.b_res_next, self.search_count):
            w.setVisible(ready)
        if ready:
            self._refresh_chapters()
        else:
            self.chapter_box.setVisible(False)

    def _refresh_chapters(self, force=False):
        chapters = self.book.chapters() if self.book else []
        self.chapter_box.setVisible(bool(chapters) and self.prep_box.isHidden())   # no chapters, no box
        if chapters == self._chapters and not force:
            return
        self._chapters = chapters
        self._fill_chapter_box()
        if chapters and self.translate and self.book.lang != self.target:
            book, target = self.book, self.target
            if self._title_cache.get((id(book), target)) is None:
                def work():
                    from .llm import titles_in_steps
                    titles_in_steps(self.models.translator, [c[1] for c in chapters], book.lang, book.nllb, target,
                                    lambda out: self.sig.titles_ready.emit((book, target, out)))
                threading.Thread(target=work, daemon=True).start()

    def _translate_book_title(self):
        """The book's title in the language being read (shown in brackets under the original)."""
        if not self.book or not self.translate or self.book.lang == self.target:
            return
        book, target = self.book, self.target
        if (id(book), target) in self._book_title_tr:
            return
        self._book_title_tr[(id(book), target)] = None          # (asked once)

        def work():
            from .llm import titles_in_steps
            titles_in_steps(self.models.translator, [book_title(book)], book.lang, book.nllb, target,
                            lambda out: out[0] and self.sig.book_title_ready.emit((book, target, out[0])))
        threading.Thread(target=work, daemon=True).start()

    def _show_title(self):
        """The book's title; when read in translation, the translated title beside it in brackets,
        smaller and grey (the original is never replaced)."""
        title = book_title(self.book)
        shown = self._book_title_tr.get((id(self.book), self.target)) if self.translate else None
        fm = QFontMetrics(self.title_lbl.font())
        if not shown or shown == title:
            text = html.escape(fm.elidedText(title, Qt.ElideRight, 290))
        else:
            small = QFontMetrics(T.font(12))
            left = fm.elidedText(title, Qt.ElideRight, 200)
            right = small.elidedText(f"({shown})", Qt.ElideRight, max(90, 300 - fm.horizontalAdvance(left)))
            text = (f"{html.escape(left)} <span style='font-size:12px; font-weight:400; color:{T.TEXT_2}'>"
                    f"{html.escape(right)}</span>")
        if self.title_lbl.text() != text:
            self.title_lbl.setText(text)

    def _book_title_ready(self, msg):
        book, target, text = msg
        self._book_title_tr[(id(book), target)] = text
        if book is self.book:
            self._update_labels()

    def _chapter_titles(self):
        """The chapters' titles as the reader sees them: in the language being read (a Russian
        book read in English lists its chapters in English)."""
        titles = [c[1] for c in self._chapters or []]
        if self.book and self.translate and self.book.lang != self.target:
            done = self._title_cache.get((id(self.book), self.target))
            if done and len(done) == len(titles):
                return done
        return titles

    def _fill_chapter_box(self):
        box = self.chapter_box
        box.blockSignals(True)
        box.clear()
        for (level, title, page, _y), shown in zip(self._chapters or [], self._chapter_titles()):
            box.addItem("      " * (min(level, 3) - 1) + shown)
            tip = tr("Page {page} of {pages}", page=page + 1, pages=self.book.page_count)
            box.setItemData(box.count() - 1, tip if shown == title else f"{title}\n{tip}", Qt.ToolTipRole)
        box.blockSignals(False)
        self._sync_chapter()

    def _titles_ready(self, msg):
        book, target, titles = msg
        self._title_cache[(id(book), target)] = titles
        if book is self.book and target == self.target:
            self._fill_chapter_box()

    def _sync_chapter(self):
        """Show the chapter the page on screen belongs to."""
        if not self._chapters or self.chapter_box.view().isVisible():
            return
        i = max((k for k, c in enumerate(self._chapters) if c[2] <= self.page), default=-1)   # -1: before chapter 1
        if self.chapter_box.currentIndex() != i:
            self.chapter_box.blockSignals(True)
            self.chapter_box.setCurrentIndex(i)
            self.chapter_box.blockSignals(False)

    def _chapter_chosen(self, i):
        """Go to the chapter and read from its first line (like clicking that line)."""
        if not 0 <= i < len(self._chapters):
            return
        _lvl, _title, page, y = self._chapters[i]
        self._goto_page(page, manual=True)
        self._pending_chapter = (page, y)
        self.book.want(page)
        self._start_chapter()

    def _start_chapter(self):
        """Start reading at the chapter chosen, as soon as its page is ready."""
        if not getattr(self, "_pending_chapter", None) or not self.book:
            return
        page, y = self._pending_chapter
        s = self.book.first_sentence_from(page, y)
        if s is None and not self.book.ready(page):
            return                                          # page not prepared yet: try again when it is
        self._pending_chapter = None
        if s is not None:
            self._start_at(s.key)
        r = self.stage.page.screen_rect((0, max(0, y - 30), 1, max(0, y - 30) + 1))
        self.stage.scroll.verticalScrollBar().setValue(int(r.top()))

    def _remove_recent(self, path):
        """Take a book off the 'Continue reading' shelf (the file itself is untouched)."""
        self.settings["recents"] = [r for r in self.settings.get("recents", []) if r.get("path") != path]
        save_settings(self.settings)
        self._refresh_welcome()

    def _open_voice_picker(self, first_run=False):
        lang = self.book.lang if self.book else None
        priority = [i18n.language(), lang, self.target, "en"] + [s[:2] for s in voices.installed()] + list(TARGETS)
        suggest = set()
        ui = i18n.language()
        if first_run and ui != "en" and not voices.for_language(ui) and voices.recommended(ui):
            suggest.add(voices.recommended(ui))      # e.g. a Spanish voice for a Spanish Windows
        d = VoicePicker(first_run, [c for c in priority if c], suggest, self)
        d.exec()
        self.settings["voices_setup"] = True
        save_settings(self.settings)
        if d.failed_remove:
            self.stage.toast.show_message(tr("Couldn't remove {names} while in use — restart BookTalker and try again",
                                             names=", ".join(voices.display_name(s) for s in d.failed_remove)), ms=6000)
        if "ai" in d.added:                              # the AI translator was just installed
            self.models.translator.best = True
            self.settings["translate_best"] = True
            save_settings(self.settings)
            self._follow_translation()
        if self.book and self.voice in d.removed:     # the voice reading now was removed
            self._choose_mode()
            self._apply_mode()

    def eventFilter(self, obj, event):
        """Scrolling the page while it reads: the voice carries on; only the automatic
        page-following steps aside for a few seconds so the view stays where you put it.
        Ctrl + wheel zooms. Esc in the search box clears it."""
        if obj is self.search_box and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.search_box.clear()
            self._run_search()
            self.stage.scroll.setFocus()
            return True
        if event.type() == QEvent.Wheel and obj is self.stage.scroll.viewport():
            if event.modifiers() & Qt.ControlModifier:
                self._zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
                return True
            self._user_scrolled()
            if self._wheel_turn(event.angleDelta().y()):
                return True
        return super().eventFilter(obj, event)

    TURN_PUSH = 360          # wheel units (3 notches) of extra scrolling past the page edge
    TURN_SETTLE = 0.4        # s after reaching the edge before the push starts to count
    TURN_HOLD = 0.25         # s the push must last (a free-spinning wheel can't turn by itself)
    TURN_FORGET = 0.9        # s without scrolling and the push starts over

    def _wheel_turn(self, dy):
        """Scrolling on past the bottom (top) of a page turns to the next (previous) page, but
        only after a short settle and a deliberate bit more scrolling: no accidental flips.
        The voice is not touched. -> True when the wheel event was used up here."""
        if not self.book or not dy:
            return False
        bar = self.stage.scroll.verticalScrollBar()
        down = dy < 0
        at_edge = bar.value() >= bar.maximum() if down else bar.value() <= bar.minimum()
        last = (self.page == self.book.page_count - 1) if down else self.page == 0
        now = time.time()
        t = self._turn
        if not at_edge or last:
            t.update(dir=0, push=0)
            return False
        if t["dir"] != (1 if down else -1) or now - t["last"] > self.TURN_FORGET:
            t.update(dir=1 if down else -1, push=0, since=now)    # just arrived at the edge
        t["last"] = now
        if now - t["since"] < self.TURN_SETTLE:                   # the scroll that got here, still spinning
            return True
        if not t["push"]:
            t["start"] = now
        t["push"] += abs(dy)
        if t["push"] < self.TURN_PUSH or now - t["start"] < self.TURN_HOLD:
            self.stage.toast.show_message(tr("Keep scrolling for the next page" if down
                                             else "Keep scrolling for the previous page"), ms=900)
            return True
        t.update(dir=0, push=0)
        self.stage.toast.clear()
        self._goto_page(self.page + (1 if down else -1))
        if not down:                                              # arrive at the bottom of the page before
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        self._turn.update(since=time.time(), last=time.time(), dir=0)
        return True

    def _user_scrolled(self):
        if self.player and not self.player.paused and self.follow:
            if time.time() > self._follow_pause_until:
                self.stage.toast.show_message(tr("Auto-scroll paused — it resumes in a few seconds, or press the target button"), ms=2500)
            self._follow_pause_until = time.time() + 6.0

    def _open_dialog(self):
        filt = convert.OPEN_FILTER.replace("Readable files", tr("Readable files")).replace("All files", tr("All files"))
        path, _ = QFileDialog.getOpenFileName(self, tr("Open a book or document"), "", filt)
        if path:
            self.open(path)

    def open(self, path):
        """Open any supported file. Non-PDFs are converted in the background first."""
        path = os.path.abspath(path)
        if self.book and os.path.abspath(self.book.source) == path:
            self.stack.setCurrentWidget(self.reader)
            return
        if not convert.supported(path):
            self.stack.setCurrentWidget(self.reader if self.book else self.welcome)
            if self.book:
                self.stage.toast.show_message(tr("BookTalker can’t open {ext} files yet", ext=os.path.splitext(path)[1]))
            return
        self.converting = path
        self._open_started = time.time()
        self._ready_at = None
        if not path.lower().endswith(".pdf"):
            self.stack.setCurrentWidget(self.reader)

        self._convert_pages = 0

        def work():
            try:
                pdf = convert.cached(path) or convert.to_pdf_apart(
                    path, lambda n: self.sig.convert_pages.emit(path, n))
                self.sig.converted.emit(path, pdf, "")
            except Exception as e:      # noqa: BLE001 — shown to the user
                self.sig.converted.emit(path, "", str(e) or e.__class__.__name__)
        threading.Thread(target=work, daemon=True).start()

    def _open_converted(self, source, pdf, error):
        if source != self.converting:
            return                      # the user opened something else meanwhile
        self.converting = None
        if error:
            self.stage.toast.show_message(tr("Couldn’t open {name}: {err}", name=os.path.basename(source), err=error), ms=6000)
            return
        self._close_book()
        self.book = Book(pdf, self.models.layout, self.sig.pages_done.emit, source=source,
                         get_ocr=self.models.ocr, code_mode=self.settings.get("code_mode", "explain"))
        title = book_title(self.book)
        self.setWindowTitle(f"{title} — BookTalker")
        from .ui.widgets import announce
        announce(self, tr("Opened {title}. Space plays or pauses.", title=title))
        fm = QFontMetrics(self.title_lbl.font())
        self.title_lbl.setText(fm.elidedText(title, Qt.ElideRight, 290))
        self.title_lbl.setToolTip(source)
        self.search_box.clear()
        self._results, self._result_i, self._chapters = [], -1, None
        self._refresh_chapters()
        saved = self.settings.get(doc_id(source), {})
        self.resume_key = tuple(saved["key"]) if saved.get("key") else None
        self.page = self.resume_key[0] if self.resume_key else 0
        self.zoom = saved.get("zoom")
        self._saved_mode = saved
        if saved.get("lang"):
            self.book.set_language(saved["lang"])
        self._choose_mode()
        self._translate_book_title()
        self._refresh_chapters(force=True)      # (a book prepared before has its chapters already: titles in the language read)
        self.book.want(self.page)
        self.shown = None
        self.stack.setCurrentWidget(self.reader)
        QTimer.singleShot(0, self._render)
        self._update_lang_button()
        self._make_player()
        self._remember(source)
        self.stage.toast.clear()
        self._announce_language()

    def _choose_mode(self):
        """English books read as they are; other languages default to the English
        translation (switchable in the globe menu). A choice the user made is remembered."""
        saved = self._saved_mode
        lang = self.book.lang
        self._mode_lang = lang
        if not voices.for_language(self.target):    # its voice was removed: fall back to English
            self._set_target_value("en")
        # a book already in the chosen language is read as it is; any other is translated into
        # it, unless the user picked the original (and a voice for it is installed)
        self.translate = (lang != self.target and Translator.available()
                          and (saved.get("translate", True) or not voices.for_language(lang)))
        if lang != self.target and not Translator.available() and not voices.for_language(lang) and not self.book.lang_pending:
            # nothing can read it yet: say how (the translator is a download, never a surprise)
            QTimer.singleShot(1500, lambda: self.stage.toast.show_message(
                tr("To hear this {lang} book, get a {lang} voice or the translator from the globe menu.",
                   **lang_values(lang)), ms=8000))
        want_lang = self.target if self.translate else lang
        have = voices.for_language(want_lang)
        v, pref = saved.get("voice"), self.settings.get("voice_" + want_lang)
        self.voice = v if v in have else (pref if pref in have else voices.default_for(want_lang))
        # start what this book needs now, behind the loading card
        threading.Thread(target=self.models.get_speaker, args=(self.voice,), daemon=True).start()
        self._follow_translation()

    def _follow_translation(self):
        """In translation mode the AI starts on the opening sentences right away, so they
        are ready by the time Play is pressed."""
        if self.translate and self.book:
            key = (self.player.current_key() if self.player else None) or self.resume_key or (self.page, -1)
            self.models.translator.follow(self.book, key, self.book.lang, self.book.nllb)

    def _announce_language(self):
        lang = self.book.lang
        if lang != self.target and not self.book.lang_pending:
            how = (tr("the {lang} translation", **lang_values(self.target)) if self.translate
                   else tr("the original {lang}", **lang_values(lang)))
            self.stage.toast.show_message(tr("{lang} detected — reading {how}. Change it with the globe button.",
                                             how=how, **lang_values(lang)), ms=5000)

    def _remember(self, path):
        rec = [r for r in self.settings.get("recents", []) if r.get("path") != path]
        rec.insert(0, {"path": path, "id": doc_id(path), "title": book_title(self.book),
                       "page": self.page, "pages": self.book.page_count})
        self.settings["recents"] = rec[:12]
        save_settings(self.settings)

    def _make_player(self):
        if self.book is not None and self.models.speaker is not None and self.player is None:
            from .player import Player
            self.player = Player(self.models.get_speaker, self.book, self.models.translator,
                                 self.voice, self.translate, self.book.nllb, self.book.lang)
            self.player.speed = self.speed

    # ---- language & voice ------------------------------------------------------------------
    def _update_lang_button(self):
        if not self.book:
            return
        code = (self.book.lang or "en").upper()
        self.lang_btn.setText(f"{code} → {self.target.upper()}" if self.translate else code)
        self._update_labels()

    def _set_book_language(self, code):
        """The reader corrects the book's language: translate / read from that language."""
        if not self.book or code == self.book.lang:
            return
        self.book.set_language(code)
        self._saved_mode = {k: v for k, v in self._saved_mode.items() if k not in ("translate", "voice")}
        self._choose_mode()
        self._apply_mode()
        self._announce_language()
        self._update_labels()

    def _targets(self):
        """Languages books can be translated into: every language with a voice on this computer."""
        have = {stem[:2] for stem in voices.installed()}
        return [c for c in TARGETS if c in have] + sorted(
            (c for c in have if c in LANGS and c not in TARGETS), key=lambda c: i18n.lang_label(c).lower())

    def _build_lang_menu(self):
        """Only what is on this computer; each section ends with its own 'More…' item."""
        m = self.lang_menu
        m.clear()
        if not self.book:
            return
        lang = self.book.lang
        def name(code):
            """A language in its own name, with the name a reader here knows beside it ('עברית  (Hebrew)')."""
            own, local = i18n.AUTONYM.get(code, code.upper()), i18n.lang_label(code)
            if own == local and code in LANGS and LANGS[code][1] != own:
                local = LANGS[code][1]                  # outside the 8 interface languages: its English name
            return own if own == local else f"{own}  ({local})"
        # 1. what the book is written in (found by itself; changed here when it guessed wrong)
        head = m.addAction(tr("THE BOOK IS IN"))
        head.setEnabled(False)
        sub = m.addMenu(name(lang))
        codes = sorted((c for c in LANGS if c not in ("nb", "la")), key=lambda c: i18n.lang_label(c).lower())
        for code in [lang] + [c for c in codes if c != lang]:
            a = sub.addAction(name(code))
            a.setCheckable(True)
            a.setChecked(code == lang)
            a.triggered.connect(lambda _c=False, c=code: self._set_book_language(c))
        m.addSeparator()
        # 2. what to hear it in: its own language, or any language with a voice (= a translation)
        head = m.addAction(tr("LISTEN IN"))
        head.setEnabled(False)
        own_label = name(lang) + "  —  " + tr("original")
        if not voices.for_language(lang) and voices.recommended(lang):     # one click gets its voice
            own_label += f"   ({tr('download voice, {mb} MB', mb=voices.size_mb(voices.recommended(lang)))})"
        if voices.for_language(lang) or voices.recommended(lang):
            a = m.addAction(own_label)
            a.setCheckable(True)
            a.setChecked(not self.translate)
            a.triggered.connect(lambda: self._set_mode(False))
        for code in self._targets():
            if code == lang:
                continue
            label = name(code) + "  —  " + tr("translated")
            if not Translator.available():
                label += f"   ({tr('download translator, {mb} MB', mb=packs.TRANSLATOR_SIZE_MB)})"
            t = m.addAction(label)
            t.setCheckable(True)
            t.setChecked(self.translate and code == self.target)
            t.triggered.connect(lambda _c=False, c=code: self._set_target(c))
        more = m.addAction(tr("More languages…"))
        more.triggered.connect(lambda: self._open_voice_picker())
        m.addSeparator()
        head = m.addAction(tr("VOICE"))
        head.setEnabled(False)
        for stem, name, desc, have in voices.catalog(self.target if self.translate else lang):
            if not have:
                continue
            a = m.addAction(f"{name}  —  {desc}")
            a.setCheckable(True)
            a.setChecked(stem == self.voice)
            a.triggered.connect(lambda _c=False, s=stem: self._set_voice(s))
        more = m.addAction(tr("More voices…"))
        more.triggered.connect(lambda: self._open_voice_picker())
        if self.book.has_code:                      # a book with computer code in it
            m.addSeparator()
            head = m.addAction(tr("COMPUTER CODE"))
            head.setEnabled(False)
            for mode, label in (("explain", "Explain it in plain words"), ("verbatim", "Read it exactly as written"),
                                ("skip", "Skip it")):
                a = m.addAction(tr(label))
                a.setCheckable(True)
                a.setChecked(self.book.code_mode == mode)
                a.triggered.connect(lambda _c=False, md=mode: self._set_code_mode(md))
        smart = self.models.translator
        if self.translate and smart.engine.available():      # a choice only once the AI is installed
            m.addSeparator()
            head = m.addAction(tr("TRANSLATION"))
            head.setEnabled(False)
            where = {"gpu": tr("on the graphics card"), "cpu": tr("on the processor"),
                     "failed": tr("needs a free graphics card")}.get(smart.engine.status, "")
            a = m.addAction(tr("Best quality — AI translator") + (f"  ({where})" if where else ""))
            a.setCheckable(True)
            a.setChecked(smart.best)
            a.setEnabled(smart.engine.status != "failed")
            a.triggered.connect(lambda: self._set_quality(True))
            b = m.addAction(tr("Fast — lighter translator"))
            b.setCheckable(True)
            b.setChecked(not smart.best)
            b.triggered.connect(lambda: self._set_quality(False))

    # ---- sleep timer --------------------------------------------------------------------
    def _build_sleep_menu(self):
        m = self.sleep_menu
        m.clear()
        head = m.addAction(tr("SLEEP TIMER"))
        head.setEnabled(False)
        off = m.addAction(tr("Off"))
        off.setCheckable(True)
        off.setChecked(self._sleep is None)
        off.triggered.connect(lambda: self._set_sleep(None))
        for mins in (5, 15, 30, 45, 60, 90, 120):
            a = m.addAction(tr("{n} minutes", n=mins))
            a.setCheckable(True)
            a.setChecked(bool(self._sleep) and self._sleep.get("minutes") == mins)
            a.triggered.connect(lambda _c=False, n=mins: self._set_sleep({"kind": "time", "left": n * 60.0, "minutes": n}))
        if self._chapters and self.book:
            m.addSeparator()
            cur = max(0, self._chapter_index())
            titles = self._chapter_titles()
            a = m.addAction(tr("End of this chapter"))
            a.setCheckable(True)
            a.setChecked(bool(self._sleep) and self._sleep.get("kind") == "chapter" and self._sleep["index"] == cur)
            a.triggered.connect(lambda _c=False, i=cur: self._set_sleep({"kind": "chapter", "index": i}))
            sub = m.addMenu(tr("End of chapter…"))
            for i in range(cur, len(self._chapters)):
                b = sub.addAction(titles[i])
                b.setCheckable(True)
                b.setChecked(bool(self._sleep) and self._sleep.get("kind") == "chapter" and self._sleep["index"] == i)
                b.triggered.connect(lambda _c=False, k=i: self._set_sleep({"kind": "chapter", "index": k}))

    def _chapter_index(self):
        """The chapter the voice (else the page on screen) is in; -1 before chapter 1."""
        page, y = self.page, 0
        s = self.player.state()[0] if self.player else None
        if s is not None and s.words and s.words[0].rects:
            page, y = s.words[0].rects[0][0], s.words[0].rects[0][2]
        return max((k for k, c in enumerate(self._chapters or []) if (c[2], c[3]) <= (page, y + 3)), default=-1)

    def _set_sleep(self, sleep):
        self._sleep = sleep
        self._sleep_last = time.time()
        if self.player:
            self.player.volume = 1.0
        self._show_sleep()
        if sleep:
            if sleep["kind"] == "time":
                msg = tr("Sleep timer: reading stops in {n} minutes", n=sleep["minutes"])
            else:
                msg = tr("Sleep timer: reading stops at the end of “{title}”", title=self._chapter_titles()[sleep["index"]])
            self.stage.toast.show_message(msg, ms=2500)

    def _show_sleep(self):
        s = self._sleep
        if not s:
            text = ""
        elif s["kind"] == "time":
            left = max(0, int(s["left"]))
            text = f"{left // 60}:{left % 60:02d}"
        else:
            text = tr("ch. end")
        if self.sleep_btn.text() != text:
            self.sleep_btn.setText(text)
            self.sleep_btn.setIcon(icons.icon("moon", T.GOLD if s else T.TEXT_2, 18))

    def _sleep_tick(self):
        s = self._sleep
        now = time.time()
        dt, self._sleep_last = now - self._sleep_last, now
        if not s or not self.player or self.player.paused:
            return
        if s["kind"] == "time":                     # counts while the voice is heard
            if self.player.state()[0] is None:
                return
            s["left"] -= dt
            if s["left"] <= 6:
                self.player.volume = max(0.0, s["left"] / 6)       # fades out over the last seconds
            if s["left"] <= 0:
                self._sleep_stop()
            else:
                self._show_sleep()
            return
        i = s["index"]                              # stop where the next chapter begins
        if i + 1 >= len(self._chapters or []):
            if self.player.finished:
                self._sleep_stop()
            return
        _lvl, _t, page, y = self._chapters[i + 1]
        cur = self.player.state()[0]
        if cur is not None and cur.words and cur.words[0].rects:
            p0, y0 = cur.words[0].rects[0][0], cur.words[0].rects[0][2]
            if (p0, y0) >= (page, y - 3):
                self._sleep_stop(at=cur.key)

    def _sleep_stop(self, at=None):
        """The timer is up: pause (after the fade), keep the place, and say so."""
        if self.player:
            self.player.set_paused(True)
            if at is not None:              # the next chapter starts from its first line next time
                self.player.play_from(at)
                self.player.set_paused(True)
            self.player.volume = 1.0
        self._sleep = None
        self._show_sleep()
        self._save_position()
        self.stage.toast.show_message(tr("Sleep timer: reading paused. Good night!"), ms=6000)

    # ---- bookmarks --------------------------------------------------------------------
    def _marks(self):
        if not self.book:
            return []
        return self.settings.setdefault(doc_id(self.book.source), {}).setdefault("bookmarks", [])

    def _save_marks(self, marks):
        if self.book:
            self.settings.setdefault(doc_id(self.book.source), {})["bookmarks"] = marks
            save_settings(self.settings)

    def _add_bookmark(self, with_note):
        """A bookmark at the sentence being read (or the first one on the page shown)."""
        if not self.book:
            return
        key = self.player.current_key() if self.player else None
        s = self.book.get(key) if key else self.book.first_sentence_from(self.page, 0)
        if not hasattr(s, "key"):
            return
        note = ""
        if with_note:
            from PySide6.QtWidgets import QInputDialog
            note, ok = QInputDialog.getMultiLineText(self, tr("Note"), tr("Your note for this place:"))
            if not ok:
                return
        text = " ".join(w.text for w in s.words[:12]) + ("…" if len(s.words) > 12 else "")
        marks = [m for m in self._marks() if tuple(m["key"]) != tuple(s.key)]
        marks.append({"key": list(s.key), "page": s.page, "text": text, "note": note.strip(),
                      "time": time.strftime("%Y-%m-%d %H:%M")})
        marks.sort(key=lambda m: tuple(m["key"]))
        self._save_marks(marks)
        self.stage.toast.show_message(tr("Bookmark added on page {page}", page=s.page + 1), ms=1800)

    def _build_bookmark_menu(self):
        m = self.bm_menu
        m.clear()
        a = m.addAction(tr("Add bookmark here") + "    Ctrl+B")
        a.triggered.connect(lambda: self._add_bookmark(False))
        a.setEnabled(self.book is not None)
        b = m.addAction(tr("Add bookmark with a note…") + "    Ctrl+Shift+B")
        b.triggered.connect(lambda: self._add_bookmark(True))
        b.setEnabled(self.book is not None)
        marks = self._marks()
        if marks:
            m.addSeparator()
            for mk in marks[:25]:
                label = tr("Page {page}", page=mk["page"] + 1) + "  —  " + mk.get("text", "")[:48]
                if mk.get("note"):
                    label += "   ✎ " + mk["note"].splitlines()[0][:30]
                act = m.addAction(label)
                act.triggered.connect(lambda _c=False, k=mk: self._go_bookmark(k))
            m.addSeparator()
            c = m.addAction(tr("All bookmarks and notes…"))
            c.triggered.connect(self._bookmarks_dialog)

    def _go_bookmark(self, mark):
        """Go to the bookmark; reading carries on from there if the voice was reading."""
        key = tuple(mark["key"])
        self._goto_page(key[0], manual=True)
        self.book.want(key[0])
        if self.player and not self.player.paused:
            self._start_at(key)
        else:
            self.resume_key = key
            if self.player:
                self.player.start_key = None        # Play starts at the bookmark
                self.player.finished = True

    def _bookmarks_dialog(self):
        BookmarksDialog(self, list(self._marks()), self._go_bookmark, self._save_marks).exec()

    # ---- save as audiobook ------------------------------------------------------------
    def _export_dialog(self):
        if not self.book:
            return
        from .export import find_year
        meta = self.book.doc.metadata or {}
        reading = (tr("the {lang} translation", **lang_values(self.target)) if self.translate
                   else i18n.AUTONYM.get(self.book.lang, self.book.lang))
        reading += "  —  " + voices.display_name(self.voice)
        job = {"source": self.book.source, "pdf": self.book.path, "voice_path": voices.installed()[self.voice]["path"],
               "translate": self.translate, "target": self.target, "best": self.models.translator.best,
               "code_mode": self.book.code_mode, "lang": self.book.lang if getattr(self.book, "lang_fixed", False) else None,
               "title": book_title(self.book), "author": (meta.get("author") or "").strip(),
               "year": find_year(self.book.source, meta)}
        titles = self._chapter_titles() if self.book.prepared() else []
        if self.translate and self.book.lang != self.target:
            # the audiobook's folder and files are named in the language it is read in
            from .llm import translate_titles
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                names = translate_titles(self.models.translator, [job["title"], job["author"] or "-"],
                                         self.book.lang, self.book.nllb, self.target)
            finally:
                QApplication.restoreOverrideCursor()
            if names:
                job["title"] = names[0] or job["title"]
                if job["author"]:
                    job["author"] = names[1] if names[1] not in ("-", "") else job["author"]
        dlg = ExportDialog(self, job, titles, reading, self.settings.get("audiobook_folder"))
        dlg.finished.connect(lambda _r: self._remember_export_folder(dlg))
        dlg.show()
        self._export_dlg = dlg                      # (kept while it records)

    def _remember_export_folder(self, dlg):
        self.settings["audiobook_folder"] = dlg.folder.text().strip()
        save_settings(self.settings)

    def _set_code_mode(self, mode):
        """How computer code in books is read: explained, exactly as written, or skipped."""
        self.settings["code_mode"] = mode
        save_settings(self.settings)
        if self.book:
            key = (self.player.current_key() if self.player else None) or (self.page, -1)
            self.book.set_code_mode(mode, around=key[0])
            if self.player:
                self.player.set_mode(self.voice, self.translate, self.book.nllb, self.book.lang)

    def _set_quality(self, best):
        if best and not packs.ai_installed():
            gb = packs.AI_SIZE_MB / 1000
            ok = QMessageBox.question(
                self, tr("Download the AI translator?"),
                tr("Best-quality translation uses Qwen3-4B (by Alibaba, free Apache licence) running on this computer. "
                   "It is a one-time download of about {size} GB from Hugging Face, plus the llama.cpp engine from GitHub."
                   "\n\nDownload it now?", size=f"{gb:.1f}"))
            if ok != QMessageBox.Yes:
                return
            self._download(tr("the AI translator"), packs.ai_items(), lambda: self._set_quality(True))
            return
        self.models.translator.best = best
        self.settings["translate_best"] = best
        save_settings(self.settings)
        self._apply_mode()

    def _set_target_value(self, code):
        self.target = code
        self.settings["target_lang"] = code
        save_settings(self.settings)
        self.models.translator.set_target(code)

    def _set_target(self, code):
        """Choose the language books are translated into (its voice downloads if needed)."""
        if not voices.for_language(code):
            stem = voices.recommended(code)
            if not stem:
                return
            self._download(tr("the {name} voice", name=voices.display_name(stem)), packs.voice_items(stem),
                           lambda: self._set_target(code))
            return
        if self.book and self.book.lang != code and not Translator.available():
            self._download(tr("the translator"), packs.translator_items(), lambda: self._set_target(code))
            return
        self._set_target_value(code)
        if not self.book:
            return
        self.translate = self.book.lang != code
        want = code if self.translate else self.book.lang
        self.voice = self.settings.get("voice_" + want) or voices.default_for(want)
        self._apply_mode()
        self._announce_language()

    def _set_mode(self, translate):
        if translate == self.translate or not self.book:
            return
        if translate and not Translator.available():
            self._download(tr("the translator"), packs.translator_items(), lambda: self._set_mode(translate))
            return
        want = self.target if translate else self.book.lang
        stem = self.settings.get("voice_" + want) or voices.default_for(want)
        if stem is None:                       # original language, voice not downloaded yet
            stem = voices.recommended(want)
            if not stem:
                return
            self._download(tr("the {name} voice", name=voices.display_name(stem)), packs.voice_items(stem),
                           lambda: self._set_mode(translate))
            return
        self.translate = translate
        self.voice = stem
        self._apply_mode()

    def _set_voice(self, stem):
        if stem not in voices.installed():
            self._download(tr("the {name} voice", name=voices.display_name(stem)), packs.voice_items(stem),
                           lambda: self._set_voice(stem))
            return
        self.voice = stem
        self.settings["voice_" + voices.installed()[stem]["lang"]] = stem
        # start loading it now: the loading card waits for this voice
        threading.Thread(target=self.models.get_speaker, args=(stem,), daemon=True).start()
        self._apply_mode()

    # ---- downloads (extra voices, AI translator) --------------------------------------------
    def _download(self, label, items, then):
        if getattr(self, "_dl", None) is not None:
            self.stage.toast.show_message(tr("Another download is still running"))
            return
        self._dl_label, self._dl_then = label, then
        self._dl = packs.Download(items, lambda d, t: self.sig.dl_progress.emit(float(d), float(t)),
                                  lambda err: self.sig.dl_done.emit(err or ""))
        self.stage.toast.show_message(tr("Downloading {what}…", what=label), sticky=True)
        self._dl.start()

    def _dl_progress(self, done, total):
        if total > 0:
            mb = lambda b: f"{b / 1e9:.2f} GB" if b > 1e9 else f"{b / 1e6:.0f} MB"
            self.stage.toast.show_message(tr("Downloading {what} — {pct}%  ({done} of {total})", what=self._dl_label,
                                             pct=f"{100 * done / total:.0f}", done=mb(done), total=mb(total)), sticky=True)

    def _dl_done(self, err):
        self._dl = None
        if err:
            self.stage.toast.show_message(tr("Download failed: {err}", err=err), ms=6000)
            return
        self.stage.toast.show_message(tr("Ready: {what}", what=self._dl_label), ms=2500)
        self._dl_then()

    def _apply_mode(self):
        self._follow_translation()
        if self.player:
            self.player.set_mode(self.voice, self.translate, self.book.nllb, self.book.lang)
        if not self.translate:
            self.stage.subtitle.hide()
        self._update_lang_button()
        self._save_position()
        self._translate_book_title()
        if self._chapters:
            self._refresh_chapters(force=True)        # chapter titles in the language now read

    def _close_book(self):
        self._set_sleep(None)
        self._save_position()
        if self.player:
            self.player.close()
            self.player = None
        if self.book:
            self.book.close()
            self.book = None

    def _save_position(self):
        if not self.book:
            return
        key = self.player.current_key() if self.player else None
        key = key or self.resume_key or (self.page, -1)
        self.settings.setdefault(doc_id(self.book.source), {}).update(
            {"key": list(key), "zoom": self.zoom, "translate": self.translate, "voice": self.voice})
        if getattr(self.book, "lang_fixed", False):            # the language the reader chose for it
            self.settings[doc_id(self.book.source)]["lang"] = self.book.lang
        for r in self.settings.get("recents", []):
            if r.get("path") == os.path.abspath(self.book.source):
                r["page"] = key[0]
        save_settings(self.settings)

    def _voice_ready(self):
        self._make_player()
        if self.book:
            self._update_labels()

    def _pages_done(self, _pages):
        # a scanned book only reveals its language after OCR: settle the reading mode then
        # (_choose_mode keeps the reader's saved translate/original choice)
        if self.book and self.book.lang != self._mode_lang:
            self._choose_mode()
            self._apply_mode()
            self._announce_language()
        self._update_labels()
        self._refresh_chapters()
        self._refresh_search()
        self._start_chapter()

    def _update_loading(self):
        """Drive the 'Preparing your book' card on a first open."""
        card = self.stage.loading
        started = getattr(self, "_open_started", 0)
        if self.converting:
            name = os.path.basename(self.converting)
            made = getattr(self, "_convert_pages", 0)
            steps = [(tr("Opening the file"), "active", tr("{n} pages so far", n=made) if made
                      else os.path.splitext(name)[1].upper().lstrip(".")),
                     (tr("Reading the page layout"), "todo", ""), (tr("Warming up the voice"), "todo", "")]
            card.set_state(name, steps, 0.08)
            if time.time() - started > 0.4:
                card.appear()
            return
        if not self.book:
            card.vanish()
            return
        b, p = self.book, self.page
        need = [q for q in (p - 1, p, p + 1) if 0 <= q < b.page_count]
        known = sum(1 for q in need if q in b.cache.pages)
        page_ok = b.ready(p) or b.no_text(p)
        scanned = b.is_scanned(p) or bool(b.cache.meta.get("ocr_kind"))
        lay_detail = ("OCR · " if scanned else "") + (tr("{known} of {total} pages", known=known, total=len(need))
                                                      if not page_ok else "")
        voice_ok = self.models.has_speaker(self.voice)
        steps = [(tr("Opening the file"), "done", ""),
                 (tr("Reading the page layout") + (" " + tr("(scanned)") if scanned else ""),
                  "done" if page_ok else "active", lay_detail.strip(" ·")),
                 (tr("Warming up the voice"), "done" if voice_ok else ("active" if page_ok or known else "todo"),
                  voices.display_name(self.voice))]
        fraction = 0.15 + 0.45 * (1.0 if page_ok else known / max(1, len(need) + 0.5)) + (0.2 if voice_ok else 0)
        smart = self.models.translator
        tr_ok = True
        if page_ok and voice_ok and not getattr(self, "_ready_at", None):
            self._ready_at = time.time()
        if self.translate and smart.best and smart.engine.available():
            st = smart.engine.status
            # never hold the reader more than 45 s for the AI: the fast translator covers until it's up
            tr_ok = st in ("gpu", "cpu", "failed") or (
                self._ready_at is not None and time.time() - self._ready_at > 45)
            detail = tr({"gpu": "graphics card", "cpu": "processor", "failed": "fast mode"}.get(st, "starting"))
            steps.append((tr("Starting the AI translator"), "done" if tr_ok else "active", detail))
            fraction += 0.2 if tr_ok else 0.05
        else:
            fraction += 0.2
        if page_ok and voice_ok and tr_ok:
            card.set_state(card.subtitle, steps, 1.0)
            card.vanish()
            return
        card.set_state(book_title(b), steps, fraction)
        if time.time() - started > 0.4:         # cached books open instantly: no flash
            card.appear()

    # ---- reading -----------------------------------------------------------------------
    def _toggle_play(self):
        if not self.player or self.stack.currentWidget() is not self.reader:
            return
        if self.player.paused:
            if self.player.current_key() is None or self.player.finished:
                self._start_at(self.resume_key or (self.page, -1))
            else:
                self.player.set_paused(False)
                self._set_follow(True)
        else:
            self.player.set_paused(True)
            self._save_position()

    def _start_at(self, key):
        if self.player:
            self.resume_key = None
            self._set_follow(True)
            self.book.want(key[0])
            self.player.play_from(key)

    def _clicked(self, x, y):
        if self.book:
            s = self.book.sentence_at(self.page, x, y)
            if s is not None:
                self._start_at(s.key)

    def _next_sentence(self):
        if self.player and self.player.current_key():
            s = self.book.next_after(self.player.current_key())
            if hasattr(s, "key"):
                self._start_at(s.key)

    def _prev_sentence(self):
        if self.player and self.player.current_key():
            s = self.book.prev_before(self.player.current_key())
            if s is not None:
                self._start_at(s.key)

    def _sentence_seconds(self, s):
        """Audio length of a sentence: measured if it has been spoken, else estimated."""
        if self.player and s.key in self.player.lengths:
            return self.player.lengths[s.key]
        text = "".join(w.text for w in s.words)
        cjk = sum(1 for ch in text if "぀" <= ch <= "鿿" or "가" <= ch <= "힯")
        other = sum(1 for w in s.words if not ("぀" <= w.text[:1] <= "鿿"))
        return (cjk / 4.2 + other / 2.6) / self.speed + s.pause

    def _jump(self, seconds):
        """Rewind / fast-forward by about `seconds`, landing on a sentence start."""
        if not self.player or not self.book:
            return
        cur = self.book.get(self.player.current_key() or self.resume_key or (self.page, -1))
        if not hasattr(cur, "key"):
            return
        into = self.player.seconds_into_current()
        s = cur
        if seconds < 0:
            left = -seconds - into
            while left > 0:
                prev = self.book.prev_before(s.key)
                if prev is None:
                    break
                s = prev
                left -= self._sentence_seconds(s)
        else:
            left = seconds - max(0.0, self._sentence_seconds(cur) - into)
            while left > 0:
                nxt = self.book.next_after(s.key)
                if not hasattr(nxt, "key"):
                    break
                s = nxt
                left -= self._sentence_seconds(s)
        paused = self.player.paused
        self._start_at(s.key)
        if paused:
            self.player.set_paused(True)
        self.stage.toast.show_message("⏪  " + tr("Back 30 seconds") if seconds < 0 else tr("Forward 30 seconds") + "  ⏩", ms=1200)

    def _step_speed(self, step):
        i = min(range(len(SPEEDS)), key=lambda k: abs(SPEEDS[k] - self.speed))
        self._set_speed(SPEEDS[max(0, min(len(SPEEDS) - 1, i + step))])
        self.stage.toast.show_message(tr("Speed {speed}×", speed=f"{self.speed:g}"), ms=1000)

    def _set_speed(self, v):
        self.speed = v
        self.speed_btn.setText(f"{v:g}×" if v != 1.0 else "1.0×")
        for s, a in self.speed_actions:
            a.setChecked(s == v)
        if self.player:
            self.player.set_speed(v)

    def _tick(self):
        alt = self.models.failed.get(self.voice)
        if alt:
            self.stage.toast.show_message(tr("The {name} voice couldn't be loaded — reading with {alt} instead",
                                             name=voices.display_name(self.voice), alt=voices.display_name(alt)), ms=6000)
            self.voice = alt
            self._apply_mode()
        self._update_loading()
        self._sleep_tick()
        if not self.player:
            return
        self.play_btn.set_playing(not self.player.paused)
        sentence, idx, spoken = self.player.state()
        if sentence is None:
            self.stage.page.set_highlight([], [])
            self.stage.subtitle.hide()
            return
        translated = spoken is not sentence.words
        rects = [r for w in sentence.words for r in w.rects]
        if translated:
            # the page shows the source sentence; the English words light up in the subtitle
            word = None
            target = sentence.page
            parts = []
            for i, w in enumerate(spoken):
                t = html.escape(w.text)
                parts.append(f'<span style="color:{T.GOLD_HI}">{t}</span>' if i == idx else t)
            # the top bar already says "Chinese → Spanish", so the box holds just the words
            self.stage.show_subtitle(f'<span style="color:{T.TEXT}">{" ".join(parts)}</span>')
        else:
            word = sentence.words[idx] if idx is not None else None
            target = word.rects[0][0] if word else sentence.page
            self.stage.subtitle.hide()
        # following the voice steps aside for a few seconds after the user scrolls
        following = self.follow and time.time() > self._follow_pause_until
        if following and target != self.page:
            self.page = target
            self._render()
        boxes = [r[1:] for r in (word.rects if word else []) if r[0] == self.page]
        self.stage.page.set_highlight(line_bars(rects, self.page), boxes)
        focus = boxes[0] if boxes else None
        if translated and sentence is not self.last_word:
            focus = next((r[1:] for r in rects if r[0] == self.page), None)
        if following and focus is not None and (word or sentence) is not self.last_word:
            r = self.stage.page.screen_rect(focus)
            # keep the reading spot in the upper-middle of the view, clear of the floating bars
            self.stage.scroll.ensureVisible(int(r.center().x()), int(r.center().y()), 60,
                                            320 if translated else 220)
        self.last_word = word or sentence

    # ---- window --------------------------------------------------------------------
    def dragEnterEvent(self, e):
        if any(convert.supported(u.toLocalFile()) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if convert.supported(u.toLocalFile()):
                self.open(u.toLocalFile())
                break

    def closeEvent(self, e):
        self._close_book()
        self.models.shutdown()
        super().closeEvent(e)


def run(path=None):
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BookTalker.Reader")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("BookTalker")
    app.setWindowIcon(QIcon(resource("booktalker.ico")))
    app.setStyleSheet(T.QSS)
    w = Main(path)
    w.show()
    return app.exec()
