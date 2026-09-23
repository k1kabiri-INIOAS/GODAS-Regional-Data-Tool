from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import math
import numpy as np
import pandas as pd
import xarray as xr
from scipy.stats import linregress, kendalltau

from .analysis import (
    VARIABLES, _standardized_file, _subset_time, _depth_selection,
    _regional_mean, _convert_units, _spatial_dims
)
from .reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION, standard_processing
from .report_validation import validate_report

SEASONS = ["DJF", "MAM", "JJA", "SON"]
SEASON_MONTHS = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}


def _time_years(times):
    idx = pd.DatetimeIndex(times)
    if len(idx) == 0:
        return np.array([], dtype=float)
    return (idx - idx[0]).total_seconds().to_numpy(dtype=float) / (365.2425 * 86400.0)


def _finite_xy(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask], mask


def _ols(x, y, alpha=0.05):
    x, y, _ = _finite_xy(x, y)
    n = len(y)
    if n < 3:
        return {"status": "insufficient_data", "n": n}
    if np.allclose(y, y[0]):
        return {"status": "constant_series", "slope": 0.0, "slope_per_decade": 0.0,
                "intercept": float(y[0]), "r_squared": 0.0, "p_value": 1.0,
                "standard_error": 0.0, "n": n, "significant": False}
    if np.allclose(x, x[0]):
        return {"status": "invalid_time_axis", "n": n}
    r = linregress(x, y)
    return {"status": "ok", "slope": float(r.slope), "slope_per_decade": float(r.slope * 10),
            "intercept": float(r.intercept), "r_squared": float(r.rvalue ** 2),
            "p_value": float(r.pvalue), "standard_error": float(r.stderr), "n": n,
            "significant": bool(r.pvalue < alpha)}


def _mk(x, y, alpha=0.05):
    x, y, _ = _finite_xy(x, y)
    n = len(y)
    if n < 3:
        return {"status": "insufficient_data", "n": n}
    if np.allclose(y, y[0]):
        return {"status": "constant_series", "kendall_tau": 0.0, "mk_s": 0.0,
                "p_value": 1.0, "n": n, "significant": False}
    # scipy's Kendall tau implements tie-aware Kendall testing; time ordering is the x input.
    r = kendalltau(x, y, nan_policy="omit", method="auto")
    tau = float(r.statistic) if np.isfinite(r.statistic) else 0.0
    p = float(r.pvalue) if np.isfinite(r.pvalue) else 1.0
    # S is useful for transparent reporting and is tie-safe.
    diff = y[np.newaxis, :] - y[:, np.newaxis]
    upper = diff[np.triu_indices(n, k=1)]
    s = float(np.sign(upper).sum())
    return {"status": "ok", "kendall_tau": tau, "mk_s": s, "p_value": p, "n": n,
            "significant": bool(p < alpha)}


def _sen(x, y):
    x, y, _ = _finite_xy(x, y)
    n = len(y)
    if n < 3:
        return {"status": "insufficient_data", "n": n}
    slopes = []
    for i in range(n - 1):
        dx = x[i + 1:] - x[i]
        dy = y[i + 1:] - y[i]
        valid = dx != 0
        slopes.extend((dy[valid] / dx[valid]).tolist())
    if not slopes:
        return {"status": "invalid_time_axis", "n": n}
    slope = float(np.median(np.asarray(slopes, dtype=float)))
    return {"status": "ok", "sen_slope": slope, "sen_slope_per_decade": slope * 10.0, "n": n}


def _statistics(x, y, methods, alpha=0.05):
    out = {}
    if "OLS" in methods:
        out["OLS"] = _ols(x, y, alpha)
    if "Mann-Kendall" in methods:
        out["Mann-Kendall"] = _mk(x, y, alpha)
    if "Sen" in methods:
        out["Sen"] = _sen(x, y)
    return out


def _series_records(da):
    if "depth" not in da.dims:
        df = da.to_dataframe(name=da.name or "value").reset_index()
        return df
    return da.to_dataframe(name=da.name or "value").reset_index()


def _aggregate_monthly(da):
    return da


def _aggregate_seasonal(da):
    months = pd.DatetimeIndex(da.time.values).month
    years = pd.DatetimeIndex(da.time.values).year
    season = np.array([next(s for s, ms in SEASON_MONTHS.items() if m in ms) for m in months], dtype=object)
    season_year = years + (months == 12)
    tmp = da.assign_coords(season=("time", season), season_year=("time", season_year))
    # Only complete 3-month seasons become observations.
    rows = []
    for sy in sorted(np.unique(season_year)):
        for s in SEASONS:
            idx = np.where((season_year == sy) & (season == s))[0]
            if len(idx) != 3:
                continue
            vals = tmp.isel(time=idx)
            rows.append((s, int(sy), vals.mean("time", skipna=True)))
    if not rows:
        return None
    seasons = [r[0] for r in rows]; years_out = [r[1] for r in rows]
    vals = xr.concat([r[2] for r in rows], dim="observation")
    vals = vals.assign_coords(season=("observation", seasons), season_year=("observation", years_out))
    return vals


def _observation_coverage(times, trend_type):
    """Summarize requested/source monthly coverage and complete analysis periods."""
    idx = pd.DatetimeIndex(times)
    out = {
        "source_time_count": int(len(idx)),
        "source_time_start": idx.min().strftime("%Y-%m-%d") if len(idx) else None,
        "source_time_end": idx.max().strftime("%Y-%m-%d") if len(idx) else None,
    }
    if len(idx) == 0:
        out.update({"complete_years": [], "complete_year_count": 0})
        if trend_type == "seasonal":
            out.update({"complete_season_years": {s: [] for s in SEASONS},
                       "complete_season_counts": {s: 0 for s in SEASONS}})
        return out

    month_pairs = {(int(t.year), int(t.month)) for t in idx}
    complete_years = [y for y in sorted({y for y, _ in month_pairs})
                      if all((y, m) in month_pairs for m in range(1, 13))]
    out.update({"complete_years": complete_years, "complete_year_count": len(complete_years)})

    if trend_type == "seasonal":
        complete_season_years = {}
        for season, months in SEASON_MONTHS.items():
            years = []
            for sy in sorted({int(t.year) + (int(t.month) == 12) for t in idx}):
                required = {(sy - 1, 12), (sy, 1), (sy, 2)} if season == "DJF" else {(sy, months[0]), (sy, months[1]), (sy, months[2])}
                if required.issubset(month_pairs):
                    years.append(sy)
            complete_season_years[season] = years
        out["complete_season_years"] = complete_season_years
        out["complete_season_counts"] = {s: len(v) for s, v in complete_season_years.items()}
    return out


def _depth_metadata(selected_depth_levels, series_df):
    """Summarize selected and data-valid native depths for reporting."""
    levels = [float(v) for v in selected_depth_levels]
    meta = {"selected_depth_count": len(levels)}
    if "depth" not in series_df.columns:
        return meta
    valid = []
    for d in levels:
        vals = series_df.loc[np.isclose(series_df["depth"].astype(float), d), "value"]
        if np.isfinite(vals.to_numpy(dtype=float)).any():
            valid.append(d)
    invalid = [d for d in levels if d not in valid]
    meta.update({
        "valid_depth_count": len(valid),
        "invalid_depth_count": len(invalid),
        "valid_depth_levels": valid,
        "invalid_depth_levels": invalid,
    })
    return meta


def _aggregate_annual(da):
    years = pd.DatetimeIndex(da.time.values).year
    rows = []
    for year in sorted(np.unique(years)):
        idx = np.where(years == year)[0]
        if len(idx) != 12:
            continue
        vals = da.isel(time=idx)
        rows.append((int(year), vals.mean("time", skipna=True)))
    if not rows:
        return None
    vals = xr.concat([r[1] for r in rows], dim="observation")
    vals = vals.assign_coords(year=("observation", [r[0] for r in rows]))
    return vals


def _collapse_depth_range(da, depth_mode):
    if depth_mode == "range":
        return da.mean("depth", skipna=True)
    return da


def _build_trend_for_series(da, trend_type, methods, alpha):
    # Returns list of (label, x, y, series_df) for one-dimensional or depth-specific analysis.
    if trend_type == "monthly":
        vals = da
        groups = [(None, vals)]
    elif trend_type == "annual":
        vals = _aggregate_annual(da)
        groups = [] if vals is None else [(None, vals)]
    elif trend_type == "seasonal":
        vals = _aggregate_seasonal(da)
        groups = [] if vals is None else [(s, vals.sel(observation=vals.season == s)) for s in SEASONS if bool((vals.season == s).any())]
    else:
        raise ValueError(f"Unsupported trend type: {trend_type}")

    results = []
    for label, v in groups:
        if trend_type == "monthly":
            times = pd.DatetimeIndex(v.time.values)
            x = _time_years(times)
            y = np.asarray(v.values, dtype=float)
            records = pd.DataFrame({"time": times, "value": y})
            results.append((label, x, y, records, _statistics(x, y, methods, alpha)))
            continue
        if "observation" in v.dims:
            if trend_type != "monthly":
                if trend_type == "annual":
                    years = np.asarray(v.year.values, dtype=int)
                    x = years - years[0] if len(years) else np.array([])
                    y = np.asarray(v.values, dtype=float)
                    records = pd.DataFrame({"year": years, "value": y})
                else:
                    years = np.asarray(v.season_year.values, dtype=int)
                    x = years - years[0] if len(years) else np.array([])
                    y = np.asarray(v.values, dtype=float)
                    records = pd.DataFrame({"season": label, "year": years, "value": y})
            results.append((label, x, y, records, _statistics(x, y, methods, alpha)))
    return results


def _plot_results(results, trend_type, label, units, variable_label, path, depth=False):
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    # Consistent scientific palette for seasonal products:
    # DJF = blue, MAM = green, JJA = orange-red, SON = yellow-orange.
    season_colors = {
        "DJF": "#1f77b4",
        "MAM": "#2ca02c",
        "JJA": "#e6550d",
        "SON": "#f2b01e",
    }
    data_color = "#1f77b4"
    trend_color = "black"
    marker_size = 3.8

    fig, ax = plt.subplots(figsize=(9, 5.4), constrained_layout=True)

    def _add_slope_annotation(x, y, slope_per_decade, color=trend_color, dx=0, dy=0):
        finite = np.isfinite(x) & np.isfinite(y)
        if not finite.any() or not np.isfinite(slope_per_decade):
            return
        xf = np.asarray(x)[finite]
        yf = np.asarray(y)[finite]
        # Place the label near the right end of the fitted trend line.
        x_pos = float(xf[-1]) + dx
        y_pos = float(yf[-1]) + dy
        ax.annotate(
            f"{slope_per_decade:+.2f}",
            xy=(x_pos, y_pos),
            xytext=(-5, 0),
            textcoords="offset points",
            ha="right",
            va="center",
            fontsize=9,
            color=color,
            fontweight="semibold",
            bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none", alpha=0.72),
        )

    def _apply_calendar_year_axis(start_year, end_year):
        # Numeric calendar-year axis: one extra year of room and 2-year major ticks.
        start_year = int(start_year)
        end_year = int(end_year)
        ax.set_xlim(float(start_year), float(end_year) + 1.0)
        ticks = np.arange(start_year, end_year + 1, 2, dtype=int)
        if len(ticks):
            ax.set_xticks(ticks)

    if depth:
        # Depth-dependent trend products: trend slope versus native depth.
        # For seasonal products, use the same seasonal colors as the time-series figures.
        for series_label, depths, slopes in results:
            color = season_colors.get(series_label, data_color)
            ax.plot(
                slopes, depths,
                marker="o", markersize=marker_size,
                linewidth=1.5, color=color, label=series_label,
            )
        ax.invert_yaxis()
        ax.set_xlabel(f"Trend ({units}/year)")
        ax.set_ylabel("Depth (m)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=.25)
        ax.set_title(f"{trend_type.title()} Trend by Depth — {variable_label}")

    elif trend_type == "seasonal":
        for season, x, y, stats in results:
            years = np.asarray(x, dtype=float)
            vals = np.asarray(y, dtype=float)
            color = season_colors.get(season, data_color)

            # Observed seasonal series: season-specific color for both line and markers.
            ax.plot(
                years, vals,
                color=color, marker="o", markersize=marker_size,
                linewidth=1.5, label=season,
            )

            if "OLS" in stats and stats["OLS"].get("status") == "ok":
                p = stats["OLS"]
                # Statistics use elapsed years relative to each season's first year.
                # Convert the fitted line back to calendar years for plotting.
                first_year = float(years.min())
                xx = np.linspace(years.min(), years.max(), 100)
                xx_elapsed = xx - first_year
                yy = p["intercept"] + p["slope"] * xx_elapsed
                ax.plot(xx, yy, color=trend_color, linewidth=1.5, zorder=3)

                # Slope annotation uses the reported per-decade slope.
                _add_slope_annotation(xx, yy, p.get("slope_per_decade", np.nan))

        ax.set_xlabel("Year")
        ax.set_ylabel(f"{variable_label} ({units})")
        ax.legend(ncol=2, fontsize=8)
        ax.set_title(f"Seasonal Trend — {variable_label}")
        if results:
            all_years = np.concatenate([np.asarray(r[1], dtype=float) for r in results if len(r[1])])
            if len(all_years):
                _apply_calendar_year_axis(np.nanmin(all_years), np.nanmax(all_years))
                plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8.5)

    else:
        label0, x, y, records, stats = results[0]
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)

        if trend_type == "monthly":
            # Use real datetimes on the x-axis while retaining elapsed years for statistics.
            times = pd.to_datetime(records["time"])
            ax.plot(
                times, y,
                color=data_color, marker="o", markersize=marker_size,
                linewidth=1.4,
            )
            xlabel = "Time"
            if "OLS" in stats and stats["OLS"].get("status") == "ok":
                p = stats["OLS"]
                xx = np.linspace(x.min(), x.max(), 100)
                yy = p["intercept"] + p["slope"] * xx
                t0 = times.iloc[0]
                tx = t0 + pd.to_timedelta(xx * 365.2425, unit="D")
                ax.plot(tx, yy, color=trend_color, linewidth=1.5, zorder=3)
                _add_slope_annotation(tx, yy, p.get("slope_per_decade", np.nan))
            if len(times):
                start = times.min()
                end = times.max() + pd.DateOffset(years=1)
                ax.set_xlim(start, end)
                ax.xaxis.set_major_locator(mdates.YearLocator(2))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
                plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8.5)
        else:
            # Annual trend: real calendar years on the x-axis.
            years = records["year"].to_numpy(dtype=float)
            ax.plot(
                years, y,
                color=data_color, marker="o", markersize=marker_size,
                linewidth=1.4,
            )
            xlabel = "Year"
            if "OLS" in stats and stats["OLS"].get("status") == "ok":
                p = stats["OLS"]
                first_year = float(years[0])
                xx_years = np.linspace(years.min(), years.max(), 100)
                xx_elapsed = xx_years - first_year
                yy = p["intercept"] + p["slope"] * xx_elapsed
                ax.plot(xx_years, yy, color=trend_color, linewidth=1.5, zorder=3)
                _add_slope_annotation(xx_years, yy, p.get("slope_per_decade", np.nan))
            if len(years):
                _apply_calendar_year_axis(np.nanmin(years), np.nanmax(years))
                plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8.5)

        ax.set_xlabel(xlabel)
        ax.set_ylabel(f"{variable_label} ({units})")
        ax.set_title(f"{trend_type.title()} Trend — {variable_label}")
        ax.grid(True, alpha=.25)

    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def run_trend(output_dir: str, variable_key: str, trend_type: str, start_date: str, end_date: str,
              depth_mode="surface", single_depth=None, depth_min=None, depth_max=None,
              unit_mode="native", methods=None, alpha=0.05, progress=None):
    if variable_key not in VARIABLES:
        raise ValueError(f"Unsupported variable: {variable_key}")
    if trend_type not in {"monthly", "seasonal", "annual"}:
        raise ValueError("Trend type must be monthly, seasonal, or annual.")
    methods = methods or ["OLS", "Mann-Kendall", "Sen"]
    prefix, label, native_units, has_depth = VARIABLES[variable_key]
    if not has_depth and depth_mode != "surface":
        depth_mode = "surface"
    root = Path(output_dir); outdir = root / "analysis" / "trend"; outdir.mkdir(parents=True, exist_ok=True)
    src = _standardized_file(root, variable_key)

    with xr.open_dataset(src, decode_times=True, mask_and_scale=True) as srcds:
        ds = _subset_time(srcds, start_date, end_date)
        da, depth_info = _depth_selection(ds[prefix], depth_mode, single_depth, depth_min, depth_max)
        regional = _regional_mean(da); regional.name = prefix
        regional, out_units, conversion = _convert_units(regional, variable_key, unit_mode)
        regional = _collapse_depth_range(regional, depth_mode)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = f"{prefix}_{trend_type}_trend_{stamp}"
        series_path = outdir / f"{base}_series.csv"
        stats_path = outdir / f"{base}_statistics.csv"
        plot_path = outdir / f"{base}.png"
        report_path = outdir / f"{prefix}_{trend_type}_trend_report_{stamp}.json"

        depth_dependent = has_depth and depth_mode == "full"
        stats_rows = []
        series_frames = []
        plot_payload = []

        if depth_dependent:
            depths = np.asarray(regional.depth.values, dtype=float)
            if trend_type == "seasonal":
                season_depth_slopes = {s: [] for s in SEASONS}
                for d in depths:
                    one = regional.sel(depth=d)
                    rlist = _build_trend_for_series(one, trend_type, methods, alpha)
                    for season, x, y, records, stats in rlist:
                        records.insert(0, "depth", float(d)); series_frames.append(records)
                        for method, st in stats.items():
                            row = {"depth": float(d), "season": season, "method": method}; row.update(st); stats_rows.append(row)
                            if method == "OLS" and st.get("status") == "ok":
                                season_depth_slopes[season].append((float(d), st["slope"]))
                # Use OLS for figure where available; fallback to Sen.
                for s in SEASONS:
                    vals = sorted(season_depth_slopes[s], key=lambda z: z[0]);
                    if vals: plot_payload.append((s, np.array([z[0] for z in vals]), np.array([z[1] for z in vals])))
            else:
                for d in depths:
                    one = regional.sel(depth=d)
                    rlist = _build_trend_for_series(one, trend_type, methods, alpha)
                    if not rlist: continue
                    _, x, y, records, stats = rlist[0]
                    records.insert(0, "depth", float(d)); series_frames.append(records)
                    for method, st in stats.items():
                        row = {"depth": float(d), "method": method}; row.update(st); stats_rows.append(row)
                # Plot OLS slopes, one point per depth.
                method_key = "OLS" if "OLS" in methods else "Sen"
                slopes = []
                for d in depths:
                    rows = [r for r in stats_rows if r.get("depth") == float(d) and r.get("method") == method_key and r.get("status") == "ok"]
                    slopes.append((float(d), rows[0].get("slope", rows[0].get("sen_slope")) if rows else np.nan))
                plot_payload.append((method_key, np.array([z[0] for z in slopes]), np.array([z[1] for z in slopes])))
        else:
            rlist = _build_trend_for_series(regional, trend_type, methods, alpha)
            if not rlist:
                raise ValueError("No complete annual/seasonal observations are available in the selected period.")
            for season, x, y, records, stats in rlist:
                series_frames.append(records)
                for method, st in stats.items():
                    row = {"method": method};
                    if season is not None: row["season"] = season
                    row.update(st); stats_rows.append(row)
                # Keep statistical x values as elapsed years, but pass calendar years
                # separately for seasonal plotting so the figure uses real years.
                if trend_type == "seasonal":
                    plot_years = records["year"].to_numpy(dtype=float)
                    plot_payload.append((season, plot_years, y, stats))
                else:
                    plot_payload.append((season, x, y, stats))

        series_df = pd.concat(series_frames, ignore_index=True) if series_frames else pd.DataFrame()
        stats_df = pd.DataFrame(stats_rows)
        series_df.to_csv(series_path, index=False)
        stats_df.to_csv(stats_path, index=False)

        # Plot using elapsed years for monthly, calendar years otherwise.
        if depth_dependent:
            _plot_results(plot_payload, trend_type, None, out_units, label, plot_path, depth=True)
        elif trend_type == "seasonal":
            _plot_results(plot_payload, trend_type, None, out_units, label, plot_path, depth=False)
        else:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            fig, ax = plt.subplots(figsize=(9, 5.4), constrained_layout=True)
            r = plot_payload[0]
            x_elapsed, y = np.asarray(r[1], dtype=float), np.asarray(r[2], dtype=float)
            stats = r[3]
            if trend_type == "monthly":
                # Use real datetimes on the x-axis while retaining elapsed years for statistics.
                times = pd.to_datetime(series_df["time"])
                ax.plot(times, series_df["value"], color="#1f77b4", marker="o", markersize=3.8, linewidth=1.4)
                xlabel = "Time"
                if "OLS" in stats and stats["OLS"].get("status") == "ok":
                    p = stats["OLS"]
                    xx = np.linspace(x_elapsed.min(), x_elapsed.max(), 100)
                    yy = p["intercept"] + p["slope"] * xx
                    t0 = times.iloc[0]
                    tx = t0 + pd.to_timedelta(xx * 365.2425, unit="D")
                    ax.plot(tx, yy, color="black", linewidth=1.5, label="OLS trend")
                    ax.annotate(f"{p.get('slope_per_decade', float('nan')):+.2f}", xy=(tx[-1], yy[-1]), xytext=(-5, 0), textcoords="offset points", ha="right", va="center", fontsize=9, fontweight="semibold", bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none", alpha=0.72))
                end = times.max() + pd.DateOffset(years=1)
                ax.set_xlim(times.min(), end)
                ax.xaxis.set_major_locator(mdates.YearLocator(2))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
                plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8.5)
            else:
                # The regression uses elapsed years (year - first_year), but the figure must
                # use calendar years on the x-axis. Convert the fitted line back to real years.
                years = series_df["year"].to_numpy(dtype=float)
                ax.plot(years, series_df["value"], color="#1f77b4", marker="o", markersize=3.8, linewidth=1.4)
                xlabel = "Year"
                if "OLS" in stats and stats["OLS"].get("status") == "ok":
                    p = stats["OLS"]
                    first_year = float(years[0])
                    xx_years = np.linspace(years.min(), years.max(), 100)
                    xx_elapsed = xx_years - first_year
                    yy = p["intercept"] + p["slope"] * xx_elapsed
                    ax.plot(xx_years, yy, color="black", linewidth=1.5, label="OLS trend")
                    ax.annotate(f"{p.get('slope_per_decade', float('nan')):+.2f}", xy=(xx_years[-1], yy[-1]), xytext=(-5, 0), textcoords="offset points", ha="right", va="center", fontsize=9, fontweight="semibold", bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none", alpha=0.72))
                ax.set_xlim(float(np.nanmin(years)), float(np.nanmax(years)) + 1.0)
                ticks = np.arange(int(np.nanmin(years)), int(np.nanmax(years)) + 1, 2, dtype=int)
                if len(ticks):
                    ax.set_xticks(ticks)
                plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8.5)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(f"{label} ({out_units})")
            ax.set_title(f"{trend_type.title()} Trend — {label}")
            ax.grid(True, alpha=.25)
            ax.legend(fontsize=8)
            fig.savefig(plot_path, dpi=300, bbox_inches="tight")
            plt.close(fig)

        valid_n = int(np.isfinite(series_df["value"]).sum()) if "value" in series_df.columns else 0
        total_n = int(len(series_df))
        integrity_status = "PASS" if valid_n >= 3 else "WARN"

        coverage = _observation_coverage(ds.time.values, trend_type)
        coverage["requested_start"] = start_date
        coverage["requested_end"] = end_date
        if trend_type == "annual":
            coverage["analysis_period_start_year"] = min(coverage["complete_years"]) if coverage["complete_years"] else None
            coverage["analysis_period_end_year"] = max(coverage["complete_years"]) if coverage["complete_years"] else None
        elif trend_type == "seasonal":
            all_complete_season_years = [y for s in SEASONS for y in coverage["complete_season_years"][s]]
            coverage["analysis_period_start_year"] = min(all_complete_season_years) if all_complete_season_years else None
            coverage["analysis_period_end_year"] = max(all_complete_season_years) if all_complete_season_years else None

        depth_report = dict(depth_info) if has_depth else {"depth_mode": "not_applicable"}
        if has_depth:
            depth_report.update(_depth_metadata(depth_info.get("selected_depth_levels", []), series_df))
        report = {
            "software_version": SOFTWARE_VERSION,
            "schema_version": REPORT_SCHEMA_VERSION,
            "analysis_type": "trend",
            "variable": variable_key,
            "trend_type": trend_type,
            "methods": methods,
            "period": {"start": start_date, "end": end_date},
            "observation_coverage": coverage,
            "depth_information": depth_report,
            "source_file": str(src), "source_units": native_units, "output_units": out_units,
            "unit_conversion": conversion,
            "processing": {**standard_processing("cos(latitude)", native_units, out_units, conversion), "alpha": alpha, "minimum_n": 3, "annual_requires_12_months": True, "seasonal_requires_3_months": True},
            "results": stats_rows,
            "integrity": {"status": integrity_status, "total_series_rows": total_n,
                          "finite_series_values": valid_n, "missing_series_values": total_n - valid_n,
                          "methods_use_same_valid_observations": True},
            "outputs": {"series_csv": str(series_path), "statistics_csv": str(stats_path), "plot": str(plot_path)},
            "warning": "Trend significance uses conventional OLS and Mann–Kendall tests without autocorrelation correction; p-values should be interpreted cautiously for temporally autocorrelated oceanographic time series."
        }
        report["outputs"]["report"] = str(report_path)
        report["provenance"] = {"created_utc": stamp, "software_version": SOFTWARE_VERSION, "report_schema_version": REPORT_SCHEMA_VERSION}
        report["report_validation"] = validate_report(report)
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if progress:
        progress(f"[TREND OK] {series_path.name}; {stats_path.name}; {plot_path.name}; {report_path.name}")
    return {"series_csv": str(series_path), "statistics_csv": str(stats_path), "plot": str(plot_path), "report": str(report_path)}
