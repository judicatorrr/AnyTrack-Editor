"""Round elapsed-time ticks and distance ticks aligned to recorded progress."""
import math
import numpy as np
import pyqtgraph as pg


class TimeAxisItem(pg.AxisItem):
    def __init__(self, parent=None):
        super().__init__(orientation='bottom', parent=parent)
        self.language = 'ru'

    def tickValues(self, minVal, maxVal, size):
        span = max(0.0, maxVal-minVal)
        target = max(2, int(size/100))
        if span >= 600:
            candidates = [600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]
        elif span >= 60:
            candidates = [60, 120, 300]
        else:
            candidates = [1, 2, 5, 10, 15, 30, 60]
        step = next((v for v in candidates if span/v <= target), candidates[-1])
        step = max(step, math.ceil(span/target/86400)*86400) if span > 86400*target else step
        first = max(0, math.ceil(minVal/step))*step
        return [(step, list(np.arange(first, maxVal+1e-8, step)))]

    def tickStrings(self, values, scale, spacing):
        if spacing >= 60:
            unit = 'мин' if self.language == 'ru' else 'min'
            return [f'{int(round(value/60))} {unit}' for value in values]
        # At close zoom use elapsed minutes:seconds, never wrap at an hour.
        return [f'{int(round(v))//60}:{int(round(v))%60:02d}' for v in values]


class DistanceAxisItem(pg.AxisItem):
    def __init__(self):
        super().__init__(orientation='top')
        self.segments = []
        self._labels = {}

    def set_segments(self, segments):
        self.segments = segments
        self.picture = None
        self.update()

    def tickValues(self, minVal, maxVal, size):
        self._labels = {}
        points = []
        for times, km in self.segments:
            if len(times) < 2 or times[-1] < minVal or times[0] > maxVal:
                continue
            low = float(np.interp(max(minVal, times[0]), times, km))
            high = float(np.interp(min(maxVal, times[-1]), times, km))
            if high <= low:
                continue
            span = high-low
            target = max(2, int(size/95))
            rough = span/target
            base = 10**math.floor(math.log10(rough))
            step = next(v*base for v in (1, 2, 5, 10) if v*base >= rough)
            for value in np.arange(math.ceil(low/step)*step, high+step*1e-8, step):
                i = int(np.searchsorted(km, value, side='left'))
                if i >= len(km):
                    continue
                t = float(times[i])
                if i > 0 and km[i] > value:
                    t = float(times[i-1] + (times[i]-times[i-1]) *
                              (value-km[i-1])/(km[i]-km[i-1]))
                if minVal <= t <= maxVal:
                    # Keep neighbouring fragment boundaries from duplicating labels.
                    if any(abs(t-old[0])/(maxVal-minVal or 1)*size < 65 for old in points):
                        continue
                    points.append((t, float(value)))
        for t, value in points:
            self._labels[round(t, 6)] = f'{value:g}'
        return [(1.0, [t for t, _value in points])]

    def tickStrings(self, values, scale, spacing):
        return [self._labels.get(round(float(value), 6), '') for value in values]


def distance_segments(documents, indices, active_index):
    """Concatenate reference distances; never sum simultaneous recordings.

    For an overlapping group use its active track, otherwise its first track.
    A group without distance contributes no invented progress.
    """
    groups = {}
    for index, doc in enumerate(documents):
        groups.setdefault(doc.timeline_group, []).append(index)
    result, names = [], []
    offset = 0.0
    unknown_before = False
    for group in sorted(groups):
        candidates = groups[group]
        if active_index in candidates:
            candidates = [active_index] + [i for i in candidates if i != active_index]
        found = False
        for index in candidates:
            doc = documents[index]
            data = indices[id(doc.model)]
            interval_mask = data.interval_mask(doc.model.active) & np.isfinite(data.distance)
            if not interval_mask.any():
                continue
            increments = np.where(interval_mask, data.distance/1000, 0.0)
            km = np.r_[0.0, np.cumsum(increments)]
            valid = doc.model.active & np.isfinite(data.times)
            times = data.times[valid] + doc.timeline_offset
            values = km[valid]
            if len(times) < 2 or (np.diff(times) < 0).any():
                continue
            if unknown_before:
                offset = 0.0
            result.append((times, values-values[0]+offset))
            offset = float(result[-1][1][-1])
            names.append(doc.model.path.name)
            found = True
            break
        unknown_before = not found
    return result, names
