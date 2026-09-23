"""Smoke tests for v2.3.4 spatial visualization and release contracts."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import box

from core.reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION
from core.report_validation import validate_report
from core.visualization import run_spatial_visualization, _mask_values_outside_region


def _make_standardized_temperature(root: Path) -> Path:
    out = root / "standardized"
    out.mkdir(parents=True, exist_ok=True)
    time = pd.date_range("2025-01-01", periods=2, freq="MS")
    depth = np.array([5.0, 75.0, 584.0, 2174.0, 2579.0])
    lat = np.array([22.5, 22.833333])
    lon = np.array([56.5, 57.5, 58.5])
    base = 298.15 + np.arange(len(time))[:, None, None, None]
    vals = base + np.arange(len(depth))[None, :, None, None] + np.zeros((len(time), len(depth), len(lat), len(lon)))
    vals[:, -1, :, :] = np.nan
    ds = xr.Dataset({"pottmp": (("time", "depth", "lat", "lon"), vals)},
                    coords={"time": time, "depth": depth, "lat": lat, "lon": lon})
    path = out / "pottmp.standardized.nc"
    ds.to_netcdf(path)
    return path


def test_version_contract():
    assert SOFTWARE_VERSION == "2.5.10"
    assert REPORT_SCHEMA_VERSION == "2.6.0"


def test_spatial_single_and_three_depth_exports():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_standardized_temperature(root)
        result = run_spatial_visualization(
            str(root), "temperature", "single", "2025-02-15", "celsius",
            "surface", None, None, "turbo", "auto", None, None,
            None, None, False, None, ("png", "svg", "pdf"),
        )
        assert Path(result["png"]).exists()
        assert Path(result["svg"]).exists()
        assert Path(result["pdf"]).exists()
        assert Path(result["csv"]).exists()
        assert Path(result["report"]).exists()

        report = __import__("json").loads(Path(result["report"]).read_text(encoding="utf-8"))
        assert report["software_version"] == SOFTWARE_VERSION
        assert report["schema_version"] == REPORT_SCHEMA_VERSION
        assert report["analysis_type"] == "spatial_visualization"
        assert report["map_product"] == "data_map"
        assert report["visualization"]["no_spatial_interpolation"] is True
        assert report["integrity"]["regridding"] is False
        assert validate_report(report)["status"] == "PASS"

        result3 = run_spatial_visualization(
            str(root), "temperature", "three_depths", "2025-02-15", "celsius",
            "surface", None, 75.0, "viridis", "auto", None, None,
            None, None, False, None, ("png",),
        )
        assert Path(result3["png"]).exists()
        assert result3["selected_depths"] == [5.0, 75.0, 2174.0]
        assert report["visualization"]["north_arrow"]["enabled"] is True
        assert report["visualization"]["scale_bar"]["color"] == "black"
        assert report["visualization"]["region_rendering"]["outside_region_fill"] == "light_gray"
        assert report["visualization"]["region_rendering"]["inside_region_no_data_fill"] == "white"


def test_region_mask_and_single_depth_label():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_standardized_temperature(root)
        region = box(56.4, 22.4, 57.6, 23.0)
        result = run_spatial_visualization(
            str(root), "temperature", "single", "2025-02-15", "celsius",
            "single", 75.0, None, "turbo", "auto", None, None,
            region, "Test Region", True, None, ("png",),
        )
        report = __import__("json").loads(Path(result["report"]).read_text(encoding="utf-8"))
        assert report["spatial_information"]["region_overlay"] is True
        assert report["visualization"]["north_arrow"]["enabled"] is True
        assert report["visualization"]["scale_bar"]["color"] == "black"
        assert report["visualization"]["region_rendering"]["outside_region_fill"] == "light_gray"
        assert report["visualization"]["region_rendering"]["inside_region_no_data_fill"] == "white"
        assert report["visualization"]["region_boundary"]["fit_to_region"] is True
        assert report["depth_information"]["selected_depth_levels_m"] == [75.0]


def test_visual_mask_keeps_native_grid_and_single_depth_label():
    from core.visualization import _mask_values_outside_region
    from shapely.geometry import box
    lat = np.array([22.5, 22.833333])
    lon = np.array([56.5, 57.5, 58.5])
    values = np.arange(6, dtype=float).reshape(2, 3)
    masked = _mask_values_outside_region(lat, lon, values, box(56.4, 22.4, 57.6, 23.0))
    assert np.isfinite(masked[0, 0]) and np.isfinite(masked[0, 1])
    assert not np.isfinite(masked[0, 2])
    assert not np.isfinite(masked[1, 2])


if __name__ == "__main__":
    test_version_contract()
    test_spatial_single_and_three_depth_exports()
    print("PASS")
