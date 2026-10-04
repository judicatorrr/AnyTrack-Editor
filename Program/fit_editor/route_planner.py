"""Interactive GraphHopper route creation dialog."""
from __future__ import annotations

import json
import heapq
import math
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets

from .icons import icon as pack_icon, route_pin_icon
from .map_widget import MapWidget


MAX_LOCATIONS_PER_REQUEST = 5
MAX_CONTROL_POINTS = 50
DEFAULT_HOSTED_CREDIT_LIMIT = 500


ROUTE_MODES = (
    ("walk", "foot", "mode_walk", "mode_walk_desc", "walking", False),
    ("run", "foot", "mode_run", "mode_run_desc", "running", False),
    ("bike", "bike", "mode_bike", "mode_bike_desc", "cycling", False),
    ("road_bike", "racingbike", "mode_road_bike", "mode_road_bike_desc", "cycling", True),
    ("mtb", "mtb", "mode_mtb", "mode_mtb_desc", "mountain", True),
    ("river", "river", "mode_river", "mode_river_desc", "river", False),
    ("direct", "direct", "mode_direct", "mode_direct_desc", "direct", False),
)


TEXT = {
    "ru": {
        "title": "Создать маршрут",
        "intro": "Поставьте старт, финиш и промежуточные точки. Если точек больше пяти, маршрут автоматически строится частями и объединяется.",
        "intro_local": "Поставьте старт, финиш и промежуточные точки. Локальный GraphHopper построит весь маршрут одним запросом без кредитов.",
        "name": "Название",
        "default_name": "Новый маршрут",
        "mode": "Режим",
        "mode_walk": "Пешком",
        "mode_walk_desc": "Прогулки и пешие маршруты · профиль GraphHopper foot.",
        "mode_run": "Бег",
        "mode_run_desc": "Беговой маршрут использует дорожную геометрию профиля foot.",
        "mode_bike": "Базовый велосипед",
        "mode_bike_desc": "Универсальный велосипедный маршрут · профиль bike.",
        "mode_road_bike": "Шоссейный велосипед",
        "mode_road_bike_desc": "Асфальт и дороги · профиль racingbike.",
        "mode_mtb": "Гравий и бездорожье",
        "mode_mtb_desc": "Грунт, тропы и сложные покрытия · профиль mtb.",
        "mode_river": "Сплав по реке",
        "mode_river_desc": "Маршрут по рекам, ручьям и каналам OpenStreetMap · требуется интернет.",
        "mode_direct": "Напрямик",
        "mode_direct_desc": "Прямые отрезки между точками. GraphHopper и кредиты не используются.",
        "advanced_suffix": " · платный тариф или локальный сервер",
        "undo": "Убрать последнюю точку",
        "clear": "Очистить",
        "build": "Построить маршрут",
        "fullscreen": "Развернуть",
        "windowed": "Обычный размер",
        "add": "Добавить в редактор",
        "save_gpx": "Сохранить GPX",
        "drag_panel": "Перетащить панель",
        "drag_panel_hint": "Зажмите и переместите панель в удобное место карты",
        "close": "Отмена",
        "points": "Контрольные точки: {count} · запросов маршрутизации: {requests}",
        "summary": "Дистанция: {distance} · Набор высоты: {ascent}",
        "distance_label": "Дистанция",
        "ascent_label": "Набор высоты",
        "removed": "Контрольная точка удалена. Маршрут перестраивается…",
        "point_limit": "Можно поставить не более 50 контрольных точек.",
        "need_points": "Поставьте на карте минимум две контрольные точки.",
        "ready_to_build": "Точки расставлены. Нажмите «Построить маршрут», чтобы получить линию по дорогам.",
        "need_key": "Для облачного GraphHopper нужен API-ключ. Укажите его в настройках либо задайте адрес локального GraphHopper-сервера.",
        "request": "GraphHopper строит маршрут: часть {current} из {total}…",
        "ready": "Маршрут готов: {distance:.2f} км · частей: {parts} · точек геометрии: {points}",
        "ready_direct": "Прямой маршрут готов: {distance:.2f} км · точек: {points}",
        "river_request": "Ищу связный путь по рекам и каналам OpenStreetMap…",
        "river_ready": "Речной маршрут готов: {distance:.2f} км · точек геометрии: {points}",
        "river_missing": "Не удалось найти связный водный путь. Поставьте точки ближе к реке или добавьте промежуточную точку у развилки.",
        "error": "Не удалось построить маршрут",
        "bad_response": "GraphHopper не вернул геометрию маршрута.",
        "from_track": "По загруженному треку",
        "from_track_empty": "В активном треке недостаточно GPS-точек.",
        "from_track_ready": "Трек превращён в {count} контрольных точек. Можно поправить их на карте и перестроить маршрут.",
        "edit_hint": "Нажмите на синюю линию, чтобы вставить точку, затем перетащите её в нужное место.",
        "inserted": "Точка вставлена внутрь маршрута. Перетащите её и нажмите «Построить маршрут».",
        "moved": "Точка перемещена. Нажмите «Построить маршрут», чтобы обновить линию.",
        "exit": "Выйти из режима",
    },
    "en": {
        "title": "Create route",
        "intro": "Place the start, finish and intermediate waypoints. Routes with more than five points are built in overlapping parts and merged.",
        "intro_local": "Place the start, finish and intermediate waypoints. Local GraphHopper builds the full route in one request without credits.",
        "name": "Name",
        "default_name": "New route",
        "mode": "Mode",
        "mode_walk": "Walking",
        "mode_walk_desc": "Walks and foot routes · GraphHopper foot profile.",
        "mode_run": "Running",
        "mode_run_desc": "Running uses the road geometry of the foot profile.",
        "mode_bike": "Basic cycling",
        "mode_bike_desc": "General-purpose cycling route · bike profile.",
        "mode_road_bike": "Road cycling",
        "mode_road_bike_desc": "Paved roads · racingbike profile.",
        "mode_mtb": "Gravel and off-road",
        "mode_mtb_desc": "Unpaved roads, trails and rough surfaces · mtb profile.",
        "mode_river": "River rafting",
        "mode_river_desc": "Routes along OSM rivers, streams and canals · internet required.",
        "mode_direct": "Direct",
        "mode_direct_desc": "Straight segments between points. GraphHopper and credits are not used.",
        "advanced_suffix": " · paid plan or local server",
        "undo": "Remove last point",
        "clear": "Clear",
        "build": "Build route",
        "fullscreen": "Maximize",
        "windowed": "Restore window",
        "add": "Add to editor",
        "save_gpx": "Save GPX",
        "drag_panel": "Move panel",
        "drag_panel_hint": "Drag to place the panel anywhere on the map",
        "close": "Cancel",
        "points": "Waypoints: {count} · routing requests: {requests}",
        "summary": "Distance: {distance} · Elevation gain: {ascent}",
        "distance_label": "Distance",
        "ascent_label": "Elevation gain",
        "removed": "Waypoint removed. Rebuilding the route…",
        "point_limit": "Up to 50 control points can be placed.",
        "need_points": "Place at least two waypoints on the map.",
        "ready_to_build": "Waypoints are ready. Select Build route to calculate the road geometry.",
        "need_key": "The hosted GraphHopper service requires an API key. Add it in Settings or use a local GraphHopper server URL.",
        "request": "GraphHopper is building route part {current} of {total}…",
        "ready": "Route ready: {distance:.2f} km · parts: {parts} · geometry points: {points}",
        "ready_direct": "Direct route ready: {distance:.2f} km · points: {points}",
        "river_request": "Looking for a connected route along OpenStreetMap waterways…",
        "river_ready": "River route ready: {distance:.2f} km · geometry points: {points}",
        "river_missing": "No connected waterway was found. Put the points closer to the river or add a waypoint near the junction.",
        "error": "Could not build route",
        "bad_response": "GraphHopper did not return route geometry.",
        "from_track": "From loaded track",
        "from_track_empty": "The active track does not contain enough GPS points.",
        "from_track_ready": "The track was converted to {count} control points. Adjust them on the map and rebuild the route.",
        "edit_hint": "Click the blue route line to insert a point, then drag it to the desired place.",
        "inserted": "A point was inserted into the route. Drag it and select Build route.",
        "moved": "The point was moved. Select Build route to refresh the line.",
        "exit": "Exit route mode",
    },
}


def normalized_route_url(value: str) -> str:
    text = value.strip() or "https://graphhopper.com/api/1/route"
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    if not path.endswith("/route"):
        path += "/route"
    return urlunsplit((parts.scheme or "http", parts.netloc, path, parts.query, parts.fragment))


def route_service_requires_key(value: str) -> bool:
    """Return whether the configured URL points to GraphHopper's hosted API."""
    hostname = (urlsplit(normalized_route_url(value)).hostname or "").lower()
    return hostname == "graphhopper.com" or hostname.endswith(".graphhopper.com")


def graphhopper_payload(points: list[tuple[float, float]], profile: str) -> dict:
    return {
        "points": [[longitude, latitude] for latitude, longitude in points],
        "profile": profile,
        "points_encoded": False,
        "instructions": False,
        "elevation": True,
        "calc_points": True,
    }


def parse_rate_limit_headers(
    header_pairs: list[tuple[bytes, bytes]] | tuple[tuple[bytes, bytes], ...],
    fallback_limit: int = DEFAULT_HOSTED_CREDIT_LIMIT,
) -> tuple[int, int, int] | None:
    """Read GraphHopper usage headers even when Limit is omitted or casing differs."""
    headers: dict[str, str] = {}
    for raw_name, raw_value in header_pairs:
        name = bytes(raw_name).decode("latin-1", "ignore").strip().lower()
        value = bytes(raw_value).decode("latin-1", "ignore").strip()
        headers[name] = value

    def number(name: str) -> int | None:
        value = headers.get(name)
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except ValueError:
            return None

    remaining = number("x-ratelimit-remaining")
    if remaining is None or remaining < 0:
        return None
    reported_limit = number("x-ratelimit-limit")
    limit = reported_limit if reported_limit is not None and reported_limit > 0 else fallback_limit
    limit = max(int(limit), remaining, 1)
    reset_seconds = max(0, number("x-ratelimit-reset") or 0)
    return limit, remaining, reset_seconds


def direct_route_distance(points: list[tuple[float, float]]) -> float:
    """Return the geodesic length of straight waypoint segments in metres."""
    distance = 0.0
    for first, second in zip(points, points[1:]):
        lat1, lon1 = map(math.radians, first)
        lat2, lon2 = map(math.radians, second)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
        distance += 6_371_000.0 * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return distance


def route_ascent_m(
    coordinates: list[tuple[float, float, float | None]],
) -> float | None:
    """Return cumulative positive elevation gain, or None without elevation data."""
    previous: float | None = None
    ascent = 0.0
    samples = 0
    for point in coordinates:
        elevation = point[2] if len(point) >= 3 else None
        if elevation is None or not math.isfinite(float(elevation)):
            continue
        current = float(elevation)
        if previous is not None:
            ascent += max(0.0, current - previous)
        previous = current
        samples += 1
    return ascent if samples >= 2 else None


def river_overpass_query(points: list[tuple[float, float]]) -> str:
    """Build one bounded Overpass query for navigable OSM waterway geometry."""
    if len(points) < 2:
        raise ValueError("At least two points are required.")
    latitudes = [point[0] for point in points]
    longitudes = [point[1] for point in points]
    lat_span = max(latitudes) - min(latitudes)
    lon_span = max(longitudes) - min(longitudes)
    lat_pad = max(0.03, lat_span * 0.2)
    lon_pad = max(0.03, lon_span * 0.2)
    south, north = min(latitudes) - lat_pad, max(latitudes) + lat_pad
    west, east = min(longitudes) - lon_pad, max(longitudes) + lon_pad
    return (
        "[out:json][timeout:35];"
        f'way["waterway"~"^(river|canal|stream)$"]({south:.6f},{west:.6f},{north:.6f},{east:.6f});'
        "(._;>;);out body;"
    )


def parse_river_route(
    payload: dict,
    control_points: list[tuple[float, float]],
    maximum_snap_distance_m: float = 5000.0,
) -> list[tuple[float, float, float | None]]:
    """Snap waypoints to OSM waterways and join them through the water graph."""
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        raise ValueError("OpenStreetMap did not return waterway data.")
    nodes: dict[int, tuple[float, float]] = {}
    ways: list[list[int]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        if element.get("type") == "node":
            try:
                nodes[int(element["id"])] = (float(element["lat"]), float(element["lon"]))
            except (KeyError, TypeError, ValueError):
                continue
        elif element.get("type") == "way" and isinstance(element.get("nodes"), list):
            ways.append([int(node_id) for node_id in element["nodes"]])
    if not nodes or not ways:
        raise ValueError("No rivers or canals were found in this area.")

    graph: dict[int, list[tuple[int, float]]] = {}
    for way in ways:
        for first, second in zip(way, way[1:]):
            if first not in nodes or second not in nodes:
                continue
            weight = direct_route_distance([nodes[first], nodes[second]])
            graph.setdefault(first, []).append((second, weight))
            graph.setdefault(second, []).append((first, weight))
    if not graph:
        raise ValueError("The returned waterways do not contain connected geometry.")

    graph_nodes = [(node_id, nodes[node_id]) for node_id in graph]
    snapped: list[int] = []
    for point in control_points:
        node_id, distance = min(
            ((candidate, direct_route_distance([point, coordinate]))
             for candidate, coordinate in graph_nodes),
            key=lambda item: item[1],
        )
        if distance > maximum_snap_distance_m:
            raise ValueError("A waypoint is too far from a mapped river or canal.")
        snapped.append(node_id)

    route_ids: list[int] = []
    for start, finish in zip(snapped, snapped[1:]):
        if start == finish:
            segment = [start]
        else:
            distances = {start: 0.0}
            previous: dict[int, int] = {}
            queue = [(0.0, start)]
            while queue:
                distance, current = heapq.heappop(queue)
                if distance != distances.get(current):
                    continue
                if current == finish:
                    break
                for neighbour, weight in graph.get(current, []):
                    candidate = distance + weight
                    if candidate < distances.get(neighbour, math.inf):
                        distances[neighbour] = candidate
                        previous[neighbour] = current
                        heapq.heappush(queue, (candidate, neighbour))
            if finish not in distances:
                raise ValueError("The selected points are on disconnected waterways.")
            segment = [finish]
            while segment[-1] != start:
                segment.append(previous[segment[-1]])
            segment.reverse()
        if route_ids and segment and route_ids[-1] == segment[0]:
            segment = segment[1:]
        route_ids.extend(segment)
    if len(route_ids) < 2:
        raise ValueError("The selected waterway segment is too short.")
    return [(nodes[node_id][0], nodes[node_id][1], None) for node_id in route_ids]


def route_batches(
    points: list[tuple[float, float]],
    maximum_locations: int = MAX_LOCATIONS_PER_REQUEST,
) -> list[list[tuple[float, float]]]:
    """Split waypoints into connected requests with one shared boundary point."""
    if len(points) < 2:
        return []
    if maximum_locations < 2:
        raise ValueError("A route request needs at least two locations.")
    result: list[list[tuple[float, float]]] = []
    start = 0
    while start < len(points) - 1:
        end = min(len(points), start + maximum_locations)
        result.append(list(points[start:end]))
        start = end - 1
    return result


def route_batches_for_service(
    points: list[tuple[float, float]], service_url: str
) -> list[list[tuple[float, float]]]:
    """Apply the hosted five-location limit only to graphhopper.com."""
    if len(points) < 2:
        return []
    if route_service_requires_key(service_url):
        return route_batches(points)
    return [list(points)]


def simplify_route_points(
    points: list[tuple[float, float]], maximum_points: int = MAX_CONTROL_POINTS
) -> list[tuple[float, float]]:
    """Shape-preserving reduction used to turn an activity into waypoints."""
    cleaned: list[tuple[float, float]] = []
    for latitude, longitude in points:
        point = (float(latitude), float(longitude))
        if not cleaned or point != cleaned[-1]:
            cleaned.append(point)
    if len(cleaned) <= maximum_points:
        return cleaned
    if maximum_points < 2:
        return cleaned[:maximum_points]

    reference_latitude = math.radians(sum(point[0] for point in cleaned) / len(cleaned))
    projected = [
        (longitude * math.cos(reference_latitude), latitude)
        for latitude, longitude in cleaned
    ]

    def reduce(tolerance: float) -> list[int]:
        keep = {0, len(projected) - 1}
        stack = [(0, len(projected) - 1)]
        while stack:
            first, last = stack.pop()
            ax, ay = projected[first]
            bx, by = projected[last]
            dx, dy = bx - ax, by - ay
            length_sq = dx * dx + dy * dy
            furthest = -1
            furthest_distance = -1.0
            for index in range(first + 1, last):
                px, py = projected[index]
                if length_sq <= 1e-20:
                    distance = math.hypot(px - ax, py - ay)
                else:
                    fraction = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
                    distance = math.hypot(px - (ax + fraction * dx), py - (ay + fraction * dy))
                if distance > furthest_distance:
                    furthest, furthest_distance = index, distance
            if furthest >= 0 and furthest_distance > tolerance:
                keep.add(furthest)
                stack.append((first, furthest))
                stack.append((furthest, last))
        return sorted(keep)

    low, high = 0.0, max(
        max(point[0] for point in projected) - min(point[0] for point in projected),
        max(point[1] for point in projected) - min(point[1] for point in projected),
    )
    indices = list(range(len(cleaned)))
    for _ in range(28):
        middle = (low + high) / 2.0
        candidate = reduce(middle)
        if len(candidate) > maximum_points:
            low = middle
        else:
            high = middle
            indices = candidate
    if len(indices) > maximum_points:
        positions = [round(index * (len(indices) - 1) / (maximum_points - 1)) for index in range(maximum_points)]
        indices = [indices[position] for position in positions]
    return [cleaned[index] for index in indices]


def parse_graphhopper_response(payload: dict) -> tuple[list[tuple[float, float, float | None]], float, float]:
    paths = payload.get("paths") or []
    if not paths:
        raise ValueError(str(payload.get("message") or "GraphHopper returned no route."))
    path = paths[0]
    geometry = path.get("points") or {}
    coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if not coordinates:
        raise ValueError("GraphHopper returned no route geometry.")
    result: list[tuple[float, float, float | None]] = []
    for coordinate in coordinates:
        if len(coordinate) < 2:
            continue
        elevation = float(coordinate[2]) if len(coordinate) > 2 else None
        result.append((float(coordinate[1]), float(coordinate[0]), elevation))
    if len(result) < 2:
        raise ValueError("GraphHopper returned no route geometry.")
    elevations = [point[2] for point in result]
    if all(value is not None and math.isfinite(value) for value in elevations) and all(
        abs(float(value)) < 1e-9 for value in elevations
    ):
        # GraphHopper databases imported without an elevation provider commonly
        # return a synthetic zero for every point.  Treat that as unavailable so
        # the editor does not present a flat zero-metre profile as measured data.
        result = [(latitude, longitude, None) for latitude, longitude, _ in result]
    return result, float(path.get("distance", 0.0)), float(path.get("time", 0.0)) / 1000.0


class RoutePlannerDialog(QtWidgets.QDialog):
    creditUsageUpdated = QtCore.Signal(int, int, int)

    def __init__(
        self,
        language: str,
        theme: str,
        service_url: str,
        api_key: str,
        provider: str,
        initial_center: tuple[float, float, int],
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.language = language if language in TEXT else "ru"
        self.text = TEXT[self.language]
        self.service_url = normalized_route_url(service_url)
        self.api_key = api_key.strip()
        self.control_points: list[tuple[float, float]] = []
        self.route_coordinates: list[tuple[float, float, float | None]] = []
        self.route_distance_m = 0.0
        self.route_duration_s = 0.0
        self._manager = QtNetwork.QNetworkAccessManager(self)
        self._reply: QtNetwork.QNetworkReply | None = None
        self._batches: list[list[tuple[float, float]]] = []
        self._batch_index = 0
        self._merged_coordinates: list[tuple[float, float, float | None]] = []
        self._merged_distance_m = 0.0
        self._merged_duration_s = 0.0

        self.setWindowTitle(self.text["title"])
        self.setWindowIcon(route_pin_icon("#111111"))
        self.setObjectName("routePlanner")
        self.setWindowFlag(QtCore.Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowMinimizeButtonHint, True)
        self.resize(1050, 720)
        layout = QtWidgets.QVBoxLayout(self)
        self.heading_label = QtWidgets.QLabel(self.text["title"])
        self.heading_label.setObjectName("routeHeading")
        layout.addWidget(self.heading_label)
        self.intro_label = QtWidgets.QLabel(self.text["intro"])
        if not route_service_requires_key(self.service_url):
            self.intro_label.setText(self.text["intro_local"])
        self.intro_label.setObjectName("routeIntro")
        self.intro_label.setWordWrap(True)
        layout.addWidget(self.intro_label)

        form = QtWidgets.QHBoxLayout()
        self.name_label = QtWidgets.QLabel(self.text["name"])
        self.name_label.setObjectName("routeFieldLabel")
        form.addWidget(self.name_label)
        self.name_edit = QtWidgets.QLineEdit(self.text["default_name"])
        form.addWidget(self.name_edit, 1)
        self.mode_label = QtWidgets.QLabel(self.text["mode"])
        self.mode_label.setObjectName("routeFieldLabel")
        form.addWidget(self.mode_label)
        self.profile_combo = QtWidgets.QComboBox()
        icon_colour = "#263445" if theme == "light" else "#e7e9ee"
        hosted = route_service_requires_key(self.service_url)
        for mode_id, profile, label_key, description_key, icon_kind, advanced in ROUTE_MODES:
            label = self.text[label_key]
            if hosted and advanced:
                label += self.text["advanced_suffix"]
            self.profile_combo.addItem(
                pack_icon(icon_kind, icon_colour),
                label,
                {
                    "mode": mode_id,
                    "profile": profile,
                    "description": description_key,
                    "advanced": advanced,
                },
            )
        self.profile_combo.setCurrentIndex(2)
        self.profile_combo.setMinimumWidth(310)
        form.addWidget(self.profile_combo)
        layout.addLayout(form)
        self.mode_description_label = QtWidgets.QLabel()
        self.mode_description_label.setObjectName("routeModeDescription")
        self.mode_description_label.setWordWrap(True)
        layout.addWidget(self.mode_description_label)

        self.map_widget = MapWidget()
        self.map_widget.set_download_visible(False)
        self.map_widget.set_theme(theme)
        self.map_widget.set_language(self.language)
        self.map_widget.set_provider(provider)
        self.map_widget._center_lat = float(initial_center[0])
        self.map_widget._center_lon = float(initial_center[1])
        self.map_widget._zoom = int(initial_center[2])
        self.map_widget.set_point_selection_enabled(True)
        self.map_widget.mapClicked.connect(self._add_point)
        layout.addWidget(self.map_widget, 1)

        self.route_controls_overlay = QtWidgets.QFrame(self.map_widget)
        self.route_controls_overlay.setObjectName("routeMapControls")
        overlay_layout = QtWidgets.QVBoxLayout(self.route_controls_overlay)
        overlay_layout.setContentsMargins(10, 8, 10, 9)
        overlay_layout.setSpacing(7)
        self.point_label = QtWidgets.QLabel()
        self.point_label.setObjectName("routePointCount")
        self.point_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(self.point_label)
        controls = QtWidgets.QGridLayout()
        controls.setSpacing(7)
        self.undo_button = QtWidgets.QPushButton(self.text["undo"])
        self.clear_button = QtWidgets.QPushButton(self.text["clear"])
        self.build_button = QtWidgets.QPushButton(self.text["build"])
        self.build_button.setObjectName("routeBuildButton")
        self.add_button = QtWidgets.QPushButton(self.text["add"])
        self.add_button.setObjectName("routeAddButton")
        self.fullscreen_button = QtWidgets.QPushButton(self.text["fullscreen"])
        self.cancel_button = QtWidgets.QPushButton(self.text["close"])
        route_buttons = (
            (self.build_button, "route_create"),
            (self.add_button, "add"),
            (self.fullscreen_button, "fit"),
            (self.undo_button, "undo"),
            (self.clear_button, "trash"),
            (self.cancel_button, "close"),
        )
        for index, (button, icon_kind) in enumerate(route_buttons):
            button.setIcon(pack_icon(icon_kind, icon_colour))
            button.setIconSize(
                QtCore.QSize(20, 20)
            )
            button.setMinimumHeight(46)
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            controls.addWidget(button, index // 3, index % 3)
        overlay_layout.addLayout(controls)
        self.route_controls_overlay.adjustSize()
        self.route_controls_overlay.raise_()
        self.map_widget.installEventFilter(self)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setObjectName("routeStatus")
        self.status_label.setMinimumHeight(36)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        self.undo_button.clicked.connect(self._remove_last)
        self.clear_button.clicked.connect(self._clear)
        self.build_button.clicked.connect(self._build_route)
        self.fullscreen_button.clicked.connect(self._toggle_maximized)
        self.profile_combo.currentIndexChanged.connect(self._mode_changed)
        accent = "#287bc1" if theme == "light" else "#4ba8ff"
        intro_colour = "#617083" if theme == "light" else "#aab5c4"
        status_background = "#eaf4fc" if theme == "light" else "#1b2835"
        overlay_background = "rgba(255,255,255,242)" if theme == "light" else "rgba(26,31,38,238)"
        overlay_border = "#aab6c4" if theme == "light" else "#596574"
        overlay_text = "#17202b" if theme == "light" else "#e7e9ee"
        self.setStyleSheet(
            "QLabel#routeHeading { font-size:22px; font-weight:700; padding:2px 0 0 0; }"
            f"QLabel#routeIntro {{ font-size:12px; color:{intro_colour}; padding-bottom:5px; }}"
            "QLabel#routeFieldLabel { font-size:12px; font-weight:650; }"
            f"QLabel#routeModeDescription {{ color:{intro_colour}; font-size:12px; padding:0 0 5px 0; }}"
            f"QFrame#routeMapControls {{ background:{overlay_background}; "
            f"border:1px solid {overlay_border}; border-radius:9px; }}"
            "QFrame#routeMapControls QLabel { background:transparent; border:none; }"
            f"QLabel#routePointCount {{ color:{overlay_text}; font-size:13px; font-weight:700; }}"
            "QFrame#routeMapControls QPushButton { font-size:12px; font-weight:650; "
            "padding:9px 12px; }"
            f"QLabel#routeStatus {{ background:{status_background}; border-left:3px solid {accent}; "
            "border-radius:4px; padding:7px 10px; }"
            f"QPushButton#routeBuildButton {{ background:{accent}; color:#ffffff; "
            f"border:1px solid {accent}; font-weight:700; }}"
            "QPushButton#routeAddButton { background:#317a51; color:#ffffff; border:1px solid #4aa36f; }"
            "QPushButton#routeBuildButton:disabled, QPushButton#routeAddButton:disabled { "
            f"background:{status_background}; color:{intro_colour}; border:1px solid {overlay_border}; }}"
        )
        self._mode_changed()
        self._refresh_controls()
        QtCore.QTimer.singleShot(0, self._position_route_controls)

    @property
    def route_name(self) -> str:
        return self.name_edit.text().strip() or self.text["default_name"]

    @property
    def profile(self) -> str:
        data = self.profile_combo.currentData()
        return str(data.get("profile", "bike")) if isinstance(data, dict) else str(data)

    @property
    def route_mode(self) -> str:
        data = self.profile_combo.currentData()
        return str(data.get("mode", "bike")) if isinstance(data, dict) else str(data)

    def _mode_changed(self) -> None:
        data = self.profile_combo.currentData()
        description_key = data.get("description") if isinstance(data, dict) else None
        self.mode_description_label.setText(self.text.get(str(description_key), ""))
        if self.route_coordinates:
            self.route_coordinates = []
            self.route_distance_m = 0.0
            self.route_duration_s = 0.0
            self.add_button.setEnabled(False)
            self.status_label.clear()
            self._refresh_map()
        self._refresh_controls()

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.map_widget and event.type() in {
            QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Show,
        }:
            QtCore.QTimer.singleShot(0, self._position_route_controls)
        return super().eventFilter(watched, event)

    def _position_route_controls(self) -> None:
        if not hasattr(self, "route_controls_overlay"):
            return
        self.route_controls_overlay.adjustSize()
        x = max(10, (self.map_widget.width() - self.route_controls_overlay.width()) // 2)
        y = max(10, self.map_widget.height() - self.route_controls_overlay.height() - 12)
        self.route_controls_overlay.move(x, y)
        self.route_controls_overlay.raise_()

    def _refresh_controls(self) -> None:
        requests = (
            0 if self.route_mode == "direct"
            else max(1, len(route_batches_for_service(
                self.control_points, self.service_url
            ))) if self.control_points else 0
        )
        self.point_label.setText(self.text["points"].format(
            count=len(self.control_points), requests=requests,
        ))
        busy = self._reply is not None
        self.undo_button.setEnabled(bool(self.control_points) and not busy)
        self.clear_button.setEnabled(bool(self.control_points) and not busy)
        self.build_button.setEnabled(len(self.control_points) >= 2 and not busy)
        if not self.status_label.text():
            self.status_label.setText(
                self.text["ready_to_build"]
                if len(self.control_points) >= 2 else self.text["need_points"]
            )

    def _refresh_map(self, fit: bool = False) -> None:
        # Before routing, waypoints are deliberately shown without straight
        # connectors: such lines can be mistaken for the calculated route.
        coordinates = self.route_coordinates
        if len(coordinates) >= 2:
            self.map_widget.set_tracks([{
                "lat": [point[0] for point in coordinates],
                "lon": [point[1] for point in coordinates],
                "colour": "#2f9df4",
                "active": True,
                "name": "",
            }], fit=fit)
        else:
            self.map_widget.set_tracks([], fit=False)
        self.map_widget.set_waypoints(self.control_points)

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QtCore.QEvent.Type.WindowStateChange
            and hasattr(self, "fullscreen_button")
        ):
            self.fullscreen_button.setText(
                self.text["windowed"] if self.isMaximized() else self.text["fullscreen"]
            )

    def _add_point(self, latitude: float, longitude: float) -> None:
        if self._reply is not None:
            return
        if len(self.control_points) >= MAX_CONTROL_POINTS:
            self.status_label.setText(self.text["point_limit"])
            QtWidgets.QApplication.beep()
            return
        self.control_points.append((latitude, longitude))
        self.route_coordinates = []
        self.add_button.setEnabled(False)
        self.status_label.clear()
        self._refresh_map()
        self._refresh_controls()

    def _remove_last(self) -> None:
        if self.control_points:
            self.control_points.pop()
        self.route_coordinates = []
        self.add_button.setEnabled(False)
        self.status_label.clear()
        self._refresh_map()
        self._refresh_controls()

    def _clear(self) -> None:
        self.control_points.clear()
        self.route_coordinates = []
        self.add_button.setEnabled(False)
        self.status_label.clear()
        self._refresh_map()
        self._refresh_controls()

    def _build_route(self) -> None:
        if len(self.control_points) < 2:
            self.status_label.setText(self.text["need_points"])
            return
        if self.route_mode == "direct":
            self._batches = []
            self.route_coordinates = [
                (latitude, longitude, None)
                for latitude, longitude in self.control_points
            ]
            self.route_distance_m = direct_route_distance(self.control_points)
            self.route_duration_s = 0.0
            self.status_label.setText(self.text["ready_direct"].format(
                distance=self.route_distance_m / 1000.0,
                points=len(self.route_coordinates),
            ))
            self._refresh_map(fit=True)
            self.add_button.setEnabled(True)
            self._refresh_controls()
            return
        if route_service_requires_key(self.service_url) and not self.api_key:
            QtWidgets.QMessageBox.warning(self, self.text["error"], self.text["need_key"])
            return
        self._batches = route_batches_for_service(self.control_points, self.service_url)
        self._batch_index = 0
        self._merged_coordinates = []
        self._merged_distance_m = 0.0
        self._merged_duration_s = 0.0
        self.route_coordinates = []
        self.add_button.setEnabled(False)
        self._post_current_batch()

    def _post_current_batch(self) -> None:
        if not self._batches or self._batch_index >= len(self._batches):
            return
        url = QtCore.QUrl(self.service_url)
        query = QtCore.QUrlQuery(url)
        if self.api_key:
            query.addQueryItem("key", self.api_key)
        url.setQuery(query)
        request = QtNetwork.QNetworkRequest(url)
        request.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        data = json.dumps(graphhopper_payload(
            self._batches[self._batch_index], self.profile,
        )).encode("utf-8")
        self._reply = self._manager.post(request, data)
        self._reply.finished.connect(self._route_finished)
        self.status_label.setText(self.text["request"].format(
            current=self._batch_index + 1, total=len(self._batches),
        ))
        self._refresh_controls()

    def _route_finished(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        usage = parse_rate_limit_headers(reply.rawHeaderPairs())
        if usage is not None:
            self.creditUsageUpdated.emit(*usage)
        try:
            raw = bytes(reply.readAll())
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                message = payload.get("message") if isinstance(payload, dict) else None
                raise ValueError(str(message or reply.errorString()))
            coordinates, distance, duration = parse_graphhopper_response(payload)
            if self._merged_coordinates and coordinates:
                # Consecutive batches share their boundary location. Drop the
                # repeated geometry sample so the exported GPX remains clean.
                coordinates = coordinates[1:]
            self._merged_coordinates.extend(coordinates)
            self._merged_distance_m += distance
            self._merged_duration_s += duration
            self._batch_index += 1
            reply.deleteLater()
            if self._batch_index < len(self._batches):
                self._post_current_batch()
                return
            self.route_coordinates = self._merged_coordinates
            self.route_distance_m = self._merged_distance_m
            self.route_duration_s = self._merged_duration_s
            self.status_label.setText(self.text["ready"].format(
                distance=self.route_distance_m / 1000.0,
                parts=len(self._batches),
                points=len(self.route_coordinates),
            ))
            self._refresh_map(fit=True)
            self.add_button.setEnabled(True)
        except Exception as error:
            self.route_coordinates = []
            self._batches = []
            self.status_label.setText(f"{self.text['error']}: {error}")
            reply.deleteLater()
        self._refresh_controls()

    def reject(self) -> None:
        if self._reply is not None:
            self._reply.abort()
        super().reject()


class RoutePlannerPanel(QtWidgets.QFrame):
    """Route-building controls embedded directly over the main map."""

    creditUsageUpdated = QtCore.Signal(int, int, int)
    routeCreated = QtCore.Signal(object, str, float)
    routeSaveRequested = QtCore.Signal(object, str)
    cancelled = QtCore.Signal(object)

    def __init__(
        self,
        language: str,
        theme: str,
        service_url: str,
        api_key: str,
        map_widget: MapWidget,
        track_points_provider: Callable[[], list[tuple[float, float]]],
        initial_state: dict | None = None,
    ):
        super().__init__(map_widget)
        self.language = language if language in TEXT else "ru"
        self.text = TEXT[self.language]
        self.theme = "light" if theme == "light" else "dark"
        self.service_url = normalized_route_url(service_url)
        self.api_key = api_key.strip()
        self.map_widget = map_widget
        self.track_points_provider = track_points_provider
        self.control_points: list[tuple[float, float]] = []
        self.route_coordinates: list[tuple[float, float, float | None]] = []
        self.route_distance_m = 0.0
        self.route_duration_s = 0.0
        self._manager = QtNetwork.QNetworkAccessManager(self)
        self._reply: QtNetwork.QNetworkReply | None = None
        self._batches: list[list[tuple[float, float]]] = []
        self._batch_index = 0
        self._merged_coordinates: list[tuple[float, float, float | None]] = []
        self._merged_distance_m = 0.0
        self._merged_duration_s = 0.0
        self._drag_source: QtCore.QObject | None = None
        self._drag_start_global = QtCore.QPoint()
        self._drag_origin = QtCore.QPoint()
        self._drag_started = False
        self._drag_surfaces: list[QtWidgets.QWidget] = []
        self._manual_position: QtCore.QPoint | None = None
        self.setObjectName("routeMapControls")
        self.setMinimumWidth(610)
        self._build_ui()
        self._restore_state(initial_state or {})
        self.map_widget.installEventFilter(self)
        self.map_widget.mapClicked.connect(self._add_point)
        self.map_widget.routePointRequested.connect(self._insert_point)
        self.map_widget.waypointMoved.connect(self._move_point)
        self.map_widget.waypointRemoveRequested.connect(self._remove_point)
        self.map_widget.overlayLaneChanged.connect(lambda _lane: self._position_panel())
        self.map_widget.set_point_selection_enabled(True)
        self.map_widget.set_search_visible(True)
        self._refresh_map()
        self.show()
        self.raise_()
        QtCore.QTimer.singleShot(0, self._position_panel)

    def _restore_state(self, state: dict) -> None:
        points = state.get("control_points", [])
        coordinates = state.get("route_coordinates", [])
        self.control_points = [
            (float(point[0]), float(point[1])) for point in points
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        self.route_coordinates = [
            (float(point[0]), float(point[1]),
             None if len(point) < 3 or point[2] is None else float(point[2]))
            for point in coordinates
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        self.route_distance_m = float(state.get("route_distance_m", 0.0) or 0.0)
        self.route_duration_s = float(state.get("route_duration_s", 0.0) or 0.0)
        saved_position = state.get("panel_position")
        if isinstance(saved_position, (list, tuple)) and len(saved_position) >= 2:
            self._manual_position = QtCore.QPoint(
                int(saved_position[0]), int(saved_position[1])
            )
        self.name_edit.setText(str(state.get("route_name") or self.text["default_name"]))
        saved_mode = str(state.get("route_mode") or "bike")
        blocker = QtCore.QSignalBlocker(self.profile_combo)
        for index in range(self.profile_combo.count()):
            data = self.profile_combo.itemData(index)
            if isinstance(data, dict) and data.get("mode") == saved_mode:
                self.profile_combo.setCurrentIndex(index)
                break
        del blocker
        if self.route_coordinates:
            self.add_button.setEnabled(True)
            self.status_label.setText(self.text["ready"].format(
                distance=self.route_distance_m / 1000.0,
                parts=1,
                points=len(self.route_coordinates),
            ) + " " + self.text["edit_hint"])
        elif len(self.control_points) >= 2:
            self.status_label.setText(self.text["ready_to_build"])
        self._refresh_controls()

    def export_state(self) -> dict:
        return {
            "control_points": list(self.control_points),
            "route_coordinates": list(self.route_coordinates),
            "route_distance_m": float(self.route_distance_m),
            "route_duration_s": float(self.route_duration_s),
            "route_name": self.route_name,
            "route_mode": self.route_mode,
            "panel_position": (
                [self._manual_position.x(), self._manual_position.y()]
                if self._manual_position is not None else None
            ),
        }

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 11)
        layout.setSpacing(8)
        drag_row = QtWidgets.QHBoxLayout()
        drag_row.setSpacing(4)
        self.drag_handle = QtWidgets.QLabel("⋮⋮")
        self.drag_handle.setObjectName("routeDragHandle")
        self.drag_handle.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.drag_handle.setToolTip(self.text["drag_panel_hint"])
        self.close_button = self._button("", "close", "routeCloseButton")
        self.close_button.setToolTip(self.text["exit"])
        self.close_button.setFixedSize(34, 31)
        drag_row.addStretch(1)
        drag_row.addWidget(self.drag_handle)
        drag_row.addStretch(1)
        drag_row.addWidget(self.close_button)
        layout.addLayout(drag_row)

        top = QtWidgets.QHBoxLayout()
        self.name_edit = QtWidgets.QLineEdit(self.text["default_name"])
        self.name_edit.setPlaceholderText(self.text["name"])
        self.profile_combo = QtWidgets.QComboBox()
        icon_colour = "#263445" if self.theme == "light" else "#e7e9ee"
        hosted = route_service_requires_key(self.service_url)
        for mode_id, profile, label_key, description_key, icon_kind, advanced in ROUTE_MODES:
            label = self.text[label_key]
            if hosted and advanced:
                label += self.text["advanced_suffix"]
            self.profile_combo.addItem(
                pack_icon(icon_kind, icon_colour),
                label,
                {"mode": mode_id, "profile": profile, "description": description_key},
            )
        self.profile_combo.setCurrentIndex(2)
        self.profile_combo.setMinimumWidth(230)
        top.addWidget(self.name_edit, 1)
        top.addWidget(self.profile_combo, 1)
        layout.addLayout(top)

        self.point_label = QtWidgets.QLabel()
        self.point_label.setObjectName("routePointCount")
        self.point_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.point_label)

        metrics = QtWidgets.QHBoxLayout()
        metrics.setSpacing(8)
        self.distance_card, self.distance_icon, self.distance_value = self._metric_card(
            "distance", self.text["distance_label"]
        )
        self.ascent_card, self.ascent_icon, self.ascent_value = self._metric_card(
            "altitude", self.text["ascent_label"]
        )
        metrics.addWidget(self.distance_card, 1)
        metrics.addWidget(self.ascent_card, 1)
        layout.addLayout(metrics)

        controls = QtWidgets.QGridLayout()
        controls.setSpacing(5)
        self.build_button = self._button(self.text["build"], "route_create", "routeBuildButton")
        self.save_gpx_button = self._button(self.text["save_gpx"], "save", "routeSaveButton")
        self.add_button = self._button(self.text["add"], "add", "routeAddButton")
        self.from_track_button = self._button(
            self.text["from_track"], "route_from_track", "routeFromTrackButton"
        )
        self.clear_button = self._button(self.text["clear"], "trash", "routeClearButton")
        controls.addWidget(self.build_button, 0, 0)
        controls.addWidget(self.save_gpx_button, 0, 1)
        controls.addWidget(self.add_button, 0, 2)
        controls.addWidget(self.from_track_button, 1, 0, 1, 2)
        controls.addWidget(self.clear_button, 1, 2)
        layout.addLayout(controls)

        self.status_label = QtWidgets.QLabel(self.text["need_points"])
        self.status_label.setObjectName("routeStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.build_button.clicked.connect(self._build_route)
        self.save_gpx_button.clicked.connect(self._save_gpx)
        self.add_button.clicked.connect(self._accept_route)
        self.from_track_button.clicked.connect(self._from_loaded_track)
        self.clear_button.clicked.connect(self._clear)
        self.close_button.clicked.connect(self.close_mode)
        self.profile_combo.currentIndexChanged.connect(self._mode_changed)
        self.save_gpx_button.setEnabled(False)
        self.add_button.setEnabled(False)
        self._apply_theme()
        self._refresh_controls()
        self._install_drag_surfaces()

    def _metric_card(
        self, icon_kind: str, caption: str,
    ) -> tuple[QtWidgets.QFrame, QtWidgets.QLabel, QtWidgets.QLabel]:
        card = QtWidgets.QFrame()
        card.setObjectName("routeMetricCard")
        row = QtWidgets.QHBoxLayout(card)
        row.setContentsMargins(11, 7, 11, 7)
        row.setSpacing(9)
        icon_label = QtWidgets.QLabel()
        icon_label.setObjectName("routeMetricIcon")
        icon_label.setFixedSize(26, 26)
        icon_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        text_column = QtWidgets.QVBoxLayout()
        text_column.setSpacing(0)
        caption_label = QtWidgets.QLabel(caption)
        caption_label.setObjectName("routeMetricCaption")
        value_label = QtWidgets.QLabel("—")
        value_label.setObjectName("routeMetricValue")
        text_column.addWidget(caption_label)
        text_column.addWidget(value_label)
        row.addWidget(icon_label)
        row.addLayout(text_column, 1)
        card.setProperty("metricIconKind", icon_kind)
        return card, icon_label, value_label

    def _button(self, text: str, kind: str, object_name: str = "") -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        if object_name:
            button.setObjectName(object_name)
        icon_colour = "#263445" if self.theme == "light" else "#e7e9ee"
        button.setIcon(pack_icon(kind, "#ffffff" if kind == "route_create" else icon_colour))
        button.setIconSize(QtCore.QSize(18, 18))
        button.setMinimumHeight(42)
        return button

    def _apply_theme(self) -> None:
        if self.theme == "light":
            background, border, text = "rgba(255,255,255,246)", "#9ba9b8", "#17202b"
            status_background, muted, accent = "#eaf4fc", "#617083", "#287bc1"
        else:
            background, border, text = "rgba(26,31,38,246)", "#596574", "#e7e9ee"
            status_background, muted, accent = "#1b2835", "#aab5c4", "#4ba8ff"
        self.setStyleSheet(
            f"QFrame#routeMapControls {{ background:{background}; border:2px solid {accent}; border-radius:11px; }}"
            "QFrame#routeMapControls QLabel { background:transparent; border:none; }"
            f"QLabel#routePointCount {{ color:{text}; font-size:12px; font-weight:700; }}"
            f"QFrame#routeMetricCard {{ background:{status_background}; border:1px solid {border}; border-radius:7px; }}"
            f"QLabel#routeMetricCaption {{ color:{muted}; font-size:11px; font-weight:600; }}"
            f"QLabel#routeMetricValue {{ color:{accent}; font-size:16px; font-weight:800; }}"
            f"QLabel#routeDragHandle {{ color:{muted}; font-size:12px; font-weight:650; "
            f"padding:1px 6px 3px 6px; }}"
            f"QLabel#routeStatus {{ color:{muted}; background:{status_background}; border-left:3px solid {accent}; padding:6px; font-size:12px; }}"
            "QPushButton { font-size:12px; font-weight:700; padding:7px 10px; }"
            "QPushButton#routeCloseButton { background:transparent; border:none; padding:2px; }"
            f"QPushButton#routeCloseButton:hover {{ background:{status_background}; }}"
            f"QPushButton#routeBuildButton {{ background:{accent}; color:#ffffff; border-color:{accent}; }}"
            "QPushButton#routeSaveButton { background:#5c4c82; color:#ffffff; border-color:#806caf; }"
            "QPushButton#routeAddButton { background:#317a51; color:#ffffff; border-color:#4aa36f; }"
            "QPushButton#routeFromTrackButton { background:#6d5638; color:#ffffff; border-color:#9a7950; }"
            "QPushButton#routeClearButton { background:#713946; color:#ffffff; border-color:#a15466; }"
            f"QPushButton#routeBuildButton:disabled, QPushButton#routeSaveButton:disabled, "
            f"QPushButton#routeAddButton:disabled, QPushButton#routeFromTrackButton:disabled, "
            f"QPushButton#routeClearButton:disabled {{ background:{status_background}; color:{muted}; border-color:{border}; }}"
        )
        self.distance_icon.setPixmap(pack_icon("distance", accent).pixmap(24, 24))
        self.ascent_icon.setPixmap(pack_icon("altitude", accent).pixmap(24, 24))

    @property
    def route_name(self) -> str:
        return self.name_edit.text().strip() or self.text["default_name"]

    @property
    def profile(self) -> str:
        data = self.profile_combo.currentData()
        return str(data.get("profile", "bike")) if isinstance(data, dict) else "bike"

    @property
    def route_mode(self) -> str:
        data = self.profile_combo.currentData()
        return str(data.get("mode", "bike")) if isinstance(data, dict) else "bike"

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched in self._drag_surfaces:
            if (
                event.type() == QtCore.QEvent.Type.MouseButtonPress
                and isinstance(event, QtGui.QMouseEvent)
                and event.button() == QtCore.Qt.MouseButton.LeftButton
            ):
                self._drag_source = watched
                self._drag_start_global = event.globalPosition().toPoint()
                self._drag_origin = self.pos()
                self._drag_started = False
                if isinstance(watched, QtWidgets.QAbstractButton):
                    return False
                # Labels and the frame itself normally ignore mouse presses,
                # which would forward the same press to the parent map.  Grab
                # the mouse here so the map never enters its own pan gesture.
                self.grabMouse()
                return True
            if (
                event.type() == QtCore.QEvent.Type.MouseMove
                and isinstance(event, QtGui.QMouseEvent)
                and self._drag_source is not None
                and bool(event.buttons() & QtCore.Qt.MouseButton.LeftButton)
            ):
                delta = event.globalPosition().toPoint() - self._drag_start_global
                if (
                    not self._drag_started
                    and delta.manhattanLength() >= QtWidgets.QApplication.startDragDistance()
                ):
                    self._drag_started = True
                    if isinstance(self._drag_source, QtWidgets.QAbstractButton):
                        self._drag_source.setDown(False)
                    self._set_drag_cursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                if self._drag_started:
                    self._move_panel_to(self._drag_origin + delta, manual=True)
                    return True
            if (
                event.type() == QtCore.QEvent.Type.MouseButtonRelease
                and isinstance(event, QtGui.QMouseEvent)
                and event.button() == QtCore.Qt.MouseButton.LeftButton
            ):
                dragged = self._drag_started
                source = self._drag_source
                if QtWidgets.QWidget.mouseGrabber() is self:
                    self.releaseMouse()
                self._drag_source = None
                self._drag_started = False
                self._set_drag_cursor(QtCore.Qt.CursorShape.OpenHandCursor)
                return dragged or not isinstance(source, QtWidgets.QAbstractButton)
        if watched is self.map_widget and event.type() in {
            QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Show,
        }:
            QtCore.QTimer.singleShot(0, self._position_panel)
        return super().eventFilter(watched, event)

    def _install_drag_surfaces(self) -> None:
        self._drag_surfaces = [self]
        for widget in self.findChildren(QtWidgets.QWidget):
            ancestor: QtWidgets.QWidget | None = widget
            belongs_to_editor = False
            while ancestor is not None and ancestor is not self:
                if isinstance(ancestor, (QtWidgets.QLineEdit, QtWidgets.QComboBox)):
                    belongs_to_editor = True
                    break
                ancestor = ancestor.parentWidget()
            if belongs_to_editor:
                continue
            self._drag_surfaces.append(widget)
        for widget in self._drag_surfaces:
            widget.installEventFilter(self)
        self._set_drag_cursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.name_edit.setCursor(QtCore.Qt.CursorShape.IBeamCursor)
        self.profile_combo.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.profile_combo.view().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.profile_combo.view().viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)

    def _set_drag_cursor(self, shape: QtCore.Qt.CursorShape) -> None:
        cursor = QtGui.QCursor(shape)
        for widget in self._drag_surfaces:
            widget.setCursor(cursor)

    def _position_panel(self) -> None:
        if not self.isVisible():
            return
        available_width = max(420, self.map_widget.width() - 32)
        self.setMinimumWidth(min(610, available_width))
        self.setMaximumWidth(available_width)
        self.adjustSize()
        if self._manual_position is not None:
            self._move_panel_to(self._manual_position, manual=False)
            return
        x = max(12, (self.map_widget.width() - self.width()) // 2)
        if getattr(self.map_widget, "_overlay_vertical", "top") == "top":
            y = max(12, self.map_widget.height() - self.height() - 14)
        else:
            y = 14
        self.move(x, y)
        self.raise_()

    def _move_panel_to(self, position: QtCore.QPoint, manual: bool) -> None:
        margin = 8
        maximum_x = max(margin, self.map_widget.width() - self.width() - margin)
        maximum_y = max(margin, self.map_widget.height() - self.height() - margin)
        clamped = QtCore.QPoint(
            max(margin, min(int(position.x()), maximum_x)),
            max(margin, min(int(position.y()), maximum_y)),
        )
        if manual:
            self._manual_position = QtCore.QPoint(clamped)
        elif self._manual_position is not None:
            self._manual_position = QtCore.QPoint(clamped)
        self.move(clamped)
        self.raise_()

    def _refresh_controls(self) -> None:
        requests = 0 if self.route_mode == "direct" else (
            1 if self.route_mode == "river" and len(self.control_points) >= 2 else
            len(route_batches_for_service(self.control_points, self.service_url))
            if len(self.control_points) >= 2 else 0
        )
        self.point_label.setText(self.text["points"].format(
            count=len(self.control_points), requests=requests,
        ))
        distance = (
            f"{self.route_distance_m / 1000.0:.2f} " + ("км" if self.language == "ru" else "km")
            if self.route_distance_m > 0.0 else "—"
        )
        ascent = route_ascent_m(self.route_coordinates)
        ascent_text = (
            f"{ascent:.0f} " + ("м" if self.language == "ru" else "m")
            if ascent is not None else "—"
        )
        self.distance_value.setText(distance)
        self.ascent_value.setText(ascent_text)
        busy = self._reply is not None
        self.clear_button.setEnabled(bool(self.control_points) and not busy)
        self.build_button.setEnabled(len(self.control_points) >= 2 and not busy)
        self.from_track_button.setEnabled(not busy)
        self.close_button.setEnabled(not busy)
        route_ready = len(self.route_coordinates) >= 2 and not busy
        self.save_gpx_button.setEnabled(route_ready)
        self.add_button.setEnabled(route_ready)

    def _refresh_map(self, fit: bool = False) -> None:
        self.map_widget.set_route_draft(self.route_coordinates, self.control_points)
        if fit:
            self.map_widget.fit_route()

    def _invalidate_route(self, message: str = "") -> None:
        self.route_coordinates = []
        self.route_distance_m = 0.0
        self.route_duration_s = 0.0
        self.add_button.setEnabled(False)
        if message:
            self.status_label.setText(message)
        self._refresh_map()
        self._refresh_controls()

    def _add_point(self, latitude: float, longitude: float) -> None:
        if self._reply is not None:
            return
        if len(self.control_points) >= MAX_CONTROL_POINTS:
            self.status_label.setText(self.text["point_limit"])
            QtWidgets.QApplication.beep()
            return
        self.control_points.append((latitude, longitude))
        self._invalidate_route(
            self.text["ready_to_build"] if len(self.control_points) >= 2 else self.text["need_points"]
        )

    def _insert_point(self, latitude: float, longitude: float, index: int) -> None:
        if self._reply is not None or len(self.control_points) >= MAX_CONTROL_POINTS:
            return
        insertion = max(1, min(int(index), len(self.control_points) - 1))
        self.control_points.insert(insertion, (latitude, longitude))
        self._invalidate_route(self.text["inserted"])

    def _move_point(self, index: int, latitude: float, longitude: float) -> None:
        if 0 <= index < len(self.control_points):
            self.control_points[index] = (latitude, longitude)
            self._invalidate_route(self.text["moved"])

    def _remove_point(self, index: int) -> None:
        if self._reply is not None or not 0 <= index < len(self.control_points):
            return
        had_built_route = len(self.route_coordinates) >= 2
        self.control_points.pop(index)
        self._invalidate_route(
            self.text["removed"] if had_built_route and len(self.control_points) >= 2
            else self.text["ready_to_build"] if len(self.control_points) >= 2
            else self.text["need_points"]
        )
        if had_built_route and len(self.control_points) >= 2:
            QtCore.QTimer.singleShot(0, self._build_route)

    def _remove_last(self) -> None:
        if self.control_points:
            self.control_points.pop()
        self._invalidate_route(
            self.text["ready_to_build"] if len(self.control_points) >= 2 else self.text["need_points"]
        )

    def _clear(self) -> None:
        self.control_points.clear()
        self._invalidate_route(self.text["need_points"])

    def _from_loaded_track(self) -> None:
        points = self.track_points_provider()
        if len(points) < 2:
            self.status_label.setText(self.text["from_track_empty"])
            QtWidgets.QApplication.beep()
            return
        self.control_points = simplify_route_points(points, MAX_CONTROL_POINTS)
        self._invalidate_route(self.text["from_track_ready"].format(count=len(self.control_points)))
        self.map_widget.fit_route()

    def _mode_changed(self) -> None:
        if self.route_coordinates:
            self._invalidate_route(self.text["ready_to_build"])
        else:
            self._refresh_controls()

    def _build_route(self) -> None:
        if len(self.control_points) < 2:
            self.status_label.setText(self.text["need_points"])
            return
        if self.route_mode == "direct":
            self.route_coordinates = [(lat, lon, None) for lat, lon in self.control_points]
            self.route_distance_m = direct_route_distance(self.control_points)
            self.route_duration_s = 0.0
            self.status_label.setText(
                self.text["ready_direct"].format(
                    distance=self.route_distance_m / 1000.0,
                    points=len(self.route_coordinates),
                ) + " " + self.text["edit_hint"]
            )
            self.add_button.setEnabled(True)
            self._refresh_map(fit=True)
            self._refresh_controls()
            return
        if self.route_mode == "river":
            self._build_river_route()
            return
        if route_service_requires_key(self.service_url) and not self.api_key:
            QtWidgets.QMessageBox.warning(self, self.text["error"], self.text["need_key"])
            return
        self._batches = route_batches_for_service(self.control_points, self.service_url)
        self._batch_index = 0
        self._merged_coordinates = []
        self._merged_distance_m = 0.0
        self._merged_duration_s = 0.0
        self.route_coordinates = []
        self.add_button.setEnabled(False)
        self._post_current_batch()

    def _build_river_route(self) -> None:
        request = QtNetwork.QNetworkRequest(
            QtCore.QUrl("https://overpass-api.de/api/interpreter")
        )
        request.setHeader(
            QtNetwork.QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "application/x-www-form-urlencoded",
        )
        request.setRawHeader(b"User-Agent", b"AnyTrackEditor/0.12")
        form = QtCore.QUrlQuery()
        form.addQueryItem("data", river_overpass_query(self.control_points))
        data = form.query(QtCore.QUrl.ComponentFormattingOption.FullyEncoded).encode("utf-8")
        self.route_coordinates = []
        self.add_button.setEnabled(False)
        self._reply = self._manager.post(request, data)
        self._reply.finished.connect(self._river_finished)
        self.status_label.setText(self.text["river_request"])
        self._refresh_controls()

    def _river_finished(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        try:
            raw = bytes(reply.readAll())
            if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            self.route_coordinates = parse_river_route(payload, self.control_points)
            flat_points = [(point[0], point[1]) for point in self.route_coordinates]
            self.route_distance_m = direct_route_distance(flat_points)
            self.route_duration_s = 0.0
            self.status_label.setText(
                self.text["river_ready"].format(
                    distance=self.route_distance_m / 1000.0,
                    points=len(self.route_coordinates),
                ) + " " + self.text["edit_hint"]
            )
            self.add_button.setEnabled(True)
            self._refresh_map(fit=True)
        except Exception:
            self.route_coordinates = []
            self.status_label.setText(self.text["river_missing"])
        finally:
            reply.deleteLater()
            self._refresh_controls()

    def _post_current_batch(self) -> None:
        if not self._batches or self._batch_index >= len(self._batches):
            return
        url = QtCore.QUrl(self.service_url)
        query = QtCore.QUrlQuery(url)
        if self.api_key:
            query.addQueryItem("key", self.api_key)
        url.setQuery(query)
        request = QtNetwork.QNetworkRequest(url)
        request.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        data = json.dumps(graphhopper_payload(self._batches[self._batch_index], self.profile)).encode("utf-8")
        self._reply = self._manager.post(request, data)
        self._reply.finished.connect(self._route_finished)
        self.status_label.setText(self.text["request"].format(
            current=self._batch_index + 1, total=len(self._batches),
        ))
        self._refresh_controls()

    def _route_finished(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        usage = parse_rate_limit_headers(reply.rawHeaderPairs())
        if usage is not None:
            self.creditUsageUpdated.emit(*usage)
        try:
            raw = bytes(reply.readAll())
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                message = payload.get("message") if isinstance(payload, dict) else None
                raise ValueError(str(message or reply.errorString()))
            coordinates, distance, duration = parse_graphhopper_response(payload)
            if self._merged_coordinates and coordinates:
                coordinates = coordinates[1:]
            self._merged_coordinates.extend(coordinates)
            self._merged_distance_m += distance
            self._merged_duration_s += duration
            self._batch_index += 1
            reply.deleteLater()
            if self._batch_index < len(self._batches):
                self._post_current_batch()
                return
            self.route_coordinates = self._merged_coordinates
            self.route_distance_m = self._merged_distance_m
            self.route_duration_s = self._merged_duration_s
            self.status_label.setText(
                self.text["ready"].format(
                    distance=self.route_distance_m / 1000.0,
                    parts=len(self._batches),
                    points=len(self.route_coordinates),
                ) + " " + self.text["edit_hint"]
            )
            self.add_button.setEnabled(True)
            self._refresh_map(fit=True)
        except Exception as error:
            self.route_coordinates = []
            self._batches = []
            self.status_label.setText(f"{self.text['error']}: {error}")
            reply.deleteLater()
        self._refresh_controls()

    def _accept_route(self) -> None:
        if len(self.route_coordinates) >= 2:
            self.routeCreated.emit(
                list(self.route_coordinates), self.route_name, float(self.route_duration_s)
            )

    def _save_gpx(self) -> None:
        if len(self.route_coordinates) >= 2:
            self.routeSaveRequested.emit(
                list(self.route_coordinates), self.route_name
            )

    def close_mode(self) -> None:
        if self._reply is not None:
            self._reply.abort()
            self._reply = None
        if QtWidgets.QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self._drag_source = None
        self._drag_started = False
        for signal, slot in (
            (self.map_widget.mapClicked, self._add_point),
            (self.map_widget.routePointRequested, self._insert_point),
            (self.map_widget.waypointMoved, self._move_point),
            (self.map_widget.waypointRemoveRequested, self._remove_point),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self.map_widget.removeEventFilter(self)
        self.map_widget.set_point_selection_enabled(False)
        self.map_widget.set_search_visible(False)
        self.map_widget.clear_route_draft()
        self.hide()
        self.cancelled.emit(self.export_state())
        self.deleteLater()
