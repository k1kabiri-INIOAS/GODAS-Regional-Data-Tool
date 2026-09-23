from pathlib import Path


def test_map_picker_is_rectangle_only():
    source = Path(__file__).resolve().parents[1] / "gui" / "map_picker.py"
    text = source.read_text(encoding="utf-8")
    assert "PolygonSelector" not in text
    assert 'self.polygon_btn' not in text
    assert "Draw Rectangle" in text
    assert "coord_w" in text and "coord_e" in text and "coord_s" in text and "coord_n" in text


def test_map_ui_uses_square_layout_contract():
    for name in ("region_preview.py", "map_picker.py"):
        source = Path(__file__).resolve().parents[1] / "gui" / name
        text = source.read_text(encoding="utf-8")
        assert "square_web_bounds" in text
        assert "set_box_aspect(1)" in text


def test_v254_rectangle_sync_and_coordinate_formatter_contract():
    main = Path(__file__).resolve().parents[1] / "gui" / "main_window.py"
    picker = Path(__file__).resolve().parents[1] / "gui" / "map_picker.py"
    main_text = main.read_text(encoding="utf-8")
    picker_text = picker.read_text(encoding="utf-8")
    assert "def _apply_map_selected_bbox(self, west, east, south, north):" in main_text
    assert "dialog.get_selected_bounds()" in main_text
    assert "self._apply_map_selected_bbox(*bounds)" in main_text
    assert "def _format_cursor_coord" in picker_text
    assert "Lon {lon:.4f}° | Lat {lat:.4f}°" in picker_text
    assert "QToolBar#mapNavigationToolbar" in picker_text


def test_iho_loading_spinner_contract():
    source = Path(__file__).resolve().parents[1] / "gui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    assert "_iho_spinner_timer" in text
    assert "_start_iho_spinner" in text
    assert "_stop_iho_spinner" in text
    assert "_iho_spinner_frames" in text


def test_only_two_online_basemaps_are_registered():
    source = Path(__file__).resolve().parents[1] / "gui" / "basemaps.py"
    text = source.read_text(encoding="utf-8")
    assert '"esri_street"' in text
    assert '"google_satellite"' in text
    assert '"google_roadmap"' not in text
    assert '"esri_imagery"' not in text
    assert '"carto_light"' not in text
    assert '"opentopomap"' not in text
    assert '"osm"' not in text


def test_v255_numeric_map_selection_uses_bbox_region_spec():
    source = Path(__file__).resolve().parents[1] / "gui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    assert "spec = make_bbox_region(west, east, south, north)" in text
    assert "Interactive Map → Numeric Bounding Box" in text


def test_v255_iho_wait_text_contract():
    source = Path(__file__).resolve().parents[1] / "gui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    assert "Please Wait ..." in text


def test_v255_startup_splash_and_console_handoff_contract():
    source = Path(__file__).resolve().parents[1] / "main.py"
    text = source.read_text(encoding="utf-8")
    assert "def _create_splash" in text
    assert "QSplashScreen" in text
    assert "pythonw.exe" in text
    assert "GODAS_GUI_CHILD" in text
    assert "QTimer.singleShot(remaining_ms" in text


def test_v255_software_version_is_centralized_in_reporting():
    source = Path(__file__).resolve().parents[1] / "gui" / "basemap_renderer.py"
    text = source.read_text(encoding="utf-8")
    assert "from core.reporting import SOFTWARE_VERSION" in text
    assert "GODAS Regional Data Tool/{SOFTWARE_VERSION}" in text


def test_v256_map_picker_exposes_explicit_wgs84_bounds_result_contract():
    picker = Path(__file__).resolve().parents[1] / "gui" / "map_picker.py"
    text = picker.read_text(encoding="utf-8")
    assert "self.selected_bounds = None" in text
    assert "def get_selected_bounds(self)" in text
    assert "Return selected rectangle bounds as (west, east, south, north) in WGS84 degrees." in text
    assert "self.selected_bounds = (float(xmin), float(xmax), float(ymin), float(ymax))" in text


def test_v256_main_window_applies_map_bounds_through_single_helper():
    source = Path(__file__).resolve().parents[1] / "gui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    assert "def _apply_map_selected_bbox(self, west, east, south, north):" in text
    assert "bounds = dialog.get_selected_bounds()" in text
    assert "self._apply_map_selected_bbox(*bounds)" in text
    assert 'self._region_spec.source_type == "bounding_box"' in text
