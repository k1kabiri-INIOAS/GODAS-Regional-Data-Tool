## v2.5.10 — Rectangle picker synchronization hardening

Version 2.5.7 keeps the validated scientific architecture unchanged and refines the study-region map UI.
The online basemap registry is intentionally limited to **Esri World StreetMap** (default) and optional **Google Satellite**.
A **bundled offline world map** is included locally and is used as the only fallback when an online basemap is unavailable.
No online provider is silently replaced by another online provider.

The interactive region picker is now **rectangle-only**. The polygon drawing tool has been removed.
The selected rectangle immediately updates numeric West/East/South/North readouts and the same coordinates are displayed on the map.
The preview and picker use a square map area with controls placed to the left of the map.

Google Satellite continues to use the official Google Maps Platform Map Tiles API with a user-supplied API key and session token.
The Google key is stored locally in application settings and is never embedded in the source.

All validated scientific processing, native-grid handling, report contracts, and no-silent-interpolation policies remain unchanged.
The report schema remains **2.6.0**.


Historical v2.5.2 introduced the first selectable basemap registry and the bundled offline-map mechanism. In v2.5.5 the online registry is intentionally reduced to **Esri World StreetMap** (default) and optional **Google Satellite**, with the bundled offline world map as the sole fallback when an online provider is unavailable.

Google **Satellite** is available through the official Google Maps Platform Map Tiles API and requires the user to supply their own API key; the software does not embed a key.

The Google API key is stored locally in the application settings when the user enters it through the basemap controls. No scientific processing uses basemap imagery. Basemap choice affects only visual context for region selection/preview.

All GODAS scientific processing, native-grid handling, report contracts, and no-silent-interpolation policies are unchanged. The report schema remains **2.6.0**.


## v2.5.0 — GODAS catalog expansion + interactive region selection

This release expands the tool to the 12 primary monthly GODAS datasets currently exposed by NOAA PSL: `dbss_obil`, `dbss_obml`, `dzdt`, `pottmp`, `salt`, `sltfl`, `sshg`, `thflx`, `ucur`, `uflx`, `vcur`, and `vflx`. This scope follows the current NOAA PSL GODAS primary catalog: https://www.psl.noaa.gov/thredds/catalog/GODAS.html. Derived/long-term-mean products are not silently treated as additional primary monthly downloads. Additional variables remain opt-in in the Downloading Data tab; the original five core variables remain selected by default to avoid unexpectedly large downloads, while **Select all** and **Clear all** controls are provided.

The interactive map region picker supports rectangle and polygon drawing with an OpenStreetMap basemap. Map-selected geometry is used directly as the study region rather than being reduced to its bounding box. The first workflow page includes a live study-region preview.

The Map Composer fixes seasonal DJF baseline handling by allowing the December immediately preceding a requested baseline period to serve as a documented supporting month when needed to form a complete DJF season-year. The baseline dates in the report remain the user-selected dates.

All native-grid and no-silent-interpolation policies remain unchanged. Variable-specific native depth grids are preserved where GODAS products differ.

# v2.5.0 — GODAS catalog expansion + interactive region selection

Version 2.5.0 expands the tool to the 12 primary monthly GODAS datasets currently exposed by NOAA PSL and adds interactive map-based study-region selection plus a first-page region preview. It preserves the validated analysis and Map Composer architecture.

Supported primary monthly datasets: `pottmp`, `salt`, `ucur`, `vcur`, `dzdt`, `dbss_obml`, `dbss_obil`, `sshg`, `thflx`, `sltfl`, `uflx`, and `vflx`. NOAA PSL also exposes derived/long-term-mean products separately; these are not treated as primary yearly downloads.

The interactive region picker is rectangle-only. A map-selected rectangle is synchronized back to the Numeric Bounding Box controls on the first workflow page, where the four WGS84 bounds replace the previous coordinates and the preview is updated immediately.

The Map Composer retains the documented DJF convention (`December of the previous year + January + February`) and can use the immediately preceding December as a supporting month when the user specifies a single calendar-year baseline.

The report schema is **2.6.0**.

# v2.4.1 — Map Composer Foundation

Version 2.4.1 extends the validated Spatial Visualization module into a unified **Map Composer** foundation. The existing Data Map behavior is preserved, while users can now select a map product and create **Data Maps, Climatology Maps, Anomaly Maps, and Trend Maps** from standardized GODAS native-grid fields. The GUI exposes only the controls relevant to the selected product.

### Map products

- **Data Map:** monthly native-grid field with Surface, Single native depth, Deepest valid level, or Three-depth comparison.
- **Climatology Map:** Monthly, Seasonal (DJF/MAM/JJA/SON), or Annual baseline field. Complete annual/seasonal periods follow the same completeness semantics as the validated climatology analysis.
- **Anomaly Map:** Monthly, Seasonal, or Annual target-period anomaly relative to the corresponding baseline climatology. Monthly/annual/seasonal completeness rules follow the validated anomaly definitions; no temporal interpolation is used.
- **Trend Map:** independent native-grid-cell temporal trend using OLS slope, Mann–Kendall tau, or Sen's slope. Trend is calculated at each grid cell without spatial averaging. Seasonal trends are generated for a user-selected season.

### Map Composer principles

The Map Composer is presentation-aware but scientifically conservative: **no horizontal interpolation, no regridding, no vertical interpolation, no extrapolation, and no gap filling**. Region geometry is used only for visualization/masking and map extent; native data values remain on their original GODAS grid.

Common map exports remain reproducible through PNG (300 dpi), SVG, PDF, CSV, and JSON report outputs. Climatology, anomaly, and trend products record their product-specific period, depth, unit, and method metadata in the common report contract.

The software version at that historical release was **2.4.1**; in v2.5.0 the report contract is **2.6.0**.

# GODAS Regional Data Tool — v2.5.10
Python/PySide6 desktop tool for regional GODAS downloading, quality control, standardization, integration, and reproducible scientific analysis.




## v2.3.0 — Spatial Visualization & Professional UI

Version 2.3.0 extends the validated GODAS analysis workflow with a dedicated **Spatial Visualization** module and a cleaner research-oriented desktop interface. The existing download, QC, standardization, core-analysis, climatology/anomaly, trend, and native-grid scientific logic is preserved.

### Spatial Visualization

The new **6. Spatial Visualization** tab creates maps directly from standardized GODAS NetCDF products. Supported first-stage products are:

- **Single map** at the shallowest native level, a user-selected native depth, or the deepest valid native level.
- **Three-depth comparison** with the shallowest native level, a user-selected middle depth, and the deepest valid native level.

The middle depth is matched to the nearest available native GODAS depth, and the actual selected depth is recorded in the JSON report. The deepest panel is determined from the deepest native depth containing finite data for the selected month; invalid deeper levels are not extrapolated.

For a selected monthly record, the tool can export the same plotted native-grid values as:

- PNG at 300 dpi
- SVG vector figure
- PDF vector figure
- CSV of latitude/longitude/value cells for reproducibility
- JSON visualization report with source, depth, unit, grid, color-scale, and integrity metadata

### Native-grid visualization principle

Spatial visualization follows the same scientific integrity policy as the analysis modules: **no horizontal interpolation, no regridding, no temporal interpolation, no vertical interpolation, no extrapolation, and no gap filling**. Map values are plotted directly from the selected native GODAS cells. The current study-region geometry can optionally be overlaid without modifying the data grid.

### Professional interface refinement

- Added a vertical topic-navigation sidebar using the existing six workflow modules.
- Added consistent icons and clearer active-tab states.
- Added a compact version/schema indicator in the header.
- Improved spacing, action-button hierarchy, group-box styling, and map/export controls.
- Preserved persistent Light/Dark themes through QSettings.
- The application icon and branded GODAS logo remain part of the interface.

The software version was **2.3.0** and the report schema was **2.4.1**.

## v2.2.2 — Release Hardening & Version Consistency

Version 2.2.2 is a maintenance release following end-to-end scientific validation. It introduces no scientific-method changes. The release hardens provenance/version handling across Download, Standardization & Integration, Marine Regions access, and GUI logging.

### Hardening changes

- Standardization & Integration now reports the current software version by default instead of the historical v1.0 fallback.
- Downloader and Marine Regions HTTP requests use the shared software-version constant.
- GUI title, product logs/status messages, and Trend metadata use the same version source.
- Corrected a stale GUI log message that still reported the product completion as v2.0.
- Scientific algorithms, native-grid processing, depth handling, completeness rules, report schema and output contracts for existing analysis families are preserved; v2.5.0 extends the catalog and region-selection workflow.

The software version was **2.2.2**; the report schema at that release was **2.4.1**.

## v2.2.1 — Depth-Independent Completeness Fix

Version 2.2.1 is a corrective release for **Climatology & Anomaly** in depth-dependent products. The validated native-grid, weighting, unit-conversion, seasonal grouping, and missing-data principles are preserved. The correction changes only how completeness is evaluated when some native vertical levels contain no valid observations.

### Corrected completeness logic

For Annual Anomaly and Seasonal Climatology/Anomaly, completeness is now evaluated **independently for each selected native depth**. Invalid native levels remain `NaN` and no longer invalidate the entire water-column product. A year is retained when at least one selected series has a complete 12-month record; a season-year is retained when at least one selected series has all three contributing months. Each individual depth still requires its own complete observations to receive a mean/anomaly.

This corrects the previous failure mode in which `_complete_annual_means()` and seasonal completeness logic reduced the depth dimension with `min("depth")`, causing valid depths to be discarded when deeper native levels had no data.

### Scientific invariants

No interpolation, extrapolation, regridding, gap filling, vertical interpolation, or autocorrelation correction is introduced by this release. Native GODAS depths remain unchanged, and the existing cosine(latitude)-weighted native-grid regional mean is unchanged.

The report schema remains **2.3.0**; the software version is **2.2.1**.

## v2.2.0 — Scientific Baseline Freeze & Report Validation

Version 2.2.0 preserves the validated v2.1.6 scientific algorithms and introduces no changes to the underlying oceanographic calculations. The release focuses on reproducibility, report-contract validation, provenance metadata, and release hardening. Existing v2.1.6 workflows are intended to reproduce the same scientific results for identical standardized inputs.

### Scientific baseline freeze

The following validated behaviors are unchanged: native-grid processing; cosine(latitude)-weighted regional means; native GODAS vertical levels; seasonal DJF/MAM/JJA/SON grouping with December assigned to the following DJF year; complete-year and complete-season requirements; OLS; Mann–Kendall; Sen's slope; explicit unit conversions; and the prohibition of interpolation, extrapolation, regridding, and gap filling.

### Report contract validation

Machine-readable reports are checked before writing for the common v2.6.0 report schema contract, including required metadata, processing safeguards, depth information, integrity information, and output declarations. A `report_validation` object records PASS/WARN/FAIL status and any detected contract issues.

### Provenance

Reports include a UTC creation timestamp and explicit software/schema versions. These metadata additions do not alter scientific calculations.

## v2.1.5 — Trend Metadata & Reporting Hardening

Version 2.1.5 preserves all validated scientific Trend calculations and refines reporting for reproducibility. Trend JSON reports now distinguish the requested analysis period from the actual source-time coverage and the complete annual/seasonal observations used for trend estimation. Reports also include explicit software and schema versions and, for depth-dependent products, counts and lists of valid and invalid native depth levels. No trend algorithm, interpolation, regridding, gap filling, or autocorrelation treatment is changed in this release.

## v2.1.4 — Trend Plot & Download Reuse Refinement

Version 2.1.4 refines Trend figures by adding one year of right-side x-axis space, using 2-year major tick intervals, preserving the established seasonal palette, black OLS trend lines, smaller markers, and per-decade slope annotations. The downloader now reuses an existing yearly regional NetCDF when its monthly time coverage already contains the requested portion of that calendar year, even when the previous run used a different overall date range; files are regenerated only when the existing time coverage is insufficient.

## v2.1.3 — Trend Analysis

Version 2.1.3 adds a dedicated Trend Analysis tab with Monthly, Seasonal, and Annual trends using OLS, Mann–Kendall, and Sen's slope. Annual observations require 12 complete months and seasonal observations require all 3 months. No interpolation, regridding, gap filling, or autocorrelation correction is applied. Outputs include the source series, trend statistics, 300-dpi PNG, and JSON report. Trend figures use a consistent seasonal palette (DJF blue, MAM green, JJA orange-red, SON yellow-orange), black OLS trend lines, smaller markers, and per-decade slope annotations.

## v2.0.2 — Interface Consistency Refinement

Version 2.0.2 refines the v2.0.1 scientific-products interface without changing the validated download, QC, standardization, core-analysis, climatology, or anomaly calculations. The Climatology & Anomaly tab now follows the same visual hierarchy as Core Scientific Analysis: Depth Selection → Output Units → Climatology & Anomaly controls.

## v1.8 — Metadata & Reporting Hardening

Version 1.8 preserves the validated v1.7 scientific workflow and focuses on reporting consistency, GUI integrity, and explicit scientific safeguards. It does not introduce interpolation, regridding, extrapolation, or gap filling.

### Workflow

**Download → Quality Control → Standardization & Integration → Scientific Analysis**

The GUI is organized into five topic tabs:

1. **Downloading Data**
2. **Data Validation & Standardization**
3. **Core Scientific Analysis** — Regional Time Series, Mean Vertical Profile, and Depth–Time Section.
4. **Climatology & Anomaly** — v2.0 scientific products.
5. **Trend Analysis** — v2.1 Monthly, Seasonal, and Annual trend analysis.

A persistent Processing Log records important operations and warnings.

## Study-region definitions

The Study Region section supports three mutually exclusive definitions:

1. **Polygon Shapefile** — any valid polygon Shapefile supplied by the user.
2. **Numeric Bounding Box** — west/east longitude and south/north latitude entered directly.
3. **Standard IHO Sea** — select a named region from IHO Sea Areas v3 maintained by Marine Regions.

All definitions are converted to the same internal `RegionSpec` representation. The scientific-analysis modules therefore remain independent of how the region was defined.

### Standard IHO Sea Areas

The full IHO Sea Areas Shapefile is not bundled with the application. The software requests a lightweight Name/MRGID catalog from the official Marine Regions WFS, caches that catalog locally, and retrieves only the selected geometry when required.

Source attribution:

> Flanders Marine Institute (2018). *IHO Sea Areas, version 3*. Marine Regions. DOI: 10.14284/323.

See `resources/regions/README.md` for the third-party attribution and license notice.

## Native-grid principle

The downloader and analysis engine preserve the native GODAS horizontal grids. Temperature/salinity and current products can have different native latitude/longitude dimensions because the source fields are on their respective GODAS grids.

The software does **not** silently:

- regrid horizontal data;
- interpolate between vertical levels;
- extrapolate below the deepest available data;
- fill missing values or gaps.

Regional means use cosine(latitude)-weighted averaging over available finite native-grid cells.

## GODAS variables

| Variable | GODAS field | Dimensions | Native units |
|---|---|---|---|
| Potential Temperature | `pottmp` | time, depth, lat, lon | K |
| Salinity | `salt` | time, depth, lat, lon | kg kg-1 |
| Mixed Layer Depth | `dbss_obml` | time, lat, lon | m |
| Zonal Current | `ucur` | time, depth, lat, lon | m s-1 |
| Meridional Current | `vcur` | time, depth, lat, lon | m s-1 |

MLD is a two-dimensional time-varying field and is therefore supported only by **Regional Time Series**.

## Scientific Analysis

### Regional Time Series

For 3-D variables, the user may select:

- Surface (shallowest available GODAS level)
- Single depth (snapped to the nearest available native GODAS level)
- Depth range (selected native levels)
- Full water column

For MLD, only the regional time series is available and no vertical selection is applied.

### Mean Vertical Profile

A regional spatial mean is calculated at each selected native depth, followed by temporal averaging. The output retains all selected native depth levels, including levels with no valid regional data.

The report distinguishes:

- `selected_depth_count`
- `deepest_selected_depth_m`
- `valid_depth_count`
- `deepest_valid_depth_m`

This distinction prevents the deepest selected level from being incorrectly interpreted as the deepest level containing observations/data.

### Depth–Time Section

A regional spatial mean is calculated independently for every time/depth pair. Coverage diagnostics report the number and fraction of finite native-grid horizontal cells for each pair.

## Output products

Each analysis produces:

- CSV data table
- 300-dpi PNG figure
- JSON analysis report

The JSON report contains a canonical `report_schema` with the following conceptual sections:

- analysis type and variable
- source and units
- time information
- depth information
- spatial information
- coverage information
- statistics
- unit conversion
- output information
- integrity safeguards

Fields that are not relevant to an analysis type are explicitly represented as `not_applicable` in the canonical schema.

The report also records the exact CSV column contract for that analysis.

## Unit handling

Source units are preserved by default. Explicit conversions are available only where scientifically defined by the tool:

- Potential Temperature: K → °C using −273.15.
- Salinity: kg kg-1 × 1000, reported as **PSU (approx.)**. This is an approximate reporting conversion and is not treated as an exact practical-salinity calculation.

No unit conversion is performed silently.

## Data acquisition

The proven acquisition workflow is:

**NOAA PSL yearly HTTP NetCDF → local temporary file → xarray → time subset → bounding-box subset → exact polygon mask → compressed regional NetCDF → temporary raw-file deletion**

OPeNDAP is intentionally not used by the downloader.

## Quality Control and Standardization

Quality control checks file structure, dimensions, time continuity, coordinates, metadata, data ranges, finite values, and provenance. Standardization canonicalizes the vertical dimension, validates the GODAS depth grid, standardizes metadata, and creates integrated native-grid products.

No horizontal interpolation is introduced during standardization.

## Scientific integrity and validation scope

The tool explicitly guards against interpolation, extrapolation, gap filling, and silent regridding. Depth selections are checked against the available native GODAS levels, and invalid or empty selections are rejected.

The project's validation tests establish **computational/internal consistency** across the five supported variables and the applicable analysis modules. They do not constitute independent oceanographic validation against observations or an external reference dataset. Independent scientific validation should be performed separately when required by a research study.

## Output naming

The region code is derived automatically. Examples:

- `GO.shp` → `pottmp.2025.GO.nc`
- `AS.shp` → `pottmp.2025.AS.nc`
- standard IHO region `Gulf of Oman` → `pottmp.2025.GULF_OF_OMAN.nc`

## Version strategy

- **v1.8** — Core hardening, metadata, reporting, and integrity safeguards
- **v2.0** — Scientific-analysis expansion
- **v2.1** — Trend analysis and diagnostics
- **v2.2.0** — Scientific baseline freeze and report validation
- **v2.2.1** — Depth-independent completeness correction for climatology/anomaly products
- **v2.3.2** — Professional UI refinement and native-depth map selection
- **v2.3.4** — Refined map decorations, publication-ready study-region masking, and cleaner single-map depth presentation
- **v2.3.5** — Refined north-arrow label spacing, map-sized shared colorbars, tighter figure title spacing, and color-coded workflow navigation
- **v2.3.0** — Spatial visualization and professional UI
- **v2.x** — Advanced oceanographic diagnostics
- **v3.x** — Publication/software-release hardening

## v2.0.0 Scientific Analysis Expansion

Version 2.0.0 adds the first research-oriented scientific products while preserving the v1.8 native-grid and integrity principles.

### Climatology

The Scientific Analysis tab now provides climatology products for all supported GODAS variables:

- **Monthly climatology:** mean for each calendar month over a user-defined baseline period.
- **Seasonal climatology:** DJF, MAM, JJA, and SON means over the baseline period. December is assigned to the following DJF season year for seasonal grouping, while the final climatological product is the four seasonal means.
- **Annual Mean:** one mean over the complete baseline period. This is explicitly a baseline-period mean, not an annual time series.

The baseline period is always explicit and user-defined. No hidden climatological baseline is applied. In the GUI, baseline dates are shown for both products. For **Anomaly**, an additional target/anomaly-period start and end are shown; these controls are hidden for **Climatology** because they are not relevant.

### Anomaly

Three anomaly products are available:

- **Monthly:** each monthly value minus the corresponding baseline monthly climatological mean.
- **Seasonal:** each seasonal value minus the corresponding baseline seasonal climatological mean.
- **Annual:** each target-year mean minus the overall baseline-period mean.

Anomaly calculations use the same selected native GODAS depth levels and the same cosine(latitude)-weighted regional mean used by the core analysis engine.

### Depth handling

For 3-D variables, v2.0.0 reuses the validated v1.8 depth-selection logic:

- Surface (shallowest native GODAS level)
- Single native depth nearest to a requested target
- Depth Range using only native GODAS levels inside the requested range
- Full Water Column

Mixed Layer Depth remains a 2-D variable and is not assigned artificial vertical structure.

### Units

Existing explicit output-unit options are retained. Temperature can be reported in °C and salinity can be reported as approximate PSU-style values. The source GODAS units remain documented in every report.

### Scientific integrity

v2.0.0 does not interpolate, extrapolate, regrid, or gap-fill GODAS data. Missing values remain missing. All products operate from the standardized native-grid NetCDF files.

### Important interpretation note

Climatology and anomaly products are statistical products derived from the selected GODAS period. They should not be interpreted as independent observational validation. Independent scientific validation requires comparison with external observations or an independent dataset and is outside the scope of the current tool version.

### Output structure

Products are written below the selected output directory:

```text
analysis/
├── climatology/
│   ├── *_monthly_climatology_*.csv
│   ├── *_seasonal_climatology_*.csv
│   ├── *_annual_mean_climatology_*.csv
│   ├── *.png
│   └── Climatology_report_*.json
└── anomaly/
    ├── *_monthly_anomaly_*.csv
    ├── *_seasonal_anomaly_*.csv
    ├── *_annual_anomaly_*.csv
    ├── *.png
    └── Anomaly_report_*.json
```

Each product has a machine-readable JSON report describing the baseline, analysis period where applicable, units, depth selection, spatial statistic, output columns, and integrity safeguards.

### Windows launchers

For normal GUI use, `main.pyw` and `Run_GODAS.vbs` launch the application without opening a console window. `main.py` remains available for command-line/debug execution.
