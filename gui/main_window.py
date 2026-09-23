from pathlib import Path
import pandas as pd
import xarray as xr
from PySide6.QtCore import QThread, Signal, QDate, QSettings, Qt, QSize, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QApplication, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QGroupBox,
    QCheckBox, QDateEdit, QPlainTextEdit, QProgressBar, QMessageBox, QComboBox,
    QTabWidget, QFormLayout, QScrollArea, QRadioButton, QButtonGroup, QDoubleSpinBox, QSpinBox, QFrame, QSizePolicy
)
from PySide6.QtGui import QFont, QIcon, QPixmap
from core.spatial import inspect_shapefile
from core.region import (
    RegionSpec, inspect_shapefile as inspect_region_shapefile, load_shapefile_region,
    load_iho_catalog, fetch_iho_sea_from_marine_regions, make_bbox_region, validate_region_for_godas
)
from core.downloader import download_selected
from core.qc import run_qc
from core.standardize import standardize_and_integrate
from core.analysis import run_analysis
from core.climatology import run_climatology, run_anomaly
from core.trend import run_trend
from core.reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION
from core.visualization import (
    run_spatial_visualization, run_map_product, available_depths, standardized_file as visualization_standardized_file,
)
from gui.theme import apply_theme
from config.variables import GODAS_VARIABLES
from core.region import make_map_region
from gui.map_picker import RegionMapPickerDialog
from gui.region_preview import RegionPreviewWidget

class IHOCatalogWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, cache_path):
        super().__init__()
        self.cache_path = cache_path

    def run(self):
        try:
            catalog = load_iho_catalog(self.cache_path)
            self.finished_ok.emit(catalog)
        except Exception as exc:
            self.failed.emit(str(exc))


class IHOFetchWorker(QThread):
    finished_ok = Signal(object, dict)
    failed = Signal(str)

    def __init__(self, name, mrgid):
        super().__init__()
        self.name = name
        self.mrgid = int(mrgid)

    def run(self):
        try:
            spec = fetch_iho_sea_from_marine_regions(self.name, self.mrgid)
            check = validate_region_for_godas(spec)
            self.finished_ok.emit(spec, check)
        except Exception as exc:
            self.failed.emit(str(exc))


class DownloadWorker(QThread):
    message = Signal(str)
    progress = Signal(int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, variables, region, start_date, end_date, output_dir):
        super().__init__()
        self.variables = variables
        self.region = region
        self.start_date = start_date
        self.end_date = end_date
        self.output_dir = output_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            def log(msg):
                self.message.emit(msg)
                if msg.startswith("[PROGRESS]"):
                    # The downloader reports completed year-slots explicitly.
                    try:
                        import re
                        match = re.search(r"(\d+)\s*/\s*(\d+)\s+year-slots", msg)
                        if match:
                            done, total = map(int, match.groups())
                            self.progress.emit(min(99, int(done / max(total, 1) * 100)))
                    except Exception:
                        pass

            summary = download_selected(
                self.variables,
                self.region,
                self.start_date,
                self.end_date,
                self.output_dir,
                progress=log,
                cancel_check=lambda: self._cancel,
            )
            if self._cancel or summary.cancelled:
                self.message.emit("[INFO] Cancellation requested.")
            elif summary.failed or summary.unavailable:
                self.progress.emit(100)
                self.message.emit(
                    f"[DONE WITH WARNINGS] Success={summary.success}, "
                    f"Skipped={summary.skipped}, Unavailable={summary.unavailable}, "
                    f"Failed={summary.failed}."
                )
                self.finished_ok.emit()
            else:
                self.progress.emit(100)
                self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

class QCWorker(QThread):
    message = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, output_dir):
        super().__init__()
        self.output_dir = output_dir

    def run(self):
        try:
            def log(msg):
                self.message.emit(msg)
            result = run_qc(self.output_dir, progress=log)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

class StandardizeWorker(QThread):
    message = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, output_dir):
        super().__init__()
        self.output_dir = output_dir

    def run(self):
        try:
            def log(msg):
                self.message.emit(msg)
            result = standardize_and_integrate(self.output_dir, progress=log)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class AnalysisWorker(QThread):
    message = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, output_dir, variable_key, analysis_type, start_date, end_date, depth_mode, single_depth, depth_min, depth_max, unit_mode):
        super().__init__()
        self.output_dir = output_dir
        self.variable_key = variable_key
        self.analysis_type = analysis_type
        self.start_date = start_date
        self.end_date = end_date
        self.depth_mode = depth_mode
        self.single_depth = single_depth
        self.depth_min = depth_min
        self.depth_max = depth_max
        self.unit_mode = unit_mode

    def run(self):
        try:
            result = run_analysis(
                self.output_dir, self.variable_key, self.analysis_type,
                self.start_date, self.end_date,
                self.depth_mode, self.single_depth, self.depth_min, self.depth_max,
                self.unit_mode, progress=self.message.emit
            )
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

class ScientificProductWorker(QThread):
    message = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, output_dir, product, variable_key, mode, baseline_start, baseline_end,
                 analysis_start, analysis_end, depth_mode, single_depth, depth_min, depth_max, unit_mode):
        super().__init__()
        self.args = (output_dir, variable_key, mode, baseline_start, baseline_end, analysis_start, analysis_end,
                     depth_mode, single_depth, depth_min, depth_max, unit_mode)
        self.product = product

    def run(self):
        try:
            if self.product == "climatology":
                result = run_climatology(self.args[0], self.args[1], self.args[2], self.args[3], self.args[4],
                                         self.args[7], self.args[8], self.args[9], self.args[10], self.args[11],
                                         progress=self.message.emit)
            else:
                result = run_anomaly(self.args[0], self.args[1], self.args[2], self.args[3], self.args[4],
                                     self.args[5], self.args[6], self.args[7], self.args[8], self.args[9], self.args[10], self.args[11],
                                     progress=self.message.emit)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

class TrendWorker(QThread):
    message = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, output_dir, variable_key, trend_type, start_date, end_date, depth_mode,
                 single_depth, depth_min, depth_max, unit_mode, methods, alpha=0.05):
        super().__init__()
        self.args = (output_dir, variable_key, trend_type, start_date, end_date, depth_mode,
                     single_depth, depth_min, depth_max, unit_mode, methods, alpha)

    def run(self):
        try:
            result = run_trend(*self.args, progress=self.message.emit)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class SpatialVisualizationWorker(QThread):
    message = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, output_dir, params):
        super().__init__()
        self.output_dir = output_dir
        self.params = params

    def run(self):
        try:
            result = run_map_product(self.output_dir, self.params, progress=self.message.emit)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    @staticmethod
    def _variable_items():
        return [(meta["label"], key) for key, meta in GODAS_VARIABLES.items()]

    @staticmethod
    def _has_depth(var):
        return bool(GODAS_VARIABLES.get(var, {}).get("has_depth", False))

    @staticmethod
    def _unit_options(var):
        return GODAS_VARIABLES.get(var, {}).get("unit_options", [("Native GODAS units", "native")])

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GODAS Regional Data Tool — v{SOFTWARE_VERSION}")
        self.resize(1180, 820)
        self.setMinimumSize(980, 660)
        self.worker = None
        self._region_spec = None
        self._iho_spinner_timer = QTimer(self)
        self._iho_spinner_timer.setInterval(180)
        self._iho_spinner_frames = ("|", "/", "-", "\\")
        self._iho_spinner_index = 0
        self._iho_spinner_text = ""
        self._iho_spinner_timer.timeout.connect(self._update_iho_spinner)
        self.settings = QSettings("GODAS", "GODAS Regional Data Tool")
        self.current_theme = apply_theme(self._qt_app(), self.settings.value("theme", "dark"))
        self._set_application_icon()
        self._build_ui()
        self._sync_theme_buttons()

    def _qt_app(self):
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication must exist before MainWindow is created.")
        return app

    def _set_application_icon(self):
        icon_path = Path(__file__).resolve().parent.parent / "resources" / "godas_logo.ico"
        if icon_path.exists():
            icon = QIcon(str(icon_path))
            self.setWindowIcon(icon)
            self._qt_app().setWindowIcon(icon)

    def _build_header(self, parent_layout):
        header = QHBoxLayout()
        header.setContentsMargins(2, 2, 2, 4)
        header.setSpacing(10)

        logo_label = QLabel()
        logo_path = Path(__file__).resolve().parent.parent / "resources" / "godas_logo.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path)).scaled(52, 52, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pixmap)
        logo_label.setFixedSize(56, 56)
        header.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignVCenter)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("GODAS")
        title.setObjectName("appWordmark")
        subtitle_title = QLabel("Regional Data Tool")
        subtitle_title.setObjectName("appProductName")
        subtitle = QLabel("From global ocean data to regional insights — analysis, visualization and reproducible outputs")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("appSubtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle_title)
        brand.addSpacing(2)
        brand.addWidget(subtitle)
        header.addLayout(brand, 1)

        self.version_chip = QLabel(f"v{SOFTWARE_VERSION}  |  Schema {REPORT_SCHEMA_VERSION}")
        self.version_chip.setObjectName("appVersion")
        header.addWidget(self.version_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        theme_box = QHBoxLayout()
        theme_box.setSpacing(4)
        self.light_theme_btn = QPushButton("Light")
        self.dark_theme_btn = QPushButton("Dark")
        self.light_theme_btn.setObjectName("themeLightButton")
        self.dark_theme_btn.setObjectName("themeDarkButton")
        for btn in (self.light_theme_btn, self.dark_theme_btn):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_group.addButton(self.light_theme_btn)
        self.theme_group.addButton(self.dark_theme_btn)
        self.light_theme_btn.clicked.connect(lambda: self.set_theme("light"))
        self.dark_theme_btn.clicked.connect(lambda: self.set_theme("dark"))
        theme_box.addWidget(self.light_theme_btn)
        theme_box.addWidget(self.dark_theme_btn)
        header.addLayout(theme_box, 0)

        parent_layout.addLayout(header)

    def _apply_tab_icon(self, index: int, icon_name: str):
        icon_path = Path(__file__).resolve().parent.parent / "resources" / "icons" / f"{icon_name}.svg"
        if icon_path.exists():
            self.tabs.setTabIcon(index, QIcon(str(icon_path)))

    def _sync_theme_buttons(self):
        is_light = self.current_theme == "light"
        self.light_theme_btn.setChecked(is_light)
        self.dark_theme_btn.setChecked(not is_light)

    def set_theme(self, theme: str):
        normalized = apply_theme(self._qt_app(), theme)
        if normalized != self.current_theme:
            self.current_theme = normalized
            self.settings.setValue("theme", normalized)
        self._sync_theme_buttons()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 12, 14, 10)
        root_layout.setSpacing(9)

        self._build_header(root_layout)

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        root_layout.addLayout(body_layout, 1)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().hide()
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setMovable(False)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body_layout.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(self._sync_navigation)

        # 1. Downloading Data: compact region/map + time period + variables/output/download
        download_data_tab = QWidget()
        dd_root = QVBoxLayout(download_data_tab)
        dd_root.setContentsMargins(8, 8, 8, 8)
        dd_root.setSpacing(8)

        # --- Study region: keep the map visually dominant but compact/square.
        region_box = QGroupBox("Study Region")
        rr = QVBoxLayout(region_box)
        rr.setContentsMargins(10, 12, 10, 10)
        rr.setSpacing(6)

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_row.addWidget(QLabel("Define region by:"))
        self.region_source_group = QButtonGroup(self)
        self.region_shp_radio = QRadioButton("Polygon Shapefile")
        self.region_bbox_radio = QRadioButton("Numeric Bounding Box")
        self.region_iho_radio = QRadioButton("Standard IHO Sea")
        self.region_shp_radio.setChecked(True)
        for rb in (self.region_shp_radio, self.region_bbox_radio, self.region_iho_radio):
            self.region_source_group.addButton(rb)
            source_row.addWidget(rb)
        source_row.addStretch(1)
        rr.addLayout(source_row)

        # Shapefile selection
        self.shp_widget = QWidget()
        sg = QGridLayout(self.shp_widget)
        sg.setContentsMargins(0, 2, 0, 2)
        sg.setHorizontalSpacing(8)
        self.shp_edit = QLineEdit()
        self.shp_edit.setPlaceholderText("Select a polygon Shapefile (e.g. GO.shp, AS.shp)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_shapefile)
        sg.addWidget(QLabel("Region Shapefile:"), 0, 0)
        sg.addWidget(self.shp_edit, 0, 1)
        sg.addWidget(browse, 0, 2)
        rr.addWidget(self.shp_widget)

        # Numeric bounding box
        self.bbox_widget = QWidget()
        bg = QGridLayout(self.bbox_widget)
        bg.setContentsMargins(0, 2, 0, 2)
        bg.setHorizontalSpacing(8)
        bg.setVerticalSpacing(4)
        self.bbox_w = QDoubleSpinBox(); self.bbox_w.setRange(-180,180); self.bbox_w.setDecimals(4); self.bbox_w.setSuffix(" °")
        self.bbox_e = QDoubleSpinBox(); self.bbox_e.setRange(-180,180); self.bbox_e.setDecimals(4); self.bbox_e.setSuffix(" °")
        self.bbox_s = QDoubleSpinBox(); self.bbox_s.setRange(-90,90); self.bbox_s.setDecimals(4); self.bbox_s.setSuffix(" °")
        self.bbox_n = QDoubleSpinBox(); self.bbox_n.setRange(-90,90); self.bbox_n.setDecimals(4); self.bbox_n.setSuffix(" °")
        bg.addWidget(QLabel("West longitude:"), 0, 0); bg.addWidget(self.bbox_w, 0, 1)
        bg.addWidget(QLabel("East longitude:"), 0, 2); bg.addWidget(self.bbox_e, 0, 3)
        bg.addWidget(QLabel("South latitude:"), 1, 0); bg.addWidget(self.bbox_s, 1, 1)
        bg.addWidget(QLabel("North latitude:"), 1, 2); bg.addWidget(self.bbox_n, 1, 3)
        self.map_select_btn = QPushButton("Select / Draw on Map…")
        self.map_select_btn.setObjectName("secondaryButton")
        self.map_select_btn.clicked.connect(self.open_region_map_picker)
        bg.addWidget(self.map_select_btn, 2, 0, 1, 2)
        map_hint = QLabel("Optional: draw a rectangle instead of entering coordinates.")
        map_hint.setWordWrap(True); map_hint.setObjectName("fieldHint")
        bg.addWidget(map_hint, 2, 2, 1, 2)
        self.bbox_widget.setVisible(False)
        rr.addWidget(self.bbox_widget)

        # Standard IHO Sea selection
        self.iho_widget = QWidget()
        ig = QGridLayout(self.iho_widget)
        ig.setContentsMargins(0, 2, 0, 2)
        ig.setHorizontalSpacing(8)
        ig.setVerticalSpacing(4)
        self.iho_combo = QComboBox()
        self.iho_combo.setEditable(True)
        self.iho_combo.setInsertPolicy(QComboBox.NoInsert)
        self.iho_combo.setEnabled(True)
        self.iho_combo.setPlaceholderText("Select a standard marine region…")
        self.iho_combo.currentIndexChanged.connect(self.iho_selection_changed)
        ig.addWidget(QLabel("Standard region:"), 0, 0)
        ig.addWidget(self.iho_combo, 0, 1, 1, 3)
        ig.addWidget(QLabel("Source:"), 1, 0)
        source_label = QLabel("Marine Regions — IHO Sea Areas v3 (Flanders Marine Institute, 2018)")
        source_label.setWordWrap(True)
        ig.addWidget(source_label, 1, 1, 1, 3)
        self.iho_status = QLabel("Select a region; its geometry will be retrieved from the official Marine Regions service when needed.")
        self.iho_status.setWordWrap(True)
        ig.addWidget(self.iho_status, 2, 0, 1, 4)
        self.iho_widget.setVisible(False)
        rr.addWidget(self.iho_widget)
        self._iho_catalog = []
        self._iho_fetch_worker = None
        self._iho_catalog_worker = None
        self._iho_fetching = False
        self._iho_catalog_loading = False

        self.region_info = QLabel("No region selected.")
        self.region_info.setWordWrap(True)
        self.region_info.setObjectName("fieldHint")
        rr.addWidget(self.region_info)

        self.region_preview = RegionPreviewWidget()
        self.region_preview.setMinimumHeight(320)
        self.region_preview.setMaximumHeight(335)
        rr.addWidget(self.region_preview, 1)

        self.region_shp_radio.toggled.connect(self.update_region_source_ui)
        self.region_bbox_radio.toggled.connect(self.update_region_source_ui)
        self.region_iho_radio.toggled.connect(self.update_region_source_ui)
        self.bbox_w.valueChanged.connect(self.refresh_bbox_info)
        self.bbox_e.valueChanged.connect(self.refresh_bbox_info)
        self.bbox_s.valueChanged.connect(self.refresh_bbox_info)
        self.bbox_n.valueChanged.connect(self.refresh_bbox_info)

        # --- Compact right-hand control column.
        side_panel = QFrame()
        side_panel.setObjectName("downloadControlPanel")
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(7)

        time_box = QGroupBox("Time Period")
        tg = QFormLayout(time_box)
        tg.setContentsMargins(10, 12, 10, 8)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(QDate(1980, 1, 1))
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(QDate(2026, 12, 31))
        tg.addRow("Start date:", self.start_date)
        tg.addRow("End date:", self.end_date)
        side_layout.addWidget(time_box)

        var_box = QGroupBox("GODAS Variables")
        vv = QVBoxLayout(var_box)
        vv.setContentsMargins(10, 12, 10, 8)
        select_row = QHBoxLayout()
        self.select_all_vars_btn = QPushButton("Select all")
        self.select_all_vars_btn.setObjectName("variableSelectButton")
        self.clear_all_vars_btn = QPushButton("Clear all")
        self.clear_all_vars_btn.setObjectName("variableSelectButton")
        select_row.addWidget(self.select_all_vars_btn)
        select_row.addWidget(self.clear_all_vars_btn)
        select_row.addStretch(1)
        vv.addLayout(select_row)
        select_hint = QLabel("Core 5 selected by default; additional monthly GODAS datasets are optional.")
        select_hint.setObjectName("fieldHint")
        select_hint.setWordWrap(True)
        vv.addWidget(select_hint)
        vg = QGridLayout()
        vg.setHorizontalSpacing(6)
        vg.setVerticalSpacing(5)
        self.vars = {key: QCheckBox(meta["label"]) for key, meta in GODAS_VARIABLES.items()}
        core_defaults = {"temperature", "salinity", "mld", "u_current", "v_current"}
        for i, (key, cb) in enumerate(self.vars.items()):
            cb.setChecked(key in core_defaults)
            vg.addWidget(cb, i // 3, i % 3)
        vv.addLayout(vg)
        self.select_all_vars_btn.clicked.connect(lambda: [cb.setChecked(True) for cb in self.vars.values()])
        self.clear_all_vars_btn.clicked.connect(lambda: [cb.setChecked(False) for cb in self.vars.values()])
        side_layout.addWidget(var_box)

        out_box = QGroupBox("Output Directory")
        og = QHBoxLayout(out_box)
        og.setContentsMargins(10, 10, 10, 8)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Select directory for regional NetCDF files")
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self.browse_output)
        og.addWidget(self.output_edit, 1)
        og.addWidget(out_browse)
        side_layout.addWidget(out_box)

        dl_box = QGroupBox("GODAS Regional Download")
        dl_layout = QVBoxLayout(dl_box)
        dl_layout.setContentsMargins(10, 10, 10, 8)
        buttons = QHBoxLayout()
        self.start_btn = QPushButton("START DOWNLOAD")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self.start_download)
        self.cancel_btn = QPushButton("CANCEL")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_download)
        buttons.addWidget(self.start_btn, 2)
        buttons.addWidget(self.cancel_btn, 1)
        dl_layout.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(18)
        dl_layout.addWidget(self.progress)
        self.status = QLabel("Status: Ready")
        self.status.setWordWrap(True)
        dl_layout.addWidget(self.status)
        side_layout.addWidget(dl_box)
        side_layout.addStretch(1)

        top_download_row = QHBoxLayout()
        top_download_row.setSpacing(10)
        top_download_row.addWidget(region_box, 3)
        top_download_row.addWidget(side_panel, 2)
        dd_root.addLayout(top_download_row, 1)

        self.tabs.addTab(download_data_tab, "1. Download")
        self._apply_tab_icon(self.tabs.count()-1, "download")
        self.tabs.setTabToolTip(self.tabs.count()-1, "Downloading Data")

        # Initialize region-dependent controls only after the download controls have been created.
        self.update_region_source_ui()

        # 2. Data Validation & Standardization: QC + standardized regional products
        validation_tab = QWidget()
        vd_root = QVBoxLayout(validation_tab)
        vd_root.setSpacing(10)

        qc_box = QGroupBox("Quality Control")
        ql = QVBoxLayout(qc_box)
        self.qc_btn = QPushButton("RUN QUALITY CONTROL")
        self.qc_btn.setObjectName("primaryButton")
        self.qc_btn.setMinimumHeight(42)
        self.qc_btn.clicked.connect(self.start_qc)
        ql.addWidget(self.qc_btn)
        ql.addWidget(QLabel(
            "Checks file structure, dimensions, time continuity, coordinates, metadata, "
            "data ranges, NaN/finite values and provenance. Creates CSV + JSON reports."
        ))
        vd_root.addWidget(qc_box)

        std_box = QGroupBox("Data Standardization & Integration")
        sl = QVBoxLayout(std_box)
        self.std_btn = QPushButton("STANDARDIZE & INTEGRATE")
        self.std_btn.setObjectName("primaryButton")
        self.std_btn.setMinimumHeight(42)
        self.std_btn.clicked.connect(self.start_standardization)
        sl.addWidget(self.std_btn)
        sl.addWidget(QLabel(
            "Standardizes coordinates and metadata and creates a native-grid master NetCDF. "
            "Horizontal grids are preserved; no silent regridding is performed."
        ))
        vd_root.addWidget(std_box)

        vd_note = QLabel(
            "Recommended workflow: Download → Quality Control → Standardization & Integration."
        )
        vd_note.setWordWrap(True)
        vd_root.addWidget(vd_note)
        vd_root.addStretch()
        self.tabs.addTab(validation_tab, "2. Validation & Standardization")
        self._apply_tab_icon(self.tabs.count()-1, "validation")
        self.tabs.setTabToolTip(self.tabs.count()-1, "Data Validation & Standardization")

        # 3. Core Scientific Analysis: regional time series, profiles, depth-time
        analysis_tab = QWidget()
        analysis_root = QVBoxLayout(analysis_tab)
        analysis_box = QGroupBox("Core Scientific Analysis")
        ag = QGridLayout(analysis_box)

        ag.addWidget(QLabel("Variable:"), 0, 0)
        self.analysis_var = QComboBox()
        for text, key in self._variable_items():
            self.analysis_var.addItem(text, key)
        ag.addWidget(self.analysis_var, 0, 1)

        ag.addWidget(QLabel("Analysis:"), 0, 2)
        self.analysis_type = QComboBox()
        self.analysis_type.addItem("Regional Time Series", "time_series")
        self.analysis_type.addItem("Mean Vertical Profile", "vertical_profile")
        self.analysis_type.addItem("Depth–Time Section", "depth_time")
        ag.addWidget(self.analysis_type, 0, 3)

        ag.addWidget(QLabel("Start:"), 1, 0)
        self.analysis_start = QDateEdit(); self.analysis_start.setCalendarPopup(True); self.analysis_start.setDate(QDate(1980, 1, 1))
        ag.addWidget(self.analysis_start, 1, 1)
        ag.addWidget(QLabel("End:"), 1, 2)
        self.analysis_end = QDateEdit(); self.analysis_end.setCalendarPopup(True); self.analysis_end.setDate(QDate(2026, 12, 31))
        ag.addWidget(self.analysis_end, 1, 3)

        depth_box = QGroupBox("Depth Selection")
        dg = QGridLayout(depth_box)
        self.depth_group = QButtonGroup(self)
        self.depth_surface = QRadioButton("Surface (shallowest GODAS level)")
        self.depth_single = QRadioButton("Single depth")
        self.depth_range = QRadioButton("Depth range")
        self.depth_full = QRadioButton("Full water column")
        self.depth_surface.setChecked(True)
        for btn in (self.depth_surface, self.depth_single, self.depth_range, self.depth_full): self.depth_group.addButton(btn)
        dg.addWidget(self.depth_surface, 0, 0, 1, 2)
        dg.addWidget(self.depth_single, 1, 0); dg.addWidget(QLabel("Target (m):"), 1, 1)
        self.single_depth_edit = QLineEdit(); self.single_depth_edit.setPlaceholderText("e.g. 50"); self.single_depth_edit.setEnabled(False); dg.addWidget(self.single_depth_edit, 1, 2)
        dg.addWidget(self.depth_range, 2, 0); dg.addWidget(QLabel("Min (m):"), 2, 1)
        self.depth_min_edit = QLineEdit(); self.depth_min_edit.setPlaceholderText("e.g. 10"); self.depth_min_edit.setEnabled(False); dg.addWidget(self.depth_min_edit, 2, 2)
        dg.addWidget(QLabel("Max (m):"), 2, 3)
        self.depth_max_edit = QLineEdit(); self.depth_max_edit.setPlaceholderText("e.g. 100"); self.depth_max_edit.setEnabled(False); dg.addWidget(self.depth_max_edit, 2, 4)
        dg.addWidget(self.depth_full, 3, 0)
        analysis_root.addWidget(depth_box)

        self.analysis_var.currentIndexChanged.connect(self.update_analysis_controls)
        self.analysis_type.currentIndexChanged.connect(self.update_analysis_controls)
        for btn in (self.depth_surface, self.depth_single, self.depth_range, self.depth_full): btn.toggled.connect(self.update_analysis_controls)

        self.analysis_btn = QPushButton("RUN CORE SCIENTIFIC ANALYSIS")
        self.analysis_btn.setObjectName("primaryButton"); self.analysis_btn.setMinimumHeight(42); self.analysis_btn.clicked.connect(self.start_analysis)
        ag.addWidget(self.analysis_btn, 3, 0, 1, 2)
        ag.addWidget(QLabel("Outputs: CSV + 300-dpi PNG + JSON report in analysis/"), 3, 2, 1, 2)
        analysis_root.addWidget(analysis_box)

        # Output Units is deliberately the final control in this tab.
        unit_box = QGroupBox("Output Units")
        ug = QHBoxLayout(unit_box)
        self.unit_combo = QComboBox()
        ug.addWidget(QLabel("Unit:")); ug.addWidget(self.unit_combo); ug.addStretch()
        analysis_root.addWidget(unit_box)
        analysis_root.addStretch()
        self.update_analysis_controls()
        self.tabs.addTab(analysis_tab, "3. Core Analysis")
        self._apply_tab_icon(self.tabs.count()-1, "analysis")
        self.tabs.setTabToolTip(self.tabs.count()-1, "Core Scientific Analysis")

        # 4. Climatology & Anomaly: self-contained v2 scientific products
        product_tab = QWidget()
        product_root = QVBoxLayout(product_tab)

        # Keep the same visual order as Core Scientific Analysis:
        # Depth Selection -> Output Units -> Climatology & Anomaly controls.
        pdepth_box = QGroupBox("Depth Selection")
        pdg = QGridLayout(pdepth_box)
        self.product_depth_group = QButtonGroup(self)
        self.product_depth_surface = QRadioButton("Surface (shallowest GODAS level)")
        self.product_depth_single = QRadioButton("Single depth")
        self.product_depth_range = QRadioButton("Depth range")
        self.product_depth_full = QRadioButton("Full water column")
        self.product_depth_surface.setChecked(True)
        for btn in (self.product_depth_surface, self.product_depth_single, self.product_depth_range, self.product_depth_full): self.product_depth_group.addButton(btn)
        pdg.addWidget(self.product_depth_surface, 0, 0, 1, 2)
        pdg.addWidget(self.product_depth_single, 1, 0); pdg.addWidget(QLabel("Target (m):"), 1, 1)
        self.product_single_depth_edit = QLineEdit(); self.product_single_depth_edit.setPlaceholderText("e.g. 50"); self.product_single_depth_edit.setEnabled(False); pdg.addWidget(self.product_single_depth_edit, 1, 2)
        pdg.addWidget(self.product_depth_range, 2, 0); pdg.addWidget(QLabel("Min (m):"), 2, 1)
        self.product_depth_min_edit = QLineEdit(); self.product_depth_min_edit.setPlaceholderText("e.g. 10"); self.product_depth_min_edit.setEnabled(False); pdg.addWidget(self.product_depth_min_edit, 2, 2)
        pdg.addWidget(QLabel("Max (m):"), 2, 3)
        self.product_depth_max_edit = QLineEdit(); self.product_depth_max_edit.setPlaceholderText("e.g. 100"); self.product_depth_max_edit.setEnabled(False); pdg.addWidget(self.product_depth_max_edit, 2, 4)
        pdg.addWidget(self.product_depth_full, 3, 0)
        product_root.addWidget(pdepth_box)

        product_box = QGroupBox("Climatology & Anomaly")
        pg = QGridLayout(product_box)

        pg.addWidget(QLabel("Variable:"), 0, 0)
        self.product_var = QComboBox()
        for text, key in self._variable_items():
            self.product_var.addItem(text, key)
        pg.addWidget(self.product_var, 0, 1)

        pg.addWidget(QLabel("Product:"), 0, 2)
        self.product_type = QComboBox(); self.product_type.addItem("Climatology", "climatology"); self.product_type.addItem("Anomaly", "anomaly"); pg.addWidget(self.product_type, 0, 3)

        pg.addWidget(QLabel("Period:"), 1, 0)
        self.product_mode = QComboBox(); pg.addWidget(self.product_mode, 1, 1)

        # Baseline is required for both climatology and anomaly.
        self.baseline_start_label = QLabel("Baseline start:"); pg.addWidget(self.baseline_start_label, 2, 0)
        self.baseline_start = QDateEdit(); self.baseline_start.setCalendarPopup(True); self.baseline_start.setDate(QDate(1980,1,1)); pg.addWidget(self.baseline_start, 2, 1)
        self.baseline_end_label = QLabel("Baseline end:"); pg.addWidget(self.baseline_end_label, 2, 2)
        self.baseline_end = QDateEdit(); self.baseline_end.setCalendarPopup(True); self.baseline_end.setDate(QDate(2026,12,31)); pg.addWidget(self.baseline_end, 2, 3)

        self.anom_start_label = QLabel("Anomaly period start:"); pg.addWidget(self.anom_start_label, 3, 0)
        self.anom_start = QDateEdit(); self.anom_start.setCalendarPopup(True); self.anom_start.setDate(QDate(1980,1,1)); pg.addWidget(self.anom_start, 3, 1)
        self.anom_end_label = QLabel("Anomaly period end:"); pg.addWidget(self.anom_end_label, 3, 2)
        self.anom_end = QDateEdit(); self.anom_end.setCalendarPopup(True); self.anom_end.setDate(QDate(2026,12,31)); pg.addWidget(self.anom_end, 3, 3)

        product_root.addWidget(product_box)

        # Output Units is deliberately the final control in this tab.
        punit_box = QGroupBox("Output Units")
        pug = QHBoxLayout(punit_box)
        self.product_unit_combo = QComboBox()
        pug.addWidget(QLabel("Unit:")); pug.addWidget(self.product_unit_combo); pug.addStretch()
        product_root.addWidget(punit_box)

        self.product_btn = QPushButton("RUN CLIMATOLOGY")
        self.product_btn.setObjectName("primaryButton"); self.product_btn.setMinimumHeight(42); self.product_btn.clicked.connect(self.start_scientific_product)
        product_root.addWidget(self.product_btn)
        self.product_note = QLabel(); self.product_note.setWordWrap(True); product_root.addWidget(self.product_note)

        self.product_type.currentIndexChanged.connect(self.update_product_controls)
        self.product_var.currentIndexChanged.connect(self.update_product_controls)
        self.product_mode.currentIndexChanged.connect(self.update_product_controls)
        for btn in (self.product_depth_surface, self.product_depth_single, self.product_depth_range, self.product_depth_full): btn.toggled.connect(self.update_product_controls)
        self.update_product_controls()
        product_root.addStretch()
        self.tabs.addTab(product_tab, "4. Climatology & Anomaly")
        self._apply_tab_icon(self.tabs.count()-1, "climatology")

        # 5. Trend Analysis
        trend_tab = QWidget()
        trend_root = QVBoxLayout(trend_tab)
        trend_root.setSpacing(8)

        tdepth_box = QGroupBox("Depth Selection")
        tdg = QGridLayout(tdepth_box)
        self.trend_depth_group = QButtonGroup(self)
        self.trend_depth_surface = QRadioButton("Surface (shallowest GODAS level)")
        self.trend_depth_single = QRadioButton("Single depth")
        self.trend_depth_range = QRadioButton("Depth range")
        self.trend_depth_full = QRadioButton("Full water column")
        self.trend_depth_surface.setChecked(True)
        for btn in (self.trend_depth_surface, self.trend_depth_single, self.trend_depth_range, self.trend_depth_full):
            self.trend_depth_group.addButton(btn)
        tdg.addWidget(self.trend_depth_surface, 0, 0, 1, 2)
        tdg.addWidget(self.trend_depth_single, 1, 0); tdg.addWidget(QLabel("Target (m):"), 1, 1)
        self.trend_single_depth_edit = QLineEdit(); self.trend_single_depth_edit.setPlaceholderText("e.g. 50"); self.trend_single_depth_edit.setEnabled(False); tdg.addWidget(self.trend_single_depth_edit, 1, 2)
        tdg.addWidget(self.trend_depth_range, 2, 0); tdg.addWidget(QLabel("Min (m):"), 2, 1)
        self.trend_depth_min_edit = QLineEdit(); self.trend_depth_min_edit.setPlaceholderText("e.g. 10"); self.trend_depth_min_edit.setEnabled(False); tdg.addWidget(self.trend_depth_min_edit, 2, 2)
        tdg.addWidget(QLabel("Max (m):"), 2, 3)
        self.trend_depth_max_edit = QLineEdit(); self.trend_depth_max_edit.setPlaceholderText("e.g. 100"); self.trend_depth_max_edit.setEnabled(False); tdg.addWidget(self.trend_depth_max_edit, 2, 4)
        tdg.addWidget(self.trend_depth_full, 3, 0)
        trend_root.addWidget(tdepth_box)

        trend_box = QGroupBox("Trend Analysis")
        tg2 = QGridLayout(trend_box)
        tg2.addWidget(QLabel("Variable:"), 0, 0)
        self.trend_var = QComboBox()
        for text, key in self._variable_items():
            self.trend_var.addItem(text, key)
        tg2.addWidget(self.trend_var, 0, 1)
        tg2.addWidget(QLabel("Trend Type:"), 0, 2)
        self.trend_type = QComboBox()
        self.trend_type.addItem("Monthly", "monthly"); self.trend_type.addItem("Seasonal (DJF/MAM/JJA/SON)", "seasonal"); self.trend_type.addItem("Annual", "annual")
        tg2.addWidget(self.trend_type, 0, 3)
        tg2.addWidget(QLabel("Method:"), 1, 0)
        self.trend_method = QComboBox()
        self.trend_method.addItem("All Methods", "all"); self.trend_method.addItem("OLS", "ols"); self.trend_method.addItem("Mann–Kendall", "mk"); self.trend_method.addItem("Sen's Slope", "sen")
        tg2.addWidget(self.trend_method, 1, 1)
        tg2.addWidget(QLabel("Start:"), 1, 2)
        self.trend_start = QDateEdit(); self.trend_start.setCalendarPopup(True); self.trend_start.setDate(QDate(1980, 1, 1)); tg2.addWidget(self.trend_start, 1, 3)
        tg2.addWidget(QLabel("End:"), 2, 0)
        self.trend_end = QDateEdit(); self.trend_end.setCalendarPopup(True); self.trend_end.setDate(QDate(2026, 12, 31)); tg2.addWidget(self.trend_end, 2, 1)
        tg2.addWidget(QLabel("Significance level:"), 2, 2)
        alpha_label = QLabel("α = 0.05 (fixed)"); alpha_label.setToolTip(f"v{SOFTWARE_VERSION} uses a fixed significance level of 0.05."); tg2.addWidget(alpha_label, 2, 3)
        self.trend_note = QLabel("Monthly trend uses all valid monthly observations. Annual observations require all 12 months; seasonal observations require all 3 months. No interpolation or autocorrelation correction is applied.")
        self.trend_note.setWordWrap(True); tg2.addWidget(self.trend_note, 3, 0, 1, 4)
        trend_root.addWidget(trend_box)

        # Output Units is deliberately the final settings control in this tab.
        trend_unit_box = QGroupBox("Output Units")
        tug = QHBoxLayout(trend_unit_box)
        self.trend_unit_combo = QComboBox(); tug.addWidget(QLabel("Unit:")); tug.addWidget(self.trend_unit_combo); tug.addStretch()
        trend_root.addWidget(trend_unit_box)

        self.trend_btn = QPushButton("RUN TREND ANALYSIS")
        self.trend_btn.setObjectName("primaryButton"); self.trend_btn.setMinimumHeight(42); self.trend_btn.clicked.connect(self.start_trend)
        trend_root.addWidget(self.trend_btn)
        trend_root.addWidget(QLabel("Outputs: series CSV + trend-statistics CSV + 300-dpi PNG + JSON report in analysis/trend/"))
        trend_root.addStretch()

        self.trend_var.currentIndexChanged.connect(self.update_trend_controls)
        self.trend_type.currentIndexChanged.connect(self.update_trend_controls)
        for btn in (self.trend_depth_surface, self.trend_depth_single, self.trend_depth_range, self.trend_depth_full):
            btn.toggled.connect(self.update_trend_controls)
        self.update_trend_controls()
        self.tabs.addTab(trend_tab, "5. Trend Analysis")
        self._apply_tab_icon(self.tabs.count()-1, "trend")

        # 6. Spatial Visualization — Map Composer foundation.
        spatial_tab = QWidget()
        spatial_root = QVBoxLayout(spatial_tab)
        spatial_root.setContentsMargins(8, 8, 8, 8)
        spatial_root.setSpacing(7)

        intro = QLabel(
            "Create publication-ready native-grid maps from Data, Climatology, Anomaly, or Trend products. "
            "Only controls relevant to the selected product are shown. No interpolation, regridding, extrapolation, or gap filling is applied."
        )
        intro.setWordWrap(True)
        intro.setObjectName("sectionCaption")
        spatial_root.addWidget(intro)

        product_setup = QGroupBox("Map Product")
        pg = QGridLayout(product_setup)
        pg.setContentsMargins(12, 12, 12, 12)
        pg.setHorizontalSpacing(12)
        pg.setVerticalSpacing(9)
        pg.setColumnStretch(1, 1)
        pg.setColumnStretch(3, 1)
        pg.addWidget(QLabel("Product:"), 0, 0)
        self.spatial_product = QComboBox()
        self.spatial_product.addItem("Data Map", "data_map")
        self.spatial_product.addItem("Climatology Map", "climatology_map")
        self.spatial_product.addItem("Anomaly Map", "anomaly_map")
        self.spatial_product.addItem("Trend Map", "trend_map")
        pg.addWidget(self.spatial_product, 0, 1)
        pg.addWidget(QLabel("Variable:"), 0, 2)
        self.spatial_var = QComboBox()
        for text, key in self._variable_items():
            self.spatial_var.addItem(text, key)
        pg.addWidget(self.spatial_var, 0, 3)
        pg.addWidget(QLabel("Output units:"), 1, 0)
        self.spatial_unit_combo = QComboBox()
        pg.addWidget(self.spatial_unit_combo, 1, 1)
        pg.addWidget(QLabel("Product status:"), 1, 2)
        self.spatial_product_hint = QLabel("Data Map: a monthly native-grid field or three-depth comparison.")
        self.spatial_product_hint.setWordWrap(True)
        self.spatial_product_hint.setObjectName("fieldHint")
        pg.addWidget(self.spatial_product_hint, 1, 3)

        self.spatial_data_setup = QGroupBox("Data Map Setup")
        dg = QGridLayout(self.spatial_data_setup)
        dg.setContentsMargins(12, 12, 12, 12)
        dg.setHorizontalSpacing(12)
        dg.setVerticalSpacing(9)
        dg.setColumnStretch(1, 1)
        dg.setColumnStretch(3, 1)
        dg.addWidget(QLabel("Layout:"), 0, 0)
        self.spatial_layout = QComboBox()
        self.spatial_layout.addItem("Single map", "single")
        self.spatial_layout.addItem("Three-depth comparison", "three_depths")
        dg.addWidget(self.spatial_layout, 0, 1)
        dg.addWidget(QLabel("Month:"), 0, 2)
        self.spatial_date = QDateEdit()
        self.spatial_date.setCalendarPopup(True)
        self.spatial_date.setDisplayFormat("MMM yyyy")
        self.spatial_date.setDate(QDate(2025, 7, 1))
        dg.addWidget(self.spatial_date, 0, 3)
        self.spatial_refresh_btn = QPushButton("Refresh source")
        self.spatial_refresh_btn.setObjectName("secondaryButton")
        dg.addWidget(self.spatial_refresh_btn, 1, 3)
        self.spatial_source_info = QLabel("Select an output directory containing standardized GODAS files.")
        self.spatial_source_info.setWordWrap(True)
        self.spatial_source_info.setObjectName("fieldHint")
        dg.addWidget(self.spatial_source_info, 1, 0, 1, 3)

        self.spatial_clim_setup = QGroupBox("Climatology Setup")
        cg = QGridLayout(self.spatial_clim_setup)
        cg.setContentsMargins(12, 12, 12, 12)
        cg.setHorizontalSpacing(12)
        cg.setVerticalSpacing(9)
        cg.setColumnStretch(1, 1); cg.setColumnStretch(3, 1)
        cg.addWidget(QLabel("Baseline start:"), 0, 0)
        self.spatial_baseline_start = QDateEdit(); self.spatial_baseline_start.setCalendarPopup(True); self.spatial_baseline_start.setDate(QDate(1980,1,1)); cg.addWidget(self.spatial_baseline_start, 0, 1)
        cg.addWidget(QLabel("Baseline end:"), 0, 2)
        self.spatial_baseline_end = QDateEdit(); self.spatial_baseline_end.setCalendarPopup(True); self.spatial_baseline_end.setDate(QDate(2026,12,31)); cg.addWidget(self.spatial_baseline_end, 0, 3)
        cg.addWidget(QLabel("Climatology period:"), 1, 0)
        self.spatial_clim_mode = QComboBox(); self.spatial_clim_mode.addItem("Monthly", "monthly"); self.spatial_clim_mode.addItem("Seasonal", "seasonal"); self.spatial_clim_mode.addItem("Annual", "annual"); cg.addWidget(self.spatial_clim_mode, 1, 1)
        self.spatial_clim_period_label = QLabel("Period:")
        cg.addWidget(self.spatial_clim_period_label, 1, 2)
        self.spatial_clim_month = QComboBox()
        for m in range(1,13): self.spatial_clim_month.addItem(pd.Timestamp(2000,m,1).strftime("%B"), m)
        cg.addWidget(self.spatial_clim_month, 1, 3)
        self.spatial_clim_season = QComboBox();
        for sname in ("DJF","MAM","JJA","SON"): self.spatial_clim_season.addItem(sname, sname)
        cg.addWidget(self.spatial_clim_season, 1, 3)

        self.spatial_anom_setup = QGroupBox("Anomaly Setup")
        ag = QGridLayout(self.spatial_anom_setup)
        ag.setContentsMargins(12, 12, 12, 12); ag.setHorizontalSpacing(12); ag.setVerticalSpacing(9)
        ag.setColumnStretch(1, 1); ag.setColumnStretch(3, 1)
        ag.addWidget(QLabel("Baseline start:"), 0, 0)
        self.spatial_anom_baseline_start = QDateEdit(); self.spatial_anom_baseline_start.setCalendarPopup(True); self.spatial_anom_baseline_start.setDate(QDate(1980,1,1)); ag.addWidget(self.spatial_anom_baseline_start, 0, 1)
        ag.addWidget(QLabel("Baseline end:"), 0, 2)
        self.spatial_anom_baseline_end = QDateEdit(); self.spatial_anom_baseline_end.setCalendarPopup(True); self.spatial_anom_baseline_end.setDate(QDate(2026,12,31)); ag.addWidget(self.spatial_anom_baseline_end, 0, 3)
        ag.addWidget(QLabel("Anomaly period:"), 1, 0)
        self.spatial_anom_mode = QComboBox(); self.spatial_anom_mode.addItem("Monthly", "monthly"); self.spatial_anom_mode.addItem("Seasonal", "seasonal"); self.spatial_anom_mode.addItem("Annual", "annual"); ag.addWidget(self.spatial_anom_mode, 1, 1)
        self.spatial_anom_target_month_label = QLabel("Target month:")
        ag.addWidget(self.spatial_anom_target_month_label, 1, 2)
        self.spatial_anom_target_date = QDateEdit(); self.spatial_anom_target_date.setCalendarPopup(True); self.spatial_anom_target_date.setDisplayFormat("MMM yyyy"); self.spatial_anom_target_date.setDate(QDate(2025,7,1)); ag.addWidget(self.spatial_anom_target_date, 1, 3)
        self.spatial_anom_season_label = QLabel("Target season:")
        ag.addWidget(self.spatial_anom_season_label, 2, 0)
        self.spatial_anom_season = QComboBox();
        for sname in ("DJF","MAM","JJA","SON"): self.spatial_anom_season.addItem(sname, sname)
        ag.addWidget(self.spatial_anom_season, 2, 1)
        self.spatial_anom_year_label = QLabel("Target season year:")
        ag.addWidget(self.spatial_anom_year_label, 2, 2)
        self.spatial_anom_year = QSpinBox(); self.spatial_anom_year.setRange(1900, 2100); self.spatial_anom_year.setValue(2025); ag.addWidget(self.spatial_anom_year, 2, 3)
        self.spatial_anom_annual_year_label = QLabel("Target year:")
        ag.addWidget(self.spatial_anom_annual_year_label, 3, 0)
        self.spatial_anom_annual_year = QSpinBox(); self.spatial_anom_annual_year.setRange(1900, 2100); self.spatial_anom_annual_year.setValue(2025); ag.addWidget(self.spatial_anom_annual_year, 3, 1)

        self.spatial_trend_setup = QGroupBox("Trend Map Setup")
        tg = QGridLayout(self.spatial_trend_setup)
        tg.setContentsMargins(12,12,12,12); tg.setHorizontalSpacing(12); tg.setVerticalSpacing(9)
        tg.setColumnStretch(1,1); tg.setColumnStretch(3,1)
        tg.addWidget(QLabel("Start:"), 0, 0)
        self.spatial_trend_start = QDateEdit(); self.spatial_trend_start.setCalendarPopup(True); self.spatial_trend_start.setDate(QDate(1980,1,1)); tg.addWidget(self.spatial_trend_start,0,1)
        tg.addWidget(QLabel("End:"),0,2)
        self.spatial_trend_end = QDateEdit(); self.spatial_trend_end.setCalendarPopup(True); self.spatial_trend_end.setDate(QDate(2026,12,31)); tg.addWidget(self.spatial_trend_end,0,3)
        tg.addWidget(QLabel("Trend type:"),1,0)
        self.spatial_trend_mode = QComboBox(); self.spatial_trend_mode.addItem("Monthly","monthly"); self.spatial_trend_mode.addItem("Seasonal","seasonal"); self.spatial_trend_mode.addItem("Annual","annual"); self.spatial_trend_mode.setCurrentIndex(2); tg.addWidget(self.spatial_trend_mode,1,1)
        tg.addWidget(QLabel("Method:"),1,2)
        self.spatial_trend_method = QComboBox(); self.spatial_trend_method.addItem("OLS slope","ols"); self.spatial_trend_method.addItem("Mann–Kendall tau","mk"); self.spatial_trend_method.addItem("Sen's slope","sen"); tg.addWidget(self.spatial_trend_method,1,3)
        self.spatial_trend_season_label = QLabel("Season:")
        tg.addWidget(self.spatial_trend_season_label,2,0)
        self.spatial_trend_season = QComboBox();
        for sname in ("DJF","MAM","JJA","SON"): self.spatial_trend_season.addItem(sname,sname)
        self.spatial_trend_season.setCurrentIndex(2)
        tg.addWidget(self.spatial_trend_season,2,1)
        self.spatial_trend_hint = QLabel("Trend is computed independently at each native-grid cell; no spatial averaging is performed. Minimum n = 3. No autocorrelation correction.")
        self.spatial_trend_hint.setWordWrap(True); self.spatial_trend_hint.setObjectName("fieldHint"); tg.addWidget(self.spatial_trend_hint,3,0,1,4)

        self.spatial_depth_setup = QGroupBox("Depth Selection")
        sg = QGridLayout(self.spatial_depth_setup)
        sg.setContentsMargins(12,12,12,12); sg.setHorizontalSpacing(12); sg.setVerticalSpacing(9)
        sg.setColumnStretch(1,1); sg.setColumnStretch(3,1)
        self.spatial_single_mode_label = QLabel("Depth:"); sg.addWidget(self.spatial_single_mode_label,0,0)
        self.spatial_single_mode = QComboBox(); self.spatial_single_mode.addItem("Surface (shallowest native level)","surface"); self.spatial_single_mode.addItem("Single native depth","single"); self.spatial_single_mode.addItem("Deepest valid native level","deepest"); sg.addWidget(self.spatial_single_mode,0,1,1,3)
        self.spatial_single_depth_label = QLabel("Target depth:"); sg.addWidget(self.spatial_single_depth_label,1,0)
        self.spatial_single_depth = QComboBox(); self.spatial_single_depth.setMinimumContentsLength(10); self.spatial_single_depth.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents); sg.addWidget(self.spatial_single_depth,1,1,1,3)
        self.spatial_three_row = QWidget()
        tr = QGridLayout(self.spatial_three_row); tr.setContentsMargins(0,0,0,0); tr.setHorizontalSpacing(12); tr.setVerticalSpacing(8)
        tr.setColumnStretch(1,1); tr.setColumnStretch(3,1)
        tr.addWidget(QLabel("Surface:"),0,0); self.spatial_surface_value=QLabel("—"); self.spatial_surface_value.setObjectName("fieldValue"); tr.addWidget(self.spatial_surface_value,0,1)
        tr.addWidget(QLabel("Middle depth:"),0,2); self.spatial_middle_depth=QComboBox(); self.spatial_middle_depth.setMinimumContentsLength(10); tr.addWidget(self.spatial_middle_depth,0,3)
        tr.addWidget(QLabel("Deepest valid:"),1,0); self.spatial_deepest_value=QLabel("—"); self.spatial_deepest_value.setObjectName("fieldValue"); tr.addWidget(self.spatial_deepest_value,1,1)
        note3=QLabel("Surface and deepest levels are determined automatically for the selected month."); note3.setWordWrap(True); note3.setObjectName("fieldHint"); tr.addWidget(note3,1,2,1,2)
        sg.addWidget(self.spatial_three_row,2,0,1,4)
        self.spatial_depth_note=QLabel("Only native GODAS depth levels with finite data are offered. No arbitrary depths or vertical interpolation are used."); self.spatial_depth_note.setWordWrap(True); self.spatial_depth_note.setObjectName("fieldHint"); sg.addWidget(self.spatial_depth_note,3,0,1,4)

        style_setup = QGroupBox("Map Appearance")
        stg = QGridLayout(style_setup); stg.setContentsMargins(12,12,12,12); stg.setHorizontalSpacing(12); stg.setVerticalSpacing(9); stg.setColumnStretch(1,1); stg.setColumnStretch(3,1)
        stg.addWidget(QLabel("Colormap:"),0,0); self.spatial_cmap=QComboBox();
        for name in ("turbo","viridis","plasma","cividis","coolwarm"): self.spatial_cmap.addItem(name,name)
        stg.addWidget(self.spatial_cmap,0,1)
        stg.addWidget(QLabel("Color scale:"),0,2); self.spatial_color_mode=QComboBox(); self.spatial_color_mode.addItem("Automatic","auto"); self.spatial_color_mode.addItem("Fixed minimum / maximum","fixed"); stg.addWidget(self.spatial_color_mode,0,3)
        self.spatial_min_row_label=QLabel("Minimum:"); self.spatial_vmin=QDoubleSpinBox(); self.spatial_vmin.setRange(-1e9,1e9); self.spatial_vmin.setDecimals(4); self.spatial_max_row_label=QLabel("Maximum:"); self.spatial_vmax=QDoubleSpinBox(); self.spatial_vmax.setRange(-1e9,1e9); self.spatial_vmax.setDecimals(4)
        stg.addWidget(self.spatial_min_row_label,1,0); stg.addWidget(self.spatial_vmin,1,1); stg.addWidget(self.spatial_max_row_label,1,2); stg.addWidget(self.spatial_vmax,1,3)
        self.spatial_region_info=QLabel("Study-region boundary and map extent follow the selected study region."); self.spatial_region_info.setObjectName("fieldHint"); self.spatial_region_info.setWordWrap(True); stg.addWidget(self.spatial_region_info,2,0,1,4)

        export_setup = QGroupBox("Export")
        eg=QGridLayout(export_setup); eg.setContentsMargins(12,12,12,12); eg.setHorizontalSpacing(12); eg.setVerticalSpacing(9); eg.setColumnStretch(1,1); eg.setColumnStretch(2,1); eg.setColumnStretch(3,1)
        eg.addWidget(QLabel("Export directory:"),0,0); self.spatial_export_dir=QLineEdit(); self.spatial_export_dir.setPlaceholderText("Leave empty to use analysis/spatial_visualization"); eg.addWidget(self.spatial_export_dir,0,1,1,3)
        self.spatial_export_browse=QPushButton("Browse…"); self.spatial_export_browse.setObjectName("secondaryButton"); self.spatial_export_browse.clicked.connect(self.browse_spatial_export_dir); eg.addWidget(self.spatial_export_browse,0,4)
        self.spatial_png=QCheckBox("PNG (300 dpi)"); self.spatial_png.setChecked(True); self.spatial_svg=QCheckBox("SVG (vector)"); self.spatial_svg.setChecked(True); self.spatial_pdf=QCheckBox("PDF (vector)"); self.spatial_pdf.setChecked(True)
        eg.addWidget(self.spatial_png,1,0); eg.addWidget(self.spatial_svg,1,1); eg.addWidget(self.spatial_pdf,1,2)
        self.spatial_btn=QPushButton("GENERATE MAP"); self.spatial_btn.setObjectName("primaryButton"); self.spatial_btn.setMinimumHeight(42); self.spatial_btn.clicked.connect(self.start_spatial_visualization); eg.addWidget(self.spatial_btn,1,3,1,2)

        # Compact two-row composer layout: product-specific controls share a row,
        # then depth and appearance share a row. Hidden product panels collapse naturally.
        spatial_row_1 = QHBoxLayout()
        spatial_row_1.setSpacing(8)
        spatial_row_1.addWidget(product_setup, 1)
        for _panel in (self.spatial_data_setup, self.spatial_clim_setup, self.spatial_anom_setup, self.spatial_trend_setup):
            spatial_row_1.addWidget(_panel, 1)
        spatial_root.addLayout(spatial_row_1)

        spatial_row_2 = QHBoxLayout()
        spatial_row_2.setSpacing(8)
        spatial_row_2.addWidget(self.spatial_depth_setup, 1)
        spatial_row_2.addWidget(style_setup, 1)
        spatial_root.addLayout(spatial_row_2)

        spatial_root.addWidget(export_setup)
        self.spatial_note=QLabel(); self.spatial_note.setWordWrap(True); self.spatial_note.setObjectName("fieldHint"); spatial_root.addWidget(self.spatial_note)
        spatial_root.addStretch(1)
        self.tabs.addTab(spatial_tab,"6. Spatial Visualization"); self._apply_tab_icon(self.tabs.count()-1,"map")

        for w in (self.spatial_product, self.spatial_var, self.spatial_layout, self.spatial_single_mode, self.spatial_clim_mode, self.spatial_anom_mode, self.spatial_trend_mode, self.spatial_trend_method, self.spatial_trend_season, self.spatial_color_mode, self.spatial_unit_combo):
            w.currentIndexChanged.connect(self.update_spatial_controls)
        for w in (self.spatial_date, self.spatial_clim_month, self.spatial_clim_season, self.spatial_anom_season):
            try: w.currentIndexChanged.connect(self.update_spatial_controls)
            except AttributeError: pass
        self.spatial_refresh_btn.clicked.connect(self.refresh_spatial_source)
        self.output_edit.editingFinished.connect(self.refresh_spatial_source)
        self.spatial_date.dateChanged.connect(lambda _=None: self.refresh_spatial_source())
        self.spatial_anom_target_date.dateChanged.connect(self.update_spatial_controls)
        self.update_spatial_controls()
        self.refresh_spatial_source(update_message_only=False)

        # The tab content remains the functional page model, but each page is wrapped
        # in a vertical scroll area so compact/non-maximized windows never clip controls.
        self._wrap_tab_pages_in_scroll_areas()
        self._build_navigation(body_layout)

        # Collapsible processing log + compact global processing indicator.
        self.log_panel = QFrame()
        self.log_panel.setObjectName("logPanel")
        lp = QVBoxLayout(self.log_panel)
        lp.setContentsMargins(8, 6, 8, 6)
        log_title = QLabel("Processing Log")
        log_title.setObjectName("logPanelTitle")
        lp.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        lp.addWidget(self.log)
        self.log_panel.setVisible(False)
        root_layout.addWidget(self.log_panel)

        bottom_bar = QHBoxLayout()
        self.process_indicator = QProgressBar()
        self.process_indicator.setObjectName("processIndicator")
        self.process_indicator.setMinimumWidth(260)
        self.process_indicator.setMaximumWidth(520)
        self.process_indicator.setRange(0, 100)
        self.process_indicator.setValue(0)
        self.process_indicator.setTextVisible(True)
        self.process_indicator.setFormat("Ready")
        bottom_bar.addWidget(self.process_indicator, 1)
        self.process_status = QLabel("Ready")
        self.process_status.setObjectName("processStatus")
        bottom_bar.addWidget(self.process_status)
        bottom_bar.addStretch(1)
        self.log_toggle_btn = QPushButton("⌃")
        self.log_toggle_btn.setObjectName("logToggleButton")
        self.log_toggle_btn.setToolTip("Show processing log")
        self.log_toggle_btn.setFixedSize(34, 26)
        self.log_toggle_btn.clicked.connect(self.toggle_processing_log)
        bottom_bar.addWidget(self.log_toggle_btn, 0, Qt.AlignmentFlag.AlignRight)
        root_layout.addLayout(bottom_bar)

    def toggle_processing_log(self):
        visible = not self.log_panel.isVisible()
        self.log_panel.setVisible(visible)
        self.log_toggle_btn.setText("⌄" if visible else "⌃")
        self.log_toggle_btn.setToolTip("Hide processing log" if visible else "Show processing log")

    def _process_started(self, text, determinate=False):
        self.process_status.setText(text)
        if determinate:
            self.process_indicator.setRange(0, 100)
            self.process_indicator.setValue(0)
            self.process_indicator.setFormat(f"{text} 0%")
        else:
            self.process_indicator.setRange(0, 0)
            self.process_indicator.setFormat(text)

    def _set_processing_progress(self, value):
        if self.process_indicator.minimum() == 0 and self.process_indicator.maximum() == 0:
            self.process_indicator.setRange(0, 100)
        value = max(0, min(100, int(value)))
        self.process_indicator.setValue(value)
        self.process_indicator.setFormat(f"Processing… {value}%")

    def _process_finished(self, message="Process completed", success=True):
        self.process_indicator.setRange(0, 100)
        self.process_indicator.setValue(100 if success else 0)
        text = f"✓ {message}" if success else f"✕ {message}"
        self.process_indicator.setFormat(text)
        self.process_status.setText(message)
        QTimer.singleShot(4500, self._reset_processing_indicator)

    def _reset_processing_indicator(self):
        if getattr(self, "process_indicator", None) is None:
            return
        self.process_indicator.setRange(0, 100)
        self.process_indicator.setValue(0)
        self.process_indicator.setFormat("Ready")
        self.process_status.setText("Ready")

    def _apply_map_selected_bbox(self, west, east, south, north):
        """Apply a rectangle selected in MapControls to the Numeric Bounding Box workflow."""
        west, east, south, north = map(float, (west, east, south, north))
        spec = make_bbox_region(west, east, south, north)
        check = validate_region_for_godas(spec)

        # The Numeric Bounding Box controls are the visible UI representation of
        # the authoritative selected region. Update them atomically so no stale
        # value can survive from the previous rectangle.
        for widget, value in (
            (self.bbox_w, west),
            (self.bbox_e, east),
            (self.bbox_s, south),
            (self.bbox_n, north),
        ):
            widget.blockSignals(True)
            try:
                widget.setValue(value)
            finally:
                widget.blockSignals(False)

        # Keep the selected RegionSpec authoritative even though its source is
        # a numeric bounding box. Manual edits to the spin boxes will continue
        # to rebuild this spec through refresh_bbox_info().
        self._region_spec = spec
        self._update_region_preview()
        if hasattr(self, "spatial_boundary"):
            self.spatial_boundary.setEnabled(True)

        warn = f" | WARNING: {check['warning']}" if check.get('warning') else ""
        self.region_info.setText(
            f"Source: Interactive Map → Numeric Bounding Box | Code: {spec.code} | Geometry: Rectangle | "
            f"Bounds: {spec.xmin:.4f}–{spec.xmax:.4f}°E, {spec.ymin:.4f}–{spec.ymax:.4f}°N | "
            f"Native GODAS grid centers: {check['native_grid_cells']}{warn}"
        )
        self.region_preview.set_region(spec.geometry, spec.label)
        self.log.appendPlainText(
            f"[OK] Map-selected study region loaded | Bounds={west:.4f},{east:.4f}, {south:.4f},{north:.4f} | "
            f"GODAS cells={check['native_grid_cells']}"
        )
        if check.get('warning'):
            self.log.appendPlainText(f"[WARNING] {check['warning']}")

    def open_region_map_picker(self):
        initial = self._region_spec.geometry if self._region_spec is not None else None
        dialog = RegionMapPickerDialog(self, initial_geometry=initial)
        # Primary synchronization path: MapControls emits an explicit WGS84
        # bounds contract when the user presses "Use Selected Region".
        dialog.boundsSelected.connect(self._apply_map_selected_bbox)
        if dialog.exec() != dialog.Accepted:
            return
        # Backward-compatible fallback for any future dialog implementation that
        # closes without emitting the signal but still exposes selected bounds.
        try:
            bounds = dialog.get_selected_bounds()
            if bounds is None or len(bounds) != 4:
                raise ValueError("The map did not return a valid rectangle selection.")
            current = (
                self.bbox_w.value(), self.bbox_e.value(),
                self.bbox_s.value(), self.bbox_n.value(),
            )
            if any(abs(float(a) - float(b)) > 1e-9 for a, b in zip(bounds, current)):
                self._apply_map_selected_bbox(*bounds)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Map Region", str(exc))

    def _update_region_preview(self):
        if hasattr(self, "region_preview"):
            if self._region_spec is not None:
                self.region_preview.set_region(self._region_spec.geometry, self._region_spec.label)
            else:
                self.region_preview.clear_region()

    def _wrap_tab_pages_in_scroll_areas(self):
        """Wrap every workflow page in a vertical scroll area for compact windows."""
        entries = []
        for i in range(self.tabs.count()):
            entries.append((
                self.tabs.widget(i),
                self.tabs.tabText(i),
                self.tabs.tabIcon(i),
                self.tabs.tabToolTip(i),
            ))
        for i in range(self.tabs.count() - 1, -1, -1):
            self.tabs.removeTab(i)
        for page, text, icon, tooltip in entries:
            page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            idx = self.tabs.addTab(scroll, icon, text)
            if tooltip:
                self.tabs.setTabToolTip(idx, tooltip)

    def _build_navigation(self, body_layout):
        panel = QFrame()
        panel.setObjectName("navPanel")
        panel.setMinimumWidth(205)
        panel.setMaximumWidth(225)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 12, 10, 12)
        panel_layout.setSpacing(5)

        workflow = QLabel("WORKFLOW")
        workflow.setObjectName("navSectionTitle")
        panel_layout.addWidget(workflow)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        items = [
            ("1.  Downloading Data", "download"),
            ("2.  Validation &\nStandardization", "validation"),
            ("3.  Core Scientific\nAnalysis", "analysis"),
            ("4.  Climatology &\nAnomaly", "climatology"),
            ("5.  Trend Analysis", "trend"),
            ("6.  Spatial\nVisualization", "map"),
        ]
        nav_tones = ("blue", "teal", "purple", "orange", "gold", "indigo")
        for idx, (label, icon_name) in enumerate(items):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setProperty("tone", nav_tones[idx])
            button.setMinimumHeight(54)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            icon_path = Path(__file__).resolve().parent.parent / "resources" / "icons" / f"{icon_name}.svg"
            if icon_path.exists():
                button.setIcon(QIcon(str(icon_path)))
                button.setIconSize(QSize(18, 18))
            button.clicked.connect(lambda checked=False, i=idx: self.tabs.setCurrentIndex(i))
            self.nav_group.addButton(button, idx)
            self.nav_buttons.append(button)
            panel_layout.addWidget(button)

        panel_layout.addStretch(1)

        footer = QLabel(f"v{SOFTWARE_VERSION}  |  Schema {REPORT_SCHEMA_VERSION}")
        footer.setObjectName("navFooter")
        footer.setWordWrap(True)
        panel_layout.addWidget(footer)

        body_layout.insertWidget(0, panel)
        self.nav_panel = panel
        self._sync_navigation(self.tabs.currentIndex())

    def _sync_navigation(self, index: int):
        if not hasattr(self, "nav_buttons"):
            return
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def update_spatial_controls(self):
        product = self.spatial_product.currentData()
        var = self.spatial_var.currentData()
        is_data = product == "data_map"
        is_clim = product == "climatology_map"
        is_anom = product == "anomaly_map"
        is_trend = product == "trend_map"

        previous_unit = self.spatial_unit_combo.currentData()
        self.spatial_unit_combo.blockSignals(True)
        self.spatial_unit_combo.clear()
        for text, key in self._unit_options(var):
            self.spatial_unit_combo.addItem(text, key)
        idx_unit = self.spatial_unit_combo.findData(previous_unit)
        self.spatial_unit_combo.setCurrentIndex(idx_unit if idx_unit >= 0 else 0)
        self.spatial_unit_combo.blockSignals(False)

        self.spatial_data_setup.setVisible(is_data)
        self.spatial_clim_setup.setVisible(is_clim)
        self.spatial_anom_setup.setVisible(is_anom)
        self.spatial_trend_setup.setVisible(is_trend)
        if is_trend:
            seasonal = self.spatial_trend_mode.currentData() == "seasonal"
            self.spatial_trend_season_label.setVisible(seasonal)
            self.spatial_trend_season.setVisible(seasonal)
        else:
            self.spatial_trend_season_label.setVisible(False)
            self.spatial_trend_season.setVisible(False)

        has_depth = self._has_depth(var)
        if is_data:
            # Surface-only variables can only produce a single map.
            self.spatial_layout.setVisible(True)
            if not has_depth and self.spatial_layout.currentData() != "single":
                idx_single = self.spatial_layout.findData("single")
                self.spatial_layout.blockSignals(True)
                self.spatial_layout.setCurrentIndex(idx_single if idx_single >= 0 else 0)
                self.spatial_layout.blockSignals(False)
            model = self.spatial_layout.model()
            if model is not None and model.rowCount() > 1:
                model.item(1).setEnabled(bool(has_depth))
            self.spatial_layout.setToolTip("Three-depth comparison is available only for depth-dependent GODAS variables." if not has_depth else "")
        self.spatial_depth_setup.setVisible(has_depth)
        if has_depth:
            if is_data:
                layout = self.spatial_layout.currentData()
                self.spatial_single_mode_label.setText("Depth:")
                self.spatial_single_mode.setVisible(layout == "single")
                self.spatial_single_depth_label.setVisible(layout == "single" and self.spatial_single_mode.currentData() == "single")
                self.spatial_single_depth.setVisible(layout == "single" and self.spatial_single_mode.currentData() == "single")
                self.spatial_three_row.setVisible(layout == "three_depths")
            else:
                self.spatial_single_mode_label.setText("Depth:")
                self.spatial_single_mode.setVisible(True)
                self.spatial_single_depth_label.setVisible(self.spatial_single_mode.currentData() == "single")
                self.spatial_single_depth.setVisible(self.spatial_single_mode.currentData() == "single")
                self.spatial_three_row.setVisible(False)
        else:
            self.spatial_single_mode.setVisible(False)
            self.spatial_single_depth_label.setVisible(False)
            self.spatial_single_depth.setVisible(False)
            self.spatial_three_row.setVisible(False)

        clim_mode = self.spatial_clim_mode.currentData() if is_clim else None
        self.spatial_clim_period_label.setVisible(is_clim and clim_mode != "annual")
        self.spatial_clim_month.setVisible(is_clim and clim_mode == "monthly")
        self.spatial_clim_season.setVisible(is_clim and clim_mode == "seasonal")

        anom_mode = self.spatial_anom_mode.currentData() if is_anom else None
        self.spatial_anom_target_month_label.setVisible(is_anom and anom_mode == "monthly")
        self.spatial_anom_target_date.setVisible(is_anom and anom_mode == "monthly")
        self.spatial_anom_season_label.setVisible(is_anom and anom_mode == "seasonal")
        self.spatial_anom_season.setVisible(is_anom and anom_mode == "seasonal")
        self.spatial_anom_year_label.setVisible(is_anom and anom_mode == "seasonal")
        self.spatial_anom_year.setVisible(is_anom and anom_mode == "seasonal")
        self.spatial_anom_annual_year_label.setVisible(is_anom and anom_mode == "annual")
        self.spatial_anom_annual_year.setVisible(is_anom and anom_mode == "annual")

        fixed = self.spatial_color_mode.currentData() == "fixed"
        for w in (self.spatial_min_row_label, self.spatial_vmin, self.spatial_max_row_label, self.spatial_vmax):
            w.setVisible(fixed)
            if hasattr(w, "setEnabled"): w.setEnabled(fixed)

        if is_data:
            self.spatial_product_hint.setText("Data Map: monthly native-grid field. Single map supports Surface, Single native depth, or Deepest valid; three-depth supports Surface + selected Middle + Deepest valid.")
        elif is_clim:
            self.spatial_product_hint.setText("Climatology Map: baseline climatological field at each native-grid cell.")
        elif is_anom:
            self.spatial_product_hint.setText("Anomaly Map: target period field minus the corresponding baseline climatology at each native-grid cell.")
        else:
            self.spatial_product_hint.setText("Trend Map: independent temporal trend at each native-grid cell; trend magnitude and p-value are exported.")

        self.spatial_region_info.setText(
            f"Study region: {self._region_spec.label}" if self._region_spec is not None else
            "Study-region boundary and map extent will follow the selected study-region geometry after it is loaded."
        )
        self.spatial_note.setText(
            "Map Composer uses native GODAS cells directly. Data Map supports three-depth comparison; climatology, anomaly, and trend foundation products use one selected native depth. "
            "No interpolation, regridding, extrapolation, or gap filling is applied."
        )

    def refresh_spatial_source(self, update_message_only: bool = False):
        out = self.output_edit.text().strip() if hasattr(self, "output_edit") else ""
        var = self.spatial_var.currentData() if hasattr(self, "spatial_var") else None
        if not out or not var:
            return
        try:
            src = visualization_standardized_file(out, var)
            requested_month = self.spatial_date.date().toString("yyyy-MM-dd")
            depths = available_depths(out, var, requested_month) if self._has_depth(var) else []
            with xr.open_dataset(src) as ds:
                times = pd.DatetimeIndex(pd.to_datetime(ds.time.values))
            if len(times):
                self.spatial_date.setMinimumDate(QDate(times[0].year, times[0].month, 1))
                self.spatial_date.setMaximumDate(QDate(times[-1].year, times[-1].month, 1))
                self.spatial_source_info.setText(
                    f"Source: {src.name} | {len(times)} monthly records | {times.min().date()} to {times.max().date()}"
                )
            if self._has_depth(var):
                for combo in (self.spatial_single_depth, self.spatial_middle_depth):
                    combo.blockSignals(True)
                    previous = combo.currentData()
                    combo.clear()
                    for d in depths:
                        combo.addItem(f"{d:g} m", float(d))
                    chosen = previous if previous in depths else None
                    if chosen is None and depths:
                        chosen = 584.0 if any(abs(float(d)-584.0)<1e-9 for d in depths) else float(depths[len(depths)//2])
                    if chosen is not None:
                        combo.setCurrentIndex(combo.findData(float(chosen)))
                    combo.blockSignals(False)
                self.spatial_surface_value.setText(f"{min(depths):g} m (shallowest valid native level)" if depths else "No valid native depth")
                self.spatial_deepest_value.setText(f"{max(depths):g} m (deepest valid native level)" if depths else "No valid native depth")
            self.update_spatial_controls()
        except Exception as exc:
            if not update_message_only:
                self.spatial_source_info.setText(f"Source unavailable: {exc}")
            self.spatial_surface_value.setText("—")
            self.spatial_deepest_value.setText("—")
            self.update_spatial_controls()

    def browse_spatial_export_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Spatial Map Export Directory")
        if path:
            self.spatial_export_dir.setText(path)

    def start_spatial_visualization(self):
        output_dir = self.output_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "Missing Output Directory", "Select the output directory containing standardized GODAS files first.")
            return
        if self._region_spec is None:
            QMessageBox.warning(self, "Missing Study Region", "Load a study-region geometry before generating a spatial map.")
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "A download is currently running. Please wait until it finishes.")
            return
        if hasattr(self, "qc_worker") and self.qc_worker.isRunning():
            QMessageBox.information(self, "Busy", "Quality control is currently running. Please wait until it finishes.")
            return
        if hasattr(self, "std_worker") and self.std_worker.isRunning():
            QMessageBox.information(self, "Busy", "Standardization is currently running. Please wait until it finishes.")
            return

        product = self.spatial_product.currentData()
        var = self.spatial_var.currentData()
        unit_mode = self.spatial_unit_combo.currentData() or "native"
        params = {
            "product": product, "variable_key": var, "unit_mode": unit_mode,
            "cmap": self.spatial_cmap.currentData(), "color_mode": self.spatial_color_mode.currentData(),
            "vmin": self.spatial_vmin.value() if self.spatial_color_mode.currentData() == "fixed" else None,
            "vmax": self.spatial_vmax.value() if self.spatial_color_mode.currentData() == "fixed" else None,
            "region_geometry": self._region_spec.geometry, "region_label": self._region_spec.label,
            "show_boundary": True, "export_dir": self.spatial_export_dir.text().strip() or None,
            "formats": [fmt for fmt, cb in (("png", self.spatial_png), ("svg", self.spatial_svg), ("pdf", self.spatial_pdf)) if cb.isChecked()],
        }
        if not params["formats"]:
            QMessageBox.warning(self, "No Export Format", "Select at least one figure export format.")
            return
        if params["color_mode"] == "fixed" and (params["vmin"] is None or params["vmax"] is None or params["vmin"] >= params["vmax"]):
            QMessageBox.warning(self, "Invalid Color Scale", "Minimum must be smaller than maximum.")
            return

        if product == "data_map":
            params.update({
                "map_layout": self.spatial_layout.currentData(),
                "requested_date": self.spatial_date.date().toString("yyyy-MM-dd"),
                "single_depth_mode": self.spatial_single_mode.currentData(),
                "single_depth": float(self.spatial_single_depth.currentData()) if self.spatial_single_mode.currentData() == "single" and self.spatial_single_depth.currentData() is not None else None,
                "middle_depth": float(self.spatial_middle_depth.currentData()) if self.spatial_layout.currentData() == "three_depths" and self.spatial_middle_depth.currentData() is not None else None,
            })
            desc = f"Data Map / {params['requested_date'][:7]}"
        elif product == "climatology_map":
            mode = self.spatial_clim_mode.currentData()
            params.update({
                "period_mode": mode,
                "baseline_start": self.spatial_baseline_start.date().toString("yyyy-MM-dd"),
                "baseline_end": self.spatial_baseline_end.date().toString("yyyy-MM-dd"),
                "period_value": self.spatial_clim_month.currentData() if mode == "monthly" else (self.spatial_clim_season.currentData() if mode == "seasonal" else None),
                "depth_mode": self.spatial_single_mode.currentData(),
                "depth_value": float(self.spatial_single_depth.currentData()) if self.spatial_single_mode.currentData() == "single" and self.spatial_single_depth.currentData() is not None else None,
            })
            desc = f"Climatology Map / {mode}"
        elif product == "anomaly_map":
            mode = self.spatial_anom_mode.currentData()
            params.update({
                "period_mode": mode,
                "baseline_start": self.spatial_anom_baseline_start.date().toString("yyyy-MM-dd"),
                "baseline_end": self.spatial_anom_baseline_end.date().toString("yyyy-MM-dd"),
                "target_date": self.spatial_anom_target_date.date().toString("yyyy-MM-dd") if mode == "monthly" else None,
                "target_season": self.spatial_anom_season.currentData() if mode == "seasonal" else None,
                "target_year": self.spatial_anom_year.value() if mode == "seasonal" else (self.spatial_anom_annual_year.value() if mode == "annual" else None),
                "period_value": self.spatial_anom_target_date.date().month() if mode == "monthly" else (self.spatial_anom_season.currentData() if mode == "seasonal" else None),
                "depth_mode": self.spatial_single_mode.currentData(),
                "depth_value": float(self.spatial_single_depth.currentData()) if self.spatial_single_mode.currentData() == "single" and self.spatial_single_depth.currentData() is not None else None,
            })
            desc = f"Anomaly Map / {mode}"
        else:
            params.update({
                "trend_start": self.spatial_trend_start.date().toString("yyyy-MM-dd"),
                "trend_end": self.spatial_trend_end.date().toString("yyyy-MM-dd"),
                "trend_mode": self.spatial_trend_mode.currentData(),
                "trend_method": self.spatial_trend_method.currentData(),
                "trend_season": self.spatial_trend_season.currentData() if self.spatial_trend_mode.currentData() == "seasonal" else None,
                "depth_mode": self.spatial_single_mode.currentData(),
                "depth_value": float(self.spatial_single_depth.currentData()) if self.spatial_single_mode.currentData() == "single" and self.spatial_single_depth.currentData() is not None else None,
            })
            desc = f"Trend Map / {params['trend_mode']} / {params['trend_method']}"

        self.spatial_btn.setEnabled(False)
        self._process_started("Generating map…")
        self.status.setText("Status: Generating map...")
        self.log.appendPlainText(f"[INFO] Starting v{SOFTWARE_VERSION} {desc}")
        self.spatial_worker = SpatialVisualizationWorker(output_dir, params)
        self.spatial_worker.message.connect(self.log.appendPlainText)
        self.spatial_worker.finished_ok.connect(self.spatial_finished)
        self.spatial_worker.failed.connect(self.spatial_failed)
        self.spatial_worker.start()

    def spatial_finished(self, result):
        self.spatial_btn.setEnabled(True)
        self._process_finished("Process completed", True)
        self.status.setText(f"Status: v{SOFTWARE_VERSION} spatial visualization completed")
        figure_names = ", ".join(Path(result[k]).name for k in ("png", "svg", "pdf") if k in result)
        self.log.appendPlainText(f"[DONE] Spatial map completed: {figure_names}; report={Path(result['report']).name}")

    def spatial_failed(self, message):
        self.spatial_btn.setEnabled(True)
        self._process_finished("Spatial visualization failed", False)
        self.status.setText("Status: Spatial visualization failed")
        self.log.appendPlainText(f"[MAP ERROR] {message}")
        QMessageBox.critical(self, "Spatial Visualization Error", message)

    def update_region_source_ui(self):
        self.shp_widget.setVisible(self.region_shp_radio.isChecked())
        self.bbox_widget.setVisible(self.region_bbox_radio.isChecked())
        self.iho_widget.setVisible(self.region_iho_radio.isChecked())
        self._region_spec = None
        self._update_region_preview()
        self.start_btn.setEnabled(not self._iho_fetching and not self._iho_catalog_loading)
        if self.region_bbox_radio.isChecked():
            self.refresh_bbox_info()
        elif self.region_iho_radio.isChecked():
            if not self._iho_catalog and not self._iho_catalog_loading:
                self._start_iho_catalog_load()
            elif self._iho_catalog:
                self.region_info.setText("Select a standard marine region from IHO Sea Areas v3.")
        elif self.region_shp_radio.isChecked() and self.shp_edit.text():
            try:
                self.load_current_shapefile()
            except Exception:
                pass
        if hasattr(self, "spatial_boundary"):
            self.spatial_boundary.setEnabled(self._region_spec is not None)

    def refresh_bbox_info(self):
        if not self.region_bbox_radio.isChecked():
            return
        try:
            spec = make_bbox_region(self.bbox_w.value(), self.bbox_e.value(), self.bbox_s.value(), self.bbox_n.value())
            check = validate_region_for_godas(spec)
            self._region_spec = spec
            self._update_region_preview()
            if hasattr(self, "spatial_boundary"):
                self.spatial_boundary.setEnabled(True)
            warn = f" | WARNING: {check['warning']}" if check.get('warning') else ""
            self.region_info.setText(
                f"Code: {spec.code} | Bounds: {spec.xmin:.4f}–{spec.xmax:.4f}°E, "
                f"{spec.ymin:.4f}–{spec.ymax:.4f}°N | Native GODAS grid centers: {check['native_grid_cells']}{warn}"
            )
        except Exception as exc:
            self._region_spec = None
            self._update_region_preview()
            if hasattr(self, "spatial_boundary"):
                self.spatial_boundary.setEnabled(False)
            self.region_info.setText(f"Bounding box not valid for GODAS: {exc}")

    def load_current_shapefile(self):
        path = self.shp_edit.text().strip()
        if not path:
            return None
        spec = load_shapefile_region(path)
        check = validate_region_for_godas(spec)
        self._region_spec = spec
        self._update_region_preview()
        if hasattr(self, "spatial_boundary"):
            self.spatial_boundary.setEnabled(True)
        warn = f" | WARNING: {check['warning']}" if check.get('warning') else ""
        self.region_info.setText(
            f"Source: Shapefile | Code: {spec.code} | Geometry: Polygon | "
            f"Bounds: {spec.xmin:.4f}–{spec.xmax:.4f}°E, {spec.ymin:.4f}–{spec.ymax:.4f}°N | "
            f"Native GODAS grid centers: {check['native_grid_cells']}{warn}"
        )
        return spec

    def _start_iho_spinner(self, text):
        self._iho_spinner_text = text
        self._iho_spinner_index = 0
        self._iho_spinner_timer.start()
        self._update_iho_spinner()

    def _update_iho_spinner(self):
        if not (self._iho_fetching or self._iho_catalog_loading):
            self._iho_spinner_timer.stop()
            return
        frame = self._iho_spinner_frames[self._iho_spinner_index % len(self._iho_spinner_frames)]
        self._iho_spinner_index += 1
        self.iho_status.setText(f"{self._iho_spinner_text} — Please Wait ... {frame}")

    def _stop_iho_spinner(self):
        self._iho_spinner_timer.stop()
        self._iho_spinner_text = ""

    def _start_iho_catalog_load(self):
        self._iho_catalog_loading = True
        self.start_btn.setEnabled(False)
        self._start_iho_spinner("Loading the IHO Sea Areas v3 list from Marine Regions")
        self.region_info.setText("Connecting to the official Marine Regions service to load standard regions…")
        cache_path = Path.home() / ".godas_regional_tool" / "iho_seas_v3_catalog.json"
        self._iho_catalog_worker = IHOCatalogWorker(str(cache_path))
        self._iho_catalog_worker.finished_ok.connect(self._iho_catalog_loaded)
        self._iho_catalog_worker.failed.connect(self._iho_catalog_failed)
        self._iho_catalog_worker.start()

    def _iho_catalog_loaded(self, catalog):
        self._iho_catalog_loading = False
        self._stop_iho_spinner()
        self._iho_catalog = list(catalog)
        self.iho_combo.blockSignals(True)
        self.iho_combo.clear()
        self.iho_combo.addItem("— Select a standard marine region —", None)
        for item in self._iho_catalog:
            self.iho_combo.addItem(item["name"], item)
        self.iho_combo.blockSignals(False)
        self.iho_combo.setEnabled(True)
        self.start_btn.setEnabled(not self._iho_fetching)
        self.iho_status.setText(
            f"{len(self._iho_catalog)} standard IHO Sea Areas are available. "
            "Geometry is retrieved only for the selected region."
        )
        self.region_info.setText("Select a standard marine region from IHO Sea Areas v3.")
        self.log.appendPlainText(f"[OK] IHO Sea Areas v3 catalog loaded: {len(self._iho_catalog)} standard regions")

    def _iho_catalog_failed(self, message):
        self._iho_catalog_loading = False
        self._stop_iho_spinner()
        self.iho_combo.clear()
        self.iho_combo.addItem("— Standard-region list unavailable —", None)
        self.iho_combo.setEnabled(False)
        self.start_btn.setEnabled(True)
        self.iho_status.setText(
            "The standard-region list could not be retrieved. "
            "Polygon Shapefile and Bounding Box modes remain available."
        )
        self.region_info.setText(f"IHO Sea Areas catalog unavailable: {message}")
        self.log.appendPlainText(f"[WARNING] IHO catalog: {message}")

    def _iho_fetch_started(self, name):
        self._iho_fetching = True
        self._region_spec = None
        self._start_iho_spinner(f"Retrieving geometry for {name} from Marine Regions")
        self.region_info.setText("Checking the selected standard marine region against the native GODAS grid…")
        self.start_btn.setEnabled(False)

    def _iho_fetch_finished(self, spec, check):
        current = self.iho_combo.currentData()
        if not current or current.get("name") != spec.label:
            return
        self._iho_fetching = False
        self._stop_iho_spinner()
        self._region_spec = spec
        self._update_region_preview()
        if hasattr(self, "spatial_boundary"):
            self.spatial_boundary.setEnabled(True)
        self.start_btn.setEnabled(True)
        warn = f" | WARNING: {check['warning']}" if check.get('warning') else ""
        self.iho_status.setText(
            "Geometry retrieved from the official Marine Regions WFS. "
            f"MRGID={spec.source_description.split('MRGID=')[-1]}"
        )
        self.region_info.setText(
            f"Source: Marine Regions / IHO Sea Areas v3 | Name: {spec.label} | Code: {spec.code} | "
            f"Bounds: {spec.xmin:.4f}–{spec.xmax:.4f}°E, {spec.ymin:.4f}–{spec.ymax:.4f}°N | "
            f"Native GODAS grid centers: {check['native_grid_cells']}{warn}"
        )
        self.log.appendPlainText(f"[OK] Standard marine region loaded: {spec.label} -> {spec.code} | GODAS cells={check['native_grid_cells']}")
        if check.get('warning'):
            self.log.appendPlainText(f"[WARNING] {check['warning']}")

    def _iho_fetch_failed(self, message):
        current = self.iho_combo.currentData()
        if not current or not self._iho_fetching:
            return
        self._iho_fetching = False
        self._stop_iho_spinner()
        self._region_spec = None
        self._update_region_preview()
        if hasattr(self, "spatial_boundary"):
            self.spatial_boundary.setEnabled(False)
        self.start_btn.setEnabled(True)
        self.iho_status.setText("Could not retrieve the selected region geometry from Marine Regions.")
        self.region_info.setText(f"Standard marine region unavailable: {message}")
        self.log.appendPlainText(f"[ERROR] Marine Regions: {message}")
        QMessageBox.warning(
            self,
            "Standard Marine Region Unavailable",
            message + "\n\nThe standard region requires internet access to the official Marine Regions service."
        )

    def iho_selection_changed(self):
        if not self.region_iho_radio.isChecked():
            return
        item = self.iho_combo.currentData()
        if not item:
            self._region_spec = None
            if hasattr(self, "spatial_boundary"):
                self.spatial_boundary.setEnabled(False)
            self.iho_status.setText("Select a region; its geometry will be retrieved from the official Marine Regions service when needed.")
            self.region_info.setText("No standard marine region selected.")
            return
        if self._iho_fetch_worker and self._iho_fetch_worker.isRunning():
            self._iho_fetch_worker.requestInterruption()
        name = item["name"]
        mrgid = item["mrgid"]
        self._iho_fetch_started(name)
        self._iho_fetch_worker = IHOFetchWorker(name, mrgid)
        self._iho_fetch_worker.finished_ok.connect(self._iho_fetch_finished)
        self._iho_fetch_worker.failed.connect(self._iho_fetch_failed)
        self._iho_fetch_worker.start()

    def browse_shapefile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Region Shapefile", "", "Shapefile (*.shp)"
        )
        if not path:
            return
        self.shp_edit.setText(path)
        try:
            self.load_current_shapefile()
            self.log.appendPlainText(f"[OK] Region loaded: {Path(path).name}")
        except Exception as exc:
            self._region_spec = None
            self.region_info.setText("Invalid, incomplete, or GODAS-incompatible Shapefile.")
            self.log.appendPlainText(f"[ERROR] {exc}")
            QMessageBox.critical(self, "Shapefile Error", str(exc))

    def browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if path:
            self.output_edit.setText(path)

    def start_download(self):
        try:
            if self.region_bbox_radio.isChecked():
                if self._region_spec is not None and self._region_spec.source_type == "bounding_box":
                    region = self._region_spec
                else:
                    region = make_bbox_region(self.bbox_w.value(), self.bbox_e.value(), self.bbox_s.value(), self.bbox_n.value())
            elif self.region_iho_radio.isChecked():
                if self._iho_fetching:
                    raise ValueError("The selected standard marine region is still being retrieved. Please wait a moment and try again.")
                region = self._region_spec
                if region is None:
                    raise ValueError("Select a standard marine region and wait until its geometry is successfully retrieved.")
            else:
                region = load_shapefile_region(self.shp_edit.text().strip())
            check = validate_region_for_godas(region)
            self._region_spec = region
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Study Region", str(exc))
            return

        if not self.output_edit.text():
            QMessageBox.warning(self, "Missing Output", "Please select the output directory.")
            return
        selected = [k for k, cb in self.vars.items() if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "No Variables", "Select at least one GODAS variable.")
            return
        start_qdate=self.start_date.date(); end_qdate=self.end_date.date()
        if end_qdate < start_qdate:
            QMessageBox.warning(self,"Invalid Period","End date must be on or after the start date.")
            return
        start_date=start_qdate.toString("yyyy-MM-dd"); end_date=end_qdate.toString("yyyy-MM-dd")
        self.start_btn.setEnabled(False); self.cancel_btn.setEnabled(True); self.progress.setValue(0)
        self._process_started("Downloading data…", determinate=True)
        self.status.setText("Status: Downloading...")
        self.log.appendPlainText(f"[INFO] Region={region.label} | Code={region.code} | Native GODAS grid centers={check['native_grid_cells']}")
        self.log.appendPlainText(f"[INFO] Starting GODAS download: {start_date} to {end_date}")
        if check.get('warning'):
            self.log.appendPlainText(f"[WARNING] {check['warning']}")
        self.worker=DownloadWorker(selected,region,start_date,end_date,self.output_edit.text())
        self.worker.message.connect(self.log.appendPlainText)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.progress.connect(self._set_processing_progress)
        self.worker.finished_ok.connect(self.download_finished)
        self.worker.failed.connect(self.download_failed)
        self.worker.start()

    def start_qc(self):
        if not self.output_edit.text():
            QMessageBox.warning(self, "Missing Output", "Please select the output directory first.")
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "A download is currently running. Please wait until it finishes.")
            return
        self.qc_btn.setEnabled(False)
        self._process_started("Running quality control…")
        self.status.setText("Status: Running quality control...")
        self.log.appendPlainText("[INFO] Starting NetCDF quality control...")
        self.qc_worker = QCWorker(self.output_edit.text())
        self.qc_worker.message.connect(self.log.appendPlainText)
        self.qc_worker.finished_ok.connect(self.qc_finished)
        self.qc_worker.failed.connect(self.qc_failed)
        self.qc_worker.start()

    def qc_finished(self, result):
        self.qc_btn.setEnabled(True)
        self._process_finished("Process completed", True)
        self.status.setText("Status: QC completed")
        self.log.appendPlainText(
            f"[DONE] QC completed: {result['files_checked']} files checked; "
            f"PASS={result['pass']}, WARN={result['pass_with_warnings']}, FAIL={result['fail']}"
        )
        if result.get("fail", 0) == 0:
            self.tabs.setCurrentIndex(1)  # move to Data Validation & Standardization

    def qc_failed(self, message):
        self.qc_btn.setEnabled(True)
        self._process_finished("QC failed", False)
        self.status.setText("Status: QC failed")
        self.log.appendPlainText(f"[QC ERROR] {message}")
        QMessageBox.critical(self, "Quality Control Error", message)

    def start_standardization(self):
        if not self.output_edit.text():
            QMessageBox.warning(self, "Missing Output", "Please select the output directory first.")
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "A download is currently running. Please wait until it finishes.")
            return
        if hasattr(self, "qc_worker") and self.qc_worker.isRunning():
            QMessageBox.information(self, "Busy", "Quality control is currently running. Please wait until it finishes.")
            return
        self.std_btn.setEnabled(False)
        self._process_started("Standardizing and integrating…")
        self.status.setText("Status: Standardizing and integrating...")
        self.log.appendPlainText("[INFO] Starting Data Standardization & Integration...")
        self.std_worker = StandardizeWorker(self.output_edit.text())
        self.std_worker.message.connect(self.log.appendPlainText)
        self.std_worker.finished_ok.connect(self.standardization_finished)
        self.std_worker.failed.connect(self.standardization_failed)
        self.std_worker.start()

    def standardization_finished(self, result):
        self.std_btn.setEnabled(True)
        self._process_finished("Process completed", True)
        self.status.setText("Status: Standardization completed")
        self.log.appendPlainText(
            f"[DONE] Standardization completed: {result['variables']} variables; "
            f"warnings={result['warnings']}."
        )
        if result.get("warnings", 0) == 0:
            self.tabs.setCurrentIndex(2)  # move to Scientific Analysis

    def standardization_failed(self, message):
        self.std_btn.setEnabled(True)
        self._process_finished("Standardization failed", False)
        self.status.setText("Status: Standardization failed")
        self.log.appendPlainText(f"[STD ERROR] {message}")
        QMessageBox.critical(self, "Standardization Error", message)

    def update_analysis_controls(self):
        var = self.analysis_var.currentData()
        analysis = self.analysis_type.currentData()
        has_depth = self._has_depth(var)

        # MLD is a 2-D (time, lat, lon) variable and is intentionally limited
        # to Regional Time Series. Rebuild the analysis list so the GUI cannot
        # enter an unsupported state.
        if not self._has_depth(var):
            if self.analysis_type.count() != 1 or self.analysis_type.itemData(0) != "time_series":
                self.analysis_type.blockSignals(True)
                self.analysis_type.clear()
                self.analysis_type.addItem("Regional Time Series", "time_series")
                self.analysis_type.blockSignals(False)
            self.analysis_type.setToolTip(
                "Mixed Layer Depth is a 2-D field and is supported only by Regional Time Series."
            )
            analysis = "time_series"
        else:
            if self.analysis_type.count() != 3 or self.analysis_type.itemData(1) != "vertical_profile":
                current = analysis or "time_series"
                self.analysis_type.blockSignals(True)
                self.analysis_type.clear()
                self.analysis_type.addItem("Regional Time Series", "time_series")
                self.analysis_type.addItem("Mean Vertical Profile", "vertical_profile")
                self.analysis_type.addItem("Depth–Time Section", "depth_time")
                idx = self.analysis_type.findData(current)
                self.analysis_type.setCurrentIndex(idx if idx >= 0 else 0)
                self.analysis_type.blockSignals(False)
            analysis = self.analysis_type.currentData()
            self.analysis_type.setToolTip(
                "Select one of the three analysis modules. Depth selection applies to 3-D variables."
            )

        self.depth_single.setEnabled(has_depth)
        self.depth_range.setEnabled(has_depth)
        self.depth_full.setEnabled(has_depth)
        self.depth_surface.setEnabled(True)
        if not has_depth:
            self.depth_surface.setChecked(True)

        # Analysis/depth dependency:
        # Regional Time Series is valid for every depth-selection mode.
        # Mean Vertical Profile and Depth–Time Section require the full
        # water column because both products operate along the native depth
        # dimension.  Keep invalid combinations out of the GUI rather than
        # letting the user run them and receive a backend warning/error.
        full_column = has_depth and self.depth_full.isChecked()
        if has_depth and not full_column:
            if self.analysis_type.currentData() != "time_series":
                self.analysis_type.blockSignals(True)
                idx = self.analysis_type.findData("time_series")
                self.analysis_type.setCurrentIndex(idx if idx >= 0 else 0)
                self.analysis_type.blockSignals(False)
            self.analysis_type.model().item(1).setEnabled(False)
            self.analysis_type.model().item(2).setEnabled(False)
            self.analysis_type.setToolTip(
                "Surface, Single depth, and Depth range support Regional Time Series only. "
                "Mean Vertical Profile and Depth–Time Section require Full water column."
            )
        elif has_depth and full_column:
            self.analysis_type.model().item(1).setEnabled(True)
            self.analysis_type.model().item(2).setEnabled(True)
            self.analysis_type.setToolTip(
                "Full water column supports Regional Time Series, Mean Vertical Profile, and Depth–Time Section."
            )

        self.single_depth_edit.setEnabled(has_depth and self.depth_single.isChecked())
        self.depth_min_edit.setEnabled(has_depth and self.depth_range.isChecked())
        self.depth_max_edit.setEnabled(has_depth and self.depth_range.isChecked())

        # Preserve the user's unit choice when controls are refreshed.
        previous_unit = self.unit_combo.currentData() if hasattr(self, "unit_combo") else None
        if hasattr(self, "unit_combo"):
            self.unit_combo.blockSignals(True)
            self.unit_combo.clear()
            for text, key in self._unit_options(var):
                self.unit_combo.addItem(text, key)
            idx = self.unit_combo.findData(previous_unit)
            self.unit_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.unit_combo.blockSignals(False)

        if not self._has_depth(var):
            self.analysis_btn.setToolTip(
                "MLD is a 2-D field: only Regional Time Series is available. "
                "No vertical selection, interpolation, or gap filling is applied."
            )
        else:
            self.analysis_btn.setToolTip(
                "Analysis preserves the native GODAS grid. No interpolation, extrapolation, "
                "gap filling, or silent regridding is performed."
            )

    def update_product_controls(self):
        is_anomaly = self.product_type.currentData() == "anomaly"
        var = self.product_var.currentData()

        current = self.product_mode.currentData()
        self.product_mode.blockSignals(True)
        self.product_mode.clear()
        if is_anomaly:
            self.product_mode.addItem("Monthly", "monthly")
            self.product_mode.addItem("Seasonal (DJF/MAM/JJA/SON)", "seasonal")
            self.product_mode.addItem("Annual", "annual")
        else:
            self.product_mode.addItem("Monthly", "monthly")
            self.product_mode.addItem("Seasonal (DJF/MAM/JJA/SON)", "seasonal")
            self.product_mode.addItem("Annual Mean", "annual_mean")
        idx = self.product_mode.findData(current)
        self.product_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self.product_mode.blockSignals(False)

        # Baseline is always needed. Target/anomaly period is shown only for anomaly.
        for w in (self.anom_start_label, self.anom_start, self.anom_end_label, self.anom_end):
            w.setVisible(is_anomaly)
        self.product_btn.setText("RUN ANOMALY" if is_anomaly else "RUN CLIMATOLOGY")

        has_depth = self._has_depth(var)
        for w in (self.product_depth_single, self.product_depth_range, self.product_depth_full,
                  self.product_single_depth_edit, self.product_depth_min_edit, self.product_depth_max_edit):
            w.setEnabled(has_depth and (not isinstance(w, QLineEdit) or True))
        if not has_depth:
            self.product_depth_surface.setChecked(True)
        self.product_depth_single.setEnabled(has_depth)
        self.product_depth_range.setEnabled(has_depth)
        self.product_depth_full.setEnabled(has_depth)
        self.product_single_depth_edit.setEnabled(has_depth and self.product_depth_single.isChecked())
        self.product_depth_min_edit.setEnabled(has_depth and self.product_depth_range.isChecked())
        self.product_depth_max_edit.setEnabled(has_depth and self.product_depth_range.isChecked())

        # Preserve the user's unit choice when controls are refreshed.
        previous_unit = self.product_unit_combo.currentData() if hasattr(self, "product_unit_combo") else None
        if hasattr(self, "product_unit_combo"):
            self.product_unit_combo.blockSignals(True)
            self.product_unit_combo.clear()
            for text, key in self._unit_options(var):
                self.product_unit_combo.addItem(text, key)
            idx = self.product_unit_combo.findData(previous_unit)
            self.product_unit_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.product_unit_combo.blockSignals(False)

        if is_anomaly:
            self.product_note.setText(
                "Anomaly uses the user-defined baseline climatology. Baseline dates define the reference period; "
                "Anomaly period dates define the target period. No interpolation, extrapolation, regridding, or gap filling is applied."
            )
        else:
            self.product_note.setText(
                "Climatology uses only the user-defined baseline period. For Annual Mean, one mean is produced for the entire baseline. "
                "No interpolation, extrapolation, regridding, or gap filling is applied."
            )

    def start_scientific_product(self):
        if not self.output_edit.text():
            QMessageBox.warning(self, "Missing Output", "Please select the output directory first."); return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "A download is currently running. Please wait until it finishes."); return
        if hasattr(self, "qc_worker") and self.qc_worker.isRunning():
            QMessageBox.information(self, "Busy", "Quality control is currently running. Please wait until it finishes."); return
        if hasattr(self, "std_worker") and self.std_worker.isRunning():
            QMessageBox.information(self, "Busy", "Standardization is currently running. Please wait until it finishes."); return

        product = self.product_type.currentData(); mode = self.product_mode.currentData(); var = self.product_var.currentData()
        bs = self.baseline_start.date(); be = self.baseline_end.date()
        ts = self.anom_start.date(); te = self.anom_end.date()
        if be < bs:
            QMessageBox.warning(self, "Invalid Baseline", "Baseline end date must be on or after baseline start date."); return
        if product == "anomaly" and te < ts:
            QMessageBox.warning(self, "Invalid Anomaly Period", "Anomaly period end date must be on or after anomaly period start date."); return
        if product == "anomaly" and mode == "annual_mean":
            QMessageBox.warning(self, "Invalid Anomaly Mode", "Annual anomaly uses the Annual mode, not Annual Mean."); return

        depth_mode = "surface"; sd = dm = dx = None
        if self._has_depth(var):
            if self.product_depth_single.isChecked():
                depth_mode = "single"; sd = float(self.product_single_depth_edit.text()) if self.product_single_depth_edit.text().strip() else None
            elif self.product_depth_range.isChecked():
                depth_mode = "range"; dm = float(self.product_depth_min_edit.text()) if self.product_depth_min_edit.text().strip() else None; dx = float(self.product_depth_max_edit.text()) if self.product_depth_max_edit.text().strip() else None
            elif self.product_depth_full.isChecked(): depth_mode = "full"
        unit_mode = self.product_unit_combo.currentData() or "native"

        self.product_btn.setEnabled(False); self._process_started(f"Running {product}…"); self.status.setText(f"Status: Running {product}...")
        self.log.appendPlainText(f"[INFO] Starting v{SOFTWARE_VERSION} product: {product} / {var} / {mode}")
        self.product_worker = ScientificProductWorker(
            self.output_edit.text(), product, var, mode,
            bs.toString("yyyy-MM-dd"), be.toString("yyyy-MM-dd"),
            ts.toString("yyyy-MM-dd"), te.toString("yyyy-MM-dd"),
            depth_mode, sd, dm, dx, unit_mode
        )
        self.product_worker.message.connect(self.log.appendPlainText)
        self.product_worker.finished_ok.connect(self.product_finished)
        self.product_worker.failed.connect(self.product_failed)
        self.product_worker.start()

    def product_finished(self,result):
        self.product_btn.setEnabled(True); self._process_finished("Process completed", True); self.status.setText(f"Status: v{SOFTWARE_VERSION} scientific product completed")
        self.log.appendPlainText(f"[DONE] v{SOFTWARE_VERSION} product completed: CSV={Path(result['csv']).name}; Plot={Path(result['plot']).name}")

    def product_failed(self,message):
        self.product_btn.setEnabled(True); self._process_finished("Scientific product failed", False); self.status.setText(f"Status: v{SOFTWARE_VERSION} scientific product failed")
        self.log.appendPlainText(f"[V2 ERROR] {message}"); QMessageBox.critical(self,"Scientific Product Error",message)

    def update_trend_controls(self):
        var = self.trend_var.currentData()
        has_depth = self._has_depth(var)
        if not has_depth:
            self.trend_depth_surface.setChecked(True)
        for b in (self.trend_depth_single, self.trend_depth_range, self.trend_depth_full):
            b.setEnabled(has_depth)
        self.trend_single_depth_edit.setEnabled(has_depth and self.trend_depth_single.isChecked())
        self.trend_depth_min_edit.setEnabled(has_depth and self.trend_depth_range.isChecked())
        self.trend_depth_max_edit.setEnabled(has_depth and self.trend_depth_range.isChecked())

        previous_unit = self.trend_unit_combo.currentData() if hasattr(self, "trend_unit_combo") else None
        self.trend_unit_combo.blockSignals(True)
        self.trend_unit_combo.clear()
        for text, key in self._unit_options(var):
            self.trend_unit_combo.addItem(text, key)
        idx = self.trend_unit_combo.findData(previous_unit)
        self.trend_unit_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.trend_unit_combo.blockSignals(False)
        self.trend_note.setText(
            "Monthly trend uses all valid monthly observations. Annual observations require all 12 months; "
            "seasonal observations require all 3 months. For Full water column, trends are calculated independently "
            "at every native GODAS depth. No interpolation, regridding, gap filling, or autocorrelation correction is applied."
        )

    def start_trend(self):
        var = self.trend_var.currentData(); trend_type = self.trend_type.currentData()
        if not self.output_edit.text():
            QMessageBox.warning(self, "Missing Output", "Please select the output directory first."); return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "A download is currently running. Please wait until it finishes."); return
        if hasattr(self, "qc_worker") and self.qc_worker.isRunning():
            QMessageBox.information(self, "Busy", "Quality control is currently running. Please wait until it finishes."); return
        if hasattr(self, "std_worker") and self.std_worker.isRunning():
            QMessageBox.information(self, "Busy", "Standardization is currently running. Please wait until it finishes."); return
        start = self.trend_start.date(); end = self.trend_end.date()
        if end < start:
            QMessageBox.warning(self, "Invalid Period", "End date must be on or after the start date."); return

        def parse_depth(edit, label):
            text = edit.text().strip()
            if not text: return None
            try: value = float(text)
            except ValueError: raise ValueError(f"{label} must be a numeric value in metres.")
            if value < 0: raise ValueError(f"{label} cannot be negative.")
            return value
        try:
            sd = parse_depth(self.trend_single_depth_edit, "Single depth")
            dm = parse_depth(self.trend_depth_min_edit, "Depth minimum")
            dx = parse_depth(self.trend_depth_max_edit, "Depth maximum")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Depth", str(exc)); return
        if self.trend_depth_single.isChecked():
            depth_mode = "single"
            if sd is None: QMessageBox.warning(self, "Missing Depth", "Enter a target depth for Single depth mode."); return
        elif self.trend_depth_range.isChecked():
            depth_mode = "range"
            if dm is None and dx is None: QMessageBox.warning(self, "Missing Depth Range", "Enter at least one depth limit."); return
        elif self.trend_depth_full.isChecked() and self._has_depth(var): depth_mode = "full"
        else: depth_mode = "surface"

        method_map = {"all": ["OLS", "Mann-Kendall", "Sen"], "ols": ["OLS"], "mk": ["Mann-Kendall"], "sen": ["Sen"]}
        methods = method_map[self.trend_method.currentData()]
        unit_mode = self.trend_unit_combo.currentData() or "native"
        self.trend_btn.setEnabled(False); self._process_started("Running trend analysis…"); self.status.setText("Status: Running trend analysis...")
        self.log.appendPlainText(f"[INFO] Starting v{SOFTWARE_VERSION} trend: {var} / {trend_type} / depth={depth_mode} / methods={','.join(methods)} / unit={unit_mode}")
        self.trend_worker = TrendWorker(
            self.output_edit.text(), var, trend_type, start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd"),
            depth_mode, sd, dm, dx, unit_mode, methods, 0.05
        )
        self.trend_worker.message.connect(self.log.appendPlainText)
        self.trend_worker.finished_ok.connect(self.trend_finished)
        self.trend_worker.failed.connect(self.trend_failed)
        self.trend_worker.start()

    def trend_finished(self, result):
        self.trend_btn.setEnabled(True); self._process_finished("Process completed", True); self.status.setText("Status: Trend analysis completed")
        self.log.appendPlainText(f"[DONE] Trend completed. Series={Path(result['series_csv']).name}; Statistics={Path(result['statistics_csv']).name}; Plot={Path(result['plot']).name}")

    def trend_failed(self, message):
        self.trend_btn.setEnabled(True); self._process_finished("Trend analysis failed", False); self.status.setText("Status: Trend analysis failed")
        self.log.appendPlainText(f"[TREND ERROR] {message}"); QMessageBox.critical(self, "Trend Analysis Error", message)

    def start_analysis(self):
        variable_key = self.analysis_var.currentData()
        analysis_type = self.analysis_type.currentData()

        if not variable_key:
            QMessageBox.warning(self, "Missing Variable", "Please select an analysis variable.")
            return
        if not analysis_type:
            QMessageBox.warning(self, "Missing Analysis Type", "Please select an analysis type.")
            return

        if not self.output_edit.text():
            QMessageBox.warning(self, "Missing Output", "Please select the output directory first.")
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "A download is currently running. Please wait until it finishes.")
            return
        if hasattr(self, "qc_worker") and self.qc_worker.isRunning():
            QMessageBox.information(self, "Busy", "Quality control is currently running. Please wait until it finishes.")
            return
        if hasattr(self, "std_worker") and self.std_worker.isRunning():
            QMessageBox.information(self, "Busy", "Standardization is currently running. Please wait until it finishes.")
            return

        start_qdate = self.analysis_start.date()
        end_qdate = self.analysis_end.date()
        if end_qdate < start_qdate:
            QMessageBox.warning(self, "Invalid Period", "End date must be on or after the start date.")
            return

        def parse_depth(edit, label):
            text = edit.text().strip()
            if not text:
                return None
            try:
                value = float(text)
            except ValueError:
                raise ValueError(f"{label} must be a numeric value in metres.")
            if value < 0:
                raise ValueError(f"{label} cannot be negative.")
            return value

        try:
            single_depth = parse_depth(self.single_depth_edit, "Single depth")
            depth_min = parse_depth(self.depth_min_edit, "Depth minimum")
            depth_max = parse_depth(self.depth_max_edit, "Depth maximum")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Depth", str(exc))
            return

        if self.depth_single.isChecked():
            depth_mode = "single"
            if single_depth is None:
                QMessageBox.warning(self, "Missing Depth", "Enter a target depth for Single depth mode.")
                return
        elif self.depth_range.isChecked():
            depth_mode = "range"
            if depth_min is None and depth_max is None:
                QMessageBox.warning(self, "Missing Depth Range", "Enter at least one depth limit.")
                return
        elif self.depth_full.isChecked() and self._has_depth(variable_key):
            depth_mode = "full"
        else:
            depth_mode = "surface"

        if not self._has_depth(variable_key) and analysis_type != "time_series":
            QMessageBox.warning(
                self, "Analysis Not Applicable",
                "Mixed Layer Depth is a 2-D monthly field; vertical profile and depth-time section require a 3-D variable."
            )
            return

        # Defensive validation: profile/depth-time are meaningful only for
        # Full water column. The GUI already prevents this state, but keep
        # the backend entry point protected as well.
        if analysis_type != "time_series" and depth_mode != "full":
            QMessageBox.warning(
                self, "Analysis Not Applicable",
                "Mean Vertical Profile and Depth–Time Section require Full water column depth selection. "
                "For Surface, Single depth, or Depth range, select Regional Time Series."
            )
            return

        unit_mode = self.unit_combo.currentData() or "native"

        start_date = start_qdate.toString("yyyy-MM-dd")
        end_date = end_qdate.toString("yyyy-MM-dd")
        self.analysis_btn.setEnabled(False)
        self._process_started("Running scientific analysis…")
        self.status.setText("Status: Running scientific analysis...")
        self.log.appendPlainText(
            f"[INFO] Starting scientific analysis: {variable_key} / {analysis_type} / depth={depth_mode} / unit={unit_mode}"
        )
        self.analysis_worker = AnalysisWorker(
            self.output_edit.text(), variable_key, analysis_type,
            start_date, end_date, depth_mode, single_depth, depth_min, depth_max, unit_mode
        )
        self.analysis_worker.message.connect(self.log.appendPlainText)
        self.analysis_worker.finished_ok.connect(self.analysis_finished)
        self.analysis_worker.failed.connect(self.analysis_failed)
        self.analysis_worker.start()

    def analysis_finished(self, result):
        self.analysis_btn.setEnabled(True)
        self._process_finished("Process completed", True)
        self.status.setText("Status: Scientific analysis completed")
        self.log.appendPlainText(
            f"[DONE] Analysis completed. Plot={Path(result['plot']).name}; CSV={Path(result['csv']).name}"
        )

    def analysis_failed(self, message):
        self.analysis_btn.setEnabled(True)
        self._process_finished("Scientific analysis failed", False)
        self.status.setText("Status: Scientific analysis failed")
        self.log.appendPlainText(f"[AN ERROR] {message}")
        QMessageBox.critical(self, "Scientific Analysis Error", message)

    def cancel_download(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText("Status: Cancelling...")

    def download_finished(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._process_finished("Process completed", True)
        self.status.setText("Status: Completed")
        self.log.appendPlainText("[DONE] GODAS regional download completed.")
        self.tabs.setCurrentIndex(1)  # move to Data Validation & Standardization

    def download_failed(self, message):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._process_finished("Download failed", False)
        self.status.setText("Status: Failed")
        self.log.appendPlainText(f"[FATAL] {message}")
        QMessageBox.critical(self, "Download Error", message)
