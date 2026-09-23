from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .reporting import SOFTWARE_VERSION
import xarray as xr

from config.variables import variable_tuple_catalog

VARIABLES = variable_tuple_catalog()
CANONICAL_DEPTH = np.array(
    [5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105, 115, 125, 135, 145, 155,
     165, 175, 185, 195, 205, 215, 225, 238, 262, 303, 366, 459, 584, 747,
     949, 1193, 1479, 1807, 2174, 2579, 3016, 3483, 3972, 4478], dtype=np.float32
)


def _same_coord(a, b, rtol=0.0, atol=1e-7) -> bool:
    av = np.asarray(a)
    bv = np.asarray(b)
    if av.shape != bv.shape:
        return False
    if np.issubdtype(av.dtype, np.number) and np.issubdtype(bv.dtype, np.number):
        return bool(np.allclose(av, bv, rtol=rtol, atol=atol, equal_nan=True))
    return bool(np.array_equal(av, bv))


def _depth_name(ds: xr.Dataset) -> str | None:
    if "depth" in ds.dims:
        return "depth"
    if "level" in ds.dims:
        return "level"
    return None


def _standardize_one(path: Path, variable_key: str) -> xr.Dataset:
    prefix, label, source_units, has_depth = VARIABLES[variable_key]
    with xr.open_dataset(path, decode_times=True, mask_and_scale=True) as src:
        ds = src.load()

    if prefix not in ds.data_vars:
        raise ValueError(f"{path.name}: expected data variable '{prefix}' was not found.")
    if "time" not in ds.coords or "lat" not in ds.coords or "lon" not in ds.coords:
        raise ValueError(f"{path.name}: required time/lat/lon coordinates are missing.")

    if has_depth:
        dname = _depth_name(ds)
        if dname is None:
            raise ValueError(f"{path.name}: no depth/level dimension found for 3-D variable.")
        if dname == "level":
            ds = ds.rename({"level": "depth"})
        depth = np.asarray(ds["depth"].values, dtype=np.float32)
        if depth.size == 0:
            raise ValueError(f"{path.name}: the depth coordinate is empty.")
        if not (np.all(np.isfinite(depth)) and (np.all(np.diff(depth) > 0) or np.all(np.diff(depth) < 0))):
            raise ValueError(f"{path.name}: native depth coordinate must be finite and strictly monotonic.")
        ds["depth"].attrs.update({
            "long_name": "Depth below sea level",
            "standard_name": "depth",
            "units": "m",
            "positive": "down",
            "axis": "Z",
        })

    # Canonical coordinate metadata.
    ds["lat"].attrs.update({"standard_name": "latitude", "units": "degrees_north", "axis": "Y"})
    ds["lon"].attrs.update({"standard_name": "longitude", "units": "degrees_east", "axis": "X"})
    ds["time"].attrs.update({"standard_name": "time", "axis": "T"})

    da = ds[prefix]
    ds[prefix].attrs.setdefault("long_name", label)
    ds[prefix].attrs["godas_variable_key"] = variable_key
    ds.attrs["standardization"] = "Canonical coordinates; GODAS level renamed to depth where applicable"
    return ds[[prefix]]


def _list_files(root: Path, variable_key: str) -> list[Path]:
    prefix = VARIABLES[variable_key][0]
    folder = root / variable_key
    return sorted(folder.glob(f"{prefix}.*.nc")) if folder.exists() else []


def _validate_time_series(datasets: list[xr.Dataset], variable_key: str):
    if not datasets:
        raise ValueError(f"No files found for {variable_key}.")
    for i in range(1, len(datasets)):
        if not _same_coord(datasets[0]["lat"].values, datasets[i]["lat"].values):
            raise ValueError(f"{variable_key}: latitude grid differs between yearly files.")
        if not _same_coord(datasets[0]["lon"].values, datasets[i]["lon"].values):
            raise ValueError(f"{variable_key}: longitude grid differs between yearly files.")
        if "depth" in datasets[0].coords or "depth" in datasets[i].coords:
            if "depth" not in datasets[0].coords or "depth" not in datasets[i].coords:
                raise ValueError(f"{variable_key}: depth coordinate is inconsistent between yearly files.")
            if not _same_coord(datasets[0]["depth"].values, datasets[i]["depth"].values, atol=1e-4):
                raise ValueError(f"{variable_key}: depth grid differs between yearly files.")


def _concat_variable(root: Path, variable_key: str, progress: Callable[[str], None] | None = None) -> tuple[xr.Dataset, dict]:
    files = _list_files(root, variable_key)
    if not files:
        raise ValueError(f"No regional NetCDF files found for {variable_key}.")
    if progress:
        progress(f"[STD] {variable_key}: standardizing {len(files)} file(s)...")
    datasets = [_standardize_one(p, variable_key) for p in files]
    _validate_time_series(datasets, variable_key)
    ds = xr.concat(datasets, dim="time", data_vars="minimal", coords="minimal", compat="override", join="exact")
    time_values = pd.to_datetime(ds.time.values)
    if pd.Index(time_values).duplicated().any():
        raise ValueError(f"{variable_key}: duplicate time records found while integrating files.")
    ds = ds.sortby("time")
    return ds, {
        "variable_key": variable_key,
        "files": [p.name for p in files],
        "time_count": int(ds.sizes.get("time", 0)),
        "time_start": str(time_values.min()),
        "time_end": str(time_values.max()),
        "lat_count": int(ds.sizes.get("lat", 0)),
        "lon_count": int(ds.sizes.get("lon", 0)),
        "depth_count": int(ds.sizes.get("depth", 0)),
    }


def _write_variable(ds: xr.Dataset, out: Path):
    encoding = {name: {"zlib": True, "complevel": 4} for name in ds.data_vars}
    ds.to_netcdf(out, mode="w", format="NETCDF4", encoding=encoding)


def _prepare_master(datasets: dict[str, xr.Dataset], metadata: dict) -> tuple[xr.Dataset, list[str]]:
    warnings: list[str] = []
    prepared = []
    time_reference = None
    depth_reference = None

    for key, ds in datasets.items():
        varname = VARIABLES[key][1]
        # All variables should share monthly timestamps. If not, preserve the
        # union rather than silently dropping records, and report the mismatch.
        if time_reference is None:
            time_reference = ds.time.values
        elif not _same_coord(time_reference, ds.time.values):
            warnings.append(f"Time axis differs for {key}; master dataset uses the union of timestamps.")

        if "depth" in ds.coords:
            if depth_reference is None:
                depth_reference = ds.depth.values
            elif not _same_coord(depth_reference, ds.depth.values, atol=1e-4):
                warnings.append(f"Depth grid differs for {key}; depth was kept as a variable-specific coordinate.")
                ds = ds.rename({"depth": f"depth_{key}"})

        # GODAS tracer fields and currents are on horizontally offset native grids:
        # pottmp/salt use 0.5, 1.5, ... lon and lat around -74.5, ..., while
        # currents use 1.0, 2.0, ... and -74.0, ... . Do not silently interpolate.
        # Rename spatial dimensions per variable so the native grids remain intact.
        rename_map = {"lat": f"lat_{key}", "lon": f"lon_{key}"}
        ds = ds.rename(rename_map)
        prepared.append(ds)

    master = xr.merge(prepared, join="outer", compat="no_conflicts", combine_attrs="override")
    master.attrs.update({
        "title": "GODAS Regional Master Dataset — native-grid integration",
        "source": "NOAA NCEP Global Ocean Data Assimilation System (GODAS)",
        "processing": "Regional polygon-masked GODAS files standardized and integrated without horizontal interpolation",
        "integration_policy": "Native horizontal grids preserved; no silent regridding",
        "variables": ", ".join(datasets.keys()),
        "created_utc": metadata["created_utc"],
        "tool_version": metadata["tool_version"],
    })
    return master, warnings


def standardize_and_integrate(output_dir: str, progress=None, tool_version: str | None = None) -> dict:
    root = Path(output_dir)
    if not root.exists():
        raise ValueError("Output directory does not exist.")

    standard_dir = root / "standardized"
    standard_dir.mkdir(exist_ok=True)
    integration_dir = root / "integration"
    integration_dir.mkdir(exist_ok=True)

    created_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    datasets: dict[str, xr.Dataset] = {}
    reports = []

    for key in VARIABLES:
        files = _list_files(root, key)
        if not files:
            continue
        ds, report = _concat_variable(root, key, progress=progress)
        datasets[key] = ds
        reports.append(report)
        out_file = standard_dir / f"{VARIABLES[key][0]}.standardized.nc"
        _write_variable(ds, out_file)
        if progress:
            progress(f"[STD OK] {key}: {out_file.name}")

    if not datasets:
        raise ValueError("No regional GODAS NetCDF files are available for standardization.")

    tool_version = tool_version or f"GODAS Regional Data Tool v{SOFTWARE_VERSION}"
    metadata = {"created_utc": created_utc, "tool_version": tool_version}
    master, warnings = _prepare_master(datasets, metadata)
    master_file = integration_dir / "GODAS_Regional_Master_native_grid.nc"
    _write_variable(master, master_file)

    report = {
        "created_utc": created_utc,
        "tool_version": tool_version,
        "standardized_directory": str(standard_dir),
        "master_file": str(master_file),
        "integration_mode": "native-grid",
        "horizontal_regridding_performed": False,
        "warnings": warnings,
        "variables": reports,
        "master_dimensions": {k: int(v) for k, v in master.sizes.items()},
        "master_variables": list(master.data_vars),
    }
    report_path = integration_dir / f"Integration_report_{created_utc}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    csv_rows = []
    for item in reports:
        csv_rows.append(item)
    csv_path = integration_dir / f"Integration_summary_{created_utc}.csv"
    pd.DataFrame(csv_rows).to_csv(csv_path, index=False)

    if progress:
        progress(f"[MASTER OK] Created {master_file.name}")
        if warnings:
            for w in warnings:
                progress(f"[STD WARN] {w}")
        progress(f"[STD SUMMARY] Variables={len(datasets)}, warnings={len(warnings)}")
        progress(f"[STD] Report: {report_path.name}")
        progress(f"[STD] Summary: {csv_path.name}")

    for ds in datasets.values():
        ds.close()
    master.close()

    return {
        "variables": len(datasets),
        "master": str(master_file),
        "report": str(report_path),
        "summary": str(csv_path),
        "warnings": len(warnings),
    }
