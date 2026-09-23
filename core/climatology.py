from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import numpy as np
import pandas as pd
import xarray as xr

from .analysis import VARIABLES, _standardized_file, _subset_time, _depth_selection, _spatial_dims, _regional_mean, _convert_units, _depth_coverage, _surface_coverage
from .reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION, observation_coverage, depth_metadata, standard_processing
from .report_validation import validate_report

SEASONS = ["DJF", "MAM", "JJA", "SON"]


def _season_year_index(times):
    t = pd.DatetimeIndex(times)
    season = t.month.map(lambda m: {12:"DJF",1:"DJF",2:"DJF",3:"MAM",4:"MAM",5:"MAM",6:"JJA",7:"JJA",8:"JJA",9:"SON",10:"SON",11:"SON"}[m])
    sy = t.year.to_numpy().copy()
    sy[t.month == 12] += 1
    return season, sy


def _aggregate(da: xr.DataArray, mode: str) -> xr.DataArray:
    if mode == "monthly":
        return da.groupby("time.month").mean("time", skipna=True).rename(month="period")
    if mode == "seasonal":
        # Build complete season-year means first, with completeness evaluated
        # independently for each selected depth. Invalid/deeper levels remain NaN
        # and must not invalidate otherwise valid depths.
        seasons, season_year = _season_year_index(da.time.values)
        tmp = da.assign_coords(season=("time", seasons.astype(str)), season_year=("time", season_year))
        season_means = _complete_season_means(tmp)
        parts = []
        for season in SEASONS:
            idx = np.where(np.asarray(season_means.season.values).astype(str) == season)[0]
            if len(idx) == 0:
                continue
            means = season_means.isel(season_year=idx).mean("season_year", skipna=True)
            # Retain a season only when at least one selected series contains finite values.
            if bool(np.isfinite(np.asarray(means.values)).any()):
                parts.append(means.expand_dims(season=[season]))
        if not parts:
            raise ValueError("No complete seasons remain in the selected baseline period.")
        out = xr.concat(parts, dim="season", coords="minimal", compat="override")
        return out.sel(season=[s for s in SEASONS if s in out.season.values]).rename(season="period")
    if mode == "annual_mean":
        return da.mean("time", skipna=True).expand_dims(period=["annual_mean"])
    raise ValueError(f"Unsupported climatology mode: {mode}")


def _complete_annual_means(da: xr.DataArray) -> xr.DataArray:
    """Return annual means using only years with 12 finite monthly values per series.

    Completeness is evaluated independently along the depth dimension. Thus, invalid
    native depth levels remain NaN, while valid depths retain complete-year means.
    """
    month_count = da.groupby("time.year").count("time")
    annual = da.groupby("time.year").mean("time", skipna=True)
    good = month_count == 12
    # Keep only years for which at least one selected series is complete. For a
    # depth-dependent product, individual depth completeness remains encoded in NaN.
    year_keep = good.any("depth") if "depth" in good.dims else good
    annual = annual.where(good)
    return annual.sel(year=annual.year[year_keep.values])


def _complete_season_means(da: xr.DataArray) -> xr.DataArray:
    """Return complete season-year means with depth-independent completeness.

    Each native depth must have all three contributing monthly values finite. A depth
    lacking one or more months is assigned NaN for that season-year, but other valid
    depths are retained. If no selected series has a complete season-year, that group
    is omitted.
    """
    seasons = np.asarray(da.season.values).astype(str)
    years = np.asarray(da.season_year.values, dtype=int)
    rows = []
    season_labels = []
    for sy in sorted(set(years.tolist())):
        for season in SEASONS:
            idx = np.where((years == sy) & (seasons == season))[0]
            if len(idx) != 3:
                continue
            block = da.isel(time=idx)
            counts = block.count("time")
            good = counts == 3
            mean = block.mean("time", skipna=True).where(good)
            has_any_complete = bool(np.isfinite(np.asarray(mean.values)).any())
            if not has_any_complete:
                continue
            rows.append(mean.expand_dims({"season_year": [int(sy)]}))
            season_labels.append(season)
    if not rows:
        raise ValueError("No complete 3-month seasons remain in the selected period.")
    out = xr.concat(rows, dim="season_year", coords="minimal", compat="override")
    out = out.assign_coords(season=("season_year", np.asarray(season_labels, dtype=str)))
    return out


def _period_label(mode, value):
    if mode == "monthly":
        return pd.Timestamp(2000, int(value), 1).strftime("%b")
    return str(value)


def run_climatology(output_dir: str, variable_key: str, mode: str, baseline_start: str, baseline_end: str,
                    depth_mode="surface", single_depth=None, depth_min=None, depth_max=None,
                    unit_mode="native", progress=None):
    if variable_key not in VARIABLES: raise ValueError(f"Unsupported variable: {variable_key}")
    prefix, label, units, has_depth = VARIABLES[variable_key]
    if not has_depth and depth_mode != "surface": depth_mode = "surface"
    root=Path(output_dir); outdir=root/"analysis"/"climatology"; outdir.mkdir(parents=True,exist_ok=True)
    src=_standardized_file(root,variable_key)
    with xr.open_dataset(src, decode_times=True, mask_and_scale=True) as srcds:
        ds=_subset_time(srcds, baseline_start, baseline_end)
        da, depth_info=_depth_selection(ds[prefix], depth_mode, single_depth, depth_min, depth_max)
        regional=_regional_mean(da); regional.name=prefix
        regional,out_units,conversion=_convert_units(regional,variable_key,unit_mode)
        clim=_aggregate(regional,mode)
        if mode == "monthly":
            clim=clim.assign_coords(period=np.arange(1,13))
        elif mode == "seasonal":
            clim=clim.assign_coords(period=SEASONS)
        df=clim.to_dataframe(name=prefix).reset_index()
        if "period" in df.columns: df["period_label"]=[_period_label(mode,x) for x in df["period"]]
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        csv=outdir/f"{prefix}_{mode}_climatology_{stamp}.csv"; df.to_csv(csv,index=False)
        import matplotlib.pyplot as plt
        png=outdir/f"{prefix}_{mode}_climatology_{stamp}.png"
        fig,ax=plt.subplots(figsize=(9,5.2),constrained_layout=True)
        x=np.arange(len(clim.period)); vals=clim.values
        if "depth" in clim.dims:
            # plot one line per selected depth only when a small selection; otherwise heatmap
            if clim.sizes["depth"] <= 10:
                for i,d in enumerate(clim.depth.values): ax.plot(x, vals[:,i], marker="o", label=f"{d:g} m")
                ax.legend(title="Depth", fontsize=8)
                ax.set_ylabel(f"{label} ({out_units})")
            else:
                mesh=ax.pcolormesh(x,clim.depth.values,clim.transpose("depth","period").values,shading="auto"); ax.invert_yaxis(); fig.colorbar(mesh,ax=ax,label=f"{label} ({out_units})"); ax.set_ylabel("Depth (m)")
        else: ax.plot(x, vals, marker="o", linewidth=1.6); ax.set_ylabel(f"{label} ({out_units})")
        ax.set_xticks(x); ax.set_xticklabels([_period_label(mode,xv) for xv in clim.period.values]); ax.set_xlabel("Period"); ax.set_title(f"{mode.title()} Climatology — {label}"); ax.grid(True,alpha=.25); fig.savefig(png,dpi=300,bbox_inches="tight"); plt.close(fig)
        report={"software_version":SOFTWARE_VERSION,"schema_version":REPORT_SCHEMA_VERSION,"analysis_type":"climatology","variable":variable_key,"product_mode":"climatology","climatology_mode":mode,"period":{"start":baseline_start,"end":baseline_end},"baseline":{"start":baseline_start,"end":baseline_end},"observation_coverage":observation_coverage(ds.time.values, baseline_start, baseline_end),"source_file":str(src),"source_units":units,"output_units":out_units,"unit_conversion":conversion,"depth_information":depth_metadata(depth_info.get("selected_depth_levels", []) if has_depth else [], depth_mode=depth_info.get("depth_mode", depth_info.get("mode", "not_applicable")), requested_single=depth_info.get("requested_single_depth_m"), requested_min=depth_info.get("requested_depth_min_m"), requested_max=depth_info.get("requested_depth_max_m")) if has_depth else depth_metadata([], depth_mode="not_applicable"),"spatial_information":{"dimensions":[d for d in regional.dims if d.startswith("lat") or d.startswith("lon")],"statistic":"cos(latitude)-weighted mean over available native-grid cells","native_grid_preserved":True},"processing":standard_processing("cos(latitude)", units, out_units, conversion),"output":{"csv":str(csv),"csv_columns":list(df.columns),"plot":str(png),"structure":"climatological mean by month/season, or single baseline annual mean"},"integrity":{"status":"PASS","interpolation":False,"extrapolation":False,"gap_filling":False,"native_grid_only":True},"outputs":{"csv":str(csv),"plot":str(png)}}
        rp=outdir/f"Climatology_report_{stamp}.json"
        report["outputs"]["report"] = str(rp)
        report["provenance"]={"created_utc":stamp,"software_version":SOFTWARE_VERSION,"report_schema_version":REPORT_SCHEMA_VERSION}
        report["report_validation"]=validate_report(report)
        rp.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    if progress: progress(f"[CLIM OK] {csv.name}; {png.name}; {rp.name}")
    return {"csv":str(csv),"plot":str(png),"report":str(rp)}


def run_anomaly(output_dir: str, variable_key: str, mode: str, baseline_start: str, baseline_end: str,
                analysis_start: str, analysis_end: str, depth_mode="surface", single_depth=None, depth_min=None, depth_max=None,
                unit_mode="native", progress=None):
    if mode not in {"monthly","seasonal","annual"}: raise ValueError("Anomaly mode must be monthly, seasonal, or annual.")
    prefix,label,units,has_depth=VARIABLES[variable_key]; root=Path(output_dir); outdir=root/"analysis"/"anomaly"; outdir.mkdir(parents=True,exist_ok=True)
    src=_standardized_file(root,variable_key)
    with xr.open_dataset(src,decode_times=True,mask_and_scale=True) as srcds:
        base=_subset_time(srcds,baseline_start,baseline_end); target=_subset_time(srcds,analysis_start,analysis_end)
        bda,_=_depth_selection(base[prefix],depth_mode,single_depth,depth_min,depth_max); tda,_=_depth_selection(target[prefix],depth_mode,single_depth,depth_min,depth_max)
        b=_regional_mean(bda); t=_regional_mean(tda); b.name=prefix; t.name=prefix
        b,out_units,conversion=_convert_units(b,variable_key,unit_mode); t,_,_=_convert_units(t,variable_key,unit_mode)
        if mode=="monthly":
            clim=b.groupby("time.month").mean("time",skipna=True); anomaly=t.groupby("time.month")-clim
        elif mode=="seasonal":
            # Conventional seasonal anomaly: aggregate each target/baseline season to a
            # season-year mean (DJF assigns December to the following year), require
            # all three months, then subtract the corresponding seasonal climatology.
            bs, by = _season_year_index(b.time.values); ts, ty = _season_year_index(t.time.values)
            b_month = b.assign_coords(season=("time",bs.astype(str)), season_year=("time",by))
            t_month = t.assign_coords(season=("time",ts.astype(str)), season_year=("time",ty))
            b_seas = _complete_season_means(b_month)
            t_seas = _complete_season_means(t_month)
            parts = []
            for season in SEASONS:
                base_part = b_seas.isel(season_year=np.where(np.asarray(b_seas.season.values).astype(str) == season)[0])
                target_idx = np.where(np.asarray(t_seas.season.values).astype(str) == season)[0]
                if base_part.sizes.get("season_year", 0) == 0 or len(target_idx) == 0:
                    continue
                clim = base_part.mean("season_year", skipna=True)
                parts.append(t_seas.isel(season_year=target_idx) - clim)
            if not parts:
                raise ValueError("No complete target seasons remain in the selected anomaly period.")
            anomaly = xr.concat(parts, dim="season_year", coords="minimal", compat="override")
        else:
            # Annual anomaly: require all 12 months, matching Annual Trend semantics.
            clim=b.mean("time",skipna=True)
            t_year = _complete_annual_means(t)
            anomaly = t_year - clim
            anomaly = anomaly.rename({"year": "time"})
        anomaly.name=f"{prefix}_anomaly"
        df=anomaly.to_dataframe(name=anomaly.name).reset_index()
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); csv=outdir/f"{prefix}_{mode}_anomaly_{stamp}.csv"; df.to_csv(csv,index=False)
        import matplotlib.pyplot as plt
        png=outdir/f"{prefix}_{mode}_anomaly_{stamp}.png"; fig,ax=plt.subplots(figsize=(9,5.2),constrained_layout=True)
        plot_anom = anomaly.mean("depth", skipna=True) if "depth" in anomaly.dims else anomaly
        if mode == "annual":
            years = np.asarray(plot_anom.time.values, dtype=int)
            xvals = pd.to_datetime([f"{int(y)}-07-01" for y in years])
            ax.plot(xvals, plot_anom.values, marker="o")
        elif mode == "seasonal":
            sy = np.asarray(plot_anom.season_year.values, dtype=int)
            ss = np.asarray(plot_anom.season.values).astype(str)
            month_for = {"DJF": 2, "MAM": 4, "JJA": 7, "SON": 10}
            xvals = pd.to_datetime([f"{int(y)}-{month_for[s]:02d}-15" for y, s in zip(sy, ss)])
            for season in SEASONS:
                mask = ss == season
                if np.any(mask):
                    ax.plot(xvals[mask], plot_anom.values[mask], marker="o", markersize=3.5, label=season)
            ax.legend(title="Season", fontsize=8)
        else:
            ax.plot(pd.to_datetime(plot_anom.time.values), plot_anom.values, marker="o")
        suffix = " — mean selected depths" if "depth" in anomaly.dims else ""
        ax.set_ylabel(f"Anomaly ({out_units}){suffix}")
        ax.axhline(0,linewidth=1); ax.set_xlabel("Time"); ax.set_title(f"{mode.title()} Anomaly — {label}"); ax.grid(True,alpha=.25); fig.savefig(png,dpi=300,bbox_inches="tight"); plt.close(fig)
        base_cov=observation_coverage(base.time.values, baseline_start, baseline_end); target_cov=observation_coverage(target.time.values, analysis_start, analysis_end)
        valid_values=int(np.isfinite(np.asarray(anomaly.values)).sum()); total_values=int(np.asarray(anomaly.values).size)
        report={"software_version":SOFTWARE_VERSION,"schema_version":REPORT_SCHEMA_VERSION,"analysis_type":"anomaly","variable":variable_key,"product_mode":"anomaly","anomaly_mode":mode,"period":{"start":analysis_start,"end":analysis_end},"baseline":{"start":baseline_start,"end":baseline_end,"definition":"value minus baseline climatological mean for the corresponding month/season, or baseline overall mean for annual anomaly"},"observation_coverage":{"requested_start":analysis_start,"requested_end":analysis_end,"baseline":base_cov,"target":target_cov},"source_file":str(src),"source_units":units,"output_units":out_units,"unit_conversion":conversion,"depth_information":depth_metadata(list(bda.depth.values) if "depth" in bda.dims else [], values=np.asarray(t.values), depth_mode=depth_mode, requested_single=single_depth, requested_min=depth_min, requested_max=depth_max) if has_depth else {"mode":"not_applicable"},"spatial_information":{"dimensions":[d for d in t.dims if d.startswith("lat") or d.startswith("lon")],"statistic":"cos(latitude)-weighted mean over available native-grid cells","native_grid_preserved":True},"processing":standard_processing("cos(latitude)", units, out_units, conversion),"output":{"csv":str(csv),"csv_columns":list(df.columns),"plot":str(png),"structure":"anomaly time series at selected native depths"},"outputs":{"csv":str(csv),"plot":str(png)},"integrity":{"status":"PASS" if valid_values >= 1 else "WARN","total_series_values":total_values,"finite_series_values":valid_values,"missing_series_values":total_values-valid_values,"interpolation":False,"extrapolation":False,"gap_filling":False,"native_grid_only":True},"warning":"Annual anomaly excludes years without all 12 monthly observations; seasonal anomaly excludes season-years without all 3 contributing months."}
        rp=outdir/f"Anomaly_report_{stamp}.json"
        report["outputs"]["report"] = str(rp)
        report["provenance"]={"created_utc":stamp,"software_version":SOFTWARE_VERSION,"report_schema_version":REPORT_SCHEMA_VERSION}
        report["report_validation"]=validate_report(report)
        rp.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    if progress: progress(f"[ANOM OK] {csv.name}; {png.name}; {rp.name}")
    return {"csv":str(csv),"plot":str(png),"report":str(rp)}
