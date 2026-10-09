"""Design tokens: colour, type, spacing. One place, used everywhere."""
from PySide6.QtGui import QColor, QFont

# Night library: deep ink chrome, warm gold accent (matches the icon).
INK_0 = "#0B0E14"        # canvas behind the page
INK_1 = "#11151D"        # bars
INK_2 = "#181D27"        # raised surfaces, cards
INK_3 = "#222937"        # hover
LINE = "#2A3242"         # hairlines
TEXT = "#ECEFF4"
TEXT_2 = "#A3ACBC"       # secondary
TEXT_3 = "#6B7586"       # tertiary / disabled
GOLD = "#F2B33D"
GOLD_HI = "#FFC95C"
GOLD_LO = "#C98E1F"
ON_GOLD = "#1A1405"

# On-page highlighter (multiplied over the page, so the print stays crisp)
SENTENCE_WASH = QColor(255, 238, 196)
WORD_MARK = QColor(255, 204, 64)

DISPLAY = "Bahnschrift"
UI = "Segoe UI"


def font(size, weight=QFont.Normal, family=UI, spacing=0.0):
    f = QFont(family)
    f.setPixelSize(size)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


QSS = f"""
* {{ font-family: "{UI}"; color: {TEXT}; }}
QMainWindow, #Root {{ background: {INK_0}; }}
QToolTip {{ background: {INK_2}; color: {TEXT}; border: 1px solid {LINE};
            padding: 6px 9px; border-radius: 6px; font-size: 12px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: #313a4b; border-radius: 4px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: #46526a; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: #313a4b; border-radius: 4px; min-width: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{ background: {INK_2}; border: 1px solid {LINE}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; font-size: 13px; }}
QMenu::item:selected {{ background: {INK_3}; }}
QMenu::item:checked {{ color: {GOLD}; }}
QLineEdit {{ background: {INK_2}; border: 1px solid {LINE}; border-radius: 8px;
             padding: 4px 8px; selection-background-color: {GOLD}; selection-color: {ON_GOLD}; }}
"""
