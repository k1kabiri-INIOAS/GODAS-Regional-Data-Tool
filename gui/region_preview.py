from __future__ import annotations

from shapely.geometry import Polygon, MultiPolygon
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox, QPushButton, QInputDialog, QMessageBox, QLineEdit, QGroupBox, QSizePolicy

from gui.basemaps import BASEMAPS, label_for_key
from gui.basemap_renderer import render_with_fallback, diagnose_basemaps, WGS84_TO_WEB, square_web_bounds


class RegionPreviewWidget(QWidget):
    """First-tab study-region preview with a compact left control panel and square map."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("GODAS", "GODAS Regional Data Tool")
        self.geometry = None
        self.label = "Study Region"

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        controls_panel = QGroupBox("Map Controls")
        controls_panel.setMinimumWidth(205)
        controls_panel.setMaximumWidth(240)
        croot = QVBoxLayout(controls_panel)
        croot.setSpacing(7)

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
        self.google_key_btn.setToolTip("Configure the optional Google Maps Platform API key.")
        croot.addWidget(self.google_key_btn)

        self.diagnose_btn = QPushButton("Basemap diagnostics")
        self.diagnose_btn.setObjectName("secondaryButton")
        croot.addWidget(self.diagnose_btn)

        self.basemap_status = QLabel()
        self.basemap_status.setObjectName("fieldHint")
        self.basemap_status.setWordWrap(True)
        croot.addWidget(self.basemap_status)
        croot.addStretch(1)

        root.addWidget(controls_panel)

        map_panel = QWidget()
        map_panel.setFixedSize(320, 320)
        map_layout = QVBoxLayout(map_panel)
        map_layout.setContentsMargins(0, 0, 0, 0)
        self.figure = Figure(figsize=(4.1, 4.1), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setFixedSize(320, 320)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_box_aspect(1)
        map_layout.addWidget(self.canvas, 1)
        root.addWidget(map_panel, 1)

        self.basemap_combo.currentIndexChanged.connect(self._basemap_changed)
        self.google_key_btn.clicked.connect(self._configure_google_key)
        self.diagnose_btn.clicked.connect(self._diagnose_basemaps)
        self.clear_region()

        # The Google key control is useful only when Google Satellite is selected.
        self._sync_google_controls()

    def _google_api_key(self) -> str:
        return str(self.settings.value("basemap/google_api_key", "") or "").strip()

    def _configure_google_key(self):
        current = self._google_api_key()
        key, ok = QInputDialog.getText(
            self,
            "Google Maps Platform API Key",
            "API key (stored locally in application settings):",
            text=current,
            echo=QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        key = key.strip()
        self.settings.setValue("basemap/google_api_key", key)
        if self.basemap_combo.currentData() == "google_satellite" and self.geometry is not None:
            self._render()

    def _sync_google_controls(self):
        is_google = self.basemap_combo.currentData() == "google_satellite"
        self.google_key_btn.setEnabled(is_google)

    def _basemap_changed(self, _index):
        self.settings.setValue("basemap/provider", self.basemap_combo.currentData())
        self._sync_google_controls()
        if self.geometry is not None:
            self._render()

    def _diagnose_basemaps(self):
        keys = [item.key for item in BASEMAPS if item.key not in {"none"}]
        rows = diagnose_basemaps(keys, self._google_api_key())
        lines = []
        for key, ok, detail in rows:
            state = "PASS" if ok else "FAIL"
            lines.append(f"{state}: {label_for_key(key)} — {detail}")
        QMessageBox.information(self, "Basemap diagnostics", "\n".join(lines))

    def clear_region(self):
        self.geometry = None
        self.ax.clear()
        self.ax.set_box_aspect(1)
        self.ax.set_axis_on()
        self.ax.set_title("Study Region Preview")
        self.ax.set_xlabel("Longitude (°)")
        self.ax.set_ylabel("Latitude (°)")
        self.ax.grid(True, alpha=0.25)
        self.ax.text(0.5, 0.5, "No study region selected", transform=self.ax.transAxes, ha="center", va="center")
        self.basemap_status.setText("")
        self.canvas.draw_idle()

    def set_region(self, geometry, label="Study Region"):
        self.geometry = geometry
        self.label = str(label)
        self._render()

    def _render(self):
        geometry = self.geometry
        if geometry is None or geometry.is_empty:
            self.clear_region()
            return

        self.ax.clear()
        self.ax.set_box_aspect(1)
        from shapely.ops import transform
        geom_web = transform(WGS84_TO_WEB.transform, geometry)
        wx0, wy0, wx1, wy1 = geom_web.bounds
        wp = max((wx1 - wx0) * 0.20, 10000.0)
        hp = max((wy1 - wy0) * 0.20, 10000.0)
        bounds = square_web_bounds((wx0 - wp, wy0 - hp, wx1 + wp, wy1 + hp))
        self.ax.set_xlim(bounds[0], bounds[2])
        self.ax.set_ylim(bounds[1], bounds[3])
        requested = self.basemap_combo.currentData() or "esri_street"
        used_key, info, error = render_with_fallback(self.ax, requested, bounds, self._google_api_key())
        self.ax.set_axis_off() if info else self.ax.set_axis_on()
        if used_key == "offline_world":
            if requested == "offline_world":
                self.basemap_status.setText("Bundled offline world map — no internet required.")
            else:
                self.basemap_status.setText(
                    f"{label_for_key(requested)} unavailable; switched to the bundled offline world map."
                )
        elif info:
            self.basemap_status.setText(
                f"{label_for_key(used_key)} loaded — {info.get('tiles_loaded', 0)}/{info.get('tiles_requested', 0)} tiles."
            )
        else:
            self.ax.grid(True, alpha=0.25)
            detail = f" Last error: {error}" if error else ""
            self.basemap_status.setText(
                f"Basemap unavailable ({label_for_key(requested)}). Showing region geometry only.{detail}"
            )

        try:
            geoms = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
            for geom in geoms:
                if isinstance(geom, Polygon):
                    g = transform(WGS84_TO_WEB.transform, geom)
                    x, y = g.exterior.xy
                    self.ax.plot(x, y, linewidth=2.0, color="#e4572e", zorder=10)
        except Exception:
            pass
        self.canvas.draw_idle()
