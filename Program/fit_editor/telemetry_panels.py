"""Telemetry panels share time, but retain their own physical value ranges."""
from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg
from .chart_axes import DistanceAxisItem


class GraphPanel(QtWidgets.QWidget):
    def __init__(self, owner, key, axis_class, view_class):
        super().__init__()
        self.key = key
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.view = view_class(owner)
        self.plot = pg.PlotWidget(axisItems={"bottom": axis_class(), "top": DistanceAxisItem()}, viewBox=self.view)
        self.plot.setBackground("#181c22")
        self.plot.setMinimumHeight(90)
        self.plot.showGrid(x=True, y=True, alpha=0.13)
        self.plot.getPlotItem().hideButtons()
        self.plot.getAxis("left").setWidth(58)
        self.plot.getAxis("left").setTextPen("#858d98")
        self.plot.getAxis("bottom").setTextPen("#858d98")
        self.plot.getAxis("top").setTextPen("#858d98")
        # Repaint moving overlays completely. Partial scene damage regions can
        # leave stale crosshair/scatter pixels on the Windows raster backend.
        self.plot.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        self.plot.viewport().setMouseTracking(True)
        self.plot.viewport().installEventFilter(owner)
        # Keep the name and statistics inside the plot. The top distance axis
        # exists only on the first panel, so an external header looked detached
        # from the speed curve while the other headings did not.
        self.header_overlay = QtWidgets.QWidget(self.plot.viewport())
        self.header_overlay.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        header = QtWidgets.QHBoxLayout(self.header_overlay)
        header.setContentsMargins(10, 4, 8, 0)
        header.setSpacing(8)
        self.title = QtWidgets.QLabel()
        self.stats = QtWidgets.QLabel()
        self.stats.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.stats.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.stats.setStyleSheet("font-size:11px; background:transparent;")
        self.stats.setWordWrap(False)
        header.addWidget(self.title)
        header.addWidget(self.stats, 1)
        self.plot.viewport().installEventFilter(self)
        self._position_header()
        self.proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=30,
                                   slot=lambda event: owner._panel_mouse_moved(key, event))
        self.view.sigXRangeChanged.connect(lambda _view, bounds: owner._sync_x_range(bounds))
        self.view.sigRangeChanged.connect(owner._position_selection_toolbar)
        layout.addWidget(self.plot, 1)
        self.cursor_line = None
        self.cursor_points = None
        self.y_range = (0.0, 1.0)

    def _position_header(self):
        height = max(26, self.title.sizeHint().height() + 7, self.stats.sizeHint().height() + 7)
        scene_bounds = self.view.sceneBoundingRect()
        if scene_bounds.isValid():
            top_left = self.plot.mapFromScene(scene_bounds.topLeft())
            top_right = self.plot.mapFromScene(scene_bounds.topRight())
            left = max(0, top_left.x())
            top = max(0, top_left.y())
            width = max(1, top_right.x() - left)
        else:
            left, top, width = 0, 0, self.plot.viewport().width()
        self.header_overlay.setGeometry(left, top, width, height)
        self.header_overlay.raise_()

    def eventFilter(self, watched, event):
        if watched is self.plot.viewport() and event.type() in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Show,
        ):
            self._position_header()
        return super().eventFilter(watched, event)

    def set_theme(self, theme):
        light = theme == "light"
        background = "#f4f6f9" if light else "#181c22"
        axis = "#586476" if light else "#858d98"
        self.plot.setBackground(background)
        self.stats.setStyleSheet("font-size:11px; background:transparent;")
        for name in ("left", "bottom", "top"):
            self.plot.getAxis(name).setTextPen(axis)


class GraphStack(QtWidgets.QScrollArea):
    def __init__(self, owner, fields, axis_class, view_class):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setMinimumHeight(180)
        container = QtWidgets.QWidget()
        self.container = container
        self.panel_layout = QtWidgets.QVBoxLayout(container)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_layout.setSpacing(6)
        self.panels = {}
        for key in ["combined", *fields]:
            panel = GraphPanel(owner, key, axis_class, view_class)
            self.panels[key] = panel
            self.panel_layout.addWidget(panel, 1)
            panel.setVisible(key == "combined")
        self.setWidget(container)
        self.visible_keys = ["combined"]

    def prepare(self, fields, combined):
        self.visible_keys = ["combined"] if combined or not fields else list(fields)
        # Keep every graph readable. When the window is shorter than the full
        # stack, this minimum activates the internal scrollbar instead of
        # compressing/cropping the lower charts.
        self.container.setMinimumHeight(
            260 if self.visible_keys == ["combined"] else 158 * len(self.visible_keys)
        )
        for key, panel in self.panels.items():
            panel.plot.clear()
            panel.cursor_line = panel.cursor_points = None
            panel.stats.clear()
            panel.setVisible(key in self.visible_keys)
            # There is one time scale, on the lowest visible graph only.
            bottom = key == self.visible_keys[-1]
            panel.plot.getAxis("bottom").setStyle(showValues=bottom)
            panel.plot.getAxis("bottom").setHeight(44 if bottom else 4)
            panel.plot.setLabel("bottom", "")
            panel.plot.hideAxis("top")

    def set_theme(self, theme):
        for panel in self.panels.values():
            panel.set_theme(theme)
