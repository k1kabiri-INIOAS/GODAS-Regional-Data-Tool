from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import re

import requests
import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
from shapely import contains_xy
from core.region import RegionSpec, geometry_to_godas_longitudes, MARINE_REGIONS_WFS
from core.reporting import SOFTWARE_VERSION

# Direct HTTP download endpoint for NOAA PSL GODAS yearly NetCDF files.
# This is intentionally used instead of OPeNDAP because it proved more robust
# on the user's system.
GODAS_BASE = "https://downloads.psl.noaa.gov/Datasets/godas"

from config.variables import GODAS_VARIABLES

DATASETS = {
    key: {"file_prefix": meta["dataset"], "variable": meta["dataset"], "has_depth": bool(meta["has_depth"])}
    for key, meta in GODAS_VARIABLES.items()
}

@dataclass
class DownloadSummary:
    requested: int = 0
    success: int = 0
    skipped: int = 0
    unavailable: int = 0
    failed: int = 0
    cancelled: bool = False

    @property
    def completed(self) -> int:
        return self.success + self.skipped


def dataset_url(prefix: str, year: int) -> str:
    return f"{GODAS_BASE}/{prefix}.{year}.nc"


def region_code_from_shapefile(shapefile: str) -> str:
    """Create a stable filename-safe region code from the selected Shapefile name."""
    stem = Path(shapefile).stem.strip()
    code = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").upper()
    if not code:
        raise ValueError("Could not derive a valid region code from the Shapefile name.")
    return code[:32]


def check_url(url: str, timeout: int = 30) -> bool:
    """Check direct HTTP availability; fall back to a small GET if HEAD fails."""
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return True
    except requests.RequestException:
        pass

    try:
        with requests.get(url, timeout=timeout, stream=True, allow_redirects=True) as r:
            return r.status_code == 200
    except requests.RequestException:
        return False


def _prepare_region(shapefile: str):
    gdf = gpd.read_file(shapefile)
    if gdf.empty:
        raise ValueError("The region Shapefile contains no features.")
    if gdf.crs is None:
        raise ValueError("The region Shapefile has no CRS (.prj).")

    gdf = gdf.to_crs(epsg=4326)
    gdf.geometry = gdf.geometry.make_valid()
    geom = gdf.geometry.union_all()
    if geom.is_empty:
        raise ValueError("The region geometry is empty after validation.")
    return geom


def _subset_spatial(ds: xr.Dataset, geom, xmin, xmax, ymin, ymax):
    """Bounding-box subset followed by exact polygon mask."""
    # GODAS uses a 0–360° longitude convention. Convert the study geometry
    # to that convention before spatial subsetting and exact masking.
    geom = geometry_to_godas_longitudes(geom)
    xmin, ymin, xmax, ymax = geom.bounds

    xmin = max(0.5, xmin)
    xmax = min(359.5, xmax)
    ymin = max(-74.5, ymin)
    ymax = min(64.5, ymax)

    if xmin > xmax or ymin > ymax:
        raise ValueError("The Shapefile extent does not intersect the GODAS grid domain.")

    ds = ds.sel(
        lon=slice(xmin, xmax),
        lat=slice(ymin, ymax),
    )

    if ds.sizes.get("lon", 0) == 0 or ds.sizes.get("lat", 0) == 0:
        raise ValueError("No GODAS grid cells intersect the region bounding box.")

    lon = ds["lon"].values
    lat = ds["lat"].values
    xx, yy = np.meshgrid(lon, lat)
    mask = contains_xy(geom, xx, yy)

    mask_da = xr.DataArray(
        mask,
        dims=("lat", "lon"),
        coords={"lat": ds["lat"], "lon": ds["lon"]},
        name="region_mask",
    )
    return ds.where(mask_da)


def _subset_time(ds: xr.Dataset, start_date: str, end_date: str) -> xr.Dataset:
    """Apply the exact user-selected date range to the monthly GODAS time axis."""
    if "time" not in ds.coords:
        raise ValueError("GODAS dataset does not contain a time coordinate.")

    subset = ds.sel(time=slice(start_date, end_date))
    if subset.sizes.get("time", 0) == 0:
        raise ValueError(
            f"No GODAS records fall inside the requested period {start_date} to {end_date}."
        )
    return subset


def _write_metadata(subset: xr.Dataset, variable_key: str, region: RegionSpec, url: str,
                    start_date: str, end_date: str, tool_version: str):
    subset.attrs["region_definition_type"] = region.source_type
    subset.attrs["region_label"] = region.label
    subset.attrs["region_code"] = region.code
    subset.attrs["region_source"] = region.source_description
    if region.source_type == "shapefile":
        subset.attrs["region_shapefile"] = Path(region.source_description).name
    elif region.source_type == "iho_sea":
        subset.attrs["region_source_dataset"] = "IHO Sea Areas v3"
        subset.attrs["region_source_url"] = MARINE_REGIONS_WFS
    subset.attrs["regional_processing"] = "Bounding-box subset + exact polygon mask + time subset"
    subset.attrs["source_url"] = url
    subset.attrs["godas_tool"] = tool_version
    subset.attrs["requested_start_date"] = start_date
    subset.attrs["requested_end_date"] = end_date
    subset.attrs["variable_key"] = variable_key

def _download_raw(url: str, temp_file: Path, progress=None,
                  cancel_check: Callable[[], bool] | None = None,
                  timeout=(30, 120)) -> bool:
    """Stream a raw yearly NetCDF file to disk with cancellation support."""
    with requests.get(url, stream=True, timeout=timeout, allow_redirects=True) as response:
        response.raise_for_status()
        total_bytes = int(response.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        last_report_mb = -1

        with open(temp_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if cancel_check and cancel_check():
                    return False
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)

                if progress and downloaded // (10 * 1024 * 1024) != last_report_mb:
                    last_report_mb = downloaded // (10 * 1024 * 1024)
                    if total_bytes:
                        pct = downloaded / total_bytes * 100
                        progress(
                            f"[DOWNLOAD] {downloaded / 1024**2:.1f} MB / "
                            f"{total_bytes / 1024**2:.1f} MB ({pct:.0f}%)"
                        )
                    else:
                        progress(f"[DOWNLOAD] {downloaded / 1024**2:.1f} MB downloaded")
    return True



def _is_compatible_output(path: Path, start_date: str, end_date: str) -> bool:
    """Return True when an existing yearly regional file covers the requested dates.

    Files are stored one calendar year at a time. A previous run may therefore have
    different global start/end attributes while still containing all monthly records
    needed for the current request. In that case the existing file should be reused.
    If its time coverage is insufficient (for example, Aug-Dec is requested but only
    Jun-Jul were previously saved), the file is regenerated.
    """
    if not path.exists() or path.stat().st_size <= 1000:
        return False
    try:
        with xr.open_dataset(path, decode_times=True, mask_and_scale=False) as ds:
            if ds.sizes.get("time", 0) <= 0 or "time" not in ds.coords:
                return False
            times = pd.DatetimeIndex(ds["time"].values)
            if len(times) == 0 or not times.is_monotonic_increasing:
                return False
            periods = times.to_period("M")
            target_start = pd.Timestamp(start_date)
            target_end = pd.Timestamp(end_date)
            # The output filename is yearly, so only the portion of the requested
            # period falling inside that calendar year is relevant here. Compare
            # monthly periods because GODAS timestamps may represent the month
            # start/midpoint rather than the final calendar day.
            year = periods[0].year
            required_start = max(target_start, pd.Timestamp(year=year, month=1, day=1))
            required_end = min(target_end, pd.Timestamp(year=year, month=12, day=31))
            if required_start > required_end:
                return False
            required_start_period = required_start.to_period("M")
            required_end_period = required_end.to_period("M")
            return periods.min() <= required_start_period and periods.max() >= required_end_period
    except Exception:
        return False

def download_variable(
    variable_key: str,
    region: RegionSpec,
    start_date: str,
    end_date: str,
    output_dir: str,
    progress: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    tool_version: str | None = None,
) -> DownloadSummary:
    """Download, spatially mask, time-subset, and save one GODAS variable for a generic region."""
    if variable_key not in DATASETS:
        raise ValueError(f"Unsupported GODAS variable: {variable_key}")

    start_year = int(start_date[:4])
    end_year = int(end_date[:4])
    tool_version = tool_version or f"GODAS Regional Data Tool v{SOFTWARE_VERSION}"
    summary = DownloadSummary(requested=end_year - start_year + 1)
    spec = DATASETS[variable_key]
    out_root = Path(output_dir) / variable_key
    out_root.mkdir(parents=True, exist_ok=True)

    xmin, ymin, xmax, ymax = region.geometry.bounds

    for year in range(start_year, end_year + 1):
        if cancel_check and cancel_check():
            summary.cancelled = True
            break

        out_file = out_root / f"{spec['file_prefix']}.{year}.{region.code}.nc"
        temp_file = out_root / f".temp_{spec['file_prefix']}.{year}.nc"

        if _is_compatible_output(out_file, start_date, end_date):
            summary.skipped += 1
            if progress:
                progress(f"[SKIP] {variable_key} {year}: already processed for this date range.")
            continue

        url = dataset_url(spec["file_prefix"], year)
        if not check_url(url):
            summary.unavailable += 1
            if progress:
                progress(f"[WARN] {variable_key} {year}: dataset not available; skipped.")
            continue

        try:
            if progress:
                progress(f"[DOWNLOAD] {variable_key} {year}: Downloading raw file via HTTP...")
            downloaded = _download_raw(url, temp_file, progress=progress, cancel_check=cancel_check)
            if not downloaded:
                summary.cancelled = True
                break
            if temp_file.stat().st_size < 1000:
                raise ValueError("Downloaded file is unexpectedly small; possible server error.")

            if progress:
                progress(f"[PROCESS] {variable_key} {year}: Reading, subsetting and masking...")

            with xr.open_dataset(temp_file, decode_times=True, mask_and_scale=True) as ds:
                year_start=max(start_date,f"{year:04d}-01-01")
                year_end=min(end_date,f"{year:04d}-12-31")
                subset=_subset_time(ds,year_start,year_end)
                subset=_subset_spatial(subset,region.geometry,xmin,ymin,xmax,ymax)
                subset=subset.load()
                if not any(bool(np.isfinite(subset[v].values).any()) for v in subset.data_vars):
                    raise ValueError("No finite GODAS data remain inside the selected region for this variable/year.")
                _write_metadata(subset,variable_key,region,url,start_date,end_date,tool_version)
                encoding={name:{"zlib":True,"complevel":4} for name in subset.data_vars}
                subset.to_netcdf(out_file,mode="w",format="NETCDF4",encoding=encoding)

            if not out_file.exists() or out_file.stat().st_size < 1000:
                raise IOError("Output NetCDF was not created correctly.")
            summary.success += 1
            if progress:
                progress(f"[OK] {variable_key} {year}: Saved -> {out_file.name}")
        except Exception as exc:
            summary.failed += 1
            if out_file.exists():
                out_file.unlink(missing_ok=True)
            if progress:
                progress(f"[ERROR] {variable_key} {year}: {exc}")
        finally:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)
    return summary


def download_selected(
    variables,
    region: RegionSpec,
    start_date,
    end_date,
    output_dir,
    progress=None,
    cancel_check=None,
):
    """Batch execution across selected variables and exact date range."""
    start_year=int(start_date[:4]); end_year=int(end_date[:4])
    total=len(variables)*(end_year-start_year+1)
    completed_slots=0
    overall=DownloadSummary(requested=total)
    for var in variables:
        if cancel_check and cancel_check():
            overall.cancelled=True
            break
        summary=download_variable(var,region,start_date,end_date,output_dir,progress=progress,cancel_check=cancel_check)
        overall.success += summary.success
        overall.skipped += summary.skipped
        overall.unavailable += summary.unavailable
        overall.failed += summary.failed
        overall.cancelled = overall.cancelled or summary.cancelled
        completed_slots += summary.completed + summary.unavailable + summary.failed
        if progress:
            progress(f"[PROGRESS] Completed variable {var}: {completed_slots}/{total} year-slots. OK={summary.success}, SKIP={summary.skipped}, WARN={summary.unavailable}, ERROR={summary.failed}")
        if summary.cancelled:
            break
    if progress:
        progress(f"[SUMMARY] Requested={overall.requested}, Success={overall.success}, Skipped={overall.skipped}, Unavailable={overall.unavailable}, Failed={overall.failed}, Cancelled={overall.cancelled}")
    return overall

