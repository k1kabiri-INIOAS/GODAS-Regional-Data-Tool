"""Smoke tests for the v2.4.1 Map Composer foundation."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import box

from core.reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION
from core.report_validation import validate_report
from core.visualization import run_map_product


def _make_standardized(root: Path) -> None:
    out = root / "standardized"
    out.mkdir(parents=True, exist_ok=True)
    time = pd.date_range("2000-01-01", "2025-12-01", freq="MS")
    depth = np.array([5.0, 75.0, 584.0, 2174.0, 2579.0])
    lat = np.array([22.5, 22.833333, 23.166667])
    lon = np.array([56.5, 57.5, 58.5, 59.5])
    t = np.arange(len(time), dtype=float)[:, None, None, None]
    d = np.arange(len(depth), dtype=float)[None, :, None, None]
    y = np.arange(len(lat), dtype=float)[None, None, :, None]
    x = np.arange(len(lon), dtype=float)[None, None, None, :]
    vals = 298.15 + 0.02 * t + 0.7 * d + 0.1 * y + 0.05 * x
    vals[:, -1, :, :] = np.nan
    ds = xr.Dataset(
        {"pottmp": (("time", "depth", "lat", "lon"), vals)},
        coords={"time": time, "depth": depth, "lat": lat, "lon": lon},
    )
    ds.to_netcdf(out / "pottmp.standardized.nc")


def _common(region):
    return {
        "variable_key": "temperature",
        "unit_mode": "celsius",
        "depth_mode": "single",
        "depth_value": 75.0,
        "cmap": "turbo",
        "color_mode": "auto",
        "region_geometry": region,
        "region_label": "Gulf of Oman",
        "show_boundary": True,
        "formats": ["png", "svg"],
    }


def test_version_contract():
    assert SOFTWARE_VERSION == "2.5.10"
    assert REPORT_SCHEMA_VERSION == "2.6.0"


def test_all_map_products():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_standardized(root)
        region = box(56.4, 22.4, 59.0, 23.2)
        products = [
            ("data_map", {"map_layout": "single", "requested_date": "2025-07-01", "single_depth_mode": "single", "single_depth": 75.0}),
            ("climatology_map", {"period_mode": "monthly", "baseline_start": "2000-01-01", "baseline_end": "2025-12-31", "period_value": 7}),
            ("anomaly_map", {"period_mode": "monthly", "baseline_start": "2000-01-01", "baseline_end": "2024-12-31", "target_date": "2025-07-01", "period_value": 7}),
            ("trend_map", {"trend_mode": "annual", "trend_start": "2000-01-01", "trend_end": "2025-12-31", "trend_method": "ols"}),
        ]
        for product, extra in products:
            params = _common(region)
            params.update({"product": product, **extra})
            result = run_map_product(str(root), params)
            assert Path(result["png"]).exists()
            assert Path(result["csv"]).exists()
            assert Path(result["report"]).exists()
            report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
            assert report["software_version"] == SOFTWARE_VERSION
            assert report["schema_version"] == REPORT_SCHEMA_VERSION
            assert report["analysis_type"] == "spatial_visualization"
            assert report["map_product"] == product
            assert report["integrity"]["native_grid_only"] is True
            assert report["processing"]["regridding"] is False
            assert validate_report(report)["status"] == "PASS"


def test_seasonal_and_annual_products():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_standardized(root)
        region = box(56.4, 22.4, 59.0, 23.2)
        for product, extra in [
            ("climatology_map", {"period_mode": "seasonal", "baseline_start": "2000-01-01", "baseline_end": "2025-12-31", "period_value": "JJA"}),
            ("climatology_map", {"period_mode": "annual", "baseline_start": "2000-01-01", "baseline_end": "2025-12-31", "period_value": None}),
            ("anomaly_map", {"period_mode": "seasonal", "baseline_start": "2000-01-01", "baseline_end": "2024-12-31", "target_season": "JJA", "target_year": 2025, "period_value": "JJA"}),
            ("anomaly_map", {"period_mode": "annual", "baseline_start": "2000-01-01", "baseline_end": "2024-12-31", "target_year": 2025, "period_value": None}),
            ("trend_map", {"trend_mode": "monthly", "trend_start": "2000-01-01", "trend_end": "2025-12-31", "trend_method": "sen"}),
            ("trend_map", {"trend_mode": "seasonal", "trend_season": "JJA", "trend_start": "2000-01-01", "trend_end": "2025-12-31", "trend_method": "mk"}),
        ]:
            params = _common(region)
            params.update({"product": product, **extra})
            result = run_map_product(str(root), params)
            report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
            assert report["integrity"]["status"] == "PASS"
            assert validate_report(report)["status"] == "PASS"


if __name__ == "__main__":
    test_version_contract()
    test_all_map_products()
    test_seasonal_and_annual_products()
    print("PASS")
