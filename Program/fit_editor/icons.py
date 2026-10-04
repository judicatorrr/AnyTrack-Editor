"""Small Fluent-style SVG icon pack used consistently across the application."""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6 import QtCore, QtGui, QtSvg


PATHS = {
    "open": '<path d="M3 7h7l2 2h9l-2 10H4z"/><path d="M3 7V5h7l2 2h7v2"/>',
    "upload": '<path d="M12 16V5m-4 4 4-4 4 4"/><path d="M5 15v4h14v-4"/>',
    "save": '<path d="M5 3h12l2 2v16H5z"/><path d="M8 3v6h8V3M8 21v-7h8v7"/>',
    "convert": '<path d="M3 3h7l2 2v7H3zM9 3v3h3"/><path d="M12 12h7l2 2v7h-9zM18 12v3h3"/><path d="M14 5h5v5m0-5-5 5M10 19H5v-5m0 5 5-5"/>',
    "route_create": '<path d="M5 11S2 8.2 2 5a3 3 0 1 1 6 0c0 3.2-3 6-3 6z"/><circle cx="5" cy="5" r="1"/><path d="M19 23s-3-2.8-3-6a3 3 0 1 1 6 0c0 3.2-3 6-3 6z"/><circle cx="19" cy="17" r="1"/><path d="M7 9c3 1 2 5 5 5s2-4 5-3" stroke-dasharray="2.2 2.2"/>',
    "add": '<path d="M12 4v16M4 12h16"/>',
    "close": '<path d="M5 5l14 14M19 5 5 19"/>',
    "track_check": '<path d="M12 22s-7-6.1-7-12a7 7 0 1 1 14 0c0 5.9-7 12-7 12z"/><path d="m9 10 2 2 4-4"/>',
    "cloud": '<path d="M6.5 19H18a4 4 0 0 0 .5-8A6.5 6.5 0 0 0 6.1 9.2 5 5 0 0 0 6.5 19z"/>',
    "local_network": '<rect x="4" y="4" width="16" height="11" rx="2"/><path d="M8 20h8M12 15v5"/><circle cx="8" cy="9.5" r="1"/><circle cx="16" cy="9.5" r="1"/><path d="M9 9.5h6"/>',
    "download": '<path d="M12 3v12m-4-4 4 4 4-4"/><path d="M5 19h14"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.7 2.7 0 1 1 3.6 2.55c-.9.36-1.1 1-1.1 2"/><path d="M12 17.5v.2"/>',
    "play": '<path d="M8 5v14l11-7z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "server_check": '<rect x="4" y="4" width="16" height="11" rx="2"/><path d="M8 20h8M12 15v5M8 9l2 2 5-5"/>',
    "undo": '<path d="m9 7-5 5 5 5"/><path d="M5 12h8a6 6 0 0 1 6 6"/>',
    "redo": '<path d="m15 7 5 5-5 5"/><path d="M19 12h-8a6 6 0 0 0-6 6"/>',
    "layout_vertical": '<rect x="4" y="3" width="16" height="7" rx="1"/><rect x="4" y="14" width="16" height="7" rx="1"/>',
    "layout_horizontal": '<rect x="3" y="4" width="7" height="16" rx="1"/><rect x="14" y="4" width="7" height="16" rx="1"/>',
    "fit": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "trash": '<path d="M5 7h14M9 4h6l1 3M7 7l1 14h8l1-14M10 11v6M14 11v6"/>',
    "delete": '<path d="M5 7h14M9 4h6l1 3M7 7l1 14h8l1-14M10 11v6M14 11v6"/>',
    "cycling": '<circle cx="6" cy="17" r="4"/><circle cx="18" cy="17" r="4"/><path d="m6 17 4-8 4 8H6l5-5h5M14 6h4M16 6l2 11"/>',
    "running": '<circle cx="14" cy="4.5" r="2"/><path d="m6 10 4-3 4 3 4 1M12 9l-2 5 5 3-1 4M10 14l-4 5H2"/>',
    "walking": '<circle cx="13" cy="4.5" r="2"/><path d="m9 21 2-7-3-3-2 4M11 8l3 4 4 1M14 12l1 4 4 4"/>',
    "car": '<path d="m4 15 2-6h12l2 6v4H4z"/><path d="M7 9l2-4h6l2 4"/><circle cx="7" cy="18" r="1.5"/><circle cx="17" cy="18" r="1.5"/>',
    "direct": '<circle cx="5" cy="18" r="2"/><circle cx="19" cy="6" r="2"/><path d="M7 16 17 8"/>',
    "mountain": '<circle cx="6" cy="17" r="4"/><circle cx="18" cy="17" r="4"/><path d="m6 17 4-8 4 8H6l5-5h5M14 6h4M16 6l2 11M3 7l3-4 3 4"/>',
    "river": '<path d="M4 14l3 4h10l3-4M7 14l5-7 5 7M12 7V3"/><path d="M3 21c2-2 4 2 6 0s4 2 6 0 4 2 6 0"/>',
    "scissors": '<circle cx="6" cy="7" r="3"/><circle cx="6" cy="17" r="3"/><path d="m8.5 8.5 11 9M8.5 15.5l11-9"/>',
    "edit": '<path d="M4 20h4l11-11-4-4L4 16zM13.5 6.5l4 4"/>',
    "zoom": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6M7 10h6M10 7v6"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "route_from_track": '<path d="M4 18c4-9 8 3 12-6"/><path d="m14 10 2 2 2-2"/><circle cx="4" cy="18" r="2"/><circle cx="19" cy="6" r="2"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
    "distance": '<path d="M4 12h16M4 12l4-4M4 12l4 4M20 12l-4-4M20 12l-4 4"/>',
    "altitude": '<path d="M3 20 10 7l3 5 2-3 6 11z"/><path d="m8 11 2 2 2-2"/>',
    "points": '<circle cx="5" cy="15" r="2"/><circle cx="11" cy="7" r="2"/><circle cx="19" cy="17" r="2"/><path d="m6.5 13.5 3-4.5m3 0 5 6.5"/>',
    "heart": '<path d="M12 20S4 15.5 4 9a4 4 0 0 1 7-2.5L12 8l1-1.5A4 4 0 0 1 20 9c0 6.5-8 11-8 11z"/>',
    "speed": '<path d="M5 18a8 8 0 1 1 14 0M12 14l5-5"/><circle cx="12" cy="14" r="1"/>',
    "power": '<path d="m14 2-8 12h6l-2 8 8-12h-6z"/>',
}


def icon(kind: str, colour: str = "#e7e9ee") -> QtGui.QIcon:
    body = PATHS.get(kind, PATHS["help"])
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{colour}" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    ).encode("utf-8")
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg))
    pixmap = QtGui.QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    renderer.render(painter, QtCore.QRectF(0, 0, 24, 24))
    painter.end()
    return QtGui.QIcon(pixmap)


def _resource_path(relative_path: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / relative_path


def route_pin_icon(colour: str = "#e7e9ee") -> QtGui.QIcon:
    """Colourise the supplied black-on-white pin as a transparent UI icon."""
    source = QtGui.QImage(str(_resource_path("assets/route_pin.png")))
    if source.isNull():
        return icon("route_create", colour)
    alpha = source.convertToFormat(QtGui.QImage.Format.Format_Grayscale8)
    alpha.invertPixels()
    result = QtGui.QImage(source.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(QtGui.QColor(colour))
    result.setAlphaChannel(alpha)
    return QtGui.QIcon(QtGui.QPixmap.fromImage(result))


@lru_cache(maxsize=1)
def route_pin_cursor() -> QtGui.QCursor:
    """Build the route-placement cursor from the supplied pin artwork."""
    source = QtGui.QImage(str(_resource_path("assets/route_pin.png")))
    if source.isNull():
        return QtGui.QCursor(QtCore.Qt.CursorShape.CrossCursor)
    alpha = source.convertToFormat(QtGui.QImage.Format.Format_Grayscale8)
    alpha.invertPixels()
    result = QtGui.QImage(source.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(QtGui.QColor("#050505"))
    result.setAlphaChannel(alpha)
    pixmap = QtGui.QPixmap.fromImage(result).scaled(
        34, 34,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )
    return QtGui.QCursor(pixmap, pixmap.width() // 2, pixmap.height() - 1)
