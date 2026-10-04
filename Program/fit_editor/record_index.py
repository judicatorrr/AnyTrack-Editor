"""Immutable sample arrays shared by plotting, selection and statistics."""
import numpy as np


class RecordIndex:
    FIELDS = ('t', 'lat', 'lon', 'speed', 'heart_rate', 'cadence', 'power', 'altitude', 'distance')

    def __init__(self, model):
        self.values = {field: np.fromiter((getattr(p, field) for p in model.points),
                                         dtype=float, count=len(model.points)) for field in self.FIELDS}
        self.times = self.values['t']
        self.dt = np.diff(self.times)
        positive = self.dt[np.isfinite(self.dt) & (self.dt > 0)]
        max_gap = min(120.0, max(30.0, float(np.median(positive))*5)) if len(positive) else 30.0
        speed = self.values['speed']
        valid = np.isfinite(speed) & (speed >= 0)
        count = valid[:-1].astype(int) + valid[1:]
        pair_sum = np.where(valid[:-1], speed[:-1], 0) + np.where(valid[1:], speed[1:], 0)
        self.speed = np.divide(pair_sum, count, out=np.full(len(count), np.nan), where=count > 0)
        distance = np.diff(self.values['distance'])
        rate = np.divide(distance, self.dt, out=np.full(len(distance), np.nan), where=self.dt > 0)
        valid_distance = np.isfinite(distance) & (distance >= 0) & (rate <= 120)
        self.distance = np.where(valid_distance, distance, self.speed*self.dt)
        derived_speed = np.divide(self.distance, self.dt, out=np.full(len(distance), np.nan), where=self.dt > 0)
        self.speed = np.where(np.isfinite(self.speed), self.speed, derived_speed)
        if not getattr(model, "has_timing", True):
            self.speed[:] = np.nan
        # GraphHopper geometry can be deliberately sparse on a straight road.
        # A >120 s interval is still continuous when its travelled distance and
        # recorded speed agree; treating it as a recording pause created a
        # visible hole in otherwise valid generated routes.
        tolerance = np.maximum(1.5, np.abs(self.speed) * 0.35)
        consistent_long_interval = (
            (self.dt > max_gap)
            & np.isfinite(derived_speed)
            & np.isfinite(self.speed)
            & (np.abs(derived_speed - self.speed) <= tolerance)
        )
        self.interval_valid = (
            np.isfinite(self.dt)
            & (self.dt > 0)
            & (
                ~np.full_like(self.dt, getattr(model, "has_timing", True), dtype=bool)
                | (self.dt <= max_gap)
                | consistent_long_interval
            )
        )

    def interval_mask(self, mask):
        return self.interval_valid & mask[:-1] & mask[1:]

    def route_coordinates(self, mask):
        """Slice only the selected range; preserve holes, cuts and long gaps."""
        indices = np.flatnonzero(mask)
        if not len(indices):
            return np.array([]), np.array([])
        lo, hi = int(indices[0]), int(indices[-1])+1
        selected = mask[lo:hi]
        lon = np.where(selected, self.values['lon'][lo:hi], np.nan)
        lat = np.where(selected, self.values['lat'][lo:hi], np.nan)
        gaps = np.flatnonzero(~self.interval_valid[lo:hi-1])+1
        if len(gaps):
            lon, lat = np.insert(lon, gaps, np.nan), np.insert(lat, gaps, np.nan)
        return lon, lat
