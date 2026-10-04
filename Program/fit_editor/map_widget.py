from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import shutil
import time
import numpy as np

from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets

from . import __version__
from .icons import icon as pack_icon, route_pin_cursor


TILE_SIZE = 256
MAX_LATITUDE = 85.05112878
WGS84_ECCENTRICITY = 0.08181919084262149


@dataclass(frozen=True)
class TileProvider:
    key: str
    title: str
    url: str
    attribution: str


@dataclass
class RouteTrack:
    """One coloured activity rendered as one or more continuous segments."""

    segments: list[list[tuple[float, float]]]
    colour: str
    active: bool = False
    name: str = ""


class FloatingMapControls(QtWidgets.QFrame):
    """One independently draggable top/bottom map-control panel."""

    def __init__(self, owner: "MapWidget", control_key: str):
        super().__init__(owner)
        self.owner = owner
        self.control_key = control_key
        self._drag_global: QtCore.QPointF | None = None
        self._drag_origin_y = 0
        self.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_global = event.globalPosition()
            self._drag_origin_y = self.y()
            self.raise_()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_global is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            delta = event.globalPosition() - self._drag_global
            self.owner._move_overlay(self, self._drag_origin_y + int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_global is not None and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_global = None
            self.owner._snap_overlay(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)


PROVIDERS = {
    "osm": TileProvider(
        "osm",
        "OpenStreetMap",
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "© OpenStreetMap contributors",
    ),
    "google": TileProvider(
        "google",
        "Google Maps",
        "https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        "© Google",
    ),
    "yandex": TileProvider(
        "yandex",
        "Яндекс.Карты",
        "https://core-renderer-tiles.maps.yandex.com.tr/tiles?l=map&x={x}&y={y}&z={z}&lang=ru_RU&scale=1",
        "© Яндекс",
    ),
}


def _world_size(zoom: int) -> float:
    return float(TILE_SIZE * (2**zoom))


def _latlon_to_world(
    lat: float,
    lon: float,
    zoom: int,
    *,
    ellipsoidal: bool = False,
) -> QtCore.QPointF:
    lat = max(-MAX_LATITUDE, min(MAX_LATITUDE, lat))
    size = _world_size(zoom)
    x = (lon + 180.0) / 360.0 * size
    sine = math.sin(math.radians(lat))
    mercator = math.log((1.0 + sine) / (1.0 - sine))
    if ellipsoidal:
        eccentric_sine = WGS84_ECCENTRICITY * sine
        mercator -= WGS84_ECCENTRICITY * math.log(
            (1.0 + eccentric_sine) / (1.0 - eccentric_sine)
        )
    y = (0.5 - mercator / (4.0 * math.pi)) * size
    return QtCore.QPointF(x, y)


def _world_to_latlon(
    point: QtCore.QPointF,
    zoom: int,
    *,
    ellipsoidal: bool = False,
) -> tuple[float, float]:
    size = _world_size(zoom)
    lon = point.x() / size * 360.0 - 180.0
    mercator = math.pi - 2.0 * math.pi * point.y() / size
    latitude = 2.0 * math.atan(math.exp(mercator)) - math.pi / 2.0
    if ellipsoidal:
        for _ in range(7):
            sine = math.sin(latitude)
            correction = ((1.0 + WGS84_ECCENTRICITY * sine) /
                          (1.0 - WGS84_ECCENTRICITY * sine)) ** (WGS84_ECCENTRICITY / 2.0)
            latitude = 2.0 * math.atan(math.exp(mercator) * correction) - math.pi / 2.0
    lat = math.degrees(latitude)
    return lat, lon


def _haversine_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1 = first
    lat2, lon2 = second
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


class MapWidget(QtWidgets.QWidget):
    """Small native slippy-map widget with an on-disk tile cache."""

    cacheDownloadProgress = QtCore.Signal(int, int)
    cacheDownloadFinished = QtCore.Signal(int, int)
    mapClicked = QtCore.Signal(float, float)
    routePointRequested = QtCore.Signal(float, float, int)
    waypointMoved = QtCore.Signal(int, float, float)
    waypointRemoveRequested = QtCore.Signal(int)
    anomalyClicked = QtCore.Signal(int)
    searchMessage = QtCore.Signal(str)
    overlayLaneChanged = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._provider = PROVIDERS["osm"]
        self._track_routes: list[RouteTrack] = []
        self._route_revision = self._selection_revision = self._tile_revision = 0
        self._base_key = self._selection_key = None
        self._cursor_point: tuple[float, float, str] | None = None
        self._anomaly_points: list[tuple[float, float, bool]] = []
        self._waypoints: list[tuple[float, float]] = []
        self._draft_route: list[tuple[float, float]] = []
        self._point_selection_enabled = False
        # Flattened compatibility view retained for older callers/tests.
        self._routes: list[list[tuple[float, float]]] = []
        self._center_lat = 55.751244
        self._center_lon = 37.618423
        self._zoom = 5
        self._pixmaps: dict[tuple[str, int, int, int], QtGui.QPixmap] = {}
        # Tiles are raster images. On a Windows display scaled to 125–200%,
        # drawing a 256 px tile directly into 256 device-independent pixels
        # makes Qt enlarge it with the fast (jagged) transform. Keep a small
        # DPR-aware, smoothly resampled display cache instead.
        self._display_pixmaps: dict[tuple[str, int, int, int, int], QtGui.QPixmap] = {}
        self._pending: set[tuple[str, int, int, int]] = set()
        self._offline_queue: list[tuple[str, int, int, int]] = []
        self._offline_total = 0
        self._offline_done = 0
        self._offline_failed = 0
        self._offline_active = 0
        self._offline_max_concurrent = 8
        self._language = "ru"
        self._theme = "dark"
        self._drag_position: QtCore.QPointF | None = None
        self._drag_waypoint_index = -1
        self._hover_waypoint_index = -1
        self._press_position: QtCore.QPointF | None = None
        self._dragged = False
        self._manager = QtNetwork.QNetworkAccessManager(self)
        self._geocode_reply: QtNetwork.QNetworkReply | None = None
        self._geocode_last_request = 0.0
        self._geocode_cache = self._load_geocode_cache()
        self._tile_refresh_timer = QtCore.QTimer(self)
        self._tile_refresh_timer.setSingleShot(True)
        self._tile_refresh_timer.setInterval(33)
        self._tile_refresh_timer.timeout.connect(self._flush_tile_refresh)
        cache_root = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.CacheLocation)
        self._cache_root = Path(cache_root) / "map_tiles"
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._build_overlay()

    def _build_overlay(self) -> None:
        self._overlay_corner = "top_right"
        self._overlay_vertical = "top"
        self._overlay_verticals = {"map": "top", "search": "top"}
        self.overlay = FloatingMapControls(self, "map")
        self.overlay.setObjectName("mapOverlay")
        self._apply_overlay_theme()
        layout = QtWidgets.QHBoxLayout(self.overlay)
        layout.setContentsMargins(8, 6, 6, 6)
        layout.setSpacing(6)
        self.provider_combo = QtWidgets.QComboBox()
        for key in ("osm", "yandex", "google"):
            self.provider_combo.addItem(PROVIDERS[key].title, key)
        self.fit_button = QtWidgets.QPushButton()
        self.fit_button.setFixedSize(34, 34)
        self.fit_button.setIcon(self._fit_route_icon())
        self.fit_button.setIconSize(QtCore.QSize(20, 20))
        self.download_button = QtWidgets.QToolButton()
        self.download_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.download_button.setIcon(pack_icon("download"))
        self.download_button.setIconSize(QtCore.QSize(18, 18))
        self.download_button.setMinimumHeight(34)
        self.provider_combo.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.download_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.fit_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.provider_combo)
        layout.addWidget(self.download_button)
        layout.addWidget(self.fit_button)
        self.provider_combo.currentIndexChanged.connect(
            lambda: self.set_provider(str(self.provider_combo.currentData()))
        )
        self.fit_button.clicked.connect(self.fit_route)
        self.overlay.adjustSize()
        self.overlay.raise_()

        self.search_overlay = FloatingMapControls(self, "search")
        self.search_overlay.setObjectName("mapSearchOverlay")
        search_layout = QtWidgets.QHBoxLayout(self.search_overlay)
        search_layout.setContentsMargins(7, 6, 6, 6)
        search_layout.setSpacing(5)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setMinimumWidth(245)
        self.search_edit.setClearButtonEnabled(True)
        self.search_button = QtWidgets.QToolButton()
        self.search_button.setIcon(pack_icon("search"))
        self.search_button.setIconSize(QtCore.QSize(18, 18))
        self.search_button.setFixedSize(34, 34)
        self.search_edit.setCursor(QtCore.Qt.CursorShape.IBeamCursor)
        self.search_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.search_source_label = QtWidgets.QLabel("© OSM")
        self.search_source_label.setObjectName("searchSource")
        search_layout.addWidget(self.search_edit)
        search_layout.addWidget(self.search_button)
        search_layout.addWidget(self.search_source_label)
        self.search_edit.returnPressed.connect(self._start_place_search)
        self.search_button.clicked.connect(self._start_place_search)
        self.search_overlay.adjustSize()
        self.search_overlay.raise_()
        self.search_overlay.hide()

        self.zoom_controls = QtWidgets.QFrame(self)
        self.zoom_controls.setObjectName("mapZoomControls")
        zoom_layout = QtWidgets.QVBoxLayout(self.zoom_controls)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(0)
        self.zoom_in_button = QtWidgets.QToolButton()
        self.zoom_out_button = QtWidgets.QToolButton()
        for button, label in (
            (self.zoom_in_button, "+"),
            (self.zoom_out_button, "−"),
        ):
            button.setText(label)
            button.setFixedSize(38, 38)
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            zoom_layout.addWidget(button)
        self.zoom_in_button.clicked.connect(lambda: self._zoom_by(1))
        self.zoom_out_button.clicked.connect(lambda: self._zoom_by(-1))
        self.zoom_controls.adjustSize()
        self.zoom_controls.raise_()
        self._apply_overlay_theme()
        self.set_language("ru")

    @staticmethod
    def _load_geocode_cache() -> dict[str, list[dict[str, object]]]:
        raw = str(QtCore.QSettings("VJ Ostrov", "Track Editor").value("geocoder/cache", "{}"))
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _save_geocode_cache(self) -> None:
        # Keep a modest persistent cache. Searches only happen on Enter/click,
        # never while the user types, which also respects Nominatim's policy.
        while len(self._geocode_cache) > 60:
            self._geocode_cache.pop(next(iter(self._geocode_cache)))
        QtCore.QSettings("VJ Ostrov", "Track Editor").setValue(
            "geocoder/cache", json.dumps(self._geocode_cache, ensure_ascii=False)
        )

    def _start_place_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query or self._geocode_reply is not None:
            return
        cache_key = query.casefold()
        if cache_key in self._geocode_cache:
            self._show_search_results(self._geocode_cache[cache_key])
            return
        wait_ms = max(0, int((1.05 - (time.monotonic() - self._geocode_last_request)) * 1000))
        if wait_ms:
            QtCore.QTimer.singleShot(wait_ms, self._start_place_search)
            return
        url = QtCore.QUrl("https://nominatim.openstreetmap.org/search")
        params = QtCore.QUrlQuery()
        params.addQueryItem("q", query)
        params.addQueryItem("format", "jsonv2")
        params.addQueryItem("limit", "5")
        url.setQuery(params)
        request = QtNetwork.QNetworkRequest(url)
        request.setRawHeader(
            b"User-Agent",
            f"AnyTrack-Editor/{__version__} desktop route editor".encode("ascii"),
        )
        request.setRawHeader(b"Accept-Language", self._language.encode("ascii", "ignore"))
        self._geocode_last_request = time.monotonic()
        self.search_button.setEnabled(False)
        self.searchMessage.emit(
            "Поиск места…" if self._language == "ru" else "Searching for a place…"
        )
        self._geocode_reply = self._manager.get(request)
        self._geocode_reply.finished.connect(
            lambda key=cache_key: self._place_search_finished(key)
        )

    def _place_search_finished(self, cache_key: str) -> None:
        reply = self._geocode_reply
        self._geocode_reply = None
        self.search_button.setEnabled(True)
        if reply is None:
            return
        try:
            if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                raise RuntimeError(reply.errorString())
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            results = [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
            self._geocode_cache[cache_key] = results
            self._save_geocode_cache()
            self._show_search_results(results)
        except Exception as error:
            self.searchMessage.emit(
                ("Поиск недоступен без интернета: " if self._language == "ru" else
                 "Search is unavailable without internet: ") + str(error)
            )
        finally:
            reply.deleteLater()

    def _show_search_results(self, results: list[dict[str, object]]) -> None:
        if not results:
            self.searchMessage.emit(
                "Ничего не найдено" if self._language == "ru" else "No places found"
            )
            return
        menu = QtWidgets.QMenu(self)
        for item in results[:5]:
            try:
                latitude = float(item["lat"])
                longitude = float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            label = str(item.get("display_name") or f"{latitude:.5f}, {longitude:.5f}")
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, lat=latitude, lon=longitude, text=label:
                self._choose_search_result(lat, lon, text)
            )
        if menu.actions():
            menu.popup(self.search_edit.mapToGlobal(QtCore.QPoint(0, self.search_edit.height() + 5)))

    def _choose_search_result(self, latitude: float, longitude: float, label: str) -> None:
        self.centre_on(latitude, longitude, minimum_zoom=14)
        self.search_edit.setText(label)
        self.searchMessage.emit(
            "Место показано на карте" if self._language == "ru" else "Place shown on map"
        )

    @staticmethod
    def _fit_route_icon(colour: str = "#d7dce5") -> QtGui.QIcon:
        return pack_icon("fit", colour)

    def set_language(self, language: str) -> None:
        self._language = language
        if language == "en":
            provider_tooltip = "Map provider"
            tooltip = "Fit entire route"
            download_text = "Download map"
            move_tooltip = "Drag this panel by its background to move it to another corner"
            search_placeholder = "Find a place or address"
            search_tooltip = "Online OpenStreetMap search · press Enter"
            zoom_in_tooltip = "Zoom in"
            zoom_out_tooltip = "Zoom out"
        else:
            provider_tooltip = "Выбор карты"
            tooltip = "Показать весь маршрут"
            download_text = "Скачать карту"
            move_tooltip = "Потяните панель за фон, чтобы переместить её в другой угол"
            search_placeholder = "Найти место или адрес"
            search_tooltip = "Онлайн-поиск OpenStreetMap · нажмите Enter"
            zoom_in_tooltip = "Приблизить карту"
            zoom_out_tooltip = "Отдалить карту"
        self.provider_combo.setToolTip(provider_tooltip)
        self.provider_combo.setAccessibleName(provider_tooltip)
        self.fit_button.setToolTip(tooltip)
        self.fit_button.setAccessibleName(tooltip)
        if self.download_button.defaultAction() is None:
            self.download_button.setText(download_text)
        self.overlay.setToolTip(move_tooltip)
        self.search_overlay.setToolTip(move_tooltip)
        self.search_edit.setPlaceholderText(search_placeholder)
        self.search_edit.setToolTip(search_tooltip)
        self.search_button.setToolTip(search_tooltip)
        self.search_source_label.setToolTip("© OpenStreetMap contributors")
        self.zoom_in_button.setToolTip(zoom_in_tooltip)
        self.zoom_out_button.setToolTip(zoom_out_tooltip)
        self.zoom_in_button.setAccessibleName(zoom_in_tooltip)
        self.zoom_out_button.setAccessibleName(zoom_out_tooltip)
        self.overlay.adjustSize()
        self.search_overlay.adjustSize()
        self._position_overlays()

    def set_download_visible(self, visible: bool) -> None:
        self.download_button.setVisible(visible)
        self.overlay.adjustSize()
        self._position_overlays()

    def set_search_visible(self, visible: bool) -> None:
        self.search_overlay.setVisible(bool(visible))
        self._position_overlays()

    def set_theme(self, theme: str) -> None:
        self._theme = "light" if theme == "light" else "dark"
        self._apply_overlay_theme()
        self.fit_button.setIcon(
            self._fit_route_icon("#263445" if self._theme == "light" else "#d7dce5")
        )
        self.download_button.setIcon(
            pack_icon("download", "#263445" if self._theme == "light" else "#d7dce5")
        )
        self.search_button.setIcon(
            pack_icon("search", "#263445" if self._theme == "light" else "#d7dce5")
        )
        self._base_key = self._selection_key = None
        self.update()

    def _apply_overlay_theme(self) -> None:
        if not hasattr(self, "overlay"):
            return
        if self._theme == "light":
            frame = "background:rgba(250,251,253,238); border:1px solid #b8c0cc;"
            separator = "#c9d0da"
        else:
            frame = "background:rgba(28,32,39,235); border:1px solid #48515f;"
            separator = "#48515f"
        self.overlay.setStyleSheet(
            f"QFrame#mapOverlay {{ {frame} border-radius:7px; }}"
            "QLabel { background:transparent; border:none; }"
            "QComboBox { min-width:132px; }"
            "QPushButton { padding:0; }"
            "QToolButton { padding:5px 9px; }"
        )
        if hasattr(self, "search_overlay"):
            self.search_overlay.setStyleSheet(
                f"QFrame#mapSearchOverlay {{ {frame} border-radius:7px; }}"
                "QLineEdit { min-height:22px; padding:5px 8px; }"
                "QToolButton { padding:0; }"
                "QLabel#searchSource { color:#89909b; font-size:9px; padding:0 2px; }"
            )
        if hasattr(self, "zoom_controls"):
            self.zoom_controls.setStyleSheet(
                f"QFrame#mapZoomControls {{ {frame} border-radius:7px; }}"
                "QToolButton { background:transparent; border:none; border-radius:0; "
                "font-size:22px; font-weight:600; padding:0; }"
                "QToolButton:hover { background:rgba(90,150,210,55); }"
            )
            self.zoom_in_button.setStyleSheet(
                f"border-bottom:1px solid {separator}; border-top-left-radius:7px; "
                "border-top-right-radius:7px;"
            )

    @property
    def _ellipsoidal_projection(self) -> bool:
        return self._provider.key == "yandex"

    def _to_world(self, lat: float, lon: float, zoom: int | None = None) -> QtCore.QPointF:
        return _latlon_to_world(
            lat,
            lon,
            self._zoom if zoom is None else zoom,
            ellipsoidal=self._ellipsoidal_projection,
        )

    def _from_world(self, point: QtCore.QPointF, zoom: int | None = None) -> tuple[float, float]:
        return _world_to_latlon(
            point,
            self._zoom if zoom is None else zoom,
            ellipsoidal=self._ellipsoidal_projection,
        )

    @property
    def provider_key(self) -> str:
        return self._provider.key

    def set_provider(self, key: str) -> None:
        if key not in PROVIDERS or key == self._provider.key:
            return
        self._provider = PROVIDERS[key]
        self._pending.clear()
        self.update()

    def set_cursor_point(self, lat: float, lon: float, colour: str = "#4DA3FF") -> None:
        if not math.isfinite(lat) or not math.isfinite(lon):
            self.clear_cursor_point()
            return
        value = (float(lat), float(lon), str(colour))
        if value == self._cursor_point:
            return
        self._cursor_point = value
        self.update()

    def clear_cursor_point(self) -> None:
        if self._cursor_point is not None:
            self._cursor_point = None
            self.update()

    def set_anomaly_points(self, points: list[tuple[float, float]], selected: int = -1) -> None:
        self._anomaly_points = [
            (float(lat), float(lon), index == selected)
            for index, (lat, lon) in enumerate(points)
            if math.isfinite(lat) and math.isfinite(lon)
        ]
        self._selection_revision += 1
        self.update()

    def clear_anomaly_points(self) -> None:
        if self._anomaly_points:
            self._anomaly_points = []
            self._selection_revision += 1
            self.update()

    def _anomaly_index_at(self, position: QtCore.QPointF) -> int:
        if not self._anomaly_points:
            return -1
        center = self._to_world(self._center_lat, self._center_lon)
        origin = center - QtCore.QPointF(self.width() / 2.0, self.height() / 2.0)
        nearest = -1
        nearest_distance = 18.0
        for index, (latitude, longitude, _selected) in enumerate(self._anomaly_points):
            point = self._to_world(latitude, longitude) - origin
            distance = (point - position).manhattanLength()
            if distance <= nearest_distance:
                nearest = index
                nearest_distance = distance
        return nearest

    def centre_on(self, lat: float, lon: float, minimum_zoom: int = 14) -> None:
        if not math.isfinite(lat) or not math.isfinite(lon):
            return
        self._center_lat, self._center_lon = float(lat), float(lon)
        self._zoom = max(self._zoom, int(minimum_zoom))
        self._update_zoom_buttons()
        self.update()

    def _update_zoom_buttons(self) -> None:
        if hasattr(self, "zoom_in_button"):
            self.zoom_in_button.setEnabled(self._zoom < 19)
            self.zoom_out_button.setEnabled(self._zoom > 2)

    def _zoom_by(self, steps: int) -> None:
        new_zoom = max(2, min(19, self._zoom + int(steps)))
        if new_zoom == self._zoom:
            return
        self._zoom = new_zoom
        self._update_zoom_buttons()
        self.update()

    def set_point_selection_enabled(self, enabled: bool) -> None:
        self._point_selection_enabled = bool(enabled)
        self.setCursor(self._pin_cursor() if enabled else QtCore.Qt.CursorShape.ArrowCursor)

    @staticmethod
    def _pin_cursor() -> QtGui.QCursor:
        return route_pin_cursor()

    def set_waypoints(self, points: list[tuple[float, float]]) -> None:
        self._waypoints = [
            (float(lat), float(lon)) for lat, lon in points
            if math.isfinite(lat) and math.isfinite(lon)
        ]
        self._selection_revision += 1
        self.update()

    def set_route_draft(
        self,
        coordinates: list[tuple[float, float, float | None]],
        waypoints: list[tuple[float, float]],
    ) -> None:
        self._draft_route = [
            (float(point[0]), float(point[1])) for point in coordinates
            if len(point) >= 2 and math.isfinite(point[0]) and math.isfinite(point[1])
        ]
        self._waypoints = [
            (float(lat), float(lon)) for lat, lon in waypoints
            if math.isfinite(lat) and math.isfinite(lon)
        ]
        self._route_revision += 1
        self._selection_revision += 1
        self.update()

    def clear_route_draft(self) -> None:
        self._draft_route = []
        self._waypoints = []
        self._hover_waypoint_index = -1
        self._route_revision += 1
        self._selection_revision += 1
        self.update()

    def set_route(self, lon: list[float], lat: list[float], fit: bool = True) -> None:
        self.set_tracks([{"lon": lon, "lat": lat, "colour": "#50e39c", "active": True}], fit=fit)

    @staticmethod
    def _segments(lon, lat):
        longitude, latitude = np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)
        indices = np.flatnonzero(np.isfinite(longitude) & np.isfinite(latitude))
        if not len(indices):
            return []
        x, y = longitude[indices], latitude[indices]
        radians = np.radians(y)
        a = (np.sin(np.diff(radians)/2)**2 + np.cos(radians[:-1])*np.cos(radians[1:]) *
             np.sin(np.radians(np.diff(x))/2)**2)
        distance = 6371000 * 2*np.arcsin(np.minimum(1.0, np.sqrt(a)))
        cuts = np.flatnonzero((np.diff(indices) > 1) | (distance > 100000))+1
        groups = np.split(np.arange(len(indices)), cuts)
        routes = [list(zip(y[group].tolist(), x[group].tolist())) for group in groups]
        if any(len(segment) >= 2 for segment in routes):
            routes = [segment for segment in routes if len(segment) >= 2]
        return routes

    def _project_segment(self, segment, origin):
        coords = np.asarray(segment, dtype=float)
        size = _world_size(self._zoom)
        sine = np.sin(np.radians(np.clip(coords[:, 0], -MAX_LATITUDE, MAX_LATITUDE)))
        mercator = np.log((1+sine)/(1-sine))
        if self._ellipsoidal_projection:
            eccentric_sine = WGS84_ECCENTRICITY*sine
            mercator -= WGS84_ECCENTRICITY*np.log((1+eccentric_sine)/(1-eccentric_sine))
        x = (coords[:, 1]+180)/360*size - origin.x()
        y = (.5-mercator/(4*math.pi))*size - origin.y()
        # Preserve every crossed physical pixel, plus endpoints. This removes
        # redundant subpixel samples without changing the stored GPS route.
        pixels = np.rint(np.column_stack((x, y))*self.devicePixelRatioF())
        keep = np.r_[True, np.any(np.diff(pixels, axis=0) != 0, axis=1)]
        keep[-1] = True
        return QtGui.QPolygonF([QtCore.QPointF(float(a), float(b)) for a, b in zip(x[keep], y[keep])])

    def set_tracks(self, tracks: list[dict[str, object]], fit: bool = True) -> None:
        self._route_revision += 1
        self._selection_revision += 1
        self._cursor_point = None
        parsed: list[RouteTrack] = []
        for track in tracks:
            segments = self._segments(track.get("lon", []), track.get("lat", []))
            if segments:
                parsed.append(RouteTrack(
                    segments=segments,
                    colour=str(track.get("colour", "#50e39c")),
                    active=bool(track.get("active", False)),
                    name=str(track.get("name", "")),
                ))
        self._track_routes = parsed
        self._selection_routes = []
        self._anomaly_points = []
        self._waypoints = []
        self._hover_waypoint_index = -1
        self._routes = [segment for track in parsed for segment in track.segments]
        if fit and self._track_routes:
            self.fit_route()
        else:
            self.update()

    def set_selection(self, tracks: list[dict[str, object]]) -> None:
        self._selection_revision += 1
        self._selection_routes = []
        for track in tracks:
            segments = self._segments(track["lon"], track["lat"])
            if segments:
                self._selection_routes.append(RouteTrack(
                    segments=segments, colour=str(track["colour"]), active=True, name=""
                ))
        self.update()

    def fit_route(self) -> None:
        # Every plausible segment matters here: deleting a middle interval
        # creates two segments, and both must remain visible after fitting.
        points = [
            point
            for track in self._track_routes
            for segment in track.segments
            for point in segment
        ]
        if self._draft_route:
            points.extend(self._draft_route)
        elif self._waypoints:
            points.extend(self._waypoints)
        if not points:
            self.update()
            return
        available_width = max(150, self.width() - 96)
        available_height = max(100, self.height() - 96)
        self._zoom = 2
        for zoom in range(18, 1, -1):
            projected = [self._to_world(lat, lon, zoom) for lat, lon in points]
            x_values = [point.x() for point in projected]
            y_values = [point.y() for point in projected]
            if (
                max(x_values) - min(x_values) <= available_width
                and max(y_values) - min(y_values) <= available_height
            ):
                self._zoom = zoom
                break
        projected = [self._to_world(lat, lon, self._zoom) for lat, lon in points]
        center = QtCore.QPointF(
            (min(point.x() for point in projected) + max(point.x() for point in projected)) / 2.0,
            (min(point.y() for point in projected) + max(point.y() for point in projected)) / 2.0,
        )
        self._center_lat, self._center_lon = self._from_world(center, self._zoom)
        self._update_zoom_buttons()
        self.update()

    def _position_overlays(self) -> None:
        if not hasattr(self, "overlay") or not hasattr(self, "search_overlay"):
            return
        self.overlay.adjustSize()
        self.search_overlay.adjustSize()
        margin = 12
        map_vertical = self._overlay_verticals.get("map", "top")
        search_vertical = self._overlay_verticals.get("search", "top")
        map_y = margin if map_vertical == "top" else max(
            margin, self.height() - self.overlay.height() - margin
        )
        search_y = margin if search_vertical == "top" else max(
            margin, self.height() - self.search_overlay.height() - margin
        )
        self.search_overlay.move(margin, search_y)
        self.overlay.move(
            max(margin, self.width() - self.overlay.width() - margin), map_y
        )
        if hasattr(self, "zoom_controls"):
            self.zoom_controls.adjustSize()
            zoom_x = max(margin, self.width() - self.zoom_controls.width() - margin)
            zoom_y = max(margin, (self.height() - self.zoom_controls.height()) // 2)
            self.zoom_controls.move(zoom_x, zoom_y)
            self.zoom_controls.raise_()
        self.search_overlay.raise_()
        self.overlay.raise_()

    def _position_overlay(self) -> None:
        """Compatibility alias for callers and older tests."""
        self._position_overlays()

    def _move_overlay(self, control: FloatingMapControls, y: int) -> None:
        if control is not self.overlay and control is not self.search_overlay:
            return
        target = max(0, min(self.height() - control.height(), int(y)))
        margin = 12
        x = (
            margin if control is self.search_overlay
            else max(margin, self.width() - control.width() - margin)
        )
        control.move(x, target)
        control.raise_()

    def _snap_overlay(self, control: FloatingMapControls) -> None:
        vertical = "top" if control.geometry().center().y() < self.height() / 2 else "bottom"
        self._overlay_verticals[control.control_key] = vertical
        if control is self.overlay:
            self._overlay_vertical = vertical
            self._overlay_corner = f"{vertical}_right"
            self.overlayLaneChanged.emit(vertical)
        self._position_overlays()

    def _move_overlay_lane(self, y: int) -> None:
        """Compatibility helper: move the map-provider panel only."""
        self._move_overlay(self.overlay, y)

    def _snap_overlay_lane(self) -> None:
        """Compatibility helper: snap the map-provider panel only."""
        self._snap_overlay(self.overlay)

    def _snap_overlay_to_nearest_corner(self) -> None:
        self._snap_overlay_lane()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_overlays()

    def _cache_path(self, zoom: int, x: int, y: int) -> Path:
        return self._cache_root / self._provider.key / str(zoom) / str(x) / f"{y}.png"

    def _tile(self, zoom: int, x: int, y: int) -> QtGui.QPixmap | None:
        count = 2**zoom
        if y < 0 or y >= count:
            return None
        x %= count
        key = (self._provider.key, zoom, x, y)
        if key in self._pixmaps:
            pixmap = self._pixmaps.pop(key)
            self._pixmaps[key] = pixmap
            return pixmap
        cache_path = self._cache_path(zoom, x, y)
        pixmap = QtGui.QPixmap()
        if cache_path.exists() and pixmap.load(str(cache_path)):
            self._remember_pixmap(key, pixmap)
            return pixmap
        if key not in self._pending:
            self._request_tile(key, cache_path)
        return None

    def _remember_pixmap(self, key: tuple[str, int, int, int], pixmap: QtGui.QPixmap) -> None:
        """Keep a bounded in-memory LRU while the disk cache remains persistent."""
        self._pixmaps.pop(key, None)
        self._pixmaps[key] = pixmap
        while len(self._pixmaps) > 512:
            self._pixmaps.pop(next(iter(self._pixmaps)))

    def _schedule_tile_refresh(self) -> None:
        if not self._tile_refresh_timer.isActive():
            self._tile_refresh_timer.start()

    def _flush_tile_refresh(self) -> None:
        self._tile_revision += 1
        self.update()

    def _request_tile(
        self,
        key: tuple[str, int, int, int],
        cache_path: Path,
        *,
        offline_batch: bool = False,
    ) -> None:
        provider_key, zoom, x, y = key
        provider = PROVIDERS[provider_key]
        url = provider.url.format(z=zoom, x=x, y=y)
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        request.setRawHeader(b"User-Agent", b"Track-Editor/0.7.0 (+desktop route viewer)")
        request.setAttribute(QtNetwork.QNetworkRequest.Attribute.CacheLoadControlAttribute, QtNetwork.QNetworkRequest.CacheLoadControl.PreferCache)
        reply = self._manager.get(request)
        reply.setProperty("tile_key", key)
        reply.setProperty("cache_path", str(cache_path))
        reply.setProperty("offline_batch", offline_batch)
        reply.finished.connect(lambda r=reply: self._tile_finished(r))
        self._pending.add(key)

    def _tile_finished(self, reply: QtNetwork.QNetworkReply) -> None:
        key = reply.property("tile_key")
        self._pending.discard(key)
        success = reply.error() == QtNetwork.QNetworkReply.NetworkError.NoError
        if success:
            data = bytes(reply.readAll())
            pixmap = QtGui.QPixmap()
            if pixmap.loadFromData(data):
                self._remember_pixmap(key, pixmap)
                cache_path = Path(reply.property("cache_path"))
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(data)
                self._schedule_tile_refresh()
            else:
                success = False
        if bool(reply.property("offline_batch")):
            self._offline_active = max(0, self._offline_active - 1)
            self._offline_done += 1
            if not success:
                self._offline_failed += 1
            self.cacheDownloadProgress.emit(self._offline_done, self._offline_total)
            self._pump_offline_cache()
        reply.deleteLater()

    @property
    def cache_download_active(self) -> bool:
        return self._offline_active > 0 or bool(self._offline_queue)

    @property
    def cache_root(self) -> Path:
        return self._cache_root

    def cache_size_bytes(self) -> int:
        try:
            return sum(path.stat().st_size for path in self._cache_root.rglob("*.png"))
        except OSError:
            return 0

    def clear_tile_cache(self) -> int:
        if self.cache_download_active:
            raise RuntimeError("Map download is still in progress.")
        size = self.cache_size_bytes()
        if self._cache_root.exists():
            shutil.rmtree(self._cache_root)
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._pixmaps.clear()
        self._display_pixmaps.clear()
        self._tile_revision += 1
        self._base_key = None
        self.update()
        return size

    def route_cache_plan(self, minimum_zoom: int, maximum_zoom: int) -> list[tuple[str, int, int, int]]:
        """Return missing tiles that cover every loaded route plus one-tile padding."""
        points = [
            point
            for track in self._track_routes
            for segment in track.segments
            for point in segment
        ]
        if self._draft_route:
            points.extend(self._draft_route)
        elif self._waypoints:
            points.extend(self._waypoints)
        if not points:
            return []
        plan: set[tuple[str, int, int, int]] = set()
        minimum_zoom = max(2, int(minimum_zoom))
        maximum_zoom = min(19, max(minimum_zoom, int(maximum_zoom)))
        for zoom in range(minimum_zoom, maximum_zoom + 1):
            projected = [self._to_world(lat, lon, zoom) for lat, lon in points]
            count = 2**zoom
            first_x = math.floor(min(point.x() for point in projected) / TILE_SIZE) - 1
            last_x = math.floor(max(point.x() for point in projected) / TILE_SIZE) + 1
            first_y = max(0, math.floor(min(point.y() for point in projected) / TILE_SIZE) - 1)
            last_y = min(count - 1, math.floor(max(point.y() for point in projected) / TILE_SIZE) + 1)
            for tile_y in range(first_y, last_y + 1):
                for tile_x in range(first_x, last_x + 1):
                    key = (self._provider.key, zoom, tile_x % count, tile_y)
                    if key in self._pixmaps or key in self._pending:
                        continue
                    if self._cache_path(zoom, key[2], tile_y).exists():
                        continue
                    plan.add(key)
        return sorted(plan, key=lambda item: (item[1], item[3], item[2]))

    def start_route_cache_download(self, plan: list[tuple[str, int, int, int]]) -> None:
        if self.cache_download_active:
            raise RuntimeError("Map download is already in progress.")
        self._offline_queue = list(plan)
        self._offline_total = len(plan)
        self._offline_done = 0
        self._offline_failed = 0
        self._offline_active = 0
        self.provider_combo.setEnabled(False)
        if not plan:
            self.provider_combo.setEnabled(True)
            QtCore.QTimer.singleShot(0, lambda: self.cacheDownloadFinished.emit(0, 0))
            return
        self.cacheDownloadProgress.emit(0, self._offline_total)
        self._pump_offline_cache()

    def _pump_offline_cache(self) -> None:
        while self._offline_queue and self._offline_active < self._offline_max_concurrent:
            key = self._offline_queue.pop(0)
            provider_key, zoom, x, y = key
            if provider_key != self._provider.key:
                self._offline_done += 1
                self._offline_failed += 1
                continue
            self._offline_active += 1
            self._request_tile(key, self._cache_path(zoom, x, y), offline_batch=True)
        if not self._offline_queue and self._offline_active == 0 and self._offline_total:
            succeeded = self._offline_done - self._offline_failed
            failed = self._offline_failed
            self._offline_total = 0
            self.provider_combo.setEnabled(True)
            self.cacheDownloadFinished.emit(succeeded, failed)

    def _display_pixmap(
        self,
        key: tuple[str, int, int, int],
        pixmap: QtGui.QPixmap,
        device_ratio: float,
    ) -> QtGui.QPixmap:
        """Return a tile whose physical size matches the current screen DPI."""
        ratio = max(1.0, float(device_ratio))
        ratio_key = int(round(ratio * 100.0))
        cache_key = (*key, ratio_key)
        cached = self._display_pixmaps.get(cache_key)
        if cached is not None:
            return cached

        pixel_size = max(TILE_SIZE, int(round(TILE_SIZE * ratio)))
        if pixmap.width() == pixel_size and pixmap.height() == pixel_size:
            display = QtGui.QPixmap(pixmap)
        else:
            display = pixmap.scaled(
                pixel_size,
                pixel_size,
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        # Keep the tile exactly 256 logical pixels wide while supplying enough
        # physical pixels for the monitor's current scale factor.
        display.setDevicePixelRatio(pixel_size / TILE_SIZE)
        if len(self._display_pixmaps) >= 192:
            self._display_pixmaps.pop(next(iter(self._display_pixmaps)))
        self._display_pixmaps[cache_key] = display
        return display

    def _camera_key(self):
        return (self.width(), self.height(), self.devicePixelRatioF(), self._zoom,
                self._center_lat, self._center_lon, self._provider.key)

    def _origin(self):
        ratio = max(1.0, self.devicePixelRatioF())
        origin = self._to_world(self._center_lat, self._center_lon) - QtCore.QPointF(
            self.width()/2, self.height()/2)
        return QtCore.QPointF(round(origin.x()*ratio)/ratio, round(origin.y()*ratio)/ratio)

    def _layer_pixmap(self):
        ratio = max(1.0, self.devicePixelRatioF())
        pixmap = QtGui.QPixmap(max(1, round(self.width()*ratio)), max(1, round(self.height()*ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QtCore.Qt.transparent)
        return pixmap

    def paintEvent(self, event):
        # Cache stationary tiles/routes separately from selection and cursor.
        camera = self._camera_key()
        base_key = (camera, self._route_revision, self._tile_revision,
                    bool(getattr(self, "_selection_routes", [])))
        if base_key != self._base_key:
            self._base_layer = self._layer_pixmap()
            painter = QtGui.QPainter(self._base_layer)
            self._paint_base(painter)
            painter.end()
            self._base_key = base_key
        selection_key = (camera, self._selection_revision)
        if selection_key != self._selection_key:
            self._selection_layer = self._layer_pixmap()
            painter = QtGui.QPainter(self._selection_layer)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            self._paint_selection(painter, self._origin())
            painter.end()
            self._selection_key = selection_key
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.drawPixmap(0, 0, self._base_layer)
        painter.drawPixmap(0, 0, self._selection_layer)
        self._paint_cursor(painter, self._origin())

    def _paint_base(self, painter):
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QtGui.QColor("#1b2027"))
        device_ratio = max(1.0, float(self.devicePixelRatioF()))
        center = self._to_world(self._center_lat, self._center_lon)
        origin = center - QtCore.QPointF(self.width() / 2, self.height() / 2)
        # Align the tile mosaic to physical pixels. Fractional placement was
        # another source of fuzzy one-pixel seams and stair-stepped labels.
        origin = QtCore.QPointF(
            round(origin.x() * device_ratio) / device_ratio,
            round(origin.y() * device_ratio) / device_ratio,
        )
        first_x = math.floor(origin.x() / TILE_SIZE)
        first_y = math.floor(origin.y() / TILE_SIZE)
        last_x = math.floor((origin.x() + self.width()) / TILE_SIZE)
        last_y = math.floor((origin.y() + self.height()) / TILE_SIZE)
        count = 2**self._zoom
        for tile_y in range(first_y, last_y + 1):
            for tile_x in range(first_x, last_x + 1):
                target = QtCore.QRectF(
                    tile_x * TILE_SIZE - origin.x(),
                    tile_y * TILE_SIZE - origin.y(),
                    TILE_SIZE,
                    TILE_SIZE,
                )
                wrapped_x = tile_x % count
                pixmap = self._tile(self._zoom, wrapped_x, tile_y)
                if pixmap is not None:
                    key = (self._provider.key, self._zoom, wrapped_x, tile_y)
                    display = self._display_pixmap(key, pixmap, device_ratio)
                    painter.drawPixmap(target.topLeft(), display)
                else:
                    painter.fillRect(target, QtGui.QColor("#20252d"))
                    painter.setPen(QtGui.QPen(QtGui.QColor("#2d333d"), 1))
                    painter.drawRect(target)

        has_selection = bool(getattr(self, "_selection_routes", []))
        if self._track_routes:
            # Paint the selected activity last so it remains visible where
            # several routes overlap exactly.
            for track in sorted(self._track_routes, key=lambda item: item.active):
                polylines = [
                    self._project_segment(segment, origin)
                    for segment in track.segments
                ]
                casing_width = 7 if track.active else 5
                route_width = 4 if track.active else 2.8
                painter.setPen(QtGui.QPen(
                    QtGui.QColor(0, 0, 0, 155), casing_width, QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin,
                ))
                for polyline in polylines:
                    painter.drawPolyline(polyline)
                colour = QtGui.QColor(track.colour)
                if has_selection:
                    colour.setAlpha(85)
                elif not track.active:
                    colour.setAlpha(215)
                painter.setPen(QtGui.QPen(
                    colour, route_width, QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin,
                ))
                for polyline in polylines:
                    painter.drawPolyline(polyline)

                first = self._to_world(*track.segments[0][0]) - origin
                last = self._to_world(*track.segments[-1][-1]) - origin
                painter.setBrush(colour)
                painter.setPen(QtGui.QPen(QtGui.QColor("#101318"), 2))
                radius = 6 if track.active else 4.5
                painter.drawEllipse(first, radius, radius)
                painter.setBrush(QtGui.QColor("#f2f4f8"))
                painter.drawEllipse(last, radius, radius)
        elif not self._waypoints and not self._draft_route:
            painter.setPen(QtGui.QColor("#aab0ba"))
            painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "NO GPS / НЕТ GPS")

        if len(self._draft_route) >= 2:
            draft = self._project_segment(self._draft_route, origin)
            painter.setPen(QtGui.QPen(
                QtGui.QColor(0, 0, 0, 175), 9.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            ))
            painter.drawPolyline(draft)
            painter.setPen(QtGui.QPen(
                QtGui.QColor("#2f9df4"), 5.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            ))
            painter.drawPolyline(draft)

        self._paint_track_legend(painter)

        attribution_rect = QtCore.QRectF(self.width() - 220, self.height() - 25, 210, 20)
        painter.setPen(QtGui.QColor(230, 233, 239, 190))
        painter.drawText(attribution_rect, QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter, self._provider.attribution)

    def _paint_selection(self, painter, origin):
        for track in getattr(self, "_selection_routes", []):
            for segment in track.segments:
                polyline = self._project_segment(segment, origin)
                painter.setBrush(QtCore.Qt.NoBrush)
                for colour, width in (("#ffffff", 9), (track.colour, 5)):
                    painter.setPen(QtGui.QPen(QtGui.QColor(colour), width,
                        QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
                    painter.drawPolyline(polyline)
        for latitude, longitude, selected in self._anomaly_points:
            point = self._to_world(latitude, longitude) - origin
            radius = 9.0 if selected else 6.0
            polygon = QtGui.QPolygonF([
                QtCore.QPointF(point.x(), point.y() - radius),
                QtCore.QPointF(point.x() + radius, point.y()),
                QtCore.QPointF(point.x(), point.y() + radius),
                QtCore.QPointF(point.x() - radius, point.y()),
            ])
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2.2))
            painter.setBrush(QtGui.QColor("#ff4057"))
            painter.drawPolygon(polygon)
        for number, (latitude, longitude) in enumerate(self._waypoints, start=1):
            point = self._to_world(latitude, longitude) - origin
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2.5))
            hovered = number - 1 == self._hover_waypoint_index
            painter.setBrush(QtGui.QColor("#d9485f") if hovered else QtGui.QColor("#287bd1"))
            painter.drawEllipse(point, 12.0, 12.0)
            painter.setPen(QtGui.QColor("#ffffff"))
            font = QtGui.QFont(painter.font())
            font.setBold(True)
            font.setPointSizeF(9.0)
            painter.setFont(font)
            marker_rect = QtCore.QRectF(point.x() - 11.0, point.y() - 11.0, 22.0, 22.0)
            if hovered:
                painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2.2))
                painter.drawLine(point.x() - 4.5, point.y() - 4.5,
                                 point.x() + 4.5, point.y() + 4.5)
                painter.drawLine(point.x() + 4.5, point.y() - 4.5,
                                 point.x() - 4.5, point.y() + 4.5)
            else:
                painter.drawText(
                    marker_rect, QtCore.Qt.AlignmentFlag.AlignCenter, str(number)
                )

    def _paint_track_legend(self, painter: QtGui.QPainter) -> None:
        tracks = [track for track in self._track_routes if track.name]
        if not tracks:
            return
        font = QtGui.QFont(painter.font())
        font.setPointSizeF(max(8.0, font.pointSizeF() - 1.0))
        painter.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        line_height = metrics.height() + 5
        maximum_width = max(150, int(self.width() * 0.55))
        names = [
            metrics.elidedText(track.name, QtCore.Qt.TextElideMode.ElideMiddle,
                               maximum_width - 38)
            for track in tracks
        ]
        box_width = min(
            maximum_width,
            max(metrics.horizontalAdvance(name) for name in names) + 38,
        )
        box_height = 12 + line_height * len(tracks)
        box = QtCore.QRectF(10, self.height() - box_height - 10, box_width, box_height)
        background = (
            QtGui.QColor(250, 251, 253, 225)
            if self._theme == "light" else QtGui.QColor(17, 19, 23, 220)
        )
        border = QtGui.QColor("#b8c0cc") if self._theme == "light" else QtGui.QColor("#434a55")
        text_colour = QtGui.QColor("#263445") if self._theme == "light" else QtGui.QColor("#e7e9ee")
        painter.setPen(QtGui.QPen(border, 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(box, 6.0, 6.0)
        for row, (track, name) in enumerate(zip(tracks, names)):
            centre_y = box.top() + 7 + line_height * row + line_height / 2.0
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(track.colour))
            painter.drawEllipse(QtCore.QPointF(box.left() + 13, centre_y), 4.5, 4.5)
            painter.setPen(text_colour)
            painter.drawText(
                QtCore.QRectF(box.left() + 25, centre_y - line_height / 2.0,
                              box.width() - 31, line_height),
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                name,
            )

    def _paint_cursor(self, painter, origin):
        if self._cursor_point is not None:
            latitude, longitude, marker_colour = self._cursor_point
            marker = self._to_world(latitude, longitude) - origin
            if self.rect().adjusted(-14, -14, 14, 14).contains(marker.toPoint()):
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(QtGui.QColor(0, 0, 0, 125))
                painter.drawEllipse(marker, 10.0, 10.0)
                painter.setPen(QtGui.QPen(QtGui.QColor("#f7f9fc"), 2.5))
                painter.setBrush(QtGui.QColor(marker_colour))
                painter.drawEllipse(marker, 7.0, 7.0)
                painter.setPen(QtGui.QPen(QtGui.QColor(marker_colour), 1.5))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawEllipse(marker, 11.5, 11.5)

    def _waypoint_index_at(self, position: QtCore.QPointF) -> int:
        if not self._point_selection_enabled or not self._waypoints:
            return -1
        origin = self._origin()
        nearest = -1
        nearest_distance = 17.0
        for index, waypoint in enumerate(self._waypoints):
            point = self._to_world(*waypoint) - origin
            distance = math.hypot(point.x() - position.x(), point.y() - position.y())
            if distance <= nearest_distance:
                nearest = index
                nearest_distance = distance
        return nearest

    def _draft_insertion_at(
        self, position: QtCore.QPointF
    ) -> tuple[float, float, int] | None:
        if len(self._draft_route) < 2 or len(self._waypoints) < 2:
            return None
        origin = self._origin()
        route_pixels = [self._to_world(*point) - origin for point in self._draft_route]
        best_distance = 15.0
        best_segment = -1
        best_fraction = 0.0
        for index, (start, end) in enumerate(zip(route_pixels, route_pixels[1:])):
            dx, dy = end.x() - start.x(), end.y() - start.y()
            length_sq = dx * dx + dy * dy
            if length_sq <= 1e-9:
                fraction = 0.0
            else:
                fraction = max(0.0, min(1.0, (
                    (position.x() - start.x()) * dx + (position.y() - start.y()) * dy
                ) / length_sq))
            projected_x = start.x() + dx * fraction
            projected_y = start.y() + dy * fraction
            distance = math.hypot(position.x() - projected_x, position.y() - projected_y)
            if distance < best_distance:
                best_distance = distance
                best_segment = index
                best_fraction = fraction
        if best_segment < 0:
            return None

        # Match each existing control point to monotonically increasing route
        # geometry. This tells us between which pins the clicked line belongs,
        # even when the calculated road bends far away from a straight chord.
        matches: list[int] = []
        start_index = 0
        for waypoint in self._waypoints:
            candidates = range(start_index, len(self._draft_route))
            match = min(
                candidates,
                key=lambda route_index: _haversine_m(waypoint, self._draft_route[route_index]),
            )
            matches.append(match)
            start_index = match
        insertion_index = len(self._waypoints) - 1
        for index in range(1, len(matches)):
            if best_segment < matches[index]:
                insertion_index = index
                break
        first = self._draft_route[best_segment]
        second = self._draft_route[best_segment + 1]
        latitude = first[0] + (second[0] - first[0]) * best_fraction
        longitude = first[1] + (second[1] - first[1]) * best_fraction
        return latitude, longitude, insertion_index

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            waypoint = self._waypoint_index_at(event.position())
            if waypoint >= 0:
                self._drag_waypoint_index = waypoint
                self._press_position = event.position()
                self._dragged = False
                self.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
                event.accept()
                return
            self._drag_position = event.position()
            self._press_position = event.position()
            self._dragged = False
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_waypoint_index >= 0:
            centre = self._to_world(self._center_lat, self._center_lon)
            world = centre + event.position() - QtCore.QPointF(
                self.width() / 2.0, self.height() / 2.0
            )
            latitude, longitude = self._from_world(world)
            self._waypoints[self._drag_waypoint_index] = (latitude, longitude)
            self._selection_revision += 1
            self._dragged = True
            self.update()
            event.accept()
            return
        if self._drag_position is None:
            waypoint = self._waypoint_index_at(event.position())
            if waypoint != self._hover_waypoint_index:
                self._hover_waypoint_index = waypoint
                self._selection_revision += 1
                self.update()
            if waypoint >= 0:
                self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
                return
            anomaly = self._anomaly_index_at(event.position())
            if anomaly >= 0:
                self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(
                    self._pin_cursor()
                    if self._point_selection_enabled else QtCore.Qt.CursorShape.ArrowCursor
                )
            return
        if self._press_position is not None and (
            event.position() - self._press_position
        ).manhattanLength() > 4.0:
            self._dragged = True
        delta = event.position() - self._drag_position
        center = self._to_world(self._center_lat, self._center_lon) - delta
        self._center_lat, self._center_lon = self._from_world(center)
        self._drag_position = event.position()
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if self._drag_waypoint_index >= 0:
                index = self._drag_waypoint_index
                self._drag_waypoint_index = -1
                latitude, longitude = self._waypoints[index]
                if self._dragged:
                    self.waypointMoved.emit(index, latitude, longitude)
                else:
                    self.waypointRemoveRequested.emit(index)
                    self._hover_waypoint_index = -1
                    self._selection_revision += 1
                self._press_position = None
                self._dragged = False
                self.setCursor(self._pin_cursor())
                event.accept()
                return
            if self._point_selection_enabled and not self._dragged:
                insertion = self._draft_insertion_at(event.position())
                if insertion is not None:
                    self.routePointRequested.emit(*insertion)
                else:
                    centre = self._to_world(self._center_lat, self._center_lon)
                    world = centre + event.position() - QtCore.QPointF(
                        self.width() / 2.0, self.height() / 2.0
                    )
                    latitude, longitude = self._from_world(world)
                    self.mapClicked.emit(latitude, longitude)
            elif not self._dragged:
                anomaly = self._anomaly_index_at(event.position())
                if anomaly >= 0:
                    self.anomalyClicked.emit(anomaly)
            self._drag_position = None
            self._press_position = None
            anomaly = self._anomaly_index_at(event.position())
            self.setCursor(
                QtCore.Qt.CursorShape.PointingHandCursor if anomaly >= 0 else
                self._pin_cursor() if self._point_selection_enabled else
                QtCore.Qt.CursorShape.ArrowCursor
            )

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        if self._hover_waypoint_index >= 0:
            self._hover_waypoint_index = -1
            self._selection_revision += 1
            self.update()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if not self._point_selection_enabled:
            self.fit_route()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta == 0:
            event.ignore()
            return
        old_zoom = self._zoom
        new_zoom = max(2, min(19, old_zoom + (1 if delta > 0 else -1)))
        if new_zoom == old_zoom:
            event.accept()
            return

        # Preserve the geographical point under the mouse. Merely changing
        # zoom around the stored centre makes the map jump toward the widget's
        # centre, which feels wrong on every modern slippy map.
        cursor = QtCore.QPointF(event.position())
        widget_centre = QtCore.QPointF(self.width() / 2.0, self.height() / 2.0)
        old_centre_world = self._to_world(self._center_lat, self._center_lon, old_zoom)
        old_cursor_world = old_centre_world + cursor - widget_centre
        cursor_lat, cursor_lon = self._from_world(old_cursor_world, old_zoom)

        self._zoom = new_zoom
        new_cursor_world = self._to_world(cursor_lat, cursor_lon, new_zoom)
        new_centre_world = new_cursor_world - cursor + widget_centre
        self._center_lat, self._center_lon = self._from_world(new_centre_world, new_zoom)
        self._update_zoom_buttons()
        self.update()
        event.accept()
