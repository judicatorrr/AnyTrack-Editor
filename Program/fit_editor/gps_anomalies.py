"""Conservative GPS anomaly detection for workout tracks.

The detector never changes source records.  It separates high-confidence
excursions (safe to preselect in the review dialog) from one-way jumps that
need a human decision because there may be no reliable way to know which side
of the jump is correct.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class GPSAnomaly:
    point_indices: tuple[int, ...]
    focus_index: int
    kind: str
    distance_m: float
    speed_kmh: float
    confidence: str
    recommended: bool


def _distance_m(first, second) -> float:
    lat1, lon1 = first
    lat2, lon2 = second
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    value = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1.0 - value)))


def _speed_limit_mps(sport: str, ordinary_speeds: list[float]) -> float:
    # Sports-oriented limits requested by the application: even if the rest of
    # the workout is fast, values above these limits remain visible for review.
    return 100.0 / 3.6 if sport == "cycling" else 45.0 / 3.6


def detect_gps_anomalies(model, sport: str = "cycling") -> list[GPSAnomaly]:
    """Return suspicious active GPS samples in chronological order.

    High-confidence results are bounded excursions: the route makes an
    implausibly fast detour and rejoins a plausible neighbouring path. A lone
    one-way jump is reported too, but is not preselected for deletion.
    """
    # Geometry-only planned routes have no time axis. Their internal ordinal
    # coordinate is useful for editing, but must never be interpreted as
    # elapsed seconds for speed or teleport detection.
    if not getattr(model, "has_timing", True):
        return []

    active = np.flatnonzero(model.active)
    valid = [
        int(index) for index in active
        if math.isfinite(model.points[index].lat) and math.isfinite(model.points[index].lon)
    ]
    if len(valid) < 2:
        return []

    edge_distance: list[float] = []
    edge_speed: list[float] = []
    edge_contiguous: list[bool] = []
    for left, right in zip(valid, valid[1:]):
        dt = float(model.points[right].t - model.points[left].t)
        contiguous = right == left + 1 and 0.0 < dt <= 120.0
        distance = _distance_m(
            (model.points[left].lat, model.points[left].lon),
            (model.points[right].lat, model.points[right].lon),
        ) if contiguous else math.nan
        edge_distance.append(distance)
        edge_speed.append(distance / dt if contiguous else math.nan)
        edge_contiguous.append(contiguous)

    limit = _speed_limit_mps(sport, [value for value in edge_speed if math.isfinite(value)])
    bad = [
        contiguous and math.isfinite(speed) and distance >= 25.0 and speed > limit
        for contiguous, speed, distance in zip(edge_contiguous, edge_speed, edge_distance)
    ]
    results: list[GPSAnomaly] = []
    covered_edges: set[int] = set()
    covered_points: set[int] = set()

    # Find short out-and-back excursions, including several consecutive bad
    # samples. The bridge between the good points must itself be plausible.
    bad_edges = [index for index, value in enumerate(bad) if value]
    for position, entry in enumerate(bad_edges):
        if entry in covered_edges:
            continue
        for exit_edge in bad_edges[position + 1:]:
            if exit_edge - entry > 12:
                break
            first = valid[entry]
            last = valid[exit_edge + 1]
            elapsed = model.points[last].t - model.points[first].t
            if elapsed <= 0.0 or elapsed > 180.0:
                continue
            bridge = _distance_m(
                (model.points[first].lat, model.points[first].lon),
                (model.points[last].lat, model.points[last].lon),
            )
            bridge_speed = bridge / elapsed
            detour = float(sum(
                value for value in edge_distance[entry:exit_edge + 1] if math.isfinite(value)
            ))
            if bridge_speed <= limit and detour >= max(180.0, bridge * 3.0 + 80.0):
                point_indices = tuple(valid[entry + 1:exit_edge + 1])
                if point_indices:
                    peak = max(edge_speed[entry:exit_edge + 1]) * 3.6
                    results.append(GPSAnomaly(
                        point_indices=point_indices,
                        focus_index=point_indices[len(point_indices) // 2],
                        kind="excursion",
                        distance_m=detour,
                        speed_kmh=peak,
                        confidence="high",
                        recommended=True,
                    ))
                    covered_edges.update(range(entry, exit_edge + 1))
                    covered_points.update(point_indices)
                break

    # Report remaining impossible transitions for review. They are deliberately
    # unchecked: deleting one endpoint cannot always repair a track that moved
    # to a new, consistently recorded location.
    for edge_index in bad_edges:
        if edge_index in covered_edges:
            continue
        focus = valid[edge_index + 1]
        if focus in covered_points:
            continue
        results.append(GPSAnomaly(
            point_indices=(focus,),
            focus_index=focus,
            kind="jump",
            distance_m=edge_distance[edge_index],
            speed_kmh=edge_speed[edge_index] * 3.6,
            confidence="review",
            recommended=False,
        ))

    # Some devices write an impossible sensor speed while their GPS geometry
    # remains plausible. Keep these records visible as a separate error type.
    already_reported = {
        index for anomaly in results for index in anomaly.point_indices
    }
    for index in active:
        point = model.points[int(index)]
        if int(index) in already_reported or not math.isfinite(point.speed):
            continue
        speed_kmh = float(point.speed) * 3.6
        if speed_kmh > limit * 3.6:
            results.append(GPSAnomaly(
                point_indices=(int(index),),
                focus_index=int(index),
                kind="speed",
                distance_m=0.0,
                speed_kmh=speed_kmh,
                confidence="review",
                recommended=False,
            ))

    return sorted(results, key=lambda anomaly: model.points[anomaly.focus_index].t)
