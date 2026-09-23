from __future__ import annotations

from shapely.geometry import box
from shapely.ops import transform
from pyproj import Transformer

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT
from matplotlib.widgets import RectangleSelector

from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton, QLabel, QMessageBox, QComboBox, QInputDialog, QLineEdit, QGroupBox, QSizePolicy, QWidget
from PySide6.QtCore import QSettings, Signal, Qt

from gui.basemaps import BASEMAPS, label_for_key
from gui.basemap_renderer import render_with_fallback, diagnose_basemaps, WGS84_TO_WEB, square_web_bounds


_WGS84_TO_WEB = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
_WEB_TO_WGS84 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


def _to_web(geom):
    return transform(_WGS84_TO_WEB.transform, geom)


def _to_wgs(geom):
    return transform(_WEB_TO_WGS84.transform, geom)


class RegionMapPickerDialog(QDialog):
    """Interactive rectangle-only region picker with selectable online/offline basemaps."""

    # Emitted only when the user explicitly accepts a valid rectangle.
    # Contract: (west, east, south, north) in WGS84 degrees.
    boundsSelected = Signal(float, float, float, float)

    def __init__(self, parent=None, initial_geometry=None):
        super().__init__(parent)
        self.setWindowTitle("Select Study Region on Map")
        self.resize(1020, 740)
        self.setMinimumSize(900, 680)
        self.settings = QSettings("GODAS", "GODAS Regional Data Tool")
        self.selected_geometry = initial_geometry
        self.selected_bounds = None
        self._selector = None
        self._pan_active = False
        self._pan_press = None

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        controls_panel = QGroupBox("Map Controls")
        controls_panel.setMinimumWidth(220)
        controls_panel.setMaximumWidth(250)
        croot = QVBoxLayout(controls_panel)
        croot.setSpacing(7)

        info = QLabel(
            "Draw one rectangle on the map. The four bounding coordinates are updated automatically and shown on the map."
        )
        info.setWordWrap(True)
        croot.addWidget(info)

        croot.addWidget(QLabel("Basemap:"))
        self.basemap_combo = QComboBox()
        for item in BASEMAPS:
            self.basemap_combo.addItem(item.label, item.key)
        saved = self.settings.value("basemap/provider", "esri_street")
        idx = self.basemap_combo.findData(saved)
        self.basemap_combo.setCurrentIndex(idx if idx >= 0 else 0)
        croot.addWidget(self.basemap_combo)

        self.google_key_btn = QPushButton("Google API key…")
        self.google_key_btn.setObjectName("secondaryButton")
        croot.addWidget(self.google_key_btn)

        self.diagnose_btn = QPushButton("Basemap diagnostics")
        self.diagnose_btn.setObjectName("secondaryButton")
        croot.addWidget(self.diagnose_btn)

        self.basemap_status = QLabel()
        self.basemap_status.setWordWrap(True)
        self.basemap_status.setObjectName("fieldHint")
        croot.addWidget(self.basemap_status)

        coord_box = QGroupBox("Selected Rectangle")
        form = QFormLayout(coord_box)
        self.coord_w = QLineEdit("—")
        self.coord_e = QLineEdit("—")
        self.coord_s = QLineEdit("—")
        self.coord_n = QLineEdit("—")
        for edit in (self.coord_w, self.coord_e, self.coord_s, self.coord_n):
            edit.setReadOnly(True)
        form.addRow("West:", self.coord_w)
        form.addRow("East:", self.coord_e)
        form.addRow("South:", self.coord_s)
        form.addRow("North:", self.coord_n)
        croot.addWidget(coord_box)

        self.rectangle_btn = QPushButton("Draw Rectangle")
        self.rectangle_btn.setObjectName("primaryButton")
        self.clear_btn = QPushButton("Clear")
        croot.addWidget(self.rectangle_btn)
        croot.addWidget(self.clear_btn)
        croot.addStretch(1)

        croot.addWidget(QLabel("Rectangle is the only drawing tool. Polygon drawing has been removed to keep the numeric bounding-box workflow unambiguous."), 0)

        root.addWidget(controls_panel)

        map_panel = QVBoxLayout()
        self.figure = Figure(figsize=(6.2, 6.2), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.map_busy_label = QLabel("Updating map …  Please Wait …", self.canvas)
        self.map_busy_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.map_busy_label.setFixedSize(230, 48)
        self.map_busy_label.setStyleSheet(
            "QLabel { color: #253746; background: #eef2f5; border: 1px solid #aebdc8; "
            "border-radius: 8px; padding: 5px 10px; font-weight: 600; }"
        )
        self.map_busy_label.hide()
        self.ax = self.figure.add_subplot(111)
        self.ax.set_box_aspect(1)
        self.toolbar = NavigationToolbar2QT(self.canvas, self, coordinates=False)
        self.toolbar.setObjectName("mapNavigationToolbar")
        self.toolbar.setMovable(False)
        # Keep the navigation strip high-contrast even when the application uses the dark theme.
        self.toolbar.setStyleSheet(
            "QToolBar#mapNavigationToolbar { background: #eef2f5; border: 1px solid #c5d0d8; "
            "border-radius: 5px; spacing: 2px; padding: 2px; }"
            "QToolButton { color: #253746; background: transparent; border: 1px solid transparent; "
            "padding: 2px; border-radius: 4px; }"
            "QToolButton:hover { background: #d9e6ee; border-color: #a8bdc9; }"
            "QToolButton:checked { background: #c8dbe7; border-color: #91afbd; }"
        )
        # Keep the Matplotlib toolbar free of ambiguous pixel/RGB readouts.
        # A dedicated WGS84 cursor label is maintained by this dialog instead.
        self.cursor_label = QLabel("")
        self.cursor_label.setObjectName("mapCursorCoordinates")
        self.cursor_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cursor_label.setMinimumWidth(210)
        self.cursor_label.setStyleSheet(
            "QLabel#mapCursorCoordinates { color: #253746; background: #eef2f5; "
            "border: 1px solid #c5d0d8; border-radius: 4px; padding: 2px 7px; }"
        )
        self.toolbar.addSeparator()
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        self.toolbar.addWidget(self.cursor_label)
        self.canvas.mpl_connect("motion_notify_event", self._update_cursor_label)
        self.canvas.mpl_connect("figure_leave_event", self._clear_cursor_label)
        self.canvas.mpl_connect("button_press_event", self._mouse_press)
        self.canvas.mpl_connect("button_release_event", self._mouse_release)
        self.canvas.mpl_connect("motion_notify_event", self._mouse_motion)
        self.canvas.mpl_connect("scroll_event", self._mouse_scroll)

        map_panel.addWidget(self.toolbar, 0)
        map_panel.addWidget(self.canvas, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.ok_btn = QPushButton("Use Selected Region")
        self.cancel_btn = QPushButton("Cancel")
        button_row.addWidget(self.ok_btn)
        button_row.addWidget(self.cancel_btn)
        map_panel.addLayout(button_row)
        root.addLayout(map_panel, 1)

        self.rectangle_btn.clicked.connect(self.start_rectangle)
        self.clear_btn.clicked.connect(self.clear_selection)
        self.ok_btn.clicked.connect(self.accept_selection)
        self.cancel_btn.clicked.connect(self.reject)
        self.basemap_combo.currentIndexChanged.connect(self._basemap_changed)
        self.google_key_btn.clicked.connect(self._configure_google_key)
        self.diagnose_btn.clicked.connect(self._diagnose_basemaps)

        self._sync_google_controls()
        self._draw_map(initial_geometry)
        if initial_geometry is not None and not initial_geometry.is_empty:
            xmin, ymin, xmax, ymax = initial_geometry.bounds
            self.selected_bounds = (float(xmin), float(xmax), float(ymin), float(ymax))

    def _google_api_key(self) -> str:
        return str(self.settings.value("basemap/google_api_key", "") or "").strip()

    def _format_cursor_coord(self, x, y) -> str:
        """Return readable WGS84 longitude/latitude for the Matplotlib toolbar."""
        if x is None or y is None:
            return ""
        try:
            lon, lat = _WEB_TO_WGS84.transform(float(x), float(y))
            return f"Lon {lon:.4f}° | Lat {lat:.4f}°"
        except Exception:
            return ""

    def _update_cursor_label(self, event):
        if event is None or event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            self._clear_cursor_label()
            return
        self.cursor_label.setText(self._format_cursor_coord(event.xdata, event.ydata))

    def _clear_cursor_label(self, _event=None):
        if hasattr(self, "cursor_label"):
            self.cursor_label.setText("")

    def _disable_navigation_tools(self):
        """Release Matplotlib pan/zoom widget lock before rectangle drawing."""
        mode = getattr(self.toolbar, "mode", None)
        mode_name = getattr(mode, "name", "") or str(mode or "")
        if "PAN" in mode_name.upper():
            self.toolbar.pan()
        elif "ZOOM" in mode_name.upper():
            self.toolbar.zoom()

    def _toolbar_mode_active(self) -> bool:
        mode = getattr(self.toolbar, "mode", None)
        return bool(str(mode or "").strip())

    def _mouse_press(self, event):
        """Pan with the left mouse button when no drawing selector is active."""
        if event is None or event.button != 1 or event.inaxes is not self.ax:
            return
        if self._selector is not None or self._toolbar_mode_active():
            return
        if event.xdata is None or event.ydata is None:
            return
        self._pan_active = True
        self._pan_press = (float(event.xdata), float(event.ydata), self.ax.get_xlim(), self.ax.get_ylim())
        try:
            self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
        except Exception:
            pass

    def _mouse_motion(self, event):
        if not self._pan_active or self._pan_press is None:
            return
        if event is None or event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        x0, y0, xlim, ylim = self._pan_press
        dx = float(event.xdata) - x0
        dy = float(event.ydata) - y0
        self.ax.set_xlim(xlim[0] - dx, xlim[1] - dx)
        self.ax.set_ylim(ylim[0] - dy, ylim[1] - dy)
        self.canvas.draw_idle()

    def _mouse_release(self, event):
        if event is None or event.button != 1:
            return
        if self._pan_active:
            self._pan_active = False
            self._pan_press = None
            try:
                self.canvas.unsetCursor()
            except Exception:
                pass

    def _mouse_scroll(self, event):
        """Zoom around the mouse pointer with the wheel."""
        if event is None or event.inaxes is not self.ax or event.ydata is None or event.xdata is None:
            return
        if self._selector is not None or self._toolbar_mode_active():
            return
        step = float(getattr(event, "step", 0.0) or 0.0)
        if step == 0:
            return
        base = 0.85
        scale = base ** step if step > 0 else (1.0 / (base ** abs(step)))
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
        x = float(event.xdata)
        y = float(event.ydata)
        new_x0 = x - (x - xlim[0]) * scale
        new_x1 = x + (xlim[1] - x) * scale
        new_y0 = y - (y - ylim[0]) * scale
        new_y1 = y + (ylim[1] - y) * scale
        if new_x1 <= new_x0 or new_y1 <= new_y0:
            return
        self.ax.set_xlim(new_x0, new_x1)
        self.ax.set_ylim(new_y0, new_y1)
        self.canvas.draw_idle()

    def _show_map_busy(self, message: str = "Updating map …  Please Wait …"):
        """Show an in-map progress indicator before potentially slow tile rendering."""
        if not hasattr(self, "map_busy_label"):
            return
        self.map_busy_label.setText(message)
        self.map_busy_label.move(
            max(0, (self.canvas.width() - self.map_busy_label.width()) // 2),
            max(0, (self.canvas.height() - self.map_busy_label.height()) // 2),
        )
        self.map_busy_label.show()
        self.map_busy_label.raise_()
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        except Exception:
            pass
        QApplication.processEvents()

    def _update_map_progress(self, message: str):
        if not hasattr(self, "map_busy_label"):
            return
        self.map_busy_label.setText(message)
        self.map_busy_label.raise_()
        QApplication.processEvents()

    def _hide_map_busy(self):
        if not hasattr(self, "map_busy_label"):
            return
        self.map_busy_label.hide()
        try:
            QApplication.restoreOverrideCursor()
        except Exception:
            pass

    def _configure_google_key(self):
        current = self._google_api_key()
        key, ok = QInputDialog.getText(
            self,
            "Google Maps Platform API Key",
            "API key (stored locally in application settings):",
            text=current,
            echo=QLineEdit.EchoMode.Password,
        )
        if ok:
            self.settings.setValue("basemap/google_api_key", key.strip())
            self._draw_map(self.selected_geometry)

    def _sync_google_controls(self):
        self.google_key_btn.setEnabled(self.basemap_combo.currentData() == "google_satellite")

    def _basemap_changed(self, _index):
        self.settings.setValue("basemap/provider", self.basemap_combo.currentData())
        self._sync_google_controls()
        self._draw_map(self.selected_geometry)

    def _diagnose_basemaps(self):
        keys = [item.key for item in BASEMAPS if item.key != "none"]
        rows = diagnose_basemaps(keys, self._google_api_key())
        lines = []
        for key, ok, detail in rows:
            state = "PASS" if ok else "FAIL"
            lines.append(f"{state}: {label_for_key(key)} — {detail}")
        QMessageBox.information(self, "Basemap diagnostics", "\n".join(lines))

    def _update_coordinate_fields(self):
        if self.selected_geometry is None or self.selected_geometry.is_empty:
            for edit in (self.coord_w, self.coord_e, self.coord_s, self.coord_n):
                edit.setText("—")
            return
        xmin, ymin, xmax, ymax = self.selected_geometry.bounds
        self.coord_w.setText(f"{xmin:.4f}°")
        self.coord_e.setText(f"{xmax:.4f}°")
        self.coord_s.setText(f"{ymin:.4f}°")
        self.coord_n.setText(f"{ymax:.4f}°")

    def _draw_map(self, geometry=None):
        self.ax.clear()
        self.ax.set_box_aspect(1)
        geom_web = _to_web(geometry) if geometry is not None and not geometry.is_empty else None
        if geom_web is not None:
            bounds = geom_web.bounds
            padx = max((bounds[2] - bounds[0]) * 0.25, 200000)
            pady = max((bounds[3] - bounds[1]) * 0.25, 200000)
            bounds = square_web_bounds((bounds[0]-padx, bounds[1]-pady, bounds[2]+padx, bounds[3]+pady))
        else:
            bounds = (-20037508.342789244, -12000000, 20037508.342789244, 12000000)
            bounds = square_web_bounds(bounds)
        self.ax.set_xlim(bounds[0], bounds[2])
        self.ax.set_ylim(bounds[1], bounds[3])

        requested = self.basemap_combo.currentData() or "esri_street"
        self._show_map_busy("Updating map …  Please Wait …")
        try:
            used_key, info, error = render_with_fallback(
                self.ax, requested, bounds, self._google_api_key(), progress=self._update_map_progress
            )
        finally:
            self._hide_map_busy()
        self.ax.set_axis_off()
        if used_key == "offline_world":
            if requested == "offline_world":
                self.basemap_status.setText("Bundled offline world map — no internet required.")
            else:
                self.basemap_status.setText(
                    f"{label_for_key(requested)} unavailable; using the bundled offline world map instead."
                )
        elif info:
            self.basemap_status.setText(
                f"{label_for_key(used_key)} loaded — {info.get('tiles_loaded', 0)}/{info.get('tiles_requested', 0)} tiles."
            )
        else:
            self.basemap_status.setText(
                f"Basemap unavailable ({label_for_key(requested)}). You can still draw the rectangle."
                + (f" Last error: {error}" if error else "")
            )

        if geom_web is not None and not geom_web.is_empty:
            try:
                x, y = geom_web.exterior.xy
                self.ax.plot(x, y, linewidth=2.2, color="#e4572e", zorder=10)
            except Exception:
                pass
            self._update_coordinate_fields()
            xmin, ymin, xmax, ymax = geometry.bounds
            self.ax.text(
                0.02, 0.02,
                f"W {xmin:.4f}°  |  E {xmax:.4f}°  |  S {ymin:.4f}°  |  N {ymax:.4f}°",
                transform=self.ax.transAxes,
                ha="left", va="bottom",
                fontsize=8.5,
                bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#a0aab4"},
                zorder=20,
            )
        else:
            self._update_coordinate_fields()

        self.canvas.draw_idle()

    def _set_selector(self, selector):
        if self._selector is not None:
            try:
                self._selector.set_active(False)
            except Exception:
                pass
        self._selector = selector
        if selector is not None:
            try:
                selector.set_active(True)
            except Exception:
                pass

    def start_rectangle(self):
        self._pan_active = False
        self._pan_press = None
        # Pan/zoom uses Matplotlib's widget lock. Release it so the RectangleSelector
        # receives the next mouse gesture, even after the user has zoomed or panned.
        self._disable_navigation_tools()
        self._set_selector(RectangleSelector(
            self.ax,
            self._rectangle_selected,
            useblit=False,
            button=[1],
            minspanx=5,
            minspany=5,
            spancoords="pixels",
            interactive=False,
        ))

    def _rectangle_selected(self, eclick, erelease):
        if eclick.xdata is None or erelease.xdata is None or eclick.ydata is None or erelease.ydata is None:
            return
        if eclick.xdata == erelease.xdata or eclick.ydata == erelease.ydata:
            return
        geom_web = box(
            min(eclick.xdata, erelease.xdata),
            min(eclick.ydata, erelease.ydata),
            max(eclick.xdata, erelease.xdata),
            max(eclick.ydata, erelease.ydata),
        )
        self.selected_geometry = _to_wgs(geom_web)
        xmin, ymin, xmax, ymax = self.selected_geometry.bounds
        # Keep an explicit WGS84 bounds tuple as the dialog result contract.
        # The parent window uses this tuple to synchronize the Numeric Bounding Box controls.
        self.selected_bounds = (float(xmin), float(xmax), float(ymin), float(ymax))
        self._set_selector(None)
        self._draw_map(self.selected_geometry)

    def clear_selection(self):
        self.selected_geometry = None
        self._set_selector(None)
        self._draw_map(None)

    def get_selected_bounds(self):
        """Return selected rectangle bounds as (west, east, south, north) in WGS84 degrees."""
        if self.selected_bounds is not None:
            return tuple(float(v) for v in self.selected_bounds)
        if self.selected_geometry is None or self.selected_geometry.is_empty:
            return None
        xmin, ymin, xmax, ymax = self.selected_geometry.bounds
        self.selected_bounds = (float(xmin), float(xmax), float(ymin), float(ymax))
        return self.selected_bounds

    def accept_selection(self):
        if self.selected_geometry is None or self.selected_geometry.is_empty:
            QMessageBox.warning(self, "No Region", "Draw a rectangle before accepting the study region.")
            return
        if self.selected_geometry.geom_type != "Polygon":
            QMessageBox.warning(self, "Invalid Region", "The selected study region must be a rectangle polygon.")
            return
        bounds = self.get_selected_bounds()
        if bounds is None:
            QMessageBox.warning(self, "Invalid Region", "The selected rectangle has no valid WGS84 bounds.")
            return
        # Emit the explicit GUI result contract before closing the dialog so the
        # parent window can synchronize its Numeric Bounding Box immediately.
        self.boundsSelected.emit(*bounds)
        self.accept()
