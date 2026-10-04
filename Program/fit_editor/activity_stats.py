"""Local movement estimates, without altering source activity records."""
from dataclasses import dataclass
import math
import numpy as np


@dataclass
class MotionTotals:
    distance: float = 0.0
    moving_distance: float = 0.0
    moving_seconds: float = 0.0
    has_distance: bool = False
    has_motion: bool = False


def motion_totals(masks, sport: str, indices=None) -> MotionTotals:
    """Integrate retained adjacent records without rescanning Python points."""
    from .record_index import RecordIndex
    total = MotionTotals()
    threshold = 0.5 if sport == "cycling" else 0.3
    for document, mask in masks:
        data = indices[id(document.model)] if indices is not None else RecordIndex(document.model)
        intervals = data.interval_mask(mask)
        distance_valid = intervals & np.isfinite(data.distance)
        speed_valid = (
            intervals & np.isfinite(data.speed)
            if getattr(document.model, "has_timing", True)
            else np.zeros_like(intervals, dtype=bool)
        )
        moving = speed_valid & (data.speed >= threshold)
        total.distance += float(np.sum(data.distance[distance_valid]))
        total.has_distance |= bool(distance_valid.any())
        total.has_motion |= bool(speed_valid.any())
        total.moving_seconds += float(np.sum(data.dt[moving]))
        moving_distance = np.where(np.isfinite(data.distance), data.distance, data.speed * data.dt)
        total.moving_distance += float(np.sum(moving_distance[moving]))
    return total


def pace_text(distance_m: float, seconds: float, unit: str = "мин/км") -> str:
    if distance_m <= 0 or seconds <= 0:
        return "—"
    pace = int(round(seconds * 1000 / distance_m))
    minutes, seconds = divmod(pace, 60)
    return f"{minutes}:{seconds:02d} {unit}"
