from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import xarray as xr

from .reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION, standard_processing
from .report_validation import validate_report

from config.variables import variable_tuple_catalog

VARIABLES = variable_tuple_catalog()
GODAS_DEPTHS = np.array([
    5, 15, 25, 35, 45, 55, 65, 75, 85, 95,
    105, 115, 125, 135, 145, 155, 165, 175, 185, 195,
    205, 215, 225, 238, 262, 303, 366, 459, 584, 747,
    949, 1193, 1479, 1807, 2174, 2579, 3016, 3483, 3972, 4478,
], dtype=float)


def standardized_file(output_dir: str | Path, variable_key: str) -> Path:
    if variable_key not in VARIABLES:
        raise ValueError(f"Unsupported variable: {variable_key}")
    prefix = VARIABLES[variable_key][0]
    path = Path(output_dir) / "standardized" / f"{prefix}.standardized.nc"
    if not path.exists():
        raise FileNotFoundError(
            f"Standardized file not found: {path}. Run Data Standardization & Integration first."
        )
    return path


def available_depths(output_dir: str | Path, variable_key: str, requested_date: str | None = None) -> list[float]:
    """Return native depth levels with finite native-grid data for the selected month when requested."""
    if not VARIABLES[variable_key][3]:
        return []
    try:
        path = standardized_file(output_dir, variable_key)
    except Exception:
        # Only the legacy core 40-level products are safe to represent with the
        # historical GODAS depth list when no standardized file exists yet.
        # Some newly supported GODAS 3-D products (e.g. dzdt) may use a
        # variable-specific native vertical coordinate, so do not invent
        # canonical depths for them.
        if variable_key in {"temperature", "salinity", "u_current", "v_current"}:
            return [float(v) for v in GODAS_DEPTHS]
        return []
    with xr.open_dataset(path) as ds:
        if "depth" not in ds.dims:
            return []
        if requested_date is None:
            return [float(v) for v in np.asarray(ds.depth.values, dtype=float)]
        da = _standardized_dataarray(ds, variable_key)
        month_da, _ = _select_month(da, requested_date)
        return [float(v) for v in _finite_depths(month_da)]


def _standardized_dataarray(ds: xr.Dataset, variable_key: str) -> xr.DataArray:
    prefix = VARIABLES[variable_key][0]
    if prefix not in ds.data_vars:
        raise ValueError(f"Variable '{prefix}' was not found in the standardized dataset.")
    da = ds[prefix]
    if "time" not in da.dims:
        raise ValueError("The standardized dataset has no time dimension.")
    spatial = [d for d in da.dims if d.startswith("lat") or d.startswith("lon")]
    if len(spatial) != 2:
        raise ValueError(
            "Spatial visualization expects exactly two horizontal native-grid dimensions; "
            f"found {spatial}."
        )
    return da


def _convert_units(da: xr.DataArray, variable_key: str, unit_mode: str) -> tuple[xr.DataArray, str, str]:
    source_units = VARIABLES[variable_key][2]
    if unit_mode == "native":
        return da, source_units, "none; source GODAS units retained"
    if variable_key == "temperature" and unit_mode == "celsius":
        out = da - 273.15
        out.attrs = dict(da.attrs)
        out.attrs["units"] = "°C"
        return out, "°C", "K → °C (subtract 273.15)"
    if variable_key == "salinity" and unit_mode == "psu_approx":
        out = da * 1000.0
        out.attrs = dict(da.attrs)
        out.attrs["units"] = "PSU (approx.)"
        return out, "PSU (approx.)", "kg kg-1 → PSU (approx.) (multiply by 1000)"
    raise ValueError(f"Unsupported output-unit mode '{unit_mode}' for {variable_key}.")


def _month_start(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.to_period("M").to_timestamp()


def _select_month(da: xr.DataArray, requested_date: str) -> tuple[xr.DataArray, str]:
    requested = _month_start(requested_date)
    times = pd.DatetimeIndex(pd.to_datetime(da.time.values))
    months = pd.PeriodIndex(times, freq="M")
    wanted_period = requested.to_period("M")
    if wanted_period not in set(months):
        first = str(times.min().date()) if len(times) else "n/a"
        last = str(times.max().date()) if len(times) else "n/a"
        raise ValueError(
            f"The requested month {wanted_period} is not available in the standardized dataset. "
            f"Available monthly records span {first} to {last}. No temporal interpolation is performed."
        )
    idx = int(np.flatnonzero(months == wanted_period)[0])
    return da.isel(time=idx), str(times[idx].date())


def _spatial_dims(da: xr.DataArray) -> tuple[str, str]:
    spatial = [d for d in da.dims if d.startswith("lat") or d.startswith("lon")]
    lat = [d for d in spatial if d.startswith("lat")]
    lon = [d for d in spatial if d.startswith("lon")]
    if len(lat) != 1 or len(lon) != 1:
        raise ValueError(f"Could not identify latitude/longitude dimensions from {spatial}.")
    return lat[0], lon[0]


def _select_depth(da: xr.DataArray, mode: str, depth_m: float | None) -> tuple[xr.DataArray, float]:
    if "depth" not in da.dims:
        if mode != "surface":
            raise ValueError("The selected variable has no depth dimension; only Surface is applicable.")
        return da, float("nan")

    levels = np.asarray(da.depth.values, dtype=float)
    if levels.size == 0:
        raise ValueError("No native depth levels are present in the standardized dataset.")

    if mode == "surface":
        target = float(np.nanmin(levels))
    elif mode == "deepest":
        valid_levels = np.asarray(_finite_depths(da), dtype=float)
        if valid_levels.size == 0:
            raise ValueError("No finite native-grid values are available for any depth at the selected month.")
        target = float(np.nanmax(valid_levels))
    elif mode == "single":
        if depth_m is None:
            raise ValueError("A target depth is required for Single native depth.")
        if depth_m < 0:
            raise ValueError("Depth cannot be negative.")
        target = float(depth_m)
    else:
        raise ValueError(f"Unsupported map depth mode: {mode}")

    idx = int(np.nanargmin(np.abs(levels - target)))
    actual = float(levels[idx])
    return da.sel(depth=actual, method="nearest"), actual


def _finite_depths(da: xr.DataArray) -> list[float]:
    if "depth" not in da.dims:
        return []
    arr = np.asarray(da.values)
    axis = da.get_axis_num("depth")
    moved = np.moveaxis(arr, axis, 0)
    valid = np.isfinite(moved).reshape(moved.shape[0], -1).any(axis=1)
    return [float(v) for v in np.asarray(da.depth.values, dtype=float)[valid]]


def _as_plot_longitudes(lon: np.ndarray, data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon_plot = ((np.asarray(lon, dtype=float) + 180.0) % 360.0) - 180.0
    order = np.argsort(lon_plot)
    return lon_plot[order], np.asarray(data)[..., order]


def _plot_polygon(ax, geometry):
    if geometry is None:
        return False
    try:
        from .region import geometry_to_godas_longitudes
        geom = geometry_to_godas_longitudes(geometry)
        plotted = False
        geoms = getattr(geom, "geoms", None)
        if geoms is None:
            geoms = [geom]
        for part in geoms:
            if getattr(part, "geom_type", "") == "Polygon":
                coords = np.asarray(part.exterior.coords)
                x = ((coords[:, 0] + 180.0) % 360.0) - 180.0
                ax.plot(x, coords[:, 1], linewidth=1.6, linestyle="-", zorder=4)
                plotted = True
        return plotted
    except Exception:
        return False


def _map_dataframe(da: xr.DataArray, depth: float | None, panel: str) -> pd.DataFrame:
    lat_name, lon_name = _spatial_dims(da)
    lat = np.asarray(da[lat_name].values, dtype=float)
    lon = np.asarray(da[lon_name].values, dtype=float)
    values = np.asarray(da.transpose(lat_name, lon_name).values, dtype=float)
    plot_lon, plot_values = _as_plot_longitudes(lon, values)
    xx, yy = np.meshgrid(plot_lon, lat)
    return pd.DataFrame({
        "panel": panel,
        "depth_m": depth if depth is not None else np.nan,
        "latitude": yy.ravel(),
        "longitude": xx.ravel(),
        "value": plot_values.ravel(),
    })


def _plot_geometry_bounds(geometry):
    """Return study-region bounds in the plotted [-180, 180] longitude convention."""
    if geometry is None:
        return None
    try:
        from .region import geometry_to_godas_longitudes
        geom = geometry_to_godas_longitudes(geometry)
        xs, ys = [], []
        geoms = getattr(geom, "geoms", None)
        if geoms is None:
            geoms = [geom]
        for part in geoms:
            if getattr(part, "geom_type", "") != "Polygon":
                continue
            coords = np.asarray(part.exterior.coords, dtype=float)
            xs.extend((((coords[:, 0] + 180.0) % 360.0) - 180.0).tolist())
            ys.extend(coords[:, 1].tolist())
        if not xs or not ys:
            return None
        return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))
    except Exception:
        return None


def _nice_scalebar_km(width_km: float) -> float:
    """Choose a conventional round scale-bar length that occupies at most ~35% of map width."""
    target = max(width_km * 0.28, 1.0)
    exponent = int(np.floor(np.log10(target)))
    for mult in (5.0, 2.0, 1.0):
        candidate = mult * (10.0 ** exponent)
        if candidate <= target:
            return candidate
    return 1.0


def _add_map_decorations(ax, region_bounds=None):
    """Add a north arrow and geodesic scale bar inside the map frame."""
    try:
        from pyproj import Geod
        geod = Geod(ellps="WGS84")
    except Exception:
        geod = None

    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    width = abs(xmax - xmin)
    height = abs(ymax - ymin)
    if width <= 0 or height <= 0:
        return None

    # North arrow: upper-right corner with the label above the arrow.
    # The N label is intentionally separated from the arrow so it does not
    # overlap the shaft/head while remaining comfortably inside the frame.
    x = xmax - 0.055 * width
    tip_y = ymax - 0.11 * height
    base_y = tip_y - 0.10 * height
    ax.annotate(
        "", xy=(x, tip_y), xytext=(x, base_y),
        arrowprops={"arrowstyle": "-|>", "linewidth": 1.4, "color": "black"},
        zorder=10,
    )
    ax.text(
        x, tip_y + 0.025 * height, "N",
        ha="center", va="bottom", fontsize=10, fontweight="bold", color="black",
        zorder=10,
    )

    # Scale bar, lower-left.
    lat_c = (ymin + ymax) / 2.0
    lon0 = xmin + 0.06 * width
    if geod is not None:
        _, _, km_per_deg = geod.inv(lon0, lat_c, lon0 + 1.0, lat_c)
        km_per_deg = abs(km_per_deg) / 1000.0
    else:
        km_per_deg = 111.32 * max(np.cos(np.deg2rad(lat_c)), 1e-6)
    width_km = width * km_per_deg
    bar_km = _nice_scalebar_km(width_km)
    if geod is not None:
        lon1, _, _ = geod.fwd(lon0, lat_c, 90.0, bar_km * 1000.0)
    else:
        lon1 = lon0 + bar_km / km_per_deg
    y = ymin + 0.08 * height
    cap = 0.018 * height
    ax.plot([lon0, lon1], [y, y], linewidth=2.6, color="black", solid_capstyle="butt", zorder=10)
    ax.plot([lon0, lon0], [y - cap, y + cap], linewidth=1.2, color="black", zorder=10)
    ax.plot([lon1, lon1], [y - cap, y + cap], linewidth=1.2, color="black", zorder=10)
    ax.text(
        (lon0 + lon1) / 2.0, y + 0.035 * height, f"{bar_km:g} km",
        ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="black",
        bbox={"boxstyle": "round,pad=0.15", "facecolor": "white", "alpha": 0.82, "edgecolor": "0.5"},
        zorder=10,
    )
    return float(bar_km)


def _mask_values_outside_region(lat: np.ndarray, lon_plot: np.ndarray, values: np.ndarray, geometry) -> np.ndarray:
    """Mask native-grid cell centers outside the selected study-region geometry.

    This is a visualization-only spatial mask; it does not interpolate, regrid,
    or alter the underlying standardized values.
    """
    if geometry is None:
        return np.asarray(values, dtype=float)
    try:
        from shapely.geometry import Point
        from .region import geometry_to_godas_longitudes

        geom = geometry_to_godas_longitudes(geometry)
        out = np.asarray(values, dtype=float).copy()
        lon360 = np.mod(np.asarray(lon_plot, dtype=float), 360.0)
        lat_arr = np.asarray(lat, dtype=float)
        inside = np.zeros((lat_arr.size, lon360.size), dtype=bool)
        for iy, y in enumerate(lat_arr):
            for ix, x in enumerate(lon360):
                inside[iy, ix] = bool(geom.covers(Point(float(x), float(y))))
        out[~inside] = np.nan
        return out
    except Exception:
        # Geometry masking is a visual enhancement. If a geometry library edge
        # case occurs, preserve the native values and keep the boundary overlay.
        return np.asarray(values, dtype=float)


def _fill_region_white(ax, geometry) -> bool:
    """Fill the selected study region white beneath the data layer.

    Together with the gray axes background and transparent masked cells, this
    yields gray outside the selected region and white inside-region areas where
    no native-grid data are available. This is visualization-only.
    """
    if geometry is None:
        return False
    try:
        from matplotlib.patches import Polygon as MplPolygon
        from .region import geometry_to_godas_longitudes

        geom = geometry_to_godas_longitudes(geometry)
        geoms = getattr(geom, "geoms", None) or [geom]
        plotted = False
        for part in geoms:
            if getattr(part, "geom_type", "") != "Polygon":
                continue
            coords = np.asarray(part.exterior.coords, dtype=float)
            x = ((coords[:, 0] + 180.0) % 360.0) - 180.0
            y = coords[:, 1]
            patch = MplPolygon(
                np.column_stack([x, y]), closed=True,
                facecolor="white", edgecolor="none",
                linewidth=0.0, zorder=1,
            )
            ax.add_patch(patch)
            plotted = True
        return plotted
    except Exception:
        return False


def _make_figure(panels, title: str, units: str, cmap: str, vmin: float, vmax: float, region_geometry=None, show_boundary: bool = True):
    import matplotlib.pyplot as plt

    n = len(panels)
    # Reserve a dedicated colorbar column so the colorbar height matches the
    # map axes height exactly for both single-map and three-panel figures.
    fig_width = 7.0 * n + 0.65
    fig, all_axes = plt.subplots(
        1, n + 1,
        figsize=(fig_width, 5.35),
        squeeze=False,
        gridspec_kw={"width_ratios": [1.0] * n + [0.055], "wspace": 0.16},
    )
    all_axes = all_axes.ravel()
    axes = all_axes[:n]
    cbar_ax = all_axes[-1]
    mappable = None
    region_bounds = _plot_geometry_bounds(region_geometry) if show_boundary and region_geometry is not None else None
    scale_bar_km = None

    for ax, panel in zip(axes, panels):
        da = panel["da"]
        panel_label = panel["label"]
        lat_name, lon_name = _spatial_dims(da)
        lat = np.asarray(da[lat_name].values, dtype=float)
        lon = np.asarray(da[lon_name].values, dtype=float)
        vals = np.asarray(da.transpose(lat_name, lon_name).values, dtype=float)
        lon_plot, vals_plot = _as_plot_longitudes(lon, vals)
        has_region = bool(region_geometry is not None and show_boundary)
        if has_region:
            vals_plot = _mask_values_outside_region(lat, lon_plot, vals_plot, region_geometry)
            # Outside selected region = light gray; inside region with no native
            # data = white. NaNs are rendered transparent over these backgrounds.
            ax.set_facecolor("#e7eaed")
            _fill_region_white(ax, region_geometry)
        else:
            ax.set_facecolor("white")

        cmap_obj = plt.get_cmap(cmap).copy()
        if has_region:
            cmap_obj.set_bad(alpha=0.0)
        else:
            cmap_obj.set_bad(color="white", alpha=1.0)
        mappable = ax.pcolormesh(
            lon_plot, lat, vals_plot, shading="nearest",
            cmap=cmap_obj, vmin=vmin, vmax=vmax
        )
        if show_boundary and region_geometry is not None:
            _plot_polygon(ax, region_geometry)

        if region_bounds is not None:
            rx0, ry0, rx1, ry1 = region_bounds
            rw = max(rx1 - rx0, 0.01)
            rh = max(ry1 - ry0, 0.01)
            padx = max(rw * 0.08, 0.12)
            pady = max(rh * 0.08, 0.12)
            ax.set_xlim(rx0 - padx, rx1 + padx)
            ax.set_ylim(ry0 - pady, ry1 + pady)
        else:
            ax.set_xlim(float(np.nanmin(lon_plot)), float(np.nanmax(lon_plot)))
            ax.set_ylim(float(np.nanmin(lat)), float(np.nanmax(lat)))

        ax.set_title(panel_label, fontsize=11, fontweight="bold", pad=7)
        ax.set_xlabel("Longitude (°)")
        ax.set_ylabel("Latitude (°)")
        ax.grid(True, alpha=0.20, linewidth=0.6)
        ax.set_aspect("equal", adjustable="box")
        scale_bar_km = _add_map_decorations(ax, region_bounds=region_bounds)

        finite = np.isfinite(vals_plot)
        count = int(finite.sum())
        total = int(finite.size)
        ax.text(
            0.98, 0.035,
            f"Valid cells: {count}/{total}",
            transform=ax.transAxes,
            ha="right", va="bottom", fontsize=8.5,
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "alpha": 0.72, "edgecolor": "0.7"},
            zorder=10,
        )

    # The shared colorbar occupies the same vertical extent as the map axes.
    cbar = fig.colorbar(mappable, cax=cbar_ax)
    cbar.set_label(units, labelpad=9)
    cbar_ax.set_frame_on(False)
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.935)
    # Keep the figure title close to the maps while preserving enough room for
    # the panel/depth labels and top map decorations.
    fig.subplots_adjust(left=0.055, right=0.955, bottom=0.12, top=0.875)
    return fig, region_bounds, scale_bar_km


def run_spatial_visualization(
    output_dir: str,
    variable_key: str,
    map_layout: str,
    requested_date: str,
    unit_mode: str = "native",
    single_depth_mode: str = "surface",
    single_depth: float | None = None,
    middle_depth: float | None = None,
    cmap: str = "turbo",
    color_mode: str = "auto",
    vmin: float | None = None,
    vmax: float | None = None,
    region_geometry=None,
    region_label: str | None = None,
    show_boundary: bool = True,
    export_dir: str | None = None,
    formats: Iterable[str] = ("png", "svg", "pdf"),
    progress=None,
) -> dict:
    if variable_key not in VARIABLES:
        raise ValueError(f"Unsupported variable: {variable_key}")
    _, _, _, has_depth = VARIABLES[variable_key]
    if not has_depth and single_depth_mode != "surface":
        raise ValueError("The selected variable has no vertical dimension; only Surface mapping is applicable.")
    if map_layout not in {"single", "three_depths"}:
        raise ValueError(f"Unsupported map layout: {map_layout}")

    root = Path(output_dir)
    src = standardized_file(root, variable_key)
    outdir = Path(export_dir) if export_dir else root / "analysis" / "spatial_visualization"
    outdir.mkdir(parents=True, exist_ok=True)

    prefix, label, source_units, has_depth = VARIABLES[variable_key]
    created_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if progress:
        progress(f"[MAP] Source: {src}")
        progress(f"[MAP] Requested month: {_month_start(requested_date).strftime('%Y-%m')}")

    with xr.open_dataset(src) as ds:
        da = _standardized_dataarray(ds, variable_key)
        month_da, actual_date = _select_month(da, requested_date)
        converted, out_units, conversion = _convert_units(month_da, variable_key, unit_mode)
        panels = []
        selected_depths: list[float] = []

        if map_layout == "single":
            selected, actual_depth = _select_depth(converted, single_depth_mode, single_depth)
            if has_depth:
                selected_depths = [actual_depth]
                depth_label = f"Depth = {actual_depth:g} m"
            else:
                depth_label = "Surface field"
            panels.append({
                "da": selected,
                "depth": actual_depth if has_depth else None,
                "label": depth_label,
            })
        else:
            if not has_depth:
                raise ValueError("Three-depth mapping is available only for depth-dependent variables.")
            surface, surface_depth = _select_depth(converted, "surface", None)
            middle, middle_actual = _select_depth(converted, "single", middle_depth)
            deepest, deepest_actual = _select_depth(converted, "deepest", None)
            selected_depths = [surface_depth, middle_actual, deepest_actual]
            panels = [
                {"da": surface, "depth": surface_depth, "label": f"Surface — {surface_depth:g} m"},
                {"da": middle, "depth": middle_actual, "label": f"Middle — {middle_actual:g} m"},
                {"da": deepest, "depth": deepest_actual, "label": f"Deepest valid — {deepest_actual:g} m"},
            ]

        finite_all = np.concatenate([
            np.asarray(p["da"].values, dtype=float).ravel()
            for p in panels
        ])
        finite_all = finite_all[np.isfinite(finite_all)]
        if finite_all.size == 0:
            raise ValueError("No finite native-grid values are available for the selected month/depth(s).")

        auto_min = float(np.nanmin(finite_all))
        auto_max = float(np.nanmax(finite_all))
        if color_mode == "fixed":
            if vmin is None or vmax is None:
                raise ValueError("Fixed color scale requires both minimum and maximum values.")
            if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
                raise ValueError("Fixed color scale requires finite values with minimum < maximum.")
            plot_min, plot_max = float(vmin), float(vmax)
        else:
            plot_min, plot_max = auto_min, auto_max

        if np.isclose(plot_min, plot_max):
            pad = max(abs(plot_min) * 0.01, 1e-6)
            plot_min -= pad
            plot_max += pad

        title = f"{label} — {actual_date[:7]}"
        if region_label:
            title = f"{title} — {region_label}"
        if map_layout == "three_depths":
            title += " | Native-grid depth comparison"
        else:
            # Keep depth information in the panel title only; avoid repeating it
            # in the figure super-title.
            pass
        fig, map_extent, scale_bar_km = _make_figure(
            panels, title, out_units, cmap, plot_min, plot_max,
            region_geometry=region_geometry if show_boundary else None,
            show_boundary=show_boundary,
        )

        base = f"{prefix}_{actual_date[:7]}_{'three_depths' if map_layout == 'three_depths' else 'map'}_{created_utc}"
        outputs: dict[str, str] = {}
        for fmt in formats:
            fmt = str(fmt).lower().lstrip(".")
            if fmt not in {"png", "svg", "pdf"}:
                continue
            path = outdir / f"{base}.{fmt}"
            fig.savefig(path, dpi=300 if fmt == "png" else 300, bbox_inches="tight")
            outputs[fmt] = str(path)

        import matplotlib.pyplot as plt
        plt.close(fig)

        csv_path = outdir / f"{base}.csv"
        frames = []
        for panel in panels:
            frames.append(_map_dataframe(panel["da"], panel.get("depth"), panel["label"]))
        pd.concat(frames, ignore_index=True).to_csv(csv_path, index=False)
        outputs["csv"] = str(csv_path)

        report = {
            "software_version": SOFTWARE_VERSION,
            "schema_version": REPORT_SCHEMA_VERSION,
            "analysis_type": "spatial_visualization",
            "map_product": "data_map",
            "variable": variable_key,
            "period": {"start": actual_date, "end": actual_date},
            "observation_coverage": {
                "requested_month": _month_start(requested_date).strftime("%Y-%m"),
                "selected_record": actual_date,
                "source_first_record": str(pd.Timestamp(da.time.values.min()).date()),
                "source_last_record": str(pd.Timestamp(da.time.values.max()).date()),
            },
            "depth_information": {
                "mode": "not_applicable" if not has_depth else ("three_depths" if map_layout == "three_depths" else single_depth_mode),
                "requested_single_depth_m": single_depth if single_depth is not None else "not_applicable",
                "selected_depth_levels_m": selected_depths,
                "selected_depth_count": len(selected_depths),
                "deepest_valid_depth_m": max(selected_depths) if selected_depths else None,
            },
            "source_file": str(src),
            "source_units": source_units,
            "output_units": out_units,
            "unit_conversion": conversion,
            "processing": standard_processing("native-grid visualization; no spatial averaging", source_units, out_units, conversion),
            "spatial_information": {
                "grid_dimensions": {d: int(month_da.sizes[d]) for d in month_da.dims if d.startswith("lat") or d.startswith("lon")},
                "native_grid_preserved": True,
                "region_overlay": bool(show_boundary and region_geometry is not None),
                "region_label": region_label,
                "spatial_statistic": "none; values plotted directly from each native-grid cell",
            },
            "visualization": {
                "map_layout": map_layout,
                "cmap": cmap,
                "color_scale_mode": color_mode,
                "color_scale_min": plot_min,
                "color_scale_max": plot_max,
                "selected_month": actual_date[:7],
                "map_extent": map_extent,
                "north_arrow": {"enabled": True, "position": "upper_right_inset"},
                "scale_bar": {"enabled": True, "length_km": scale_bar_km, "color": "black"},
                "region_boundary": {"enabled": bool(show_boundary and region_geometry is not None), "fit_to_region": True},
                "region_rendering": {
                    "outside_region_fill": "light_gray",
                    "inside_region_no_data_fill": "white",
                },
                "no_temporal_interpolation": True,
                "no_spatial_interpolation": True,
                "no_regridding": True,
            },
            "integrity": {
                "status": "PASS",
                "finite_cells_total": int(finite_all.size),
                "native_grid_only": True,
                "interpolation": False,
                "extrapolation": False,
                "gap_filling": False,
                "regridding": False,
            },
            "outputs": {**outputs},
        }
        report_path = outdir / f"Spatial_Visualization_report_{created_utc}.json"
        report["outputs"]["report"] = str(report_path)
        report["report_validation"] = validate_report(report)
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        report["report"] = str(report_path)

        if progress:
            progress(f"[MAP OK] Figure outputs: {', '.join(sorted(k for k in outputs if k in {'png','svg','pdf'}))}")
            progress(f"[MAP OK] Data CSV: {csv_path.name}")
            progress(f"[MAP OK] Report: {report_path.name}")
            progress("[DONE] Spatial visualization completed successfully.")

        return {**outputs, "report": str(report_path), "actual_date": actual_date, "selected_depths": selected_depths}

# -----------------------------------------------------------------------------
# Map Composer foundation (v2.5.0)
# -----------------------------------------------------------------------------

def _subset_period(da: xr.DataArray, start: str | None, end: str | None) -> xr.DataArray:
    if start:
        da = da.sel(time=slice(start, end or None))
    elif end:
        da = da.sel(time=slice(None, end))
    if da.sizes.get("time", 0) == 0:
        raise ValueError("No monthly records remain in the selected time period.")
    return da


def _period_from_value(value: str | pd.Timestamp) -> pd.Period:
    return pd.Timestamp(value).to_period("M")


def _complete_year_field(da: xr.DataArray) -> xr.DataArray:
    """Annual means using only complete 12-month years, per native grid cell."""
    times = pd.DatetimeIndex(pd.to_datetime(da.time.values))
    years = np.asarray(times.year, dtype=int)
    parts = []
    labels = []
    for year in sorted(np.unique(years)):
        idx = np.where(years == year)[0]
        if len(idx) != 12:
            continue
        block = da.isel(time=idx)
        mean = block.mean("time", skipna=True)
        complete = block.count("time") == 12
        parts.append(mean.where(complete).expand_dims(year=[int(year)]))
        labels.append(int(year))
    if not parts:
        raise ValueError("No complete calendar years are available in the selected period.")
    return xr.concat(parts, dim="year", coords="minimal", compat="override")


def _complete_season_field(da: xr.DataArray) -> xr.DataArray:
    """Season-year means using complete 3-month seasons, per native grid cell."""
    times = pd.DatetimeIndex(pd.to_datetime(da.time.values))
    seasons = np.full(len(times), "", dtype=object)
    season_year = times.year.to_numpy(dtype=int)
    for i, month in enumerate(times.month):
        if month in (12, 1, 2):
            seasons[i] = "DJF"
            if month == 12:
                season_year[i] += 1
        elif month in (3, 4, 5):
            seasons[i] = "MAM"
        elif month in (6, 7, 8):
            seasons[i] = "JJA"
        else:
            seasons[i] = "SON"
    tagged = da.assign_coords(
        _season=("time", seasons.astype(str)),
        _season_year=("time", season_year),
    )
    rows = []
    for sy in sorted(np.unique(season_year)):
        for season in ("DJF", "MAM", "JJA", "SON"):
            idx = np.where((season_year == sy) & (seasons == season))[0]
            if len(idx) != 3:
                continue
            block = tagged.isel(time=idx)
            mean = block.mean("time", skipna=True)
            complete = block.count("time") == 3
            rows.append(
                mean.where(complete).expand_dims(season_year=[int(sy)]).assign_coords(_season=("season_year", [season]))
            )
    if not rows:
        raise ValueError("No complete 3-month seasons are available in the selected period.")
    return xr.concat(rows, dim="season_year", coords="minimal", compat="override")


def _climatology_field(da: xr.DataArray, mode: str, baseline_start: str, baseline_end: str,
                       period_value: int | str | None = None) -> tuple[xr.DataArray, str]:
    base = _subset_period(da, baseline_start, baseline_end)
    if mode == "monthly":
        if period_value is None:
            raise ValueError("A target month is required for Monthly climatology.")
        month = int(period_value)
        mask = pd.DatetimeIndex(pd.to_datetime(base.time.values)).month == month
        idx = np.flatnonzero(mask)
        if len(idx) == 0:
            raise ValueError(f"No records for month {month} exist in the baseline period.")
        field = base.isel(time=idx).mean("time", skipna=True)
        # All available monthly records are part of a valid monthly climatology.
        label = pd.Timestamp(2000, month, 1).strftime("%B")
        return field, label
    if mode == "seasonal":
        wanted = str(period_value)
        if wanted not in {"DJF", "MAM", "JJA", "SON"}:
            raise ValueError("Season must be one of DJF, MAM, JJA, or SON.")

        # DJF season-year Y is defined as Dec(Y-1) + Jan(Y) + Feb(Y).
        # When a user selects a complete calendar-year baseline (e.g. 1995),
        # include the immediately preceding December only as a scientifically
        # documented supporting month. The requested baseline period itself is
        # unchanged in the report.
        support_period = None
        base_for_season = base
        if wanted == "DJF":
            start_ts = pd.Timestamp(baseline_start).to_period("M").to_timestamp()
            previous_dec = (start_ts - pd.offsets.MonthBegin(1)).to_period("M")
            all_periods = pd.PeriodIndex(pd.to_datetime(da.time.values), freq="M")
            base_periods = pd.PeriodIndex(pd.to_datetime(base.time.values), freq="M")
            has_previous = previous_dec in set(all_periods)
            needs_previous = previous_dec not in set(base_periods)
            if has_previous and needs_previous:
                mask = np.isin(all_periods.astype(str), np.array([previous_dec.strftime("%Y-%m")]))
                support_idx = np.flatnonzero(mask)
                base_for_season = xr.concat([da.isel(time=support_idx), base], dim="time").sortby("time")
                support_period = str(previous_dec)

        season_field = _complete_season_field(base_for_season)
        idx = np.flatnonzero(np.asarray(season_field["_season"].values).astype(str) == wanted)
        if len(idx) == 0:
            if wanted == "DJF" and support_period is None:
                raise ValueError(
                    "No complete DJF seasons exist in the baseline period. DJF requires December of the previous year plus January and February. "
                    "The source dataset does not contain the required supporting December."
                )
            raise ValueError(f"No complete {wanted} seasons exist in the baseline period.")
        field = season_field.isel(season_year=idx).mean("season_year", skipna=True)
        if support_period is not None:
            field.attrs = dict(field.attrs)
            field.attrs["djf_supporting_month"] = support_period
        return field, wanted
    if mode == "annual":
        annual = _complete_year_field(base)
        return annual.mean("year", skipna=True), "Annual"
    raise ValueError(f"Unsupported map climatology mode: {mode}")


def _target_field(da: xr.DataArray, mode: str, target_date: str | None = None,
                  target_season: str | None = None, target_year: int | None = None) -> tuple[xr.DataArray, str]:
    times = pd.DatetimeIndex(pd.to_datetime(da.time.values))
    if mode == "monthly":
        if target_date is None:
            raise ValueError("A target month is required for Monthly anomaly mapping.")
        target = _month_start(target_date).to_period("M")
        months = pd.PeriodIndex(times, freq="M")
        idx = np.flatnonzero(months == target)
        if len(idx) == 0:
            raise ValueError(f"Target month {target} is not available. No temporal interpolation is performed.")
        return da.isel(time=int(idx[0])), target.strftime("%B %Y")
    if mode == "seasonal":
        if target_season not in {"DJF", "MAM", "JJA", "SON"} or target_year is None:
            raise ValueError("Seasonal anomaly mapping requires a season and season year.")
        seasons, sy = [], []
        for ts in times:
            m = int(ts.month)
            if m in (12,1,2):
                s = "DJF"; y = int(ts.year) + (1 if m == 12 else 0)
            elif m in (3,4,5): s = "MAM"; y = int(ts.year)
            elif m in (6,7,8): s = "JJA"; y = int(ts.year)
            else: s = "SON"; y = int(ts.year)
            seasons.append(s); sy.append(y)
        idx = np.flatnonzero((np.asarray(seasons) == target_season) & (np.asarray(sy) == int(target_year)))
        if len(idx) != 3:
            raise ValueError(f"Target {target_season} {target_year} is incomplete; all 3 months are required.")
        block = da.isel(time=idx)
        complete = block.count("time") == 3
        return block.mean("time", skipna=True).where(complete), f"{target_season} {target_year}"
    if mode == "annual":
        if target_year is None:
            raise ValueError("Annual anomaly mapping requires a target year.")
        idx = np.flatnonzero(times.year == int(target_year))
        if len(idx) != 12:
            raise ValueError(f"Target year {target_year} is incomplete; all 12 months are required.")
        block = da.isel(time=idx)
        complete = block.count("time") == 12
        return block.mean("time", skipna=True).where(complete), str(target_year)
    raise ValueError(f"Unsupported map anomaly mode: {mode}")


def _elapsed_years(times: pd.DatetimeIndex) -> np.ndarray:
    if len(times) == 0:
        return np.array([], dtype=float)
    origin = times[0]
    return (times - origin).total_seconds() / (365.2425 * 24 * 3600)


def _trend_cellwise(field: xr.DataArray, trend_mode: str, method: str, target_season: str | None = None) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray]:
    """Compute a native-grid-cell temporal trend without spatial averaging."""
    from scipy.stats import kendalltau, linregress

    lat_name, lon_name = _spatial_dims(field)
    dims = list(field.dims)
    if trend_mode == "monthly":
        x = _elapsed_years(pd.DatetimeIndex(pd.to_datetime(field.time.values)))
        time_dim = "time"
    elif trend_mode == "annual":
        field = _complete_year_field(field)
        x = np.asarray(field.year.values, dtype=float) - float(field.year.values[0])
        time_dim = "year"
    elif trend_mode == "seasonal":
        field = _complete_season_field(field)
        time_dim = "season_year"
    else:
        raise ValueError(f"Unsupported trend mode: {trend_mode}")

    if trend_mode == "seasonal":
        if target_season not in {"DJF", "MAM", "JJA", "SON"}:
            raise ValueError("Seasonal trend maps require one of DJF, MAM, JJA, or SON.")
        idx = np.flatnonzero(np.asarray(field["_season"].values).astype(str) == target_season)
        if len(idx) < 3:
            raise ValueError(f"No seasonal trend series with at least three observations are available for {target_season}.")
        sub = field.isel(season_year=idx)
        x = np.asarray(sub.season_year.values, dtype=float)
        return _trend_grid_single_series(sub, x, method, lat_name, lon_name, time_dim)

    return _trend_grid_single_series(field, x, method, lat_name, lon_name, time_dim)


def _trend_grid_single_series(field: xr.DataArray, x: np.ndarray, method: str,
                              lat_name: str, lon_name: str, time_dim: str) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray]:
    from scipy.stats import kendalltau, linregress

    arr = np.asarray(field.transpose(time_dim, lat_name, lon_name).values, dtype=float)
    nlat, nlon = arr.shape[1], arr.shape[2]
    trend = np.full((nlat, nlon), np.nan, dtype=float)
    pval = np.full((nlat, nlon), np.nan, dtype=float)
    nobs = np.zeros((nlat, nlon), dtype=int)

    def sen_slope(xx, yy):
        slopes = []
        for i in range(len(xx) - 1):
            dx = xx[i+1:] - xx[i]
            dy = yy[i+1:] - yy[i]
            good = dx != 0
            if np.any(good):
                slopes.extend((dy[good] / dx[good]).tolist())
        return float(np.median(slopes)) if slopes else np.nan

    for iy in range(nlat):
        for ix in range(nlon):
            y = arr[:, iy, ix]
            good = np.isfinite(y) & np.isfinite(x)
            xx = np.asarray(x)[good]
            yy = y[good]
            n = len(yy)
            nobs[iy, ix] = n
            if n < 3:
                continue
            if np.nanmax(xx) == np.nanmin(xx):
                continue
            if method == "ols":
                res = linregress(xx, yy)
                trend[iy, ix] = float(res.slope * 10.0)
                pval[iy, ix] = float(res.pvalue)
            elif method == "sen":
                slope = sen_slope(xx, yy)
                trend[iy, ix] = slope * 10.0 if np.isfinite(slope) else np.nan
                tau, p = kendalltau(xx, yy)
                pval[iy, ix] = float(p) if np.isfinite(p) else np.nan
            elif method == "mk":
                tau, p = kendalltau(xx, yy)
                trend[iy, ix] = float(tau) if np.isfinite(tau) else np.nan
                pval[iy, ix] = float(p) if np.isfinite(p) else np.nan
            else:
                raise ValueError("Trend method must be OLS, Mann–Kendall, or Sen's Slope.")

    coords = {lat_name: field[lat_name], lon_name: field[lon_name]}
    trend_da = xr.DataArray(trend, coords=coords, dims=(lat_name, lon_name), name="trend")
    p_da = xr.DataArray(pval, coords=coords, dims=(lat_name, lon_name), name="p_value")
    n_da = xr.DataArray(nobs, coords=coords, dims=(lat_name, lon_name), name="n_obs")
    return trend_da, p_da, n_da


def _render_map_product(output_dir: str, variable_key: str, field: xr.DataArray, label: str,
                        panel_label: str, units: str, cmap: str, color_mode: str,
                        vmin: float | None, vmax: float | None, region_geometry, region_label,
                        export_dir: str | None, formats: Iterable[str], product_label: str,
                        csv_extra: dict[str, np.ndarray] | None = None, report_extra: dict | None = None,
                        progress=None) -> dict:
    root = Path(output_dir)
    outdir = Path(export_dir) if export_dir else root / "analysis" / "spatial_visualization"
    outdir.mkdir(parents=True, exist_ok=True)
    values = np.asarray(field.values, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("The selected map product contains no finite native-grid values.")
    auto_min, auto_max = float(np.nanmin(finite)), float(np.nanmax(finite))
    if color_mode == "fixed":
        if vmin is None or vmax is None or not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
            raise ValueError("Fixed color scale requires finite Minimum < Maximum values.")
        plot_min, plot_max = float(vmin), float(vmax)
    else:
        plot_min, plot_max = auto_min, auto_max
    if np.isclose(plot_min, plot_max):
        pad = max(abs(plot_min) * 0.01, 1e-6)
        plot_min -= pad; plot_max += pad

    panel = {"da": field, "depth": None, "label": panel_label}
    fig, map_extent, scale_bar_km = _make_figure(
        [panel], f"{label} — {region_label}" if region_label else label,
        units, cmap, plot_min, plot_max,
        region_geometry=region_geometry, show_boundary=region_geometry is not None,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = product_label.lower().replace(" ", "_")
    base = f"{VARIABLES[variable_key][0]}_{safe_label}_{stamp}"
    outputs: dict[str, str] = {}
    for fmt in formats:
        fmt = str(fmt).lower().lstrip(".")
        if fmt not in {"png", "svg", "pdf"}:
            continue
        path = outdir / f"{base}.{fmt}"
        fig.savefig(path, dpi=300, bbox_inches="tight")
        outputs[fmt] = str(path)
    import matplotlib.pyplot as plt
    plt.close(fig)

    df = _map_dataframe(field, None, panel_label)
    if csv_extra:
        for key, arr in csv_extra.items():
            df[key] = np.asarray(arr).ravel()
    csv_path = outdir / f"{base}.csv"
    df.to_csv(csv_path, index=False)
    outputs["csv"] = str(csv_path)

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "software_version": SOFTWARE_VERSION,
        "schema_version": REPORT_SCHEMA_VERSION,
        "analysis_type": "spatial_visualization",
        "map_product": product_label,
        "variable": variable_key,
        "period": report_extra.get("period", {"start": None, "end": None}) if report_extra else {"start": None, "end": None},
        "observation_coverage": report_extra.get("observation_coverage", {}) if report_extra else {},
        "depth_information": report_extra.get("depth_information", {"mode": "not_applicable"}) if report_extra else {"mode": "not_applicable"},
        "source_file": report_extra.get("source_file") if report_extra else None,
        "source_units": report_extra.get("source_units", units) if report_extra else units,
        "output_units": units,
        "unit_conversion": report_extra.get("unit_conversion", "none") if report_extra else "none",
        "processing": standard_processing("none; direct native-grid cells", report_extra.get("source_units", units) if report_extra else units, units, report_extra.get("unit_conversion", "none") if report_extra else "none"),
        "spatial_information": {
            "grid_dimensions": {d: int(field.sizes[d]) for d in field.dims if d.startswith("lat") or d.startswith("lon")},
            "native_grid_preserved": True,
            "region_overlay": region_geometry is not None,
            "region_label": region_label,
            "spatial_statistic": "none; independent native-grid cells",
        },
        "visualization": {
            "map_product": product_label,
            "panel_label": panel_label,
            "cmap": cmap,
            "color_scale_mode": color_mode,
            "color_scale_min": plot_min,
            "color_scale_max": plot_max,
            "map_extent": map_extent,
            "north_arrow": {"enabled": True, "position": "upper_right_inset"},
            "scale_bar": {"enabled": True, "length_km": scale_bar_km, "color": "black"},
            "region_boundary": {"enabled": region_geometry is not None, "fit_to_region": region_geometry is not None},
            "region_rendering": {"outside_region_fill": "light_gray", "inside_region_no_data_fill": "white"},
        },
        "integrity": {
            "status": "PASS",
            "finite_cells_total": int(finite.size),
            "native_grid_only": True,
            "interpolation": False,
            "extrapolation": False,
            "gap_filling": False,
            "regridding": False,
        },
        "outputs": {**outputs},
        "created_utc": now,
    }
    if report_extra:
        # Keep product-specific scientific metadata alongside the common contract.
        for k, v in report_extra.items():
            if k not in report:
                report[k] = v
    report_path = outdir / f"Map_{safe_label}_report_{stamp}.json"
    report["outputs"]["report"] = str(report_path)
    report["report_validation"] = validate_report(report)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    outputs["report"] = str(report_path)
    if progress:
        progress(f"[MAP OK] {product_label}: {csv_path.name}; report={report_path.name}")
    return {**outputs, "report": str(report_path)}


def run_map_product(output_dir: str, params: dict, progress=None) -> dict:
    """Unified Map Composer foundation for Data / Climatology / Anomaly / Trend maps."""
    product = str(params.get("product", "data_map"))
    if product == "data_map":
        return run_spatial_visualization(
            output_dir,
            params["variable_key"],
            params.get("map_layout", "single"),
            params.get("requested_date", "2025-07-01"),
            params.get("unit_mode", "native"),
            params.get("single_depth_mode", "surface"),
            params.get("single_depth"),
            params.get("middle_depth"),
            params.get("cmap", "turbo"),
            params.get("color_mode", "auto"),
            params.get("vmin"), params.get("vmax"),
            params.get("region_geometry"), params.get("region_label"),
            params.get("show_boundary", True), params.get("export_dir"),
            params.get("formats", ("png", "svg", "pdf")), progress=progress,
        )

    variable_key = params["variable_key"]
    root = Path(output_dir)
    src = standardized_file(root, variable_key)
    prefix, var_label, source_units, has_depth = VARIABLES[variable_key]
    unit_mode = params.get("unit_mode", "native")
    cmap = params.get("cmap", "turbo")
    color_mode = params.get("color_mode", "auto")
    vmin, vmax = params.get("vmin"), params.get("vmax")
    geometry = params.get("region_geometry")
    region_label = params.get("region_label")
    formats = params.get("formats", ("png", "svg", "pdf"))

    with xr.open_dataset(src, decode_times=True, mask_and_scale=True) as ds:
        da = _standardized_dataarray(ds, variable_key)
        converted_all, out_units, conversion = _convert_units(da, variable_key, unit_mode)

        depth_mode = params.get("depth_mode", "surface")
        depth_value = params.get("depth_value")
        if has_depth:
            selected_source, actual_depth = _select_depth(converted_all, depth_mode, depth_value)
        else:
            selected_source, actual_depth = converted_all, None

        source_times = pd.DatetimeIndex(pd.to_datetime(da.time.values))
        report_extra = {
            "source_file": str(src), "source_units": source_units, "unit_conversion": conversion,
            "depth_information": {"mode": "not_applicable" if not has_depth else depth_mode,
                                   "selected_depth_levels_m": [] if actual_depth is None else [actual_depth],
                                   "selected_depth_count": 0 if actual_depth is None else 1},
        }

        if product == "climatology_map":
            mode = params.get("period_mode", "monthly")
            baseline_start = params.get("baseline_start", "1980-01-01")
            baseline_end = params.get("baseline_end", "2026-12-31")
            period_value = params.get("period_value")
            field, period_label = _climatology_field(selected_source, mode, baseline_start, baseline_end, period_value)
            panel_label = f"{period_label} | Depth = {actual_depth:g} m" if actual_depth is not None else period_label
            report_extra.update({
                "period": {"start": baseline_start, "end": baseline_end},
                "baseline": {"start": baseline_start, "end": baseline_end},
                "observation_coverage": {"source_first_record": str(source_times.min().date()), "source_last_record": str(source_times.max().date())},
                "climatology_mode": mode,
                "climatology_period": period_label,
            })
            if mode == "seasonal" and str(period_value) == "DJF":
                report_extra["season_definition"] = "DJF = December of previous year + January + February"
                report_extra["supporting_months_used"] = ([field.attrs["djf_supporting_month"]]
                                                            if "djf_supporting_month" in field.attrs else [])
            return _render_map_product(output_dir, variable_key, field, f"{var_label} Climatology", panel_label,
                                       out_units, cmap, color_mode, vmin, vmax, geometry, region_label,
                                       params.get("export_dir"), formats, "climatology_map", report_extra=report_extra, progress=progress)

        if product == "anomaly_map":
            mode = params.get("period_mode", "monthly")
            baseline_start = params.get("baseline_start", "1980-01-01")
            baseline_end = params.get("baseline_end", "2026-12-31")
            baseline_field, baseline_label = _climatology_field(selected_source, mode, baseline_start, baseline_end,
                                                                params.get("period_value"))
            target_field, target_label = _target_field(selected_source, mode,
                                                       params.get("target_date"), params.get("target_season"), params.get("target_year"))
            field = target_field - baseline_field
            panel_label = f"{target_label} | Depth = {actual_depth:g} m" if actual_depth is not None else target_label
            report_extra.update({
                "period": {"start": params.get("target_date") or str(params.get("target_year") or target_label), "end": params.get("target_date") or str(params.get("target_year") or target_label)},
                "baseline": {"start": baseline_start, "end": baseline_end},
                "observation_coverage": {"source_first_record": str(source_times.min().date()), "source_last_record": str(source_times.max().date())},
                "anomaly_mode": mode,
                "target_period": target_label,
                "baseline_period": baseline_label,
            })
            if mode == "seasonal" and str(params.get("period_value")) == "DJF":
                report_extra["season_definition"] = "DJF = December of previous year + January + February"
                report_extra["supporting_months_used"] = ([baseline_field.attrs["djf_supporting_month"]]
                                                            if "djf_supporting_month" in baseline_field.attrs else [])
            return _render_map_product(output_dir, variable_key, field, f"{var_label} Anomaly", panel_label,
                                       out_units, cmap, color_mode, vmin, vmax, geometry, region_label,
                                       params.get("export_dir"), formats, "anomaly_map", report_extra=report_extra, progress=progress)

        if product == "trend_map":
            trend_mode = params.get("trend_mode", "annual")
            trend_start = params.get("trend_start", "1980-01-01")
            trend_end = params.get("trend_end", "2026-12-31")
            method = params.get("trend_method", "ols")
            field = _subset_period(selected_source, trend_start, trend_end)
            trend_season = params.get("trend_season") if trend_mode == "seasonal" else None
            trend_field, p_field, n_field = _trend_cellwise(field, trend_mode, method, trend_season)
            if method == "mk":
                units = "Kendall tau (dimensionless)"
                method_label = "Mann–Kendall tau"
            else:
                units = f"{out_units} decade⁻¹"
                method_label = "OLS slope" if method == "ols" else "Sen's slope"
            panel_label = f"{trend_season} | {method_label} | Depth = {actual_depth:g} m" if actual_depth is not None and trend_mode == "seasonal" else (f"{trend_season} | {method_label}" if trend_mode == "seasonal" else (f"{method_label} | Depth = {actual_depth:g} m" if actual_depth is not None else method_label))
            extra_cols = {"p_value": np.asarray(p_field.values), "n_obs": np.asarray(n_field.values)}
            report_extra.update({
                "period": {"start": trend_start, "end": trend_end},
                "trend_mode": trend_mode,
                "trend_method": method,
                "trend_season": trend_season if trend_mode == "seasonal" else "not_applicable",
                "observation_coverage": {"source_first_record": str(source_times.min().date()), "source_last_record": str(source_times.max().date())},
                "trend_definition": "independent temporal trend at each native-grid cell; no spatial averaging",
                "minimum_n": 3,
                "autocorrelation_correction": "none",
            })
            return _render_map_product(output_dir, variable_key, trend_field,
                                       f"{var_label} Trend — {trend_start[:4]}–{trend_end[:4]}", panel_label,
                                       units, cmap, color_mode, vmin, vmax, geometry, region_label,
                                       params.get("export_dir"), formats, "trend_map", csv_extra=extra_cols,
                                       report_extra=report_extra, progress=progress)

    raise ValueError(f"Unsupported map product: {product}")
