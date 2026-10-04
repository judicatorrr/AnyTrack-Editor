from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import math
import xml.etree.ElementTree as ET

import gpxpy
import numpy as np

try:
    from fit_tool import EncodeMode, FitFile
    from fit_tool.profile.messages.record_message import RecordMessage
except Exception:  # A helpful error is shown by the GUI.
    EncodeMode = None
    FitFile = None
    RecordMessage = None


SEMICIRCLES = 2**31 / 180.0
SUPPORTED_EXTENSIONS = {".fit", ".gpx", ".tcx"}


def _float(value: Any) -> float:
    try:
        if value is None:
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _bounded(value: Any, minimum: float, maximum: float) -> float:
    number = _float(value)
    return number if math.isfinite(number) and minimum <= number <= maximum else math.nan


def _fit_value(message: Any, field_name: str, *, explicit_only: bool = False) -> float:
    """Return a decoded FIT value while rejecting the protocol's raw invalid marker.

    fit-tool currently considers a decoded field valid when it exists in the local
    definition. Some devices (including Zepp/Amazfit) write FIT's all-ones invalid
    value into those fields, so checking the raw encoded value is required before
    using the decoded/scaled property.
    """
    field = message.get_field_by_name(field_name) if hasattr(message, "get_field_by_name") else None
    if field is None or field.size == 0 or not field.encoded_values:
        return math.nan
    if explicit_only and getattr(message, "definition_message", None) is not None:
        defined_ids = {definition.field_id for definition in message.definition_message.field_definitions}
        if field.field_id not in defined_ids:
            return math.nan
    raw_value = field.encoded_values[0]
    if raw_value is None or raw_value == field.base_type.invalid_raw_value():
        return math.nan
    return _float(getattr(message, field_name, None))


def _coord(value: Any) -> float:
    number = _float(value)
    if math.isnan(number):
        return number
    if abs(number) > 180.0:
        return number / SEMICIRCLES
    return number


def _seconds_from_timestamp(value: Any) -> float:
    number = _float(value)
    if math.isnan(number):
        return number
    return number / 1000.0 if abs(number) > 10_000_000_000 else number


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _extension_value(extensions: list[Any], names: set[str]) -> float:
    for root in extensions:
        for element in root.iter():
            if _local_name(element.tag) in names and element.text:
                result = _float(element.text)
                if math.isfinite(result):
                    return result
    return math.nan


def _child_text(element: ET.Element, name: str) -> str | None:
    wanted = name.lower()
    for child in element.iter():
        if _local_name(child.tag) == wanted and child.text:
            return child.text.strip()
    return None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _iso_datetime(value: datetime | None, fallback_seconds: float) -> str:
    if value is None:
        value = datetime.fromtimestamp(fallback_seconds, tz=timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if not all(math.isfinite(v) for v in (lat1, lon1, lat2, lon2)):
        return 0.0
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _densify_route(
    coordinates: list[tuple[float, float, float | None]],
    maximum_step_m: float = 75.0,
) -> list[tuple[float, float, float | None]]:
    """Add samples to sparse routing geometry without changing its shape."""
    if len(coordinates) < 2:
        return list(coordinates)
    result = [coordinates[0]]
    for previous, current in zip(coordinates, coordinates[1:]):
        distance = _haversine_m(previous[0], previous[1], current[0], current[1])
        pieces = max(1, int(math.ceil(distance / maximum_step_m)))
        longitude_delta = (current[1] - previous[1] + 180.0) % 360.0 - 180.0
        for piece in range(1, pieces + 1):
            ratio = piece / pieces
            elevation = None
            if previous[2] is not None and current[2] is not None:
                elevation = float(previous[2]) + (
                    float(current[2]) - float(previous[2])
                ) * ratio
            longitude = (previous[1] + longitude_delta * ratio + 180.0) % 360.0 - 180.0
            result.append((
                previous[0] + (current[0] - previous[0]) * ratio,
                longitude,
                elevation,
            ))
    return result


def _sanitise_point(point: "Point") -> None:
    point.lat = _bounded(point.lat, -90.0, 90.0)
    point.lon = _bounded(point.lon, -180.0, 180.0)
    point.speed = _bounded(point.speed, 0.0, 500.0)
    point.heart_rate = _bounded(point.heart_rate, 0.0, 300.0)
    point.cadence = _bounded(point.cadence, 0.0, 500.0)
    point.power = _bounded(point.power, 0.0, 100_000.0)
    point.altitude = _bounded(point.altitude, -1_000.0, 10_000.0)
    point.distance = _bounded(point.distance, 0.0, 1_000_000_000.0)


def _meaningful_fit_validation_errors(fit: Any) -> list[Any]:
    """Return real validation failures, excluding fit-tool projection artefacts.

    fit-tool expands legacy speed/altitude components into synthetic enhanced
    fields. Its validator counts those in ``message.size`` even though the
    encoder correctly writes only the fields present in the active definition.
    Confirm the actual encoded message length before suppressing that specific
    false-positive wire finding.
    """
    report = fit.validate() if hasattr(fit, "validate") else None
    errors = list(getattr(report, "errors", []) if report is not None else [])
    meaningful: list[Any] = []
    for finding in errors:
        message = str(getattr(finding, "message", ""))
        record_index = getattr(finding, "record_index", None)
        level = getattr(getattr(finding, "level", None), "value", "")
        if (
            level == "wire"
            and message.startswith("record encodes ")
            and isinstance(record_index, int)
            and 0 <= record_index < len(fit.records)
        ):
            record_message = fit.records[record_index].message
            definition = getattr(record_message, "definition_message", None)
            try:
                actual_size = len(record_message.to_bytes())
            except Exception:
                actual_size = -1
            if definition is not None and actual_size == definition.defined_data_size:
                continue
        meaningful.append(finding)
    return meaningful


def _fit_finding_key(finding: Any) -> tuple[str, str]:
    """Compare source/output findings without unstable record indices."""
    level = getattr(getattr(finding, "level", None), "value", "")
    return str(level), str(getattr(finding, "message", finding))


@dataclass
class Point:
    fit_record_index: int = -1
    timestamp_raw: Any = None
    timestamp_dt: datetime | None = None
    t: float = 0.0
    lat: float = math.nan
    lon: float = math.nan
    speed: float = math.nan
    heart_rate: float = math.nan
    cadence: float = math.nan
    power: float = math.nan
    altitude: float = math.nan
    distance: float = math.nan


@dataclass
class ActivityModel:
    path: Path
    source_format: str
    points: list[Point] = field(default_factory=list)
    active: np.ndarray = field(default_factory=lambda: np.array([], dtype=bool))
    # Planned routes have an internal horizontal coordinate for editing, but
    # no recorded workout clock. UI statistics must not present it as real time.
    has_timing: bool = True

    @classmethod
    def load(cls, path: str | Path) -> "ActivityModel":
        source = Path(path)
        suffix = source.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError("Unsupported file type. Open a FIT, GPX or TCX file.")
        loaders = {".fit": cls._load_fit, ".gpx": cls._load_gpx, ".tcx": cls._load_tcx}
        points = loaders[suffix](source)
        if not points:
            raise ValueError("No track points were found in this activity file.")
        for point in points:
            _sanitise_point(point)
        # Planned GPX routes often contain geometry and elevation but no clock.
        # Treating their ordinal point numbers as seconds creates fictitious
        # speeds and hundreds of false GPS warnings after reloading the file.
        has_timing = len(points) >= 2 and all(
            point.timestamp_dt is not None for point in points
        )
        model = cls(
            path=source,
            source_format=suffix[1:],
            points=points,
            has_timing=has_timing,
        )
        model.active = np.ones(len(points), dtype=bool)
        model._fill_derived_values()
        return model

    @classmethod
    def from_route(
        cls,
        coordinates: list[tuple[float, float, float | None]],
        name: str,
        duration_s: float = 0.0,
    ) -> "ActivityModel":
        """Create an editable GPX-backed model from routing-engine geometry."""
        if len(coordinates) < 2:
            raise ValueError("A route needs at least two coordinates.")
        coordinates = _densify_route(coordinates)
        safe_name = "".join(
            character if character not in '<>:"/\\|?*' else "_" for character in name
        ).strip(" .") or "New route"
        if not safe_name.lower().endswith(".gpx"):
            safe_name += ".gpx"
        cumulative = [0.0]
        for previous, current in zip(coordinates, coordinates[1:]):
            cumulative.append(
                cumulative[-1] + _haversine_m(previous[0], previous[1], current[0], current[1])
            )
        total_distance = cumulative[-1]
        elapsed = float(duration_s) if duration_s > 0.0 else max(1.0, float(len(coordinates) - 1))
        points: list[Point] = []
        for coordinate, distance in zip(coordinates, cumulative):
            seconds = elapsed * distance / total_distance if total_distance > 0.0 else 0.0
            elevation = coordinate[2]
            points.append(Point(
                timestamp_dt=None,
                t=seconds,
                lat=float(coordinate[0]),
                lon=float(coordinate[1]),
                speed=math.nan,
                altitude=float(elevation) if elevation is not None else math.nan,
                distance=distance,
            ))
        return cls(
            path=Path(safe_name),
            source_format="gpx",
            points=points,
            active=np.ones(len(points), dtype=bool),
            has_timing=False,
        )

    @staticmethod
    def _load_fit(path: Path) -> list[Point]:
        if FitFile is None:
            raise RuntimeError("fit-tool is not installed. Run start.bat to install dependencies.")
        fit = FitFile.from_file(str(path))
        points: list[Point] = []
        t0: float | None = None
        for fit_index, record in enumerate(fit.records):
            message = getattr(record, "message", None)
            if RecordMessage is not None and not isinstance(message, RecordMessage):
                continue
            if message is None:
                continue
            raw = _fit_value(message, "timestamp")
            timestamp = _seconds_from_timestamp(raw)
            if math.isnan(timestamp):
                continue
            if t0 is None:
                t0 = timestamp
            speed = _fit_value(message, "enhanced_speed", explicit_only=True)
            if not math.isfinite(speed):
                speed = _fit_value(message, "speed")
            altitude = _fit_value(message, "enhanced_altitude", explicit_only=True)
            if not math.isfinite(altitude):
                altitude = _fit_value(message, "altitude")
            points.append(Point(
                fit_record_index=fit_index,
                timestamp_raw=raw,
                timestamp_dt=datetime.fromtimestamp(timestamp, tz=timezone.utc),
                t=timestamp - t0,
                lat=_coord(_fit_value(message, "position_lat")),
                lon=_coord(_fit_value(message, "position_long")),
                speed=_float(speed),
                heart_rate=_fit_value(message, "heart_rate"),
                cadence=_fit_value(message, "cadence"),
                power=_fit_value(message, "power"),
                altitude=_float(altitude),
                distance=_fit_value(message, "distance"),
            ))
        return points

    @staticmethod
    def _load_gpx(path: Path) -> list[Point]:
        with path.open("r", encoding="utf-8-sig") as handle:
            document = gpxpy.parse(handle)
        raw_points = [point for track in document.tracks for segment in track.segments for point in segment.points]
        if not raw_points:
            raw_points = [point for route in document.routes for point in route.points]
        if not raw_points:
            raw_points = list(document.waypoints)
        points: list[Point] = []
        first_time = next((point.time for point in raw_points if point.time is not None), None)
        for index, point in enumerate(raw_points):
            point_time = point.time
            t = (point_time - first_time).total_seconds() if point_time and first_time else float(index)
            speed = _extension_value(point.extensions, {"speed"})
            points.append(Point(
                timestamp_dt=point_time,
                t=t,
                lat=_float(point.latitude),
                lon=_float(point.longitude),
                speed=speed,
                heart_rate=_extension_value(point.extensions, {"hr", "heartrate"}),
                cadence=_extension_value(point.extensions, {"cad", "cadence"}),
                power=_extension_value(point.extensions, {"power", "watts"}),
                altitude=_float(point.elevation),
            ))
        return points

    @staticmethod
    def _load_tcx(path: Path) -> list[Point]:
        root = ET.parse(path).getroot()
        trackpoints = [element for element in root.iter() if _local_name(element.tag) == "trackpoint"]
        points: list[Point] = []
        first_time: datetime | None = None
        for index, element in enumerate(trackpoints):
            point_time = _parse_iso_datetime(_child_text(element, "time"))
            if first_time is None and point_time is not None:
                first_time = point_time
            t = (point_time - first_time).total_seconds() if point_time and first_time else float(index)
            points.append(Point(
                timestamp_dt=point_time,
                t=t,
                lat=_float(_child_text(element, "latitudedegrees")),
                lon=_float(_child_text(element, "longitudedegrees")),
                speed=_float(_child_text(element, "speed")),
                heart_rate=_float(_child_text(element, "value")),
                cadence=_float(_child_text(element, "cadence")),
                power=_float(_child_text(element, "watts")),
                altitude=_float(_child_text(element, "altitudemeters")),
                distance=_float(_child_text(element, "distancemeters")),
            ))
        return points

    def _fill_derived_values(self) -> None:
        gps_distance = 0.0
        gps_distances: list[float] = []
        previous_gps: Point | None = None
        for point in self.points:
            if math.isfinite(point.lat) and math.isfinite(point.lon):
                if previous_gps is not None:
                    delta = _haversine_m(previous_gps.lat, previous_gps.lon, point.lat, point.lon)
                    delta_t = point.t - previous_gps.t
                    # A huge single jump is a broken/missing coordinate, not travelled distance.
                    plausible = delta <= 100_000.0 and (
                        not self.has_timing or delta_t <= 0 or delta / delta_t <= 500.0
                    )
                    if plausible:
                        gps_distance += delta
                        if self.has_timing and not math.isfinite(point.speed) and delta_t > 0:
                            point.speed = delta / delta_t
                    else:
                        previous_gps = None
                previous_gps = point
            else:
                previous_gps = None
            gps_distances.append(gps_distance)

        recorded = [point.distance for point in self.points if math.isfinite(point.distance)]
        recorded_span = max(recorded) - min(recorded) if len(recorded) >= 2 else math.nan
        recorded_is_implausible = (
            not math.isfinite(recorded_span)
            or recorded_span > 2_000_000.0
            or (gps_distance > 100.0 and recorded_span > max(5_000.0, gps_distance * 10.0))
        )
        if recorded_is_implausible:
            for point, derived_distance in zip(self.points, gps_distances):
                point.distance = derived_distance if gps_distance > 0 else math.nan
        else:
            last_distance = recorded[0]
            for point in self.points:
                if math.isfinite(point.distance):
                    last_distance = point.distance
                else:
                    point.distance = last_distance

    @property
    def duration(self) -> float:
        indices = np.flatnonzero(self.active)
        return float(self.points[indices[-1]].t - self.points[indices[0]].t) if len(indices) > 1 else 0.0

    @property
    def distance_m(self) -> float:
        indices = np.flatnonzero(self.active)
        values = [self.points[i].distance for i in indices if math.isfinite(self.points[i].distance)]
        return max(values) - min(values) if len(values) >= 2 else math.nan

    def arrays(self, field_name: str) -> tuple[np.ndarray, np.ndarray]:
        indices = np.flatnonzero(self.active)
        x = np.array([self.points[i].t for i in indices], dtype=float)
        y = np.array([getattr(self.points[i], field_name) for i in indices], dtype=float)
        return x, y

    def gps(self) -> tuple[np.ndarray, np.ndarray]:
        # Keep NaN separators so the map never joins unrelated pieces across a
        # missing coordinate or a deleted section.
        lon = np.array(
            [point.lon if self.active[index] else math.nan for index, point in enumerate(self.points)],
            dtype=float,
        )
        lat = np.array(
            [point.lat if self.active[index] else math.nan for index, point in enumerate(self.points)],
            dtype=float,
        )
        return lon, lat

    def select_mask(self, start: float, end: float) -> np.ndarray:
        low, high = sorted((float(start), float(end)))
        times = np.array([point.t for point in self.points], dtype=float)
        return self.active & (times >= low) & (times <= high)

    def mask_after_delete(self, start: float, end: float) -> np.ndarray:
        result = self.active.copy()
        result[self.select_mask(start, end)] = False
        return result

    def mask_after_crop(self, start: float, end: float) -> np.ndarray:
        return self.active & self.select_mask(start, end)

    def export(self, destination: str | Path) -> tuple[bool, str]:
        destination = Path(destination)
        if destination.suffix.lower() != self.path.suffix.lower():
            raise ValueError("This version saves to the same activity format that was opened.")
        if self.source_format == "fit":
            return self._export_fit(destination)
        if self.source_format == "gpx":
            self._export_gpx(destination)
            return True, "GPX saved successfully."
        self._export_tcx(destination)
        return True, "TCX saved successfully."

    def export_as(self, destination: str | Path) -> tuple[bool, str]:
        """Convert active RECORD/track points to a supported interchange format."""
        destination = Path(destination)
        suffix = destination.suffix.lower()
        if suffix == ".gpx":
            self._export_gpx(destination)
            return True, "GPX conversion completed successfully."
        if suffix == ".tcx":
            self._export_tcx(destination)
            return True, "TCX conversion completed successfully."
        raise ValueError("Conversion is currently available to GPX or TCX.")

    def _export_fit(self, destination: Path) -> tuple[bool, str]:
        fit = FitFile.from_file(str(self.path))
        source_findings = {
            _fit_finding_key(finding)
            for finding in _meaningful_fit_validation_errors(fit)
        }
        deleted = sorted(
            (point.fit_record_index for i, point in enumerate(self.points) if not bool(self.active[i])),
            reverse=True,
        )
        # Structural deletion requires a canonical rebuild of the definition/data stream.
        for record_index in deleted:
            fit.remove_record(fit.records[record_index])
        destination.write_bytes(fit.to_bytes(mode=EncodeMode.CANONICAL))
        check = FitFile.from_file(str(destination))
        new_errors = [
            finding
            for finding in _meaningful_fit_validation_errors(check)
            if _fit_finding_key(finding) not in source_findings
        ]
        if new_errors:
            return False, "FIT was written, but validation returned: " + "; ".join(map(str, new_errors[:5]))
        return True, "FIT saved and decoded successfully."

    def _export_gpx(self, destination: Path) -> None:
        gpx = gpxpy.gpx.GPX()
        track = gpxpy.gpx.GPXTrack(name=self.path.stem + " edited")
        segment = gpxpy.gpx.GPXTrackSegment()
        track.segments.append(segment)
        gpx.tracks.append(track)
        exported_points = 0
        for index in np.flatnonzero(self.active):
            source = self.points[index]
            if not math.isfinite(source.lat) or not math.isfinite(source.lon):
                continue
            point = gpxpy.gpx.GPXTrackPoint(
                latitude=source.lat,
                longitude=source.lon,
                elevation=source.altitude if math.isfinite(source.altitude) else None,
                time=source.timestamp_dt,
            )
            extension = ET.Element("TrackPointExtension")
            for name, value in (("hr", source.heart_rate), ("cad", source.cadence), ("speed", source.speed), ("power", source.power)):
                if math.isfinite(value):
                    ET.SubElement(extension, name).text = f"{value:g}"
            if len(extension):
                point.extensions.append(extension)
            segment.points.append(point)
            exported_points += 1
        if not exported_points:
            raise ValueError("GPX needs GPS coordinates, but the selected track has none.")
        destination.write_text(gpx.to_xml(), encoding="utf-8")

    def _export_tcx(self, destination: Path) -> None:
        namespace = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
        ET.register_namespace("", namespace)
        root = ET.Element(f"{{{namespace}}}TrainingCenterDatabase")
        activities = ET.SubElement(root, f"{{{namespace}}}Activities")
        activity = ET.SubElement(activities, f"{{{namespace}}}Activity", Sport="Other")
        active_indices = np.flatnonzero(self.active)
        first = self.points[active_indices[0]]
        ET.SubElement(activity, f"{{{namespace}}}Id").text = _iso_datetime(first.timestamp_dt, first.t)
        lap = ET.SubElement(activity, f"{{{namespace}}}Lap", StartTime=_iso_datetime(first.timestamp_dt, first.t))
        ET.SubElement(lap, f"{{{namespace}}}TotalTimeSeconds").text = f"{self.duration:.3f}"
        ET.SubElement(lap, f"{{{namespace}}}DistanceMeters").text = f"{self.distance_m:.3f}"
        track = ET.SubElement(lap, f"{{{namespace}}}Track")
        for index in active_indices:
            source = self.points[index]
            point = ET.SubElement(track, f"{{{namespace}}}Trackpoint")
            ET.SubElement(point, f"{{{namespace}}}Time").text = _iso_datetime(source.timestamp_dt, source.t)
            if math.isfinite(source.lat) and math.isfinite(source.lon):
                position = ET.SubElement(point, f"{{{namespace}}}Position")
                ET.SubElement(position, f"{{{namespace}}}LatitudeDegrees").text = f"{source.lat:.8f}"
                ET.SubElement(position, f"{{{namespace}}}LongitudeDegrees").text = f"{source.lon:.8f}"
            if math.isfinite(source.altitude):
                ET.SubElement(point, f"{{{namespace}}}AltitudeMeters").text = f"{source.altitude:.3f}"
            if math.isfinite(source.distance):
                ET.SubElement(point, f"{{{namespace}}}DistanceMeters").text = f"{source.distance:.3f}"
            if math.isfinite(source.heart_rate):
                heart = ET.SubElement(point, f"{{{namespace}}}HeartRateBpm")
                ET.SubElement(heart, f"{{{namespace}}}Value").text = str(round(source.heart_rate))
            if math.isfinite(source.cadence):
                ET.SubElement(point, f"{{{namespace}}}Cadence").text = str(round(source.cadence))
            if math.isfinite(source.speed) or math.isfinite(source.power):
                extensions = ET.SubElement(point, f"{{{namespace}}}Extensions")
                if math.isfinite(source.speed):
                    ET.SubElement(extensions, "Speed").text = f"{source.speed:.3f}"
                if math.isfinite(source.power):
                    ET.SubElement(extensions, "Watts").text = str(round(source.power))
        ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def export_combined_gpx(
    activities: list[tuple[ActivityModel, float]],
    destination: str | Path,
) -> None:
    """Export the visible montage as one GPX with one segment per source file.

    The source files remain independent in the editor. Their calculated
    timeline offsets are applied only to timestamps in this combined export,
    making restarted recordings one chronological activity without pretending
    that heterogeneous FIT/TCX internals can be losslessly merged.
    """
    destination = Path(destination)
    if destination.suffix.lower() != ".gpx":
        raise ValueError("Combined activities are exported as GPX.")

    active_entries: list[tuple[ActivityModel, float, np.ndarray]] = []
    datetimes: list[datetime] = []
    global_times: list[float] = []
    for model, offset in activities:
        indices = np.flatnonzero(model.active)
        if not len(indices):
            continue
        active_entries.append((model, float(offset), indices))
        for index in indices:
            point = model.points[index]
            global_times.append(point.t + float(offset))
            if point.timestamp_dt is not None:
                value = point.timestamp_dt
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                datetimes.append(value.astimezone(timezone.utc))
    if not active_entries:
        raise ValueError("There are no active points to export.")

    global_origin = min(global_times)
    time_origin = min(datetimes) if datetimes else None
    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack(name="AnyTrack Editor combined activity")
    gpx.tracks.append(track)
    exported_points = 0
    for model, offset, indices in active_entries:
        segment = gpxpy.gpx.GPXTrackSegment()
        track.segments.append(segment)
        for index in indices:
            source = model.points[index]
            if not math.isfinite(source.lat) or not math.isfinite(source.lon):
                continue
            adjusted_time = (
                time_origin + timedelta(seconds=source.t + offset - global_origin)
                if time_origin is not None else None
            )
            point = gpxpy.gpx.GPXTrackPoint(
                latitude=source.lat,
                longitude=source.lon,
                elevation=source.altitude if math.isfinite(source.altitude) else None,
                time=adjusted_time,
            )
            extension = ET.Element("TrackPointExtension")
            for name, value in (
                ("hr", source.heart_rate),
                ("cad", source.cadence),
                ("speed", source.speed),
                ("power", source.power),
            ):
                if math.isfinite(value):
                    ET.SubElement(extension, name).text = f"{value:g}"
            if len(extension):
                point.extensions.append(extension)
            segment.points.append(point)
            exported_points += 1
    track.segments = [segment for segment in track.segments if segment.points]
    if not exported_points:
        raise ValueError("The selected activities contain no valid GPS points.")
    destination.write_text(gpx.to_xml(), encoding="utf-8")
    with destination.open("r", encoding="utf-8-sig") as handle:
        check = gpxpy.parse(handle)
    if not any(segment.points for item in check.tracks for segment in item.segments):
        raise ValueError("The combined GPX could not be verified after saving.")
