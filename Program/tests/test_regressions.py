"""Run: QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v"""
import math
import os
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from fit_editor.main_window import (
    MainWindow, TrackDocument, TimeAxisItem, TrackWarningDialog, TRANSLATIONS,
)
from fit_editor.model import ActivityModel, Point
from fit_editor.record_index import RecordIndex
from fit_editor.activity_stats import motion_totals, pace_text
from fit_editor.gps_anomalies import detect_gps_anomalies
from fit_editor.map_widget import MapWidget
from fit_editor.local_graphhopper import (
    LOCAL_ROUTE_URL, LocalGraphHopperManager, _graphhopper_error_summary,
)
from fit_editor.route_planner import (
    RoutePlannerDialog, RoutePlannerPanel, direct_route_distance, graphhopper_payload,
    normalized_route_url, parse_graphhopper_response, parse_rate_limit_headers,
    parse_river_route, river_overpass_query,
    route_batches, route_batches_for_service, route_service_requires_key,
    route_ascent_m, simplify_route_points,
)


def activity(name="demo.gpx", offset=0):
    points = []
    for t in range(181):
        points.append(Point(t=float(t), timestamp_dt=datetime(2026, 1, 1, tzinfo=timezone.utc)
                            + timedelta(seconds=t + offset),
                            lat=59 + t * .00003, lon=39 + t * .00003,
                            speed=3.0, heart_rate=80 + 40 * math.sin(t / 180 * math.pi)
                            if t % 5 == 0 else math.nan,
                            distance=t * 3.0, altitude=-10 + t / 30,
                            cadence=0, power=math.nan))
    return ActivityModel(Path(name), "gpx", points, np.ones(len(points), dtype=bool))


class StatisticsTests(unittest.TestCase):
    def test_pace_and_speed_for_continuous_track(self):
        model = activity()
        totals = motion_totals([(TrackDocument(model, "#50D890"), model.active)], "running")
        self.assertAlmostEqual(totals.distance, 540)
        self.assertAlmostEqual(totals.moving_seconds, 180)
        self.assertEqual(pace_text(1000, 300), "5:00 мин/км")
        self.assertEqual(pace_text(0, 300), "—")

    def test_cuts_and_recording_gaps_do_not_add_distance_or_motion(self):
        model = activity()
        model.active[60:121] = False
        totals = motion_totals([(TrackDocument(model, "#50D890"), model.active)], "cycling")
        self.assertAlmostEqual(totals.distance, 354)
        self.assertAlmostEqual(totals.moving_seconds, 118)
        model.points[121].t = 900
        totals = motion_totals([(TrackDocument(model, "#50D890"), model.active)], "cycling")
        self.assertAlmostEqual(totals.moving_seconds, 117)

    def test_sport_thresholds_and_missing_data(self):
        model = activity()
        for p in model.points:
            p.speed = 0.4
            p.distance = p.t * .4
        masks = [(TrackDocument(model, "#50D890"), model.active)]
        self.assertEqual(motion_totals(masks, "cycling").moving_seconds, 0)
        self.assertEqual(motion_totals(masks, "walking").moving_seconds, 180)
        for p in model.points:
            p.speed = p.distance = math.nan
        self.assertFalse(motion_totals(masks, "running").has_motion)

    def test_gps_detector_marks_isolated_excursion_for_removal(self):
        model = activity()
        model.points[90].lat += 0.08
        model.points[90].lon += 0.08
        anomalies = detect_gps_anomalies(model, "cycling")
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0].kind, "excursion")
        self.assertEqual(anomalies[0].point_indices, (90,))
        self.assertTrue(anomalies[0].recommended)

    def test_gps_detector_reports_one_way_teleport_for_review(self):
        model = activity()
        for point in model.points[90:]:
            point.lat += 0.08
            point.lon += 0.08
        anomalies = detect_gps_anomalies(model, "cycling")
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0].kind, "jump")
        self.assertFalse(anomalies[0].recommended)

    def test_speed_over_sports_limit_is_reported(self):
        model = activity()
        model.points[50].speed = 31.0  # 111.6 km/h
        anomalies = detect_gps_anomalies(model, "cycling")
        self.assertEqual([(item.kind, item.focus_index) for item in anomalies], [("speed", 50)])

    def test_graphhopper_payload_response_and_route_model(self):
        control = [(59.22, 39.88), (59.23, 39.90)]
        payload = graphhopper_payload(control, "bike")
        self.assertEqual(payload["points"], [[39.88, 59.22], [39.90, 59.23]])
        self.assertFalse(payload["points_encoded"])
        response = {"paths": [{
            "distance": 1500,
            "time": 300000,
            "points": {"coordinates": [[39.88, 59.22, 120], [39.90, 59.23, 125]]},
        }]}
        coordinates, distance, duration = parse_graphhopper_response(response)
        self.assertEqual(coordinates[0], (59.22, 39.88, 120.0))
        self.assertEqual((distance, duration), (1500.0, 300.0))
        zero_elevation_response = {"paths": [{
            "points": {"coordinates": [[39.88, 59.22, 0], [39.90, 59.23, 0]]},
        }]}
        zero_coordinates, _, _ = parse_graphhopper_response(zero_elevation_response)
        self.assertEqual([point[2] for point in zero_coordinates], [None, None])
        route = ActivityModel.from_route(coordinates, "Test route", duration)
        self.assertEqual(route.path.name, "Test route.gpx")
        self.assertAlmostEqual(route.duration, 300.0)
        self.assertFalse(route.has_timing)
        self.assertIsNone(route.points[0].timestamp_dt)
        self.assertTrue(all(math.isnan(point.speed) for point in route.points))
        self.assertGreater(len(route.points), len(coordinates))
        self.assertLessEqual(max(np.diff([point.t for point in route.points])), 30.0)
        self.assertEqual(normalized_route_url("http://localhost:8989"),
                         "http://localhost:8989/route")
        self.assertTrue(route_service_requires_key("https://graphhopper.com/api/1/route"))
        self.assertFalse(route_service_requires_key("http://localhost:8989"))

    def test_river_router_follows_connected_waterway_nodes(self):
        payload = {"elements": [
            {"type": "node", "id": 1, "lat": 59.0, "lon": 39.0},
            {"type": "node", "id": 2, "lat": 59.01, "lon": 39.01},
            {"type": "node", "id": 3, "lat": 59.02, "lon": 39.02},
            {"type": "way", "id": 10, "nodes": [1, 2, 3]},
        ]}
        route = parse_river_route(payload, [(59.0, 39.0), (59.02, 39.02)])
        self.assertEqual([(point[0], point[1]) for point in route], [
            (59.0, 39.0), (59.01, 39.01), (59.02, 39.02),
        ])
        query = river_overpass_query([(59.0, 39.0), (59.02, 39.02)])
        self.assertIn('"waterway"', query)
        self.assertIn("river|canal|stream", query)

    def test_graphhopper_batches_overlap_and_cover_all_points(self):
        points = [(59.0 + index / 100.0, 39.0) for index in range(10)]
        batches = route_batches(points)
        self.assertEqual([len(batch) for batch in batches], [5, 5, 2])
        self.assertEqual(batches[0][-1], batches[1][0])
        self.assertEqual(batches[1][-1], batches[2][0])
        restored = batches[0] + batches[1][1:] + batches[2][1:]
        self.assertEqual(restored, points)
        self.assertEqual(
            [len(batch) for batch in route_batches_for_service(
                points, "https://graphhopper.com/api/1/route"
            )],
            [5, 5, 2],
        )
        self.assertEqual(
            route_batches_for_service(points, LOCAL_ROUTE_URL),
            [points],
        )

    def test_local_graphhopper_writes_private_multimode_config(self):
        settings = QtCore.QSettings("VJ Ostrov", "Track Editor local test")
        settings.clear()
        with tempfile.TemporaryDirectory() as directory:
            manager = LocalGraphHopperManager(settings)
            manager.set_root(directory)
            pbf = Path(directory) / "vologda.osm.pbf"
            pbf.write_bytes(b"test")
            manager.set_pbf_path(pbf)
            config = manager.write_config().read_text(encoding="utf-8")
            self.assertIn("bind_host: 127.0.0.1", config)
            self.assertIn("port: 8989", config)
            self.assertIn("import.osm.ignored_highways: ''", config)
            self.assertIn("custom_model_files: [bike.json]", config)
            self.assertIn("graph.elevation.provider: srtm", config)
            self.assertIn("graph.elevation.interpolate: bilinear", config)
            self.assertIn("elevation-cache", config)
            self.assertNotIn("custom_model_file: empty", config)
            for encoded_value in (
                "racingbike_priority", "racingbike_access", "racingbike_average_speed",
                "mtb_priority", "mtb_access", "mtb_average_speed",
            ):
                self.assertIn(encoded_value, config)
            for profile in ("bike", "racingbike", "mtb", "foot", "car"):
                self.assertIn(f"name: {profile}", config)
            self.assertEqual(manager.pbf_path, pbf)
            self.assertFalse(manager.graph_prepared())
            manager.graph_dir.mkdir()
            (manager.graph_dir / "properties").write_text(
                "graph.elevation=false", encoding="utf-8"
            )
            self.assertTrue(manager.graph_prepared())
            self.assertTrue(manager.graph_requires_rebuild())
            with patch.object(manager, "components_installed", return_value=True):
                self.assertEqual(manager.state(), "needs_rebuild")
            manager._write_graph_schema()
            self.assertFalse(manager.graph_requires_rebuild())
            replacement = Path(directory) / "replacement.osm.pbf"
            replacement.write_bytes(b"new")
            manager.set_pbf_path(replacement)
            self.assertTrue(manager.graph_requires_rebuild())
            manager.set_pbf_path(pbf)
            with patch.object(manager, "components_installed", return_value=True):
                self.assertEqual(manager.state(), "stopped")
            manager.delete_graph_cache()
            self.assertFalse(manager.graph_prepared())
            self.assertFalse(manager.graph_schema_path.exists())
            manager.deleteLater()
        settings.clear()

    def test_graphhopper_error_summary_skips_java_stack_frames(self):
        output = """java.lang.IllegalArgumentException: Encoded values missing: mtb_access
at com.graphhopper.GraphHopper.prepareImport(GraphHopper.java:874)
at com.graphhopper.application.GraphHopperApplication.main(GraphHopperApplication.java:37)
"""
        self.assertIn("Encoded values missing", _graphhopper_error_summary(output, 1))
        self.assertNotIn("GraphHopperApplication.java", _graphhopper_error_summary(output, 1))
        route_listing = """INFO routes registered
POST /tasks/gc (io.dropwizard.servlets.tasks.GarbageCollectionTask)
"""
        summary = _graphhopper_error_summary(route_listing, 1)
        self.assertNotIn("/tasks/gc", summary)
        self.assertIn("code 1", summary)

    def test_graphhopper_credit_headers_allow_missing_limit_and_mixed_case(self):
        self.assertEqual(
            parse_rate_limit_headers([
                (b"x-ratelimit-remaining", b"493"),
                (b"X-RateLimit-Reset", b"3600"),
            ]),
            (500, 493, 3600),
        )
        self.assertEqual(
            parse_rate_limit_headers([
                (b"X-RateLimit-Limit", b"5000"),
                (b"X-RateLimit-Remaining", b"4980"),
            ]),
            (5000, 4980, 0),
        )
        self.assertIsNone(parse_rate_limit_headers([(b"Content-Type", b"application/json")]))

    def test_sparse_generated_interval_remains_continuous(self):
        points = [
            Point(t=0.0, lat=59.325830, lon=39.827679, speed=4.95243, distance=0.0),
            Point(t=159.700787, lat=59.331822, lon=39.820166,
                  speed=4.95243, distance=791.81258),
        ]
        model = ActivityModel(Path("route.gpx"), "gpx", points, np.ones(2, dtype=bool))
        index = RecordIndex(model)
        longitude, latitude = index.route_coordinates(model.active)
        self.assertEqual(len(longitude), 2)
        self.assertTrue(np.isfinite(longitude).all())
        self.assertTrue(np.isfinite(latitude).all())
        self.assertTrue(index.interval_valid[0])


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        QtCore.QSettings("VJ Ostrov", "Track Editor").clear()
        self.w = MainWindow()
        self.w.map_widget._tile = lambda *args: None
        self.w.resize(1450, 1100)
        self.w.show()
        self.model = activity()
        self.w.tracks = [TrackDocument(self.model, "#50D890")]
        self.w.active_track_index = 0
        self.w.refresh_plots(reset_region=True, fit_map=True)
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def test_startup_scales_sparse_hr_and_time_axis(self):
        self.assertEqual(self.w.graph_stack.visible_keys, ["speed", "heart_rate", "altitude"])
        panels = self.w.graph_stack.panels
        self.assertLess(panels["speed"].y_range[1], 20)
        self.assertGreater(panels["heart_rate"].y_range[1], 120)
        self.assertLess(panels["altitude"].y_range[0], -10)
        curves = [item for item in panels["heart_rate"].plot.listDataItems()
                  if isinstance(item, pg.PlotDataItem)]
        self.assertEqual(len(curves), 1)
        self.assertGreater(np.isfinite(curves[0].yData).sum(), 30)
        self.assertFalse(self.w.metric_checks["cadence"].isEnabled())
        self.assertFalse(self.w.selection_card.isVisible())
        axis = TimeAxisItem()
        self.assertEqual("0:40", axis.tickStrings([40], 1, 10)[0])

    def pos(self, panel, t):
        y = sum(panel.y_range) / 2
        return panel.plot.mapFromScene(panel.view.mapViewToScene(QtCore.QPointF(t, y)))

    def drag(self, panel, a, b):
        viewport = panel.plot.viewport()
        QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton, pos=self.pos(panel, a))
        QtTest.QTest.mouseMove(viewport, self.pos(panel, b))
        QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=self.pos(panel, b))
        self.app.processEvents()

    def test_selection_move_resize_map_and_mode_switch(self):
        panel = self.w.graph_stack.panels["heart_rate"]
        self.drag(panel, 30, 70)
        self.assertAlmostEqual(self.w._current_region()[0], 30, delta=1)
        self.assertTrue(self.w.selection_card.isVisible())
        self.assertEqual(len(self.w.map_widget._selection_routes), 1)
        selected = self.w.map_widget._selection_routes[0].segments[0]
        self.assertGreater(selected[0][0], self.model.points[0].lat)
        self.drag(panel, 50, 60)  # Move existing interval by 10 seconds.
        self.assertAlmostEqual(self.w._current_region()[0], 40, delta=1)
        self.drag(panel, self.w._current_region()[1], 100)
        self.assertAlmostEqual(self.w._current_region()[1], 100, delta=1)
        region = self.w._current_region()
        for r in self.w._regions:
            self.assertEqual(r.getRegion(), region)
        self.w.zoom_to_selection()
        self.w.chart_mode.setCurrentIndex(1)
        self.app.processEvents()
        np.testing.assert_allclose(self.w.telemetry_view_box.viewRange()[0], region)
        self.w.chart_mode.setCurrentIndex(0)
        self.w.reset_telemetry_view()
        for key in self.w.graph_stack.visible_keys:
            p = self.w.graph_stack.panels[key]
            np.testing.assert_allclose(p.view.viewRange()[0], [0, 180])
        self.assertEqual(self.w._current_region(), region)

    def test_wheel_only_changes_time_and_hover_does_not_accumulate(self):
        panel = self.w.graph_stack.panels["heart_rate"]
        old_y = panel.view.viewRange()[1].copy()
        viewport = panel.plot.viewport()
        point = self.pos(panel, 90)
        event = QtGui.QWheelEvent(QtCore.QPointF(point), QtCore.QPointF(viewport.mapToGlobal(point)),
                                 QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.NoButton,
                                 QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
        self.app.sendEvent(viewport, event)
        self.app.processEvents()
        self.assertLess(panel.view.viewRange()[0][1] - panel.view.viewRange()[0][0], 180)
        np.testing.assert_allclose(panel.view.viewRange()[1], old_y)
        self.w._activate_panel("heart_rate")
        for t in (60, 70, 80, 90):
            self.w._telemetry_mouse_moved((panel.view.mapViewToScene(QtCore.QPointF(t, 100)),))
            for key in self.w.graph_stack.visible_keys:
                self.assertEqual(len(self.w.graph_stack.panels[key].cursor_points.data), 1)
        self.w._hide_hover_feedback()
        for key in self.w.graph_stack.visible_keys:
            self.assertEqual(len(self.w.graph_stack.panels[key].cursor_points.data), 0)

    def test_multitrack_timeline_cut_undo_and_clear(self):
        self.w.tracks.append(TrackDocument(activity("second.gpx", offset=3600), "#FFA000"))
        self.w.refresh_plots(reset_region=True)
        self.assertGreaterEqual(self.w.tracks[1].timeline_start, self.w.tracks[0].timeline_end)
        self.w._selection_user_defined = True
        self.w._set_selection_region(40, 60)
        self.w.delete_selected()
        self.assertFalse(self.model.active[50])
        self.w.undo_stack.undo()
        self.assertTrue(self.model.active.all())
        self.w.tracks.clear()
        self.w.active_track_index = -1
        self.w._clear_activity_ui()
        self.assertEqual(self.w.graph_stack.visible_keys, ["combined"])
        self.assertFalse(self.w._regions)

    def test_xml_export_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            for extension in ("gpx", "tcx"):
                path = Path(directory) / ("sample." + extension)
                getattr(self.model, "_export_" + extension)(path)
                loaded = ActivityModel.load(path)
                self.assertEqual(len(loaded.points), len(self.model.points))
                self.assertAlmostEqual(loaded.points[0].heart_rate, 80)

    def test_save_conversion_settings_and_offline_cache_plan(self):
        self.assertEqual(self.w.save_action.text(), "СОХРАНИТЬ РЕЗУЛЬТАТ")
        self.assertEqual(self.w.gps_check_action.text(), "ПРОВЕРИТЬ ТРЕК НА ОШИБКИ")
        self.assertEqual(self.w.create_route_action.text(), "СОЗДАТЬ МАРШРУТ")
        self.assertEqual(self.w.convert_action.text(), "СОХРАНИТЬ В ДРУГОМ ФОРМАТЕ")
        expected_button_names = {
            self.w.save_action: "saveResultButton",
            self.w.convert_action: "convertFileButton",
            self.w.create_route_action: "createRouteButton",
            self.w.gps_check_action: "checkTrackButton",
        }
        for action, name in expected_button_names.items():
            button = self.w.toolbar.widgetForAction(action)
            self.assertEqual(button.objectName(), name)
            self.assertTrue(button.font().bold())
        self.assertFalse(self.w.settings_action.icon().isNull())
        toolbar_commands = [
            action for action in self.w.toolbar.actions() if not action.isSeparator()
        ]
        self.assertEqual(
            toolbar_commands[:4],
            [self.w.save_action, self.w.convert_action,
             self.w.create_route_action, self.w.gps_check_action],
        )
        self.assertFalse(hasattr(self.w, "open_action"))
        toolbar_actions = self.w.toolbar.actions()
        convert_position = toolbar_actions.index(self.w.convert_action)
        create_position = toolbar_actions.index(self.w.create_route_action)
        self.assertTrue(any(
            action.isSeparator()
            for action in toolbar_actions[convert_position + 1:create_position]
        ))
        self.assertNotIn(self.w.offline_map_action, toolbar_actions)
        self.assertIs(
            self.w.map_widget.download_button.defaultAction(), self.w.offline_map_action
        )
        self.assertTrue(self.w.map_widget.download_button.isEnabled())
        self.assertEqual(
            self.w.map_widget.download_button.cursor().shape(),
            QtCore.Qt.CursorShape.PointingHandCursor,
        )
        self.w.map_widget.overlay.move(0, self.w.map_widget.height())
        self.w.map_widget._snap_overlay_to_nearest_corner()
        self.assertEqual(self.w.map_widget._overlay_corner, "bottom_right")
        self.assertGreater(
            self.w.map_widget.overlay.y(), self.w.map_widget.search_overlay.y()
        )
        self.assertEqual(self.w.chart_display_label.text(), "ОТОБРАЖЕНИЕ ГРАФИКОВ")
        self.assertIn("Перетащите", self.w.activity_drop_zone.title_label.text())
        self.assertEqual(
            self.w.open_shortcut.shortcut(), QtGui.QKeySequence.StandardKey.Open
        )
        self.assertFalse(hasattr(self.w, "selection_edit_button"))
        self.assertEqual(self.w.selection_cut_button.text(), "Удалить")
        self.assertFalse(self.w.selection_cut_button.icon().isNull())
        self.assertFalse(self.w.activity_title.isVisible())
        self.assertEqual(
            self.w.toolbar.widgetForAction(self.w.undo_action).size(),
            self.w.toolbar.widgetForAction(self.w.redo_action).size(),
        )
        self.assertEqual(
            self.w.routing_source.group.button(0).icon().isNull(), False
        )
        self.assertEqual(
            self.w.routing_source.group.button(1).icon().isNull(), False
        )
        self.assertIn("<br>", self.w.summary.toolTip())
        self.assertIn("border:2px", self.w.routing_group.styleSheet())
        self.assertIn("border:2px", self.w.appearance_group.styleSheet())
        self.assertIn("border:2px", self.w.cache_group.styleSheet())
        self.assertIn("graphhopper.com/dashboard/signup", self.w.routing_account_link.text())
        self.assertEqual(self.w.routing_source.currentData(), "local")
        self.assertEqual(self.w.routing_stack.currentWidget(), self.w.routing_local_page)
        self.assertIn("не установлены", self.w.local_status_text.text())
        self.assertFalse(self.w.local_start_button.icon().isNull())
        self.assertFalse(self.w.local_stop_button.icon().isNull())
        self.assertFalse(self.w.local_test_button.icon().isNull())
        self.assertGreaterEqual(self.w.local_auto_start_check.font().pointSizeF(), 10.5)
        self.assertIn("border:2px", self.w.local_server_card.styleSheet())
        self.assertTrue(self.w.local_setup_title.text().startswith("01."))
        self.assertTrue(self.w.local_map_title.text().startswith("02."))
        self.assertTrue(self.w.local_prepare_title.text().startswith("03."))
        self.assertEqual(
            self.w.local_region_combo.currentData()["slug"],
            "northwestern-fed-district",
        )
        self.assertFalse(self.w.local_download_map_button.icon().isNull())
        self.assertIn("#ff5f73", self.w.local_server_indicator.text())
        self.assertIn("Локальный сервер не запущен", self.w.local_server_indicator.text())
        self.w._local_graphhopper_state_changed("running", "")
        self.assertIn("#4fd17b", self.w.local_server_indicator.text())
        self.assertIn("Локальный сервер запущен", self.w.local_server_indicator.text())
        self.assertTrue(self.w.local_choose_map_button.isEnabled())
        self.w._local_graphhopper_state_changed("stopped", "")
        self.assertIn("#ff5f73", self.w.local_server_indicator.text())
        with (
            patch.object(
                QtWidgets.QMessageBox, "question",
                return_value=QtWidgets.QMessageBox.StandardButton.Yes,
            ),
            patch.object(self.w.local_graphhopper, "download_map") as download_map,
        ):
            self.w._download_local_graphhopper_map()
            download_map.assert_called_once_with(
                "https://download.geofabrik.de/russia/"
                "northwestern-fed-district-latest.osm.pbf",
                "northwestern-fed-district-latest.osm.pbf",
            )
        with (
            patch.object(self.w.local_graphhopper, "state", return_value="stopped"),
            patch.object(self.w.local_graphhopper, "start_service") as start_service,
        ):
            self.w._maybe_start_local_graphhopper()
            start_service.assert_called_once()
        self.w.routing_source.setCurrentIndex(0)
        self.assertFalse(self.w.language_combo.isVisible())
        self.assertEqual(self.w.language_combo.parentWidget(), self.w.appearance_group)
        self.w.routing_key_edit.setText("test-key-abcdefgh")
        self.w.show_settings()
        self.assertFalse(hasattr(self.w, "_credits_reply"))
        self.w._update_graphhopper_credits(500, 493, 3600)
        self.assertEqual(self.w.credits_value_label.text(), "7 / 500")
        self.assertEqual(self.w.credits_progress.maximum(), 500)
        self.assertEqual(self.w.credits_progress.value(), 7)
        self.assertIn("1%", self.w.credits_percent_label.text())
        self.w.settings.setValue("routing_credit_reset_at", time.time() - 1)
        self.w._refresh_credit_labels_from_cache()
        self.assertEqual(self.w.credits_value_label.text(), "0 / 500")
        self.assertFalse(self.w.credits_reset_label.isVisible())
        self.w.theme_combo.setCurrentIndex(1)
        self.assertEqual(self.w.theme, "light")
        with tempfile.TemporaryDirectory() as directory:
            self.w.map_widget._cache_root = Path(directory) / "tiles"
            self.w.map_widget._cache_root.mkdir()
            plan = self.w.map_widget.route_cache_plan(
                self.w.map_widget._zoom, self.w.map_widget._zoom
            )
            self.assertGreater(len(plan), 0)
            output = Path(directory) / "converted.tcx"
            ok, _ = self.model.export_as(output)
            self.assertTrue(ok)
            self.assertEqual(ActivityModel.load(output).source_format, "tcx")

    def test_route_builder_is_embedded_and_can_start_from_loaded_track(self):
        model = activity()
        document = TrackDocument(model=model, colour="#50e39c")
        self.w.tracks.append(document)
        self.w.active_track_index = 0
        self.w._open_route_planner("http://127.0.0.1:8989/route", "")
        panel = self.w._route_panel
        self.assertIsInstance(panel, RoutePlannerPanel)
        self.assertIs(panel.parentWidget(), self.w.map_widget)
        self.assertTrue(self.w.map_widget.search_overlay.isVisible())
        self.assertFalse(self.w.activity_sidebar.isVisible())
        self.assertFalse(self.w.telemetry_container.isVisible())
        self.assertFalse(self.w.header.isVisible())
        for action in (
            self.w.save_action, self.w.convert_action,
            self.w.create_route_action, self.w.gps_check_action,
            self.w.undo_action, self.w.redo_action,
            self.w.history_view_separator, self.w.view_gap_action,
            self.w.view_label_action, self.w.vertical_view_action,
            self.w.horizontal_view_action, self.w.view_end_separator,
        ):
            self.assertFalse(action.isVisible())
        self.assertEqual(panel.drag_handle.cursor().shape(), QtCore.Qt.CursorShape.OpenHandCursor)
        self.assertNotIn("Перетащить", panel.drag_handle.text())
        self.assertEqual(panel.build_button.cursor().shape(), QtCore.Qt.CursorShape.OpenHandCursor)
        self.assertEqual(panel.profile_combo.cursor().shape(), QtCore.Qt.CursorShape.ArrowCursor)
        self.assertNotIn(panel.profile_combo.view().viewport(), panel._drag_surfaces)
        self.assertFalse(hasattr(panel, "undo_button"))
        panel._move_panel_to(QtCore.QPoint(24, 32), manual=True)
        self.assertEqual(panel.pos(), QtCore.QPoint(24, 32))
        self.assertEqual(panel.export_state()["panel_position"], [24, 32])
        press = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(8, 8), QtCore.QPointF(100, 100),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        move = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove,
            QtCore.QPointF(48, 33), QtCore.QPointF(140, 125),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        release = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(48, 33), QtCore.QPointF(140, 125),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        panel.eventFilter(panel.build_button, press)
        self.assertTrue(panel.eventFilter(panel.build_button, move))
        self.assertTrue(panel.eventFilter(panel.build_button, release))
        self.assertEqual(panel.pos(), QtCore.QPoint(64, 57))
        self.assertTrue(panel.eventFilter(panel.drag_handle, press))
        self.assertTrue(panel.eventFilter(panel.drag_handle, release))
        self.assertIsNone(self.w.map_widget._drag_position)
        panel._from_loaded_track()
        self.assertGreaterEqual(len(panel.control_points), 2)
        self.assertLessEqual(len(panel.control_points), 50)
        panel.route_coordinates = [
            (latitude, longitude, 100.0 + index * 2.0)
            for index, (latitude, longitude) in enumerate(panel.control_points)
        ]
        panel.route_distance_m = 12_340.0
        panel._refresh_map()
        panel._refresh_controls()
        self.assertTrue(panel.save_gpx_button.isEnabled())
        self.assertEqual(panel.distance_value.text(), "12.34 км")
        self.assertTrue(panel.ascent_value.text().endswith(" м"))
        self.assertFalse(panel.distance_icon.pixmap().isNull())
        self.assertFalse(panel.ascent_icon.pixmap().isNull())
        self.assertGreaterEqual(panel.minimumWidth(), 600)
        for button in (
            panel.build_button, panel.save_gpx_button, panel.add_button,
            panel.from_track_button, panel.clear_button,
        ):
            self.assertGreaterEqual(button.minimumHeight(), 42)
        save_spy = QtTest.QSignalSpy(panel.routeSaveRequested)
        with patch.object(
            QtWidgets.QFileDialog, "getSaveFileName", return_value=("", "")
        ):
            panel.save_gpx_button.click()
        self.assertEqual(save_spy.count(), 1)
        panel._insert_point(59.001, 39.001, 1)
        self.assertEqual(panel.control_points[1], (59.001, 39.001))
        panel.route_coordinates = [
            (latitude, longitude, 100.0) for latitude, longitude in panel.control_points
        ]
        removed = panel.control_points[1]
        with patch.object(panel, "_build_route") as rebuild:
            panel._remove_point(1)
            self.app.processEvents()
            rebuild.assert_called_once()
        self.assertNotEqual(panel.control_points[1], removed)
        point_count = len(panel.control_points)
        panel.close_mode()
        self.app.processEvents()
        self.assertFalse(self.w.map_widget.search_overlay.isVisible())
        self.assertTrue(self.w.activity_sidebar.isVisible())
        self.assertTrue(self.w.telemetry_container.isVisible())
        self.assertTrue(self.w.header.isVisible())
        for action in (
            self.w.save_action, self.w.convert_action,
            self.w.create_route_action, self.w.gps_check_action,
            self.w.undo_action, self.w.redo_action,
            self.w.history_view_separator, self.w.view_gap_action,
            self.w.view_label_action, self.w.vertical_view_action,
            self.w.horizontal_view_action, self.w.view_end_separator,
        ):
            self.assertTrue(action.isVisible())
        self.w._open_route_planner("http://127.0.0.1:8989/route", "")
        self.app.processEvents()
        self.assertEqual(len(self.w._route_panel.control_points), point_count)
        self.assertEqual(self.w._route_panel.pos(), QtCore.QPoint(64, 57))
        close_event = QtGui.QCloseEvent()
        self.w.closeEvent(close_event)
        self.app.processEvents()
        self.assertFalse(close_event.isAccepted())
        self.assertIsNone(self.w._route_panel)
        self.assertTrue(self.w.isVisible())
        self.assertEqual(len(self.w._route_draft_state["control_points"]), point_count)

        with patch.object(
            QtWidgets.QMessageBox, "question",
            return_value=QtWidgets.QMessageBox.StandardButton.No,
        ):
            self.assertFalse(self.w._confirm_application_exit())
        with patch.object(
            QtWidgets.QMessageBox, "question",
            return_value=QtWidgets.QMessageBox.StandardButton.Yes,
        ):
            self.assertTrue(self.w._confirm_application_exit())

    def test_route_ascent_and_flexible_content_splitter(self):
        self.assertEqual(route_ascent_m([
            (59.0, 39.0, 100.0),
            (59.1, 39.1, 105.0),
            (59.2, 39.2, 103.0),
            (59.3, 39.3, 110.0),
        ]), 12.0)
        self.assertIsNone(route_ascent_m([
            (59.0, 39.0, None), (59.1, 39.1, None),
        ]))
        self.w.resize(1400, 900)
        self.w.show()
        self.app.processEvents()
        self.w._set_content_orientation(QtCore.Qt.Orientation.Horizontal)
        self.w.content_splitter.setSizes([850, 100])
        self.app.processEvents()
        sizes = self.w.content_splitter.sizes()
        self.assertGreaterEqual(sizes[0], 320)
        self.assertGreaterEqual(sizes[1], 760)
        self.assertFalse(self.w.content_splitter.childrenCollapsible())
        self.w._set_content_orientation(QtCore.Qt.Orientation.Vertical)
        self.w.content_splitter.setSizes([50, 850])
        self.app.processEvents()
        vertical_sizes = self.w.content_splitter.sizes()
        self.assertGreaterEqual(vertical_sizes[0], 190)
        self.assertGreaterEqual(vertical_sizes[1], 260)

    def test_route_waypoint_hover_and_click_requests_exact_removal(self):
        widget = MapWidget()
        widget._tile = lambda *args: None
        widget.resize(640, 420)
        widget.show()
        widget.centre_on(59.22, 39.89, 15)
        widget.set_point_selection_enabled(True)
        widget.set_waypoints([(59.22, 39.89), (59.221, 39.892)])
        self.app.processEvents()
        centre = widget._to_world(widget._center_lat, widget._center_lon)
        origin = centre - QtCore.QPointF(widget.width() / 2, widget.height() / 2)
        position = (widget._to_world(59.22, 39.89) - origin).toPoint()
        move = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove,
            QtCore.QPointF(position), QtCore.QPointF(position),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        revision = widget._selection_revision
        widget.mouseMoveEvent(move)
        self.assertEqual(widget._hover_waypoint_index, 0)
        self.assertGreater(widget._selection_revision, revision)
        self.assertEqual(widget.cursor().shape(), QtCore.Qt.CursorShape.PointingHandCursor)
        removal = QtTest.QSignalSpy(widget.waypointRemoveRequested)
        press = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(position), QtCore.QPointF(position),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        release = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(position), QtCore.QPointF(position),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        widget.mousePressEvent(press)
        widget.mouseReleaseEvent(release)
        self.assertEqual(removal.count(), 1)
        self.assertEqual(removal.at(0), [0])
        widget.close()
        widget.deleteLater()

    def test_route_mode_saves_geometry_only_gpx(self):
        coordinates = [
            (59.2201, 39.8912, 118.0),
            (59.2210, 39.8940, 120.5),
            (59.2222, 39.8980, None),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "planned-route.gpx"
            with (
                patch.object(
                    QtWidgets.QFileDialog,
                    "getSaveFileName",
                    return_value=(str(output), "GPX (*.gpx)"),
                ),
                patch.object(QtWidgets.QMessageBox, "information"),
            ):
                self.w._save_route_gpx_from_panel(coordinates, "Плановый маршрут")
            xml = output.read_text(encoding="utf-8")
            self.assertIn("<trkpt", xml)
            self.assertIn("<ele>118", xml)
            self.assertNotIn("<time>", xml)
            self.assertNotIn("<speed>", xml)
            self.assertNotIn("TrackPointExtension", xml)
            reloaded = ActivityModel.load(output)
            self.assertFalse(reloaded.has_timing)
            self.assertFalse(any(math.isfinite(point.speed) for point in reloaded.points))
            self.assertEqual(detect_gps_anomalies(reloaded, "cycling"), [])

    def test_track_simplification_preserves_shape_endpoints_and_limit(self):
        points = [
            (59.0 + index * 0.0001, 39.0 + math.sin(index / 7) * 0.01)
            for index in range(500)
        ]
        simplified = simplify_route_points(points, 50)
        self.assertLessEqual(len(simplified), 50)
        self.assertEqual(simplified[0], points[0])
        self.assertEqual(simplified[-1], points[-1])

    def test_drop_zone_accepts_activity_files_only(self):
        accepted = self.w.activity_drop_zone.accepted_paths([
            QtCore.QUrl.fromLocalFile("/tmp/ride.fit"),
            QtCore.QUrl.fromLocalFile("/tmp/route.GPX"),
            QtCore.QUrl.fromLocalFile("/tmp/notes.txt"),
        ])
        self.assertEqual(accepted, ["/tmp/ride.fit", "/tmp/route.GPX"])

    def test_local_map_download_marks_existing_region_and_stops_server_first(self):
        with tempfile.TemporaryDirectory() as directory:
            self.w.local_graphhopper.root = Path(directory)
            maps = Path(directory) / "maps"
            maps.mkdir()
            downloaded = maps / "northwestern-fed-district-latest.osm.pbf"
            downloaded.write_bytes(b"map")
            self.w._refresh_local_region_labels()
            self.assertTrue(self.w.local_region_combo.currentText().startswith("✓"))
            with (
                patch.object(
                    QtWidgets.QMessageBox, "question",
                    return_value=QtWidgets.QMessageBox.StandardButton.Yes,
                ),
                patch.object(self.w.local_graphhopper, "is_running", return_value=True),
                patch.object(self.w.local_graphhopper, "stop_service") as stop_service,
                patch.object(self.w._map_download_wait_timer, "start") as timer_start,
            ):
                self.w._download_local_graphhopper_map()
            stop_service.assert_called_once()
            timer_start.assert_called_once()
            self.assertIsNotNone(self.w._pending_map_download)
            self.w._pending_map_download = None

            self.w._local_graphhopper_download_bytes(
                3 * 1024 ** 2, 12 * 1024 ** 2, "map"
            )
            self.assertIn("3.0 MB", self.w.local_progress_label.text())
            self.assertIn("12.0 MB", self.w.local_progress_label.text())
            with patch.object(
                QtWidgets.QMessageBox, "question",
                return_value=QtWidgets.QMessageBox.StandardButton.Yes,
            ):
                self.w._delete_local_graphhopper_map()
            self.assertFalse(downloaded.exists())
            self.assertFalse(self.w.local_region_combo.currentText().startswith("✓"))

    def test_structured_track_warning_and_map_zoom_buttons(self):
        dialog = TrackWarningDialog(9, TRANSLATIONS["ru"], "dark", self.w)
        self.assertEqual(dialog.findChild(QtWidgets.QLabel, "warningCount").text(),
                         "Найдено подозрительных участков: 9")
        self.assertEqual(len(dialog.findChildren(QtWidgets.QFrame, "warningDivider")), 2)
        self.assertEqual(dialog.review_button.text(), "Проверить сейчас")
        dialog.close()

        map_widget = self.w.map_widget
        original_zoom = map_widget._zoom
        map_widget.zoom_in_button.click()
        self.assertEqual(map_widget._zoom, min(19, original_zoom + 1))
        map_widget.zoom_out_button.click()
        self.assertEqual(map_widget._zoom, original_zoom)
        self.assertGreater(map_widget.zoom_controls.x(), map_widget.width() // 2)

    def test_separate_charts_scroll_in_short_window(self):
        self.w.graph_stack.resize(900, 220)
        self.app.processEvents()
        self.assertGreater(self.w.graph_stack.verticalScrollBar().maximum(), 0)

    def test_select_all_anomalies_in_review_dialog(self):
        self.model.points[40].speed = 31.0
        self.model.points[120].speed = 32.0
        checked_rows = []

        def inspect_dialog():
            dialog = self.app.activeModalWidget()
            self.assertIsInstance(dialog, QtWidgets.QDialog)
            table = dialog.findChild(QtWidgets.QTableWidget)
            self.assertIsNotNone(table)
            select_all = next(
                button for button in dialog.findChildren(QtWidgets.QPushButton)
                if button.text() == "Выбрать всё"
            )
            select_all.click()
            checked_rows.extend(
                row for row in range(table.rowCount())
                if table.item(row, 0).checkState() == QtCore.Qt.CheckState.Checked
            )
            dialog.reject()

        QtCore.QTimer.singleShot(0, inspect_dialog)
        self.w.check_gps_dialog()
        self.assertEqual(checked_rows, [0, 1])

    def test_anomaly_map_marker_opens_matching_chart_interval(self):
        self.model.points[40].speed = 31.0

        def click_anomaly_marker():
            dialog = self.app.activeModalWidget()
            self.assertIsInstance(dialog, QtWidgets.QDialog)
            review_map = dialog.findChild(MapWidget)
            self.assertIsNotNone(review_map)
            review_map.anomalyClicked.emit(0)

        QtCore.QTimer.singleShot(0, click_anomaly_marker)
        self.w.check_gps_dialog()
        self.assertTrue(self.w._selection_user_defined)
        start, end = self.w._current_region()
        self.assertLessEqual(start, 40.0)
        self.assertGreaterEqual(end, 40.0)
        view_start, view_end = self.w.telemetry_view_box.viewRange()[0]
        self.assertLessEqual(view_start, 40.0)
        self.assertGreaterEqual(view_end, 40.0)
        self.assertLess(view_end - view_start, self.w._telemetry_duration)

    def test_route_planner_shows_waypoints_without_provisional_lines(self):
        dialog = RoutePlannerDialog(
            "ru", "dark", "http://localhost:8989", "", "osm",
            (59.22, 39.89, 12), self.w,
        )
        dialog.map_widget._tile = lambda *args: None
        dialog._add_point(59.22, 39.88)
        dialog._add_point(59.23, 39.90)
        self.assertEqual(len(dialog.map_widget._waypoints), 2)
        self.assertFalse(dialog.map_widget._track_routes)
        self.assertTrue(
            dialog.windowFlags() & QtCore.Qt.WindowType.WindowMaximizeButtonHint
        )
        for index in range(8):
            dialog._add_point(59.24 + index / 100.0, 39.91 + index / 100.0)
        self.assertEqual(len(dialog.control_points), 10)
        self.assertEqual([len(batch) for batch in route_batches(dialog.control_points)], [5, 5, 2])
        self.assertIn("1", dialog.point_label.text())
        self.assertEqual(dialog.map_widget.cursor().shape(), QtCore.Qt.CursorShape.BitmapCursor)
        self.assertEqual(dialog.map_widget.cursor().hotSpot().y(), 33)
        mode_ids = [
            dialog.profile_combo.itemData(index)["mode"]
            for index in range(dialog.profile_combo.count())
        ]
        self.assertEqual(
            mode_ids,
            ["walk", "run", "bike", "road_bike", "mtb", "river", "direct"],
        )
        direct_index = mode_ids.index("direct")
        dialog.profile_combo.setCurrentIndex(direct_index)
        self.assertEqual(dialog.profile, "direct")
        self.assertIn("GraphHopper", dialog.mode_description_label.text())
        dialog._build_route()
        self.assertIsNone(dialog._reply)
        self.assertEqual(len(dialog.route_coordinates), 10)
        self.assertAlmostEqual(
            dialog.route_distance_m,
            direct_route_distance(dialog.control_points),
        )
        self.assertTrue(dialog.add_button.isEnabled())
        dialog.resize(1050, 720)
        dialog.show()
        self.app.processEvents()
        self.assertIs(dialog.route_controls_overlay.parentWidget(), dialog.map_widget)
        controls = dialog.build_button.parentWidget().layout().itemAt(1).layout()
        self.assertEqual(controls.getItemPosition(0)[:2], (0, 0))
        self.assertIs(controls.itemAtPosition(0, 0).widget(), dialog.build_button)
        self.assertIs(controls.itemAtPosition(1, 0).widget(), dialog.undo_button)
        for button in (
            dialog.undo_button, dialog.clear_button, dialog.build_button,
            dialog.add_button, dialog.fullscreen_button, dialog.cancel_button,
        ):
            self.assertGreaterEqual(button.height(), 46)
            self.assertFalse(button.icon().isNull())
        self.assertLessEqual(
            dialog.route_controls_overlay.geometry().right(), dialog.map_widget.width()
        )
        dialog.route_coordinates = [(59.22, 39.88, None), (59.23, 39.90, None)]
        dialog._refresh_map()
        self.assertEqual(len(dialog.map_widget._track_routes), 1)
        dialog.close()

    def test_planned_route_has_only_available_statistics(self):
        route = ActivityModel.from_route(
            [(59.22, 39.88, 120.0), (59.23, 39.90, 125.0)],
            "Planned route", 300.0,
        )
        document = TrackDocument(route, "#50D890")
        self.w.tracks = [document]
        self.w.active_track_index = 0
        self.w._record_indices.clear()
        stats = self.w._stats_for_masks([(document, route.active)], len(route.points))
        by_caption = {caption: value for _icon, _colour, caption, value in stats}
        self.assertEqual(by_caption["Общее время"], "—")
        self.assertEqual(by_caption["Время в движении"], "—")
        self.assertEqual(by_caption["Скорость в движении"], "—")
        self.assertNotEqual(by_caption["Расстояние"], "—")
        self.assertEqual(by_caption["Набор высоты"], "5 m")

    def test_hosted_road_route_without_key_opens_warning(self):
        titles = []

        def close_warning():
            warning = self.app.activeModalWidget()
            self.assertIsInstance(warning, QtWidgets.QMessageBox)
            titles.append(warning.windowTitle())
            warning.button(QtWidgets.QMessageBox.StandardButton.Ok).click()

        dialog = RoutePlannerDialog(
            "ru", "dark", "https://graphhopper.com/api/1/route", "", "osm",
            (59.22, 39.89, 12), self.w,
        )
        dialog.map_widget._tile = lambda *args: None
        dialog._add_point(59.22, 39.88)
        dialog._add_point(59.23, 39.90)
        QtCore.QTimer.singleShot(0, close_warning)
        dialog._build_route()
        self.assertEqual(titles, ["Не удалось построить маршрут"])
        direct_index = next(
            index for index in range(dialog.profile_combo.count())
            if dialog.profile_combo.itemData(index)["mode"] == "direct"
        )
        dialog.profile_combo.setCurrentIndex(direct_index)
        dialog._build_route()
        self.assertIsNone(dialog._reply)
        self.assertTrue(dialog.add_button.isEnabled())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
