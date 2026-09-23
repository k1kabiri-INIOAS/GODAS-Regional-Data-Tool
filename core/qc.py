from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from config.variables import GODAS_VARIABLES

EXPECTED = {
    key: {"prefix": meta["dataset"], "data_var": meta["dataset"], "has_depth": bool(meta["has_depth"])}
    for key, meta in GODAS_VARIABLES.items()
}
DEPTH_DIM_NAMES = ("depth", "level")


def _safe_float(value):
    try:
        value = float(value)
        return value if np.isfinite(value) else None
    except Exception:
        return None


def _find_depth_name(ds: xr.Dataset) -> str | None:
    for name in DEPTH_DIM_NAMES:
        if name in ds.dims:
            return name
    return None


def _time_summary(ds):
    if "time" not in ds.coords:
        return {"time_count": 0, "time_start": None, "time_end": None, "duplicate_times": 0, "monthly_gaps": None}
    t = pd.to_datetime(ds["time"].values)
    if len(t) == 0:
        return {"time_count": 0, "time_start": None, "time_end": None, "duplicate_times": 0, "monthly_gaps": None}
    periods = pd.PeriodIndex(t, freq="M")
    unique_periods = periods.unique().sort_values()
    gaps = 0
    if len(unique_periods) > 1:
        expected = pd.period_range(unique_periods[0], unique_periods[-1], freq="M")
        gaps = int(len(expected.difference(unique_periods)))
    return {
        "time_count": int(len(t)),
        "time_start": str(t.min()),
        "time_end": str(t.max()),
        "duplicate_times": int(pd.Index(t).duplicated().sum()),
        "monthly_gaps": gaps,
    }


def _coordinate_summary(ds: xr.Dataset, coord: str):
    vals = np.asarray(ds[coord].values)
    return {
        "count": int(vals.size),
        "min": _safe_float(np.nanmin(vals)) if vals.size else None,
        "max": _safe_float(np.nanmax(vals)) if vals.size else None,
        "monotonic_increasing": bool(np.all(np.diff(vals) > 0)) if vals.size > 1 else True,
        "monotonic_decreasing": bool(np.all(np.diff(vals) < 0)) if vals.size > 1 else True,
    }


def inspect_netcdf(path: str | Path, variable_key: str | None = None) -> dict:
    path = Path(path)
    result = {
        "file": path.name,
        "path": str(path),
        "file_size_mb": round(path.stat().st_size / 1024**2, 3) if path.exists() else 0,
        "status": "PASS",
        "warnings": [],
        "errors": [],
    }
    if not path.exists() or path.stat().st_size < 1000:
        result["status"] = "FAIL"
        result["errors"].append("File is missing or unexpectedly small.")
        return result

    try:
        with xr.open_dataset(path, decode_times=True, mask_and_scale=True) as ds:
            result["dimensions"] = {k: int(v) for k, v in ds.sizes.items()}
            result["coordinates"] = list(ds.coords)
            result["data_variables"] = list(ds.data_vars)
            result["global_attributes"] = dict(ds.attrs)

            expected = EXPECTED.get(variable_key or "")
            if expected:
                if expected["data_var"] not in ds.data_vars:
                    result["errors"].append(f"Expected data variable '{expected['data_var']}' not found.")

                depth_name = _find_depth_name(ds)
                if expected["has_depth"] and depth_name is None:
                    result["errors"].append(
                        "Expected a depth/level dimension for this 3-D variable."
                    )
                if not expected["has_depth"] and depth_name is not None:
                    result["warnings"].append(
                        f"Unexpected vertical dimension '{depth_name}' found for this variable."
                    )
                result["depth_dimension"] = depth_name

            for coord in ("time", "lat", "lon"):
                if coord not in ds.coords:
                    result["errors"].append(f"Missing required coordinate: {coord}.")

            for coord in ("lat", "lon"):
                if coord in ds.coords:
                    result.setdefault("coordinate_summary", {})[coord] = _coordinate_summary(ds, coord)
                    s = result["coordinate_summary"][coord]
                    if s["count"] > 1 and not (s["monotonic_increasing"] or s["monotonic_decreasing"]):
                        result["warnings"].append(f"Coordinate '{coord}' is not monotonic.")

            depth_name = result.get("depth_dimension")
            if depth_name and depth_name in ds.coords:
                result.setdefault("coordinate_summary", {})["depth"] = _coordinate_summary(ds, depth_name)
                result["depth_count"] = int(ds.sizes.get(depth_name, 0))
                depth_units = ds[depth_name].attrs.get("units")
                if depth_units and str(depth_units).lower() not in {"m", "meter", "meters", "metre", "metres"}:
                    result["warnings"].append(f"Unexpected depth units: {depth_units}")
            else:
                result["depth_count"] = 0

            result["time_summary"] = _time_summary(ds)
            if result["time_summary"]["duplicate_times"]:
                result["errors"].append("Duplicate time records detected.")
            if result["time_summary"]["monthly_gaps"]:
                result["warnings"].append(
                    f"{result['time_summary']['monthly_gaps']} monthly gap(s) detected in the time axis."
                )

            data_var = expected["data_var"] if expected and expected["data_var"] in ds.data_vars else None
            if data_var is None and ds.data_vars:
                data_var = list(ds.data_vars)[0]
            if data_var:
                da = ds[data_var]
                arr = np.asarray(da.values)
                finite = np.isfinite(arr)
                finite_fraction = float(finite.mean()) if arr.size else None
                result["variable_summary"] = {
                    "name": data_var,
                    "dims": list(da.dims),
                    "shape": [int(x) for x in da.shape],
                    "dtype": str(da.dtype),
                    "units": da.attrs.get("units"),
                    "long_name": da.attrs.get("long_name"),
                    "finite_count": int(finite.sum()),
                    "nan_count": int((~finite).sum()),
                    "finite_fraction": round(finite_fraction, 6) if finite_fraction is not None else None,
                    "min": _safe_float(np.nanmin(arr)) if finite.any() else None,
                    "max": _safe_float(np.nanmax(arr)) if finite.any() else None,
                    "mean": _safe_float(np.nanmean(arr)) if finite.any() else None,
                }
                # Do not treat a low global finite fraction as a failure/warning:
                # polygon masking and land/bottom NaNs are expected in regional GODAS files.
                if not finite.any():
                    result["errors"].append("Data variable contains no finite values.")

            for attr in ("requested_start_date", "requested_end_date", "source_url", "region_definition_type", "region_label", "region_source"):
                if attr not in ds.attrs:
                    result["warnings"].append(f"Missing provenance attribute: {attr}.")
            if str(ds.attrs.get("region_definition_type", "")).lower() == "shapefile" and "region_shapefile" not in ds.attrs:
                result["warnings"].append("Missing provenance attribute: region_shapefile.")

    except Exception as exc:
        result["status"] = "FAIL"
        result["errors"].append(f"Could not open/read NetCDF: {exc}")
        return result

    if result["errors"]:
        result["status"] = "FAIL"
    elif result["warnings"]:
        result["status"] = "PASS_WITH_WARNINGS"
    return result


def run_qc(output_dir: str, progress=None) -> dict:
    """Scan regional GODAS NetCDF outputs and create CSV + JSON QC reports."""
    root = Path(output_dir)
    if not root.exists():
        raise ValueError("Output directory does not exist.")

    records = []
    for variable_key, spec in EXPECTED.items():
        folder = root / variable_key
        if not folder.exists():
            continue
        files = sorted(folder.glob(f"{spec['prefix']}.*.nc"))
        for path in files:
            if progress:
                progress(f"[QC] Inspecting {variable_key}: {path.name}")
            records.append(inspect_netcdf(path, variable_key))

    if not records:
        raise ValueError("No regional GODAS NetCDF files were found in the output directory.")

    report_dir = root / "qc"
    report_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    flat = []
    for r in records:
        ts = r.get("time_summary", {})
        vs = r.get("variable_summary", {})
        flat.append({
            "file": r["file"],
            "variable": vs.get("name"),
            "status": r["status"],
            "size_mb": r["file_size_mb"],
            "time_count": ts.get("time_count"),
            "time_start": ts.get("time_start"),
            "time_end": ts.get("time_end"),
            "duplicate_times": ts.get("duplicate_times"),
            "monthly_gaps": ts.get("monthly_gaps"),
            "depth_dimension": r.get("depth_dimension"),
            "depth_count": r.get("depth_count", 0),
            "lat_count": r.get("dimensions", {}).get("lat", 0),
            "lon_count": r.get("dimensions", {}).get("lon", 0),
            "units": vs.get("units"),
            "min": vs.get("min"),
            "max": vs.get("max"),
            "mean": vs.get("mean"),
            "finite_fraction": vs.get("finite_fraction"),
            "warnings": " | ".join(r.get("warnings", [])),
            "errors": " | ".join(r.get("errors", [])),
        })

    csv_path = report_dir / f"QC_summary_{timestamp}.csv"
    json_path = report_dir / f"QC_report_{timestamp}.json"
    pd.DataFrame(flat).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps({
        "created_utc": timestamp,
        "output_directory": str(root),
        "files_checked": len(records),
        "pass": sum(r["status"] == "PASS" for r in records),
        "pass_with_warnings": sum(r["status"] == "PASS_WITH_WARNINGS" for r in records),
        "fail": sum(r["status"] == "FAIL" for r in records),
        "results": records,
    }, indent=2, default=str), encoding="utf-8")

    summary = {
        "files_checked": len(records),
        "pass": sum(r["status"] == "PASS" for r in records),
        "pass_with_warnings": sum(r["status"] == "PASS_WITH_WARNINGS" for r in records),
        "fail": sum(r["status"] == "FAIL" for r in records),
        "csv": str(csv_path),
        "json": str(json_path),
    }
    if progress:
        progress(
            f"[QC SUMMARY] Files={summary['files_checked']}, PASS={summary['pass']}, "
            f"WARN={summary['pass_with_warnings']}, FAIL={summary['fail']}"
        )
        progress(f"[QC] CSV report: {csv_path.name}")
        progress(f"[QC] JSON report: {json_path.name}")
    return summary
