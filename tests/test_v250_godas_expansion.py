"""v2.5.2 regression tests for GODAS catalog expansion and region selection."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import box, Polygon

from config.variables import GODAS_VARIABLES
from core.region import make_map_region
from core.visualization import run_map_product
from core.reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION


EXPECTED_KEYS = {
    "temperature", "salinity", "u_current", "v_current", "vertical_velocity",
    "mld", "isothermal_layer_depth", "sea_surface_height", "surface_heat_flux",
    "surface_salt_flux", "u_momentum_flux", "v_momentum_flux",
}


def _write_standardized(root: Path) -> None:
    out = root / "standardized"
    out.mkdir(parents=True, exist_ok=True)
    time = pd.date_range("1994-01-01", "1996-12-01", freq="MS")
    depth = np.array([5.0, 75.0, 584.0, 2174.0])
    lat = np.array([22.5, 22.833333])
    lon = np.array([56.5, 57.5, 58.5])
    n = len(time)
    base = np.arange(n, dtype=float)[:, None, None, None]
    depth_term = np.arange(len(depth), dtype=float)[None, :, None, None]
    vals = 300.0 + base + depth_term + np.zeros((n, len(depth), len(lat), len(lon)))
    ds = xr.Dataset({"pottmp": (("time", "depth", "lat", "lon"), vals)},
                    coords={"time": time, "depth": depth, "lat": lat, "lon": lon})
    ds.to_netcdf(out / "pottmp.standardized.nc")

    # A representative 2-D product to ensure expanded surface variables stay depth-independent.
    surf = 2.0 + np.arange(n, dtype=float)[:, None, None] + np.zeros((n, len(lat), len(lon)))
    xr.Dataset({"sshg": (("time", "lat", "lon"), surf)},
               coords={"time": time, "lat": lat, "lon": lon}).to_netcdf(out / "sshg.standardized.nc")


def test_catalog_has_all_primary_monthly_variables():
    assert SOFTWARE_VERSION == "2.5.10"
    assert REPORT_SCHEMA_VERSION == "2.6.0"
    assert set(GODAS_VARIABLES) == EXPECTED_KEYS
    for key, meta in GODAS_VARIABLES.items():
        assert meta["dataset"]
        assert meta["units"]
        assert isinstance(meta["has_depth"], bool)
        assert meta["unit_options"]



def test_all_modules_share_the_same_variable_catalog():
    from core.analysis import VARIABLES as analysis_vars
    from core.downloader import DATASETS as downloader_vars
    from core.qc import EXPECTED as qc_vars
    from core.standardize import VARIABLES as standardize_vars
    from core.visualization import VARIABLES as visualization_vars
    from core.trend import VARIABLES as trend_vars
    assert set(analysis_vars) == EXPECTED_KEYS
    assert set(downloader_vars) == EXPECTED_KEYS
    assert set(qc_vars) == EXPECTED_KEYS
    assert set(standardize_vars) == EXPECTED_KEYS
    assert set(visualization_vars) == EXPECTED_KEYS
    assert set(trend_vars) == EXPECTED_KEYS


def test_standardization_accepts_variable_specific_dzdt_depth_grid():
    from core.standardize import _standardize_one
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "dzdt.1995.nc"
        time = pd.date_range("1995-01-01", periods=2, freq="MS")
        depth = np.array([10.0, 50.0, 200.0])
        lat = np.array([22.5, 22.833333])
        lon = np.array([56.5, 57.5])
        vals = np.ones((2,3,2,2), dtype=float)
        xr.Dataset({"dzdt": (("time","depth","lat","lon"), vals)},
                   coords={"time":time,"depth":depth,"lat":lat,"lon":lon}).to_netcdf(path)
        ds = _standardize_one(path, "vertical_velocity")
        assert ds.sizes["depth"] == 3
        assert np.allclose(ds.depth.values, depth)
        assert ds["dzdt"].attrs["godas_variable_key"] == "vertical_velocity"
        ds.close()

def test_map_region_preserves_polygon_geometry_and_bounds():
    geom = Polygon([(56.2, 22.4), (57.1, 22.4), (57.2, 23.1), (56.5, 23.3), (56.2, 22.4)])
    spec = make_map_region(geom, "Test Map Region")
    assert spec.source_type == "map_polygon"
    assert spec.code == "MAP_REGION"
    assert spec.label == "Test Map Region"
    assert np.isclose(spec.xmin, 56.2)
    assert np.isclose(spec.ymax, 23.3)


def test_single_year_djf_climatology_uses_supporting_previous_december():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_standardized(root)
        region = box(56.4, 22.4, 57.6, 23.0)
        params = {
            "product": "climatology_map",
            "variable_key": "temperature",
            "unit_mode": "celsius",
            "depth_mode": "single",
            "depth_value": 75.0,
            "period_mode": "seasonal",
            "baseline_start": "1995-01-01",
            "baseline_end": "1995-12-31",
            "period_value": "DJF",
            "cmap": "turbo", "color_mode": "auto", "region_geometry": region,
            "region_label": "Gulf of Oman", "show_boundary": True,
            "formats": ["png"],
        }
        result = run_map_product(str(root), params)
        report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
        assert report["map_product"] == "climatology_map"
        assert report["climatology_period"] == "DJF"
        assert report["season_definition"].startswith("DJF = December")
        assert report["supporting_months_used"] == ["1994-12"]
        assert report["period"] == {"start": "1995-01-01", "end": "1995-12-31"}


def test_surface_variable_map_for_expanded_catalog():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        _write_standardized(root)
        region=box(56.4,22.4,57.6,23.0)
        params={
            "product":"data_map","variable_key":"sea_surface_height","unit_mode":"native",
            "map_layout":"single","requested_date":"1995-07-01","single_depth_mode":"surface",
            "cmap":"viridis","color_mode":"auto","region_geometry":region,
            "region_label":"Gulf of Oman","show_boundary":True,"formats":["png"],
        }
        result=run_map_product(str(root),params)
        assert Path(result["png"]).exists()


if __name__ == "__main__":
    test_catalog_has_all_primary_monthly_variables()
    test_map_region_preserves_polygon_geometry_and_bounds()
    test_single_year_djf_climatology_uses_supporting_previous_december()
    test_surface_variable_map_for_expanded_catalog()
    print("PASS")
