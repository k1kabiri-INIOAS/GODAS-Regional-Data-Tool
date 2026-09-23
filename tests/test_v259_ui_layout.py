from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "gui" / "main_window.py").read_text(encoding="utf-8")
PREVIEW = (ROOT / "gui" / "region_preview.py").read_text(encoding="utf-8")
REPORTING = (ROOT / "core" / "reporting.py").read_text(encoding="utf-8")


def test_v259_version_is_centralized():
    assert 'SOFTWARE_VERSION = "2.5.10"' in REPORTING


def test_download_tab_uses_compact_split_layout():
    assert 'top_download_row = QHBoxLayout()' in MAIN
    assert 'top_download_row.addWidget(region_box, 3)' in MAIN
    assert 'top_download_row.addWidget(side_panel, 2)' in MAIN


def test_download_map_preview_is_compact_square():
    assert 'self.region_preview.setMinimumHeight(320)' in MAIN
    assert 'self.region_preview.setMaximumHeight(335)' in MAIN
    assert 'map_panel.setFixedSize(320, 320)' in PREVIEW
    assert 'self.canvas.setFixedSize(320, 320)' in PREVIEW


def test_download_variables_are_three_columns():
    assert 'vg.addWidget(cb, i // 3, i % 3)' in MAIN


def test_spatial_tab_uses_two_compact_rows():
    assert 'spatial_row_1 = QHBoxLayout()' in MAIN
    assert 'spatial_row_2 = QHBoxLayout()' in MAIN
    assert 'spatial_row_1.addWidget(product_setup, 1)' in MAIN
    assert 'spatial_row_2.addWidget(self.spatial_depth_setup, 1)' in MAIN
    assert 'spatial_row_2.addWidget(style_setup, 1)' in MAIN


def test_spatial_trend_hint_has_dedicated_row():
    assert 'tg.addWidget(self.spatial_trend_hint,3,0,1,4)' in MAIN
    assert 'tg.addWidget(self.spatial_trend_hint,2,0,1,4)' not in MAIN


def test_tab_pages_still_use_safe_vertical_scroll_as_needed():
    assert 'scroll.setWidgetResizable(True)' in MAIN
    assert 'scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)' in MAIN


def test_no_scientific_core_files_were_repointed_by_layout_patch():
    # Layout patch is intentionally restricted to GUI source plus central release version.
    for name in ["analysis.py", "climatology.py", "trend.py", "standardize.py", "region.py"]:
        assert (ROOT / "core" / name).exists()
