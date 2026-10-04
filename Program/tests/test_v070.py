import unittest
import numpy as np
from PySide6 import QtCore, QtGui, QtTest
import test_regressions as regression
from test_regressions import activity
from fit_editor.main_window import TrackDocument
from fit_editor.chart_axes import TimeAxisItem, DistanceAxisItem, distance_segments
from fit_editor.record_index import RecordIndex


class UpdatedInterfaceTests(unittest.TestCase):
    setUpClass = classmethod(regression.InterfaceTests.setUpClass.__func__)
    setUp = regression.InterfaceTests.setUp
    tearDown = regression.InterfaceTests.tearDown

    def test_two_position_controls_and_no_reset_action(self):
        self.assertEqual(self.w.chart_mode.currentIndex(), 0)
        speed = self.w.graph_stack.panels['speed']
        self.assertIs(speed.header_overlay.parentWidget(), speed.plot.viewport())
        self.assertEqual(speed.title.text(), 'Скорость [km/h]')
        self.assertIn('#4DA3FF', speed.stats.styleSheet())
        self.assertGreaterEqual(self.w.chart_options_layout.indexOf(self.w.smooth_slider), 0)
        self.assertGreaterEqual(self.w.metric_controls_layout.indexOf(self.w.telemetry_fit_button), 0)
        self.assertGreaterEqual(self.w.chart_options_layout.indexOf(self.w.chart_mode), 0)
        self.assertEqual(self.w.about_action.text(), '')
        self.assertFalse(self.w.about_action.icon().isNull())
        self.assertEqual(self.w.settings_button.size(), QtCore.QSize(38, 34))
        self.assertEqual(self.w.about_button.size(), QtCore.QSize(38, 34))
        QtTest.QTest.mouseClick(self.w.chart_mode.group.button(1), QtCore.Qt.LeftButton)
        self.assertEqual(self.w.graph_stack.visible_keys, ['combined'])
        combined = self.w.graph_stack.panels['combined']
        self.assertEqual(combined.title.text(), '')
        self.assertIn('#4DA3FF', combined.stats.text())
        self.assertIn('#FF6178', combined.stats.text())
        QtTest.QTest.mouseClick(self.w.sport_mode.group.button(1), QtCore.Qt.LeftButton)
        self.assertEqual(self.w.sport_mode.currentData(), 'running')
        captions = [row.caption_label.text() for row in self.w.summary._rows if row.isVisible()]
        self.assertIn('Темп в движении', captions)
        self.assertFalse(any('СБРОС' in action.text() for action in self.w.toolbar.actions()))
        self.w.language_combo.setCurrentIndex(1)
        self.assertEqual(self.w.sport_mode.group.button(1).text(), 'Run / walk')

    def test_round_time_ticks_and_high_zoom(self):
        axis = TimeAxisItem()
        step, ticks = axis.tickValues(0, 5400, 650)[0]
        self.assertIn(step, [600, 900, 1800])
        self.assertTrue(all(value % step == 0 for value in ticks))
        self.assertEqual(axis.tickStrings([5400], 1, 900), ['90 мин'])
        self.assertEqual(axis.tickStrings([40], 1, 10), ['0:40'])
        step, ticks = axis.tickValues(3950, 5750, 650)[0]
        self.assertTrue(all(tick % 600 == 0 for tick in ticks))

    def test_distance_ticks_use_recorded_speed_and_stops(self):
        axis = DistanceAxisItem()
        axis.set_segments([(np.array([0., 60., 61., 62.]), np.array([0., 0., 1., 2.]))])
        ticks = axis.tickValues(0, 62, 1000)[0][1]
        labels = axis.tickStrings(ticks, 1, 1)
        pairs = {label: t for label, t in zip(labels, ticks)}
        self.assertTrue(any(float(label) > 0 for label in pairs))
        for label, t in pairs.items():
            if float(label) > 0:
                self.assertAlmostEqual(t, 60 + float(label))
        # No invented linear kilometre progress during the first minute's stop.
        self.assertFalse(any(0 < t < 60 for t in ticks))

    def test_montage_distance_overlap_and_cuts(self):
        other = activity('second.gpx', offset=3600)
        self.w.tracks.append(TrackDocument(other, '#ff8800'))
        self.w.refresh_plots(reset_region=True)
        segments, _ = distance_segments(self.w.tracks, self.w._record_indices, 0)
        self.assertAlmostEqual(segments[1][1][0], .540)
        self.assertAlmostEqual(segments[1][1][-1], 1.080)
        self.assertFalse(self.w.track_legend_scroll.isVisible())
        self.assertEqual([track.name for track in self.w.map_widget._track_routes],
                         ['demo.gpx', 'second.gpx'])
        self.model.active[60:121] = False
        self.w.refresh_plots(reset_region=True)
        segments, _ = distance_segments(self.w.tracks, self.w._record_indices, 0)
        self.assertAlmostEqual(segments[0][1][-1], .354)
        # Two simultaneous sources: use a reference, not twice the distance.
        a, b = activity('a.gpx'), activity('b.gpx')
        docs = [TrackDocument(a, '#fff'), TrackDocument(b, '#000')]
        arrays = {id(a): RecordIndex(a), id(b): RecordIndex(b)}
        segments, names = distance_segments(docs, arrays, 1)
        self.assertEqual(names, ['b.gpx'])
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0][1][-1], .540)

    def test_cached_layers_clean_hover_and_camera_invalidation(self):
        self.w._selection_user_defined = True
        self.w._set_selection_region(30, 90)
        self.app.processEvents()
        chart = self.w.graph_stack.panels['heart_rate']
        self.w._activate_panel('heart_rate')
        self.w._hide_hover_feedback()
        self.app.processEvents()
        baseline = chart.plot.viewport().grab().toImage()
        base_layer = self.w.map_widget._base_layer.cacheKey()
        for t in (40, 55, 65, 80):
            self.w._telemetry_mouse_moved((chart.view.mapViewToScene(QtCore.QPointF(t, 100)),))
            self.app.processEvents()
        self.assertEqual(base_layer, self.w.map_widget._base_layer.cacheKey())
        self.w._hide_hover_feedback()
        self.app.processEvents()
        self.assertEqual(baseline, chart.plot.viewport().grab().toImage())
        self.w.map_widget.set_provider('yandex')
        self.app.processEvents()
        self.assertNotEqual(base_layer, self.w.map_widget._base_layer.cacheKey())

    def test_projection_preserves_scalar_provider_coordinates(self):
        origin = QtCore.QPointF(0, 0)
        for provider in ('osm', 'yandex', 'google'):
            self.w.map_widget.set_provider(provider)
            segment = [(59.0, 39.0), (59.1, 39.1)]
            polygon = self.w.map_widget._project_segment(segment, origin)
            for point, (lat, lon) in zip(polygon, segment):
                expected = self.w.map_widget._to_world(lat, lon)
                self.assertAlmostEqual(point.x(), expected.x(), places=6)
                self.assertAlmostEqual(point.y(), expected.y(), places=6)

    def test_map_wheel_zoom_keeps_coordinate_under_cursor(self):
        map_widget = self.w.map_widget
        cursor = QtCore.QPointF(map_widget.width() * .77, map_widget.height() * .31)

        def coordinate_at(position):
            centre = map_widget._to_world(map_widget._center_lat, map_widget._center_lon)
            world = centre + position - QtCore.QPointF(
                map_widget.width() / 2.0, map_widget.height() / 2.0
            )
            return map_widget._from_world(world)

        latitude_before, longitude_before = coordinate_at(cursor)
        event = QtGui.QWheelEvent(
            cursor,
            map_widget.mapToGlobal(cursor.toPoint()),
            QtCore.QPoint(),
            QtCore.QPoint(0, 120),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            QtCore.Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        map_widget.wheelEvent(event)
        latitude_after, longitude_after = coordinate_at(cursor)
        self.assertAlmostEqual(latitude_before, latitude_after, places=7)
        self.assertAlmostEqual(longitude_before, longitude_after, places=7)

    def test_map_pixmap_memory_cache_is_bounded(self):
        map_widget = self.w.map_widget
        for index in range(520):
            map_widget._remember_pixmap(
                ("test", 1, index, 0), QtGui.QPixmap(1, 1)
            )
        self.assertEqual(len(map_widget._pixmaps), 512)
        self.assertNotIn(("test", 1, 0, 0), map_widget._pixmaps)


if __name__ == '__main__':
    unittest.main()
