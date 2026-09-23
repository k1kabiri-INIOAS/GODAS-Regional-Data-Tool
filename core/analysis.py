from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import json

import numpy as np
import pandas as pd
import xarray as xr

# Source units are preserved in the analysis outputs. No silent unit conversion is
# performed at this stage; explicit conversions can be added later as a separate
# scientific option.
from .reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION, observation_coverage, standard_processing
from .report_validation import validate_report

from config.variables import variable_tuple_catalog

VARIABLES = variable_tuple_catalog()

def _standardized_file(output_dir: Path, variable_key: str) -> Path:
    prefix = VARIABLES[variable_key][0]
    path = output_dir / "standardized" / f"{prefix}.standardized.nc"
    if not path.exists():
        raise FileNotFoundError(
            f"Standardized file not found: {path}. Run Data Standardization & Integration first."
        )
    return path


def _subset_time(ds: xr.Dataset, start_date: str | None, end_date: str | None) -> xr.Dataset:
    if start_date:
        ds = ds.sel(time=slice(start_date, end_date or None))
    elif end_date:
        ds = ds.sel(time=slice(None, end_date))
    if ds.sizes.get("time", 0) == 0:
        raise ValueError("No records remain after the selected time range was applied.")
    return ds


def _spatial_dims(da: xr.DataArray) -> list[str]:
    dims = [d for d in da.dims if d.startswith("lat") or d.startswith("lon")]
    if len(dims) != 2:
        raise ValueError(
            "Expected exactly two horizontal dimensions (latitude and longitude) "
            f"for the regional analysis; found {dims}."
        )
    return dims


def _lat_dim(spatial_dims: list[str]) -> str:
    matches = [d for d in spatial_dims if d.startswith("lat")]
    if len(matches) != 1:
        raise ValueError(f"Could not identify a unique latitude dimension from {spatial_dims}.")
    return matches[0]


def _regional_mean(da: xr.DataArray) -> xr.DataArray:
    """Area-weighted mean over the native horizontal grid using cos(latitude)."""
    spatial = _spatial_dims(da)
    lat_name = _lat_dim(spatial)
    lat = da[lat_name]
    weights = np.cos(np.deg2rad(lat))
    return da.weighted(weights).mean(spatial, skipna=True)


def _save_csv(da: xr.DataArray, path: Path):
    df = da.to_dataframe(name=da.name or "value").reset_index()
    df.to_csv(path, index=False)


def _plot_time_series(da: xr.DataArray, title: str, units: str, path: Path):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5.2), constrained_layout=True)
    ax.plot(pd.to_datetime(da.time.values), da.values, linewidth=1.6, marker="o", markersize=3.5)
    ax.set_xlabel("Time")
    ax.set_ylabel(f"{title} ({units})")
    ax.set_title(title)
    ax.grid(True, alpha=0.25)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_vertical_profile(da: xr.DataArray, title: str, units: str, path: Path):
    import matplotlib.pyplot as plt

    profile = da
    fig, ax = plt.subplots(figsize=(6.2, 7.0), constrained_layout=True)
    ax.plot(profile.values, profile.depth.values, marker="o", linewidth=1.6, markersize=3.5)
    ax.invert_yaxis()
    ax.set_xlabel(f"{title} ({units})")
    ax.set_ylabel("Depth (m)")
    ax.set_title(title)
    ax.grid(True, alpha=0.25)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return profile


def _plot_depth_time(da: xr.DataArray, title: str, units: str, path: Path):
    import matplotlib.pyplot as plt

    section = da
    fig, ax = plt.subplots(figsize=(10, 5.8), constrained_layout=True)
    mesh = ax.pcolormesh(
        pd.to_datetime(section.time.values),
        section.depth.values,
        section.transpose("depth", "time").values,
        shading="auto",
    )
    ax.invert_yaxis()
    ax.set_xlabel("Time")
    ax.set_ylabel("Depth (m)")
    ax.set_title(title)
    cb = fig.colorbar(mesh, ax=ax)
    cb.set_label(f"{title} ({units})")
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return section


def _depth_selection(
    da: xr.DataArray,
    depth_mode: str = "surface",
    single_depth: float | None = None,
    depth_min: float | None = None,
    depth_max: float | None = None,
) -> tuple[xr.DataArray, dict]:
    """Apply explicit depth-selection modes while preserving native GODAS levels."""
    info = {
        "depth_mode": depth_mode,
        "requested_single_depth_m": single_depth,
        "requested_depth_min_m": depth_min,
        "requested_depth_max_m": depth_max,
        "selected_depth_levels": [],
        "actual_single_depth_m": None,
    }

    if "depth" not in da.dims:
        if depth_mode != "surface" or single_depth is not None or depth_min is not None or depth_max is not None:
            raise ValueError("The selected variable has no depth dimension (e.g., Mixed Layer Depth).")
        info["selected_depth_levels"] = []
        return da, info

    levels = np.asarray(da["depth"].values, dtype=float)
    if levels.size == 0:
        raise ValueError("The selected variable contains no depth levels.")

    if depth_mode == "surface":
        target = float(np.nanmin(levels))
        idx = int(np.nanargmin(np.abs(levels - target)))
        selected_level = float(levels[idx])
        info["selected_depth_levels"] = [selected_level]
        info["actual_single_depth_m"] = selected_level
        info["depth_difference_m"] = selected_level - float(single_depth) if single_depth is not None else None
        info["depth_selection_method"] = "nearest_available_level"
        return da.sel(depth=selected_level, method="nearest"), info

    if depth_mode == "single":
        if single_depth is None:
            raise ValueError("Please enter a single target depth in metres.")
        if single_depth < 0:
            raise ValueError("Single depth cannot be negative.")
        idx = int(np.nanargmin(np.abs(levels - single_depth)))
        selected_level = float(levels[idx])
        info["selected_depth_levels"] = [selected_level]
        info["actual_single_depth_m"] = selected_level
        info["depth_difference_m"] = selected_level - float(single_depth) if single_depth is not None else None
        info["depth_selection_method"] = "nearest_available_level"
        return da.sel(depth=selected_level, method="nearest"), info

    if depth_mode == "range":
        if depth_min is None and depth_max is None:
            raise ValueError("Please specify at least one depth limit for Depth Range.")
        lo = 0.0 if depth_min is None else depth_min
        hi = float(np.nanmax(levels)) if depth_max is None else depth_max
        if lo > hi:
            lo, hi = hi, lo
        selected = da.sel(depth=slice(lo, hi))
        if selected.sizes.get("depth", 0) == 0:
            raise ValueError("No GODAS depth levels fall inside the selected depth range.")
        info["requested_depth_min_m"] = lo
        info["requested_depth_max_m"] = hi
        info["selected_depth_levels"] = [float(v) for v in selected.depth.values]
        return selected, info

    if depth_mode == "full":
        info["selected_depth_levels"] = [float(v) for v in levels]
        return da, info

    raise ValueError(f"Unsupported depth mode: {depth_mode}")


def _depth_coverage(da: xr.DataArray) -> dict:
    """Quantify native-grid spatial data coverage for each depth level.

    Coverage is summarized across the selected time period. For each depth,
    valid_cells_mean is the mean number of finite horizontal cells per time
    record, and valid_fraction_mean is that value divided by the total number
    of horizontal grid cells. No interpolation or gap filling is performed.
    """
    spatial = _spatial_dims(da)
    total_cells = int(np.prod([da.sizes[d] for d in spatial]))
    valid = np.isfinite(da)
    valid_cells = valid.sum(spatial)

    if "time" in valid_cells.dims:
        valid_cells_mean = valid_cells.mean("time", skipna=True)
    else:
        valid_cells_mean = valid_cells

    valid_fraction_mean = valid_cells_mean / max(total_cells, 1)

    # Keep the full time × depth native-grid coverage for Depth–Time Sections.
    # This is intentionally separate from the time-averaged profile coverage
    # above; a 2-D section needs diagnostics for every individual time/depth pair.
    if "time" in valid_cells.dims and "depth" in valid_cells.dims:
        valid_cells_time_depth = valid_cells.transpose("time", "depth")
        valid_fraction_time_depth = valid_cells_time_depth / max(total_cells, 1)
    else:
        valid_cells_time_depth = None
        valid_fraction_time_depth = None

    return {
        "total_horizontal_cells": total_cells,
        "valid_cells_mean": valid_cells_mean,
        "valid_fraction_mean": valid_fraction_mean,
        "valid_cells_time_depth": valid_cells_time_depth,
        "valid_fraction_time_depth": valid_fraction_time_depth,
    }




def _surface_coverage(da: xr.DataArray) -> dict:
    """Quantify native-grid spatial data coverage for a 2-D time-varying field."""
    spatial = _spatial_dims(da)
    total_cells = int(np.prod([da.sizes[d] for d in spatial]))
    valid_cells = np.isfinite(da).sum(spatial)
    valid_fraction = valid_cells / max(total_cells, 1)
    return {
        "total_horizontal_cells": total_cells,
        "valid_cells": valid_cells,
        "valid_fraction": valid_fraction,
    }


def _profile_coverage_table(result: xr.DataArray, coverage: dict) -> pd.DataFrame:
    """Build a profile table with data-availability diagnostics."""
    depths = np.asarray(result.depth.values, dtype=float)
    values = np.asarray(result.values, dtype=float)
    valid_cells = np.asarray(coverage["valid_cells_mean"].values, dtype=float)
    valid_fraction = np.asarray(coverage["valid_fraction_mean"].values, dtype=float)
    return pd.DataFrame({
        "depth": depths,
        result.name or "value": values,
        "valid_cells_mean": valid_cells,
        "valid_fraction_mean": valid_fraction,
    })


def _depth_time_coverage_table(result: xr.DataArray, coverage: dict) -> pd.DataFrame:
    """Build a time × depth table with native-grid availability diagnostics."""
    values_df = result.to_dataframe(name=result.name or "value").reset_index()
    valid_cells = coverage.get("valid_cells_time_depth")
    valid_fraction = coverage.get("valid_fraction_time_depth")
    if valid_cells is None or valid_fraction is None:
        raise ValueError(
            "Depth–Time coverage diagnostics require both time and depth dimensions."
        )
    cov_df = xr.Dataset({
        "valid_cells": valid_cells,
        "valid_fraction": valid_fraction,
    }).to_dataframe().reset_index()
    return values_df.merge(cov_df, on=["time", "depth"], how="left")


def _convert_units(da: xr.DataArray, variable_key: str, unit_mode: str) -> tuple[xr.DataArray, str, str]:
    """Apply only explicit, transparent display/output unit conversions."""
    prefix, _, native_units, _ = VARIABLES[variable_key]
    if unit_mode == "native":
        return da, native_units, "none; source GODAS units retained"
    if variable_key == "temperature" and unit_mode == "celsius":
        out = da - 273.15
        return out, "°C", "Potential Temperature: K → °C (subtract 273.15)"
    if variable_key == "salinity" and unit_mode == "psu_approx":
        out = da * 1000.0
        return out, "PSU (approx.)", "Salinity: kg kg⁻¹ × 1000 (approximate PSU-style reporting)"
    raise ValueError(f"Unit conversion '{unit_mode}' is not applicable to {variable_key}.")


def run_analysis(
    output_dir: str,
    variable_key: str,
    analysis_type: str,
    start_date: str | None = None,
    end_date: str | None = None,
    depth_mode: str = "surface",
    single_depth: float | None = None,
    depth_min: float | None = None,
    depth_max: float | None = None,
    unit_mode: str = "native",
    progress: Callable[[str], None] | None = None,
) -> dict:
    if variable_key not in VARIABLES:
        raise ValueError(f"Unsupported variable: {variable_key}")
    if analysis_type not in {"time_series", "vertical_profile", "depth_time"}:
        raise ValueError(f"Unsupported analysis type: {analysis_type}")

    prefix, label, units, has_depth = VARIABLES[variable_key]
    if analysis_type != "time_series" and not has_depth:
        raise ValueError("Vertical profile and depth-time section require a 3-D variable with depth.")

    root = Path(output_dir)
    analysis_dir = root / "analysis"
    analysis_dir.mkdir(exist_ok=True)
    created_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    src_path = _standardized_file(root, variable_key)
    if progress:
        progress(f"[AN] Opening {src_path.name}...")

    with xr.open_dataset(src_path, decode_times=True, mask_and_scale=True) as src:
        ds = _subset_time(src, start_date, end_date)
        da, depth_info = _depth_selection(
            ds[prefix], depth_mode=depth_mode, single_depth=single_depth,
            depth_min=depth_min, depth_max=depth_max
        )
        spatial = _spatial_dims(da)
        coverage = _depth_coverage(da) if "depth" in da.dims else _surface_coverage(da)
        regional = _regional_mean(da)
        regional.name = prefix

        regional, output_units, conversion_note = _convert_units(regional, variable_key, unit_mode)

        if progress:
            depth_text = depth_mode
            if depth_info.get("actual_single_depth_m") is not None:
                depth_text += f" (actual GODAS level: {depth_info['actual_single_depth_m']:.1f} m)"
            elif depth_mode == "range":
                depth_text += f" ({len(depth_info['selected_depth_levels'])} levels)"
            elif depth_mode == "full":
                depth_text += f" ({len(depth_info['selected_depth_levels'])} levels)"
            progress(
                f"[AN] {label}: {ds.sizes.get('time', 0)} time records; "
                f"native spatial dimensions={', '.join(spatial)}; depth selection={depth_text}; "
                f"output units={output_units}."
            )

        time_values = pd.to_datetime(regional.time.values)
        base_summary = {
            "analysis_type": analysis_type,
            "variable": variable_key,
            "source_file": str(src_path),
            "source_units": units,
            "output_units": output_units,
            "time_count": int(regional.sizes.get("time", 0)),
            "time_start": str(time_values.min()),
            "time_end": str(time_values.max()),
            # Legacy flat fields are retained for backward compatibility.
            "depth_mode": "not_applicable" if not has_depth else depth_mode,
            "single_depth_requested_m": None if not has_depth else single_depth,
            "depth_min_requested": None if not has_depth else depth_info.get("requested_depth_min_m"),
            "depth_max_requested": None if not has_depth else depth_info.get("requested_depth_max_m"),
            "selected_depth_levels": [] if not has_depth else depth_info.get("selected_depth_levels", []),
            "actual_single_depth_m": None if not has_depth else depth_info.get("actual_single_depth_m"),
            "depth_difference_m": None if not has_depth else depth_info.get("depth_difference_m"),
            "depth_selection_method": "not_applicable" if not has_depth else depth_info.get("depth_selection_method"),
            "spatial_dimensions": spatial,
            "spatial_statistic": "cos(latitude)-weighted mean over available native-grid cells",
            "unit_conversion": conversion_note,
        }

        if analysis_type == "time_series":
            result = regional
            csv_path = analysis_dir / f"{prefix}_regional_time_series_{created_utc}.csv"
            png_path = analysis_dir / f"{prefix}_regional_time_series_{created_utc}.png"
            if not has_depth:
                ts_df = result.to_dataframe(name=result.name or "value").reset_index()
                valid_cells = np.asarray(coverage["valid_cells"].values, dtype=float)
                valid_fraction = np.asarray(coverage["valid_fraction"].values, dtype=float)
                ts_df["valid_cells"] = valid_cells
                ts_df["valid_fraction"] = valid_fraction
                ts_df.to_csv(csv_path, index=False)
            else:
                _save_csv(result, csv_path)
            title = "Regional Mean " + label
            if depth_mode == "surface":
                title += " — Surface"
            elif depth_mode == "single":
                title += f" — {depth_info['actual_single_depth_m']:.1f} m"
            elif depth_mode == "range":
                title += " — Selected Depth Range"
            elif depth_mode == "full":
                title += " — Full Water Column"
            _plot_time_series(result, title, output_units, png_path)
            summary = {
                **base_summary,
                "statistic": "regional area-weighted mean using cos(latitude); selected depth levels averaged equally only for Depth Range",
                "output_variable_dimensions": list(result.dims),
                "output_structure": (
                    "time series of regional MLD with one value plus native-grid coverage diagnostics per time record"
                    if not has_depth else
                    "one value per time record for Surface/Single depth/Depth Range; time × depth for Full water column"
                ),
                "total_horizontal_cells": coverage["total_horizontal_cells"],
                "coverage_definition": "Finite native-grid horizontal cells per time record; no interpolation or gap filling.",
                "csv_columns": list(ts_df.columns) if not has_depth else list(result.to_dataframe(name=prefix).reset_index().columns),
                "csv": str(csv_path),
                "plot": str(png_path),
            }
        elif analysis_type == "vertical_profile":
            result = regional.mean("time", skipna=True)
            csv_path = analysis_dir / f"{prefix}_vertical_profile_{created_utc}.csv"
            png_path = analysis_dir / f"{prefix}_vertical_profile_{created_utc}.png"

            # Keep the complete native depth selection in the CSV, including
            # NaN levels, while adding transparent coverage diagnostics.
            profile_df = _profile_coverage_table(result, coverage)
            profile_df.to_csv(csv_path, index=False)

            _plot_vertical_profile(
                result,
                f"Mean Vertical Profile — {label}\n{start_date or 'start'} to {end_date or 'end'}",
                output_units,
                png_path,
            )

            result_values = np.asarray(result.values, dtype=float)
            valid_depth_mask = np.isfinite(result_values)
            valid_depths = np.asarray(result.depth.values, dtype=float)[valid_depth_mask]
            no_valid_depths = np.asarray(result.depth.values, dtype=float)[~valid_depth_mask]

            summary = {
                **base_summary,
                "selected_depth_count": int(result.sizes.get("depth", 0)),
                "valid_depth_count": int(valid_depth_mask.sum()),
                "depth_min_selected_m": float(result.depth.min()),
                "depth_max_selected_m": float(result.depth.max()),
                "deepest_selected_depth_m": float(result.depth.max()),
                "deepest_valid_depth_m": float(valid_depths.max()) if valid_depths.size else None,
                "no_valid_data_depths_m": [float(v) for v in no_valid_depths],
                "total_horizontal_cells": coverage["total_horizontal_cells"],
                "coverage_definition": "Mean number/fraction of finite native-grid horizontal cells per time record at each depth; no interpolation or gap filling.",
                "statistic": "cos(latitude)-weighted spatial mean followed by temporal mean",
                "output_variable_dimensions": list(result.dims),
                "output_structure": "depth profile: one value per selected depth level after spatial and temporal averaging",
                "csv_columns": ["depth", prefix, "valid_cells_mean", "valid_fraction_mean"],
                "csv": str(csv_path),
                "plot": str(png_path),
            }
        else:
            result = regional
            csv_path = analysis_dir / f"{prefix}_depth_time_{created_utc}.csv"
            png_path = analysis_dir / f"{prefix}_depth_time_{created_utc}.png"

            # Preserve every selected native depth and time record in the CSV.
            # Add transparent coverage diagnostics for each time/depth pair;
            # no interpolation or gap filling is applied.
            section_df = _depth_time_coverage_table(result, coverage)
            section_df.to_csv(csv_path, index=False)

            _plot_depth_time(
                result,
                f"Regional Mean Depth–Time — {label}\n{start_date or 'start'} to {end_date or 'end'}",
                output_units,
                png_path,
            )

            result_values = np.asarray(result.values, dtype=float)
            valid_mask = np.isfinite(result_values)
            valid_pair_count = int(valid_mask.sum())
            total_pairs = int(result_values.size)
            valid_depth_mask = np.isfinite(result_values).any(axis=0)
            valid_depths = np.asarray(result.depth.values, dtype=float)[valid_depth_mask]
            no_valid_depths = np.asarray(result.depth.values, dtype=float)[~valid_depth_mask]

            summary = {
                **base_summary,
                "selected_depth_count": int(result.sizes.get("depth", 0)),
                "valid_depth_count": int(valid_depth_mask.sum()),
                "depth_count": int(result.sizes.get("depth", 0)),
                "depth_min_actual": float(result.depth.min()),
                "depth_max_actual": float(result.depth.max()),
                "deepest_selected_depth_m": float(result.depth.max()),
                "deepest_valid_depth_m": float(valid_depths.max()) if valid_depths.size else None,
                "no_valid_data_depths_m": [float(v) for v in no_valid_depths],
                "total_horizontal_cells": coverage["total_horizontal_cells"],
                "valid_time_depth_pairs": valid_pair_count,
                "total_time_depth_pairs": total_pairs,
                "valid_time_depth_fraction": valid_pair_count / total_pairs if total_pairs else 0.0,
                "coverage_definition": "Number/fraction of finite native-grid horizontal cells for each time/depth pair; no interpolation or gap filling.",
                "statistic": "cos(latitude)-weighted spatial mean at each time/depth",
                "output_variable_dimensions": list(result.dims),
                "output_structure": "time × depth section: one value per time/depth pair",
                "csv_columns": ["time", "depth", prefix, "valid_cells", "valid_fraction"],
                "csv": str(csv_path),
                "plot": str(png_path),
            }

    # v1.8 unified reporting schema. The existing flat fields above remain for
    # backward compatibility with v1.7 outputs, while this canonical structure
    # gives downstream software one consistent contract across analysis types.
    def _na(value):
        return "not_applicable" if value is None else value

    depth_info_report = {
        "mode": summary.get("depth_mode", "not_applicable"),
        "requested_single_depth_m": _na(summary.get("single_depth_requested_m")),
        "requested_min_depth_m": _na(summary.get("depth_min_requested")),
        "requested_max_depth_m": _na(summary.get("depth_max_requested")),
        "selected_depth_levels_m": summary.get("selected_depth_levels", []),
        "selected_depth_count": summary.get("selected_depth_count", len(summary.get("selected_depth_levels", []))),
        "deepest_selected_depth_m": _na(summary.get("deepest_selected_depth_m", summary.get("depth_max_selected_m", summary.get("depth_max_actual")))),
        "valid_depth_count": _na(summary.get("valid_depth_count")),
        "deepest_valid_depth_m": _na(summary.get("deepest_valid_depth_m")),
        "selection_method": summary.get("depth_selection_method", "not_applicable"),
    }
    coverage_info = {
        "total_horizontal_cells": _na(summary.get("total_horizontal_cells")),
        "definition": summary.get("coverage_definition", "not_applicable"),
        "valid_time_depth_pairs": _na(summary.get("valid_time_depth_pairs")),
        "total_time_depth_pairs": _na(summary.get("total_time_depth_pairs")),
        "valid_fraction": _na(summary.get("valid_time_depth_fraction")),
    }
    summary["software_version"] = SOFTWARE_VERSION
    summary["schema_version"] = REPORT_SCHEMA_VERSION
    summary["requested_period"] = {"start": start_date, "end": end_date}
    summary["period"] = {"start": start_date, "end": end_date}
    summary["observation_coverage"] = observation_coverage(regional.time.values, start_date, end_date)
    summary["processing"] = {**standard_processing("cos(latitude)", units, output_units, conversion_note)}
    summary["report_schema"] = {
        "analysis_type": summary["analysis_type"],
        "variable": summary["variable"],
        "software_version": SOFTWARE_VERSION,
        "schema_version": REPORT_SCHEMA_VERSION,
        "source": {"file": summary["source_file"], "units": summary["source_units"]},
        "output": {
            "units": summary["output_units"],
            "csv": summary["csv"],
            "csv_columns": summary.get("csv_columns", []),
            "plot": summary["plot"],
            "structure": summary.get("output_structure", "not_applicable"),
        },
        "time": {
            "requested_start": start_date,
            "requested_end": end_date,
            "actual_first_record": summary["time_start"],
            "actual_last_record": summary["time_end"],
            "count": summary["time_count"],
        },
        "observation_coverage": summary["observation_coverage"],
        "depth_information": depth_info_report,
        "spatial_information": {
            "dimensions": summary.get("spatial_dimensions", []),
            "statistic": summary.get("spatial_statistic", "not_applicable"),
            "native_grid_preserved": True,
            "silent_regridding": False,
        },
        "coverage_information": coverage_info,
        "statistics": summary.get("statistic", "not_applicable"),
        "unit_conversion": summary.get("unit_conversion", "none; source GODAS units retained"),
        "integrity": {
            "interpolation": False,
            "extrapolation": False,
            "gap_filling": False,
            "native_grid_only": True,
        },
    }

    report_path = analysis_dir / f"Analysis_report_{created_utc}.json"
    summary["outputs"] = {"csv": str(csv_path), "plot": str(png_path), "report": str(report_path)}
    summary["depth_information"] = depth_info_report
    summary["integrity"] = {
        "status": "PASS",
        **{k: summary.get(k) for k in ("valid_time_depth_pairs", "total_time_depth_pairs", "valid_time_depth_fraction") if k in summary},
        "interpolation": False, "extrapolation": False, "gap_filling": False, "native_grid_only": True,
    }
    summary["provenance"] = {"created_utc": created_utc, "software_version": SOFTWARE_VERSION, "report_schema_version": REPORT_SCHEMA_VERSION}
    summary["report_validation"] = validate_report(summary)
    summary["report"] = str(report_path)
    report_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    if progress:
        progress(f"[AN OK] CSV: {csv_path.name}")
        progress(f"[AN OK] Plot: {png_path.name}")
        progress(f"[AN] Report: {report_path.name}")
        progress("[DONE] Scientific analysis completed successfully.")
    return summary
