from __future__ import annotations

import numpy as np
import pandas as pd

SOFTWARE_VERSION = "2.5.10"
REPORT_SCHEMA_VERSION = "2.6.0"


def observation_coverage(times, requested_start=None, requested_end=None):
    t = pd.DatetimeIndex(pd.to_datetime(times))
    months = pd.PeriodIndex(t, freq="M")
    unique = set(months)
    years = sorted({p.year for p in months})
    complete_years = [y for y in years if all(pd.Period(f"{y}-{m:02d}", freq="M") in unique for m in range(1, 13))]
    complete_season_years = {s: [] for s in ("DJF", "MAM", "JJA", "SON")}
    season_months = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}
    for sy in sorted(set(years) | ({y + 1 for y in years})):
        for s, ms in season_months.items():
            pairs = []
            for m in ms:
                y = sy - 1 if (s == "DJF" and m == 12) else sy
                pairs.append(pd.Period(f"{y}-{m:02d}", freq="M"))
            if all(p in unique for p in pairs):
                complete_season_years[s].append(sy)
    cov = {
        "source_first_record": str(t.min()) if len(t) else None,
        "source_last_record": str(t.max()) if len(t) else None,
        "source_record_count": int(len(t)),
        "unique_month_count": int(len(unique)),
        "complete_years": complete_years,
        "complete_year_count": int(len(complete_years)),
        "complete_season_years": complete_season_years,
        "complete_season_counts": {k: len(v) for k, v in complete_season_years.items()},
    }
    if requested_start is not None:
        cov["requested_start"] = requested_start
    if requested_end is not None:
        cov["requested_end"] = requested_end
    all_season_years = [y for vals in complete_season_years.values() for y in vals]
    cov["analysis_period_start_year"] = min(all_season_years) if all_season_years else (min(complete_years) if complete_years else None)
    cov["analysis_period_end_year"] = max(all_season_years) if all_season_years else (max(complete_years) if complete_years else None)
    return cov


def depth_metadata(selected_levels, values=None, depth_mode="not_applicable", requested_single=None, requested_min=None, requested_max=None):
    levels = [float(v) for v in (selected_levels or [])]
    out = {
        "mode": depth_mode,
        "requested_single_depth_m": "not_applicable" if requested_single is None else float(requested_single),
        "requested_min_depth_m": "not_applicable" if requested_min is None else float(requested_min),
        "requested_max_depth_m": "not_applicable" if requested_max is None else float(requested_max),
        "selected_depth_levels_m": levels,
        "selected_depth_count": len(levels),
    }
    if depth_mode == "not_applicable" or not levels:
        out.update({"valid_depth_count": "not_applicable", "invalid_depth_count": "not_applicable", "valid_depth_levels_m": [], "invalid_depth_levels_m": []})
        return out
    if values is None:
        out.update({"valid_depth_count": "not_available", "invalid_depth_count": "not_available", "valid_depth_levels_m": [], "invalid_depth_levels_m": []})
        return out
    arr = np.asarray(values)
    if arr.ndim == 1:
        valid = np.isfinite(arr)
    else:
        valid = np.isfinite(arr).any(axis=0)
    valid_levels = [levels[i] for i, ok in enumerate(valid[:len(levels)]) if ok]
    invalid_levels = [levels[i] for i, ok in enumerate(valid[:len(levels)]) if not ok]
    out.update({
        "valid_depth_count": len(valid_levels),
        "invalid_depth_count": len(invalid_levels),
        "valid_depth_levels_m": valid_levels,
        "invalid_depth_levels_m": invalid_levels,
        "deepest_selected_depth_m": max(levels) if levels else None,
        "deepest_valid_depth_m": max(valid_levels) if valid_levels else None,
    })
    return out


def standard_processing(spatial_weighting="cos(latitude)", source_units=None, output_units=None, conversion="none"):
    return {
        "spatial_weighting": spatial_weighting,
        "native_grid_preserved": True,
        "regridding": False,
        "vertical_interpolation": False,
        "interpolation": False,
        "extrapolation": False,
        "gap_filling": False,
        "autocorrelation_correction": "none",
        "unit_conversion": conversion,
        "source_units": source_units,
        "output_units": output_units,
    }
