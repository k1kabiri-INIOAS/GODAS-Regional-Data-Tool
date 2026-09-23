"""Lightweight regression/smoke checks for GODAS Regional Data Tool v2.3.2.

These tests preserve the scientific algorithms validated in v2.1.6 and verify the
v2.2.1 depth-independent completeness correction (preserved in v2.3.1), report contract, and trend primitives.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

from core.report_validation import validate_report
from core.reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION
from core.standardize import standardize_and_integrate
from core.trend import _ols, _mk, _sen, _time_years
from core.climatology import _aggregate, _complete_annual_means, _complete_season_means, SEASONS
import xarray as xr


def test_report_contract() -> None:
    report = {
        "software_version": SOFTWARE_VERSION,
        "schema_version": REPORT_SCHEMA_VERSION,
        "analysis_type": "trend",
        "variable": "mld",
        "period": {"start": "1980-01-01", "end": "2026-12-31"},
        "observation_coverage": {},
        "depth_information": {"depth_mode": "not_applicable"},
        "source_file": "synthetic.nc",
        "source_units": "m",
        "output_units": "m",
        "unit_conversion": "none; source GODAS units retained",
        "processing": {
            "spatial_weighting": "cos(latitude)",
            "native_grid_preserved": True,
            "regridding": False,
            "vertical_interpolation": False,
            "interpolation": False,
            "extrapolation": False,
            "gap_filling": False,
            "autocorrelation_correction": "none",
            "unit_conversion": "none; source GODAS units retained",
            "source_units": "m",
            "output_units": "m",
        },
        "integrity": {"status": "PASS"},
        "outputs": {"report": "synthetic.json"},
    }
    assert validate_report(report)["status"] == "PASS"



def test_release_version_consistency() -> None:
    import inspect
    assert SOFTWARE_VERSION == "2.5.10"
    assert REPORT_SCHEMA_VERSION == "2.6.0"
    assert inspect.signature(standardize_and_integrate).parameters["tool_version"].default is None


def test_trend_primitives() -> None:
    times = pd.date_range("2000-01-01", periods=60, freq="MS")
    x = _time_years(times)
    y = 12.0 + 0.2 * x + 0.02 * np.sin(np.arange(60) / 3.0)
    ols = _ols(x, y)
    mk = _mk(x, y)
    sen = _sen(x, y)
    assert ols["status"] == mk["status"] == sen["status"] == "ok"
    assert np.isclose(ols["slope"], 0.2, atol=0.01)
    assert np.sign(ols["slope"]) == np.sign(sen["sen_slope"]) == np.sign(mk["kendall_tau"])




def _synthetic_depth_series():
    times = pd.date_range("2000-01-01", periods=48, freq="MS")
    depth = np.array([5.0, 15.0, 2579.0])
    vals = np.empty((48, 3), dtype=float)
    vals[:, 0] = np.arange(48, dtype=float)
    vals[:, 1] = 10.0 + np.arange(48, dtype=float)
    vals[:, 2] = np.nan
    return xr.DataArray(vals, coords={"time": times, "depth": depth}, dims=("time", "depth"), name="pottmp")


def test_depth_independent_annual_completeness() -> None:
    da = _synthetic_depth_series()
    out = _complete_annual_means(da)
    assert out.sizes["year"] == 4
    assert np.isfinite(out.sel(depth=5.0)).all()
    assert np.isfinite(out.sel(depth=15.0)).all()
    assert np.isnan(out.sel(depth=2579.0)).all()


def test_depth_independent_seasonal_climatology() -> None:
    da = _synthetic_depth_series()
    clim = _aggregate(da, "seasonal")
    assert set(map(str, clim.period.values)) == set(SEASONS)
    assert np.isfinite(clim.sel(period="DJF", depth=5.0))
    assert np.isfinite(clim.sel(period="DJF", depth=15.0))
    assert np.isnan(clim.sel(period="DJF", depth=2579.0))


def test_complete_season_means_preserve_valid_depths() -> None:
    da = _synthetic_depth_series()
    seasons, sy = __import__("core.climatology", fromlist=["_season_year_index"])._season_year_index(da.time.values)
    tagged = da.assign_coords(season=("time", seasons.astype(str)), season_year=("time", sy))
    out = _complete_season_means(tagged)
    assert out.sizes["season_year"] > 0
    assert np.isfinite(out.sel(depth=5.0)).any()
    assert np.isnan(out.sel(depth=2579.0)).all()


if __name__ == "__main__":
    test_report_contract()
    test_trend_primitives()
    test_depth_independent_annual_completeness()
    test_depth_independent_seasonal_climatology()
    test_complete_season_means_preserve_valid_depths()
    test_release_version_consistency()
    print(json.dumps({"status": "PASS", "tests": 5}, indent=2))
