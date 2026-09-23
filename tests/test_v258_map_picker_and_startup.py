from pathlib import Path


def test_v258_dark_mode_cursor_label_has_explicit_contrast():
    source = Path(__file__).resolve().parents[1] / "gui" / "map_picker.py"
    text = source.read_text(encoding="utf-8")
    assert "QLabel#mapCursorCoordinates" in text
    assert "color: #253746" in text
    assert "background: #eef2f5" in text


def test_v258_interactive_map_has_wheel_zoom_and_left_pan():
    source = Path(__file__).resolve().parents[1] / "gui" / "map_picker.py"
    text = source.read_text(encoding="utf-8")
    assert 'mpl_connect("button_press_event", self._mouse_press)' in text
    assert 'mpl_connect("button_release_event", self._mouse_release)' in text
    assert 'mpl_connect("scroll_event", self._mouse_scroll)' in text
    assert "ClosedHandCursor" in text
    assert "def _mouse_scroll" in text


def test_v258_rectangle_disables_custom_pan_state():
    source = Path(__file__).resolve().parents[1] / "gui" / "map_picker.py"
    text = source.read_text(encoding="utf-8")
    assert "self._pan_active = False" in text
    assert "def start_rectangle" in text
    assert "self._disable_navigation_tools()" in text


def test_v258_splash_is_shown_before_main_window_import():
    for name in ("main.py", "main.pyw"):
        source = Path(__file__).resolve().parents[1] / name
        text = source.read_text(encoding="utf-8")
        splash_pos = text.index("splash.show()")
        import_pos = text.index("from gui.main_window import MainWindow", text.index("def _run_gui"))
        assert splash_pos < import_pos
        assert "splash_started = time.monotonic()" in text
        assert "3000" in text
