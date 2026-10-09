"""Line icons drawn as SVG (24-unit grid, 1.8 stroke, round caps), tinted on demand."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_S = 'fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
PATHS = {
    "play": '<path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" fill="{c}" stroke="none"/>',
    "pause": '<rect x="6.5" y="5" width="3.6" height="14" rx="1.2" fill="{c}"/><rect x="13.9" y="5" width="3.6" height="14" rx="1.2" fill="{c}"/>',
    "prev": f'<path d="M6 5v14" {_S}/><path d="M18 6.2v11.6a.8.8 0 0 1-1.25.66L9.4 12.66a.8.8 0 0 1 0-1.32l7.35-5.8A.8.8 0 0 1 18 6.2z" fill="{{c}}" stroke="none"/>',
    "next": f'<path d="M18 5v14" {_S}/><path d="M6 6.2v11.6a.8.8 0 0 0 1.25.66l7.35-5.8a.8.8 0 0 0 0-1.32L7.25 5.54A.8.8 0 0 0 6 6.2z" fill="{{c}}" stroke="none"/>',
    "open": f'<path d="M3.5 7.5V18a1.5 1.5 0 0 0 1.5 1.5h14a1.5 1.5 0 0 0 1.5-1.5V9.5A1.5 1.5 0 0 0 19 8h-7l-2-2.5H5A1.5 1.5 0 0 0 3.5 7z" {_S}/>',
    "zoom_in": f'<circle cx="10.5" cy="10.5" r="6" {_S}/><path d="M20 20l-5.2-5.2M10.5 8v5M8 10.5h5" {_S}/>',
    "zoom_out": f'<circle cx="10.5" cy="10.5" r="6" {_S}/><path d="M20 20l-5.2-5.2M8 10.5h5" {_S}/>',
    "fit": f'<path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15" {_S}/>',
    "follow": f'<circle cx="12" cy="12" r="7" {_S}/><circle cx="12" cy="12" r="2.4" fill="{{c}}" stroke="none"/><path d="M12 2.5V5M12 19v2.5M2.5 12H5M19 12h2.5" {_S}/>',
    "info": f'<circle cx="12" cy="12" r="8.5" {_S}/><path d="M12 11v5.5" {_S}/><circle cx="12" cy="7.8" r="1.1" fill="{{c}}" stroke="none"/>',
    "book": f'<path d="M12 6.5C10 5 7 4.6 4 5v13c3-.4 6 0 8 1.5 2-1.5 5-1.9 8-1.5V5c-3-.4-6 0-8 1.5zM12 6.5v13" {_S}/>',
    "speed": f'<path d="M5 16a7 7 0 1 1 14 0" {_S}/><path d="M12 16l3.5-4.5" {_S}/><circle cx="12" cy="16" r="1.3" fill="{{c}}" stroke="none"/>',
    "close": f'<path d="M6 6l12 12M18 6L6 18" {_S}/>',
    "drop": f'<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5" {_S}/><path d="M4.5 15.5v2A2.5 2.5 0 0 0 7 20h10a2.5 2.5 0 0 0 2.5-2.5v-2" {_S}/>',
    "back30": f'<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" {_S}/><path d="M6.5 2.8v4h4" {_S}/>'
              '<text x="12.2" y="15.6" font-family="Segoe UI" font-weight="700" font-size="8.4" text-anchor="middle" fill="{c}">30</text>',
    "fwd30": f'<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" {_S}/><path d="M17.5 2.8v4h-4" {_S}/>'
             '<text x="11.8" y="15.6" font-family="Segoe UI" font-weight="700" font-size="8.4" text-anchor="middle" fill="{c}">30</text>',
    "globe":f'<circle cx="12" cy="12" r="8.5" {_S}/><path d="M3.5 12h17M12 3.5c2.5 2.4 3.6 5.3 3.6 8.5s-1.1 6.1-3.6 8.5M12 3.5C9.5 5.9 8.4 8.8 8.4 12s1.1 6.1 3.6 8.5" {_S}/>',
    "keyboard":f'<rect x="2.5" y="6" width="19" height="12" rx="2" {_S}/><path d="M6 10h.01M9.5 10h.01M13 10h.01M16.5 10h.01M7.5 14h9" {_S}/>',
    "page_prev": f'<path d="M14.5 6l-6 6 6 6" {_S}/>',
    "page_next": f'<path d="M9.5 6l6 6-6 6" {_S}/>',
    "nav_up": f'<path d="M6 14.5l6-6 6 6" {_S}/>',
    "nav_down": f'<path d="M6 9.5l6 6 6-6" {_S}/>',
    "search": f'<circle cx="10.5" cy="10.5" r="6" {_S}/><path d="M20 20l-5.2-5.2" {_S}/>',
    "moon": f'<path d="M19.5 14.2A7.8 7.8 0 0 1 9.8 4.5a7.8 7.8 0 1 0 9.7 9.7z" {_S}/>',
    "bookmark": f'<path d="M7 4.5h10a1 1 0 0 1 1 1v14l-6-4-6 4v-14a1 1 0 0 1 1-1z" {_S}/>',
    "headphones": f'<path d="M4.5 15v-3a7.5 7.5 0 0 1 15 0v3" {_S}/><rect x="3.5" y="14" width="4" height="6" rx="1.4" {_S}/><rect x="16.5" y="14" width="4" height="6" rx="1.4" {_S}/>',
    "chapters": f'<path d="M9 6.5h11M9 12h11M9 17.5h11" {_S}/><circle cx="4.8" cy="6.5" r="1.1" fill="{{c}}" stroke="none"/><circle cx="4.8" cy="12" r="1.1" fill="{{c}}" stroke="none"/><circle cx="4.8" cy="17.5" r="1.1" fill="{{c}}" stroke="none"/>',
}


def svg(name, color):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{PATHS[name].format(c=color)}</svg>'


def pixmap(name, color, size, dpr=2.0):
    r = QSvgRenderer(QByteArray(svg(name, color).encode()))
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name, color, size=20, active_color=None):
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    if active_color:
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Normal, QIcon.On)
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Active, QIcon.On)
    return ic
