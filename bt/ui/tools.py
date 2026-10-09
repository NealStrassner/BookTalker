"""Dialogs for the reader's tools: saving a book as an audiobook, and the bookmark list."""
import os

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QProgressBar, QRadioButton, QVBoxLayout)

from . import theme as T
from .i18n import tr
from .widgets import PillButton

CSS = f"""
QDialog {{ background: {T.INK_2}; }}
QLabel {{ color: {T.TEXT}; }}
QRadioButton {{ color: {T.TEXT}; font-size: 13px; spacing: 8px; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 9px; border: 2px solid {T.TEXT_3}; background: transparent; }}
QRadioButton::indicator:checked {{ border: 2px solid {T.GOLD};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {T.GOLD}, stop:0.5 {T.GOLD}, stop:0.56 transparent); }}
QComboBox {{ background: {T.INK_3}; border: 1px solid {T.LINE}; border-radius: 8px; padding: 5px 8px; font-size: 13px; }}
QComboBox QAbstractItemView {{ background: {T.INK_2}; border: 1px solid {T.LINE};
    selection-background-color: {T.INK_3}; selection-color: {T.GOLD}; }}
QListWidget {{ background: {T.INK_1}; border: 1px solid {T.LINE}; border-radius: 10px; padding: 4px; font-size: 13px; }}
QListWidget::item {{ padding: 8px 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {T.INK_3}; color: {T.GOLD}; }}
QProgressBar {{ background: {T.INK_1}; border: 1px solid {T.LINE}; border-radius: 6px; height: 12px; text-align: center; }}
QProgressBar::chunk {{ background: {T.GOLD}; border-radius: 5px; }}
"""


def default_audiobook_folder():
    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
    return os.path.normpath(os.path.join(docs, "BookTalker Audiobooks"))


def _label(text, size=13, weight=QFont.Normal, color=T.TEXT):
    lab = QLabel(text)
    lab.setFont(T.font(size, weight))
    lab.setStyleSheet(f"color: {color};")
    lab.setWordWrap(True)
    return lab


class ExportDialog(QDialog):
    """Choose what to save and where; then the progress while it is made (in its own process)."""

    def __init__(self, parent, job, chapters, reading, folder):
        """job: the export job without first/last/out_root (bt/export.run); chapters: titles as
        shown (may be empty); reading: 'English translation — Lessac voice'; folder: last used."""
        super().__init__(parent)
        from ..export import folder_name
        self.job, self.proc, self.queue = dict(job), None, None
        self.setWindowTitle(tr("Save as audiobook"))
        self.setStyleSheet(CSS)
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(10)
        lay.addWidget(_label(job["title"], 18, QFont.DemiBold))
        sub = " · ".join(x for x in (job.get("author"), job.get("year")) if x)
        if sub:
            lay.addWidget(_label(sub, 13, color=T.TEXT_2))
        lay.addWidget(_label(tr("Read in: {how}", how=reading), 13, color=T.TEXT_2))
        lay.addSpacing(6)
        self.chapters = chapters
        self.all_btn = QRadioButton(tr("The whole book"))
        self.all_btn.setChecked(True)
        lay.addWidget(self.all_btn)
        self.some_btn = QRadioButton(tr("Chapters:"))
        self.from_box, self.to_box = QComboBox(), QComboBox()
        if chapters:
            for t in chapters:
                self.from_box.addItem(t)
                self.to_box.addItem(t)
            self.to_box.setCurrentIndex(len(chapters) - 1)
            row = QHBoxLayout()
            row.addWidget(self.some_btn)
            row.addWidget(self.from_box, 1)
            row.addWidget(_label(tr("to"), 13, color=T.TEXT_2))
            row.addWidget(self.to_box, 1)
            lay.addLayout(row)
            for b in (self.from_box, self.to_box):
                b.activated.connect(lambda _i: self.some_btn.setChecked(True))
        lay.addSpacing(6)
        lay.addWidget(_label(tr("Folder"), 12, QFont.DemiBold, T.TEXT_2))
        row = QHBoxLayout()
        self.folder = QLineEdit(folder or default_audiobook_folder())
        change = PillButton(tr("Change…"))
        change.setFixedHeight(34)
        change.clicked.connect(self._choose_folder)
        row.addWidget(self.folder, 1)
        row.addWidget(change)
        lay.addLayout(row)
        self.where = _label("", 12, color=T.TEXT_3)
        lay.addWidget(self.where)
        self._name = folder_name(job["title"], job.get("author"), job.get("year"))
        self.folder.textChanged.connect(self._show_where)
        self._show_where()
        self.status = _label("", 13, color=T.TEXT_2)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        lay.addWidget(self.status)
        lay.addWidget(self.bar)
        lay.addSpacing(8)
        row = QHBoxLayout()
        row.addStretch()
        self.open_btn = PillButton(tr("Open folder"))
        self.open_btn.clicked.connect(self._open_folder)
        self.open_btn.hide()
        self.close_btn = PillButton(tr("Close"))
        self.close_btn.clicked.connect(self._close_or_cancel)
        self.go_btn = PillButton(tr("Save audiobook"), "headphones", primary=True)
        self.go_btn.clicked.connect(self._start)
        for b in (self.open_btn, self.close_btn, self.go_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.done_folder = None

    def _show_where(self):
        self.where.setText(os.path.join(self.folder.text().strip(), self._name))

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Save audiobooks in"), self.folder.text())
        if d:
            self.folder.setText(os.path.normpath(d))

    def _start(self):
        import multiprocessing
        from .. import export
        job = dict(self.job, out_root=self.folder.text().strip(), titles=self.chapters)
        if self.chapters and self.some_btn.isChecked():
            a, b = self.from_box.currentIndex(), self.to_box.currentIndex()
            # the plan may begin with an 'Opening' part before chapter 1: export.plan aligns the
            # titles; first/last are given as chapter indexes and shifted there
            job["chapter_range"] = (min(a, b), max(a, b))
        os.makedirs(job["out_root"], exist_ok=True)
        ctx = multiprocessing.get_context("spawn")
        self.queue = ctx.Queue()
        self.proc = ctx.Process(target=export.run_job, args=(job, self.queue), daemon=True)
        self.proc.start()
        self.go_btn.hide()
        self.close_btn.setText(tr("Cancel"))
        self.bar.show()
        self.status.setText(tr("Getting ready…"))
        self.timer.start(300)

    def _poll(self):
        import queue as _q
        while True:
            try:
                msg = self.queue.get_nowait()
            except _q.Empty:
                break
            kind = msg[0]
            if kind == "prep":
                self.status.setText(tr("Preparing pages {pct}%", pct=int(msg[1] * 100)))
                self.bar.setValue(int(msg[1] * 100))
            elif kind == "start":
                self.files = msg[1]
                self.bar.setValue(0)
            elif kind == "file":
                self.status.setText(tr("Recording {n} of {total}: {title}", n=msg[1], total=self.files, title=msg[2]))
            elif kind == "progress":
                self.bar.setValue(int(msg[1] * 1000))
            elif kind == "done":
                self.done_folder = msg[1]
                self.status.setText(tr("Saved {n} files in {folder}", n=len(msg[2]), folder=msg[1]))
                self._finished()
            elif kind == "error":
                self.status.setText(tr("Couldn’t save the audiobook: {err}", err=msg[1].splitlines()[0]))
                self._finished()
        if self.proc is not None and not self.proc.is_alive() and self.timer.isActive() and self.queue.empty():
            if self.done_folder is None:
                self.status.setText(tr("Couldn’t save the audiobook: the recorder stopped"))
            self._finished()

    def _finished(self):
        self.timer.stop()
        self.proc = None
        self.close_btn.setText(tr("Close"))
        self.bar.setValue(1000 if self.done_folder else self.bar.value())
        self.open_btn.setVisible(bool(self.done_folder))

    def _open_folder(self):
        if self.done_folder and os.path.isdir(self.done_folder):
            os.startfile(self.done_folder)

    def _close_or_cancel(self):
        if self.proc is not None:                      # only the recorder this dialog started
            self.proc.terminate()
            self.proc = None
            self.timer.stop()
            self.status.setText(tr("Stopped."))
            self.close_btn.setText(tr("Close"))
            self.go_btn.show()
            return
        self.accept()

    def closeEvent(self, e):
        if self.proc is not None:
            self.proc.terminate()
        super().closeEvent(e)


class BookmarksDialog(QDialog):
    """The book's bookmarks: go to one, write a note on it, or remove it."""

    def __init__(self, parent, marks, go, save):
        """marks: list of dicts {key, page, text, note}; go(mark); save(marks)."""
        super().__init__(parent)
        self.marks, self.go, self.save = marks, go, save
        self.setWindowTitle(tr("Bookmarks"))
        self.setStyleSheet(CSS)
        self.setMinimumSize(560, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.addWidget(_label(tr("Bookmarks"), 18, QFont.DemiBold))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _it: self._go())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_note = PillButton(tr("Note…"))
        b_note.clicked.connect(self._note)
        b_del = PillButton(tr("Remove"))
        b_del.clicked.connect(self._remove)
        b_go = PillButton(tr("Go there"), primary=True)
        b_go.clicked.connect(self._go)
        for b in (b_note, b_del):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(b_go)
        lay.addLayout(row)
        self._fill()

    def _fill(self):
        self.list.clear()
        for m in self.marks:
            text = tr("Page {page}", page=m["page"] + 1) + "  —  " + m.get("text", "")
            if m.get("note"):
                text += "\n" + "✎  " + m["note"]
            it = QListWidgetItem(text)
            self.list.addItem(it)
        if self.marks:
            self.list.setCurrentRow(0)

    def _current(self):
        i = self.list.currentRow()
        return i if 0 <= i < len(self.marks) else None

    def _go(self):
        i = self._current()
        if i is not None:
            self.go(self.marks[i])
            self.accept()

    def _note(self):
        i = self._current()
        if i is None:
            return
        text, ok = QInputDialog.getMultiLineText(self, tr("Note"), tr("Your note for this place:"),
                                                 self.marks[i].get("note", ""))
        if ok:
            self.marks[i]["note"] = text.strip()
            self.save(self.marks)
            self._fill()
            self.list.setCurrentRow(i)

    def _remove(self):
        i = self._current()
        if i is not None:
            del self.marks[i]
            self.save(self.marks)
            self._fill()
