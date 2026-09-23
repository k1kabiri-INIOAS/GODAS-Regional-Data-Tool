from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "gui" / "main_window.py").read_text(encoding="utf-8")
MAP_PICKER = (ROOT / "gui" / "map_picker.py").read_text(encoding="utf-8")
RENDERER = (ROOT / "gui" / "basemap_renderer.py").read_text(encoding="utf-8")
MAIN_PY = (ROOT / "main.py").read_text(encoding="utf-8")
MAIN_PYW = (ROOT / "main.pyw").read_text(encoding="utf-8")
REPORTING = (ROOT / "core" / "reporting.py").read_text(encoding="utf-8")
THEME = (ROOT / "gui" / "theme.py").read_text(encoding="utf-8")


def test_v2510_version_is_centralized():
    assert 'SOFTWARE_VERSION = "2.5.10"' in REPORTING


def test_v2510_starts_main_window_maximized():
    for source in (MAIN_PY, MAIN_PYW):
        assert 'window.showMaximized()' in source
        assert 'window.show()' not in source[source.index('window = MainWindow()'):source.index('window.raise_()')]
        assert '3000 - (time.monotonic() - splash_started) * 1000' in source


def test_v2510_navigation_buttons_wrap_long_labels():
    assert '("3.  Core Scientific\\nAnalysis", "analysis")' in MAIN
    assert '("4.  Climatology &\\nAnomaly", "climatology")' in MAIN
    assert 'button.setMinimumHeight(54)' in MAIN
    assert 'button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)' in MAIN


def test_v2510_map_picker_has_visible_busy_overlay_and_progress_updates():
    assert 'self.map_busy_label = QLabel("Updating map …  Please Wait …", self.canvas)' in MAP_PICKER
    assert 'def _show_map_busy' in MAP_PICKER
    assert 'def _update_map_progress' in MAP_PICKER
    assert 'progress=self._update_map_progress' in MAP_PICKER
    assert 'QApplication.processEvents()' in MAP_PICKER


def test_v2510_renderer_accepts_progress_callback():
    assert 'Callable[[str], None] | None = None' in RENDERER
    assert 'progress(f"Loading map tiles {completed}/{total} …")' in RENDERER
    assert '_render_provider(ax, provider, bounds_web, session=session, progress=progress)' in RENDERER


def test_v2510_navigation_stylesheet_matches_taller_buttons():
    assert "QPushButton#navButton" in THEME
    assert "min-height: 54px;" in THEME
    assert "padding: 7px 10px;" in THEME
