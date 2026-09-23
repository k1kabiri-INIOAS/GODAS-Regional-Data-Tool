from pathlib import Path


def test_v257_map_picker_releases_pan_zoom_before_rectangle():
    text = (Path(__file__).resolve().parents[1] / "gui" / "map_picker.py").read_text(encoding="utf-8")
    assert "def _disable_navigation_tools(self):" in text
    assert "self._disable_navigation_tools()" in text
    assert "interactive=False" in text


def test_v257_map_picker_emits_bounds_contract():
    text = (Path(__file__).resolve().parents[1] / "gui" / "map_picker.py").read_text(encoding="utf-8")
    assert "boundsSelected = Signal(float, float, float, float)" in text
    assert "self.boundsSelected.emit(*bounds)" in text


def test_v257_parent_connects_map_picker_signal():
    text = (Path(__file__).resolve().parents[1] / "gui" / "main_window.py").read_text(encoding="utf-8")
    assert "dialog.boundsSelected.connect(self._apply_map_selected_bbox)" in text
