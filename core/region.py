from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import math

import fiona
import geopandas as gpd
import numpy as np
from shapely.geometry import box, shape, LineString
from shapely import contains_xy
from shapely.ops import split, transform, unary_union
from core.reporting import SOFTWARE_VERSION

GODAS_LON_MIN = 0.5
GODAS_LON_MAX = 359.5
GODAS_LAT_MIN = -74.5
GODAS_LAT_MAX = 64.5
GODAS_LON_STEP = 1.0
GODAS_LAT_STEP = 1.0 / 3.0

@dataclass
class RegionSpec:
    geometry: object
    code: str
    label: str
    source_type: str
    source_description: str
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    native_grid_cells: int = 0


def sanitize_region_code(text: str, max_len: int = 32) -> str:
    code = re.sub(r"[^A-Za-z0-9]+", "_", str(text).strip()).strip("_").upper()
    if not code:
        raise ValueError("Could not derive a valid region code.")
    return code[:max_len]


def shapefile_region_code(path: str) -> str:
    return sanitize_region_code(Path(path).stem)


def bbox_region_code(west: float, east: float, south: float, north: float) -> str:
    def fmt(v):
        sign = "W" if v < 0 else "E"
        return f"{sign}{abs(v):g}"
    def fmt_lat(v):
        sign = "S" if v < 0 else "N"
        return f"{sign}{abs(v):g}"
    return sanitize_region_code(f"BOX_{fmt(west)}_{fmt(east)}_{fmt_lat(south)}_{fmt_lat(north)}")


def geometry_to_godas_longitudes(geom):
    """Convert an EPSG:4326 geometry from [-180, 180] to GODAS [0, 360] longitude convention.

    The geometry is split at Greenwich so that regions crossing 0° longitude remain
    spatially correct after negative longitudes are shifted by +360°.
    Dateline-crossing regions remain unsupported by the numeric bounding-box interface.
    """
    if geom.is_empty:
        return geom
    try:
        parts = split(geom, LineString([(0.0, -90.0), (0.0, 90.0)]))
        shifted = []
        for part in getattr(parts, "geoms", [parts]):
            rp = part.representative_point()
            if rp.x < 0:
                shifted.append(transform(lambda x, y, z=None: (x + 360.0, y), part))
            else:
                shifted.append(part)
        return unary_union(shifted)
    except Exception:
        # A fallback for geometries that do not intersect Greenwich.
        minx, _, maxx, _ = geom.bounds
        if maxx <= 0:
            return transform(lambda x, y, z=None: (x + 360.0, y), geom)
        return geom


def inspect_shapefile(path: str):
    p = Path(path)
    if p.suffix.lower() != ".shp":
        raise ValueError("The selected file must have a .shp extension.")
    gdf = gpd.read_file(p)
    if gdf.empty:
        raise ValueError("The region Shapefile contains no features.")
    if gdf.crs is None:
        raise ValueError("The region Shapefile has no CRS definition (.prj).")
    gdf = gdf.to_crs(4326)
    gdf.geometry = gdf.geometry.make_valid()
    geom = gdf.geometry.union_all()
    if geom.is_empty:
        raise ValueError("The region geometry is empty.")
    bounds = geom.bounds
    return {
        "crs": "EPSG:4326",
        "geometry": ", ".join(sorted(set(gdf.geometry.geom_type))),
        "features": len(gdf),
        "xmin": float(bounds[0]), "ymin": float(bounds[1]),
        "xmax": float(bounds[2]), "ymax": float(bounds[3]),
    }


def load_shapefile_region(path: str) -> RegionSpec:
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError("The region Shapefile contains no features.")
    if gdf.crs is None:
        raise ValueError("The region Shapefile has no CRS definition (.prj).")
    gdf = gdf.to_crs(4326)
    gdf.geometry = gdf.geometry.make_valid()
    geom = gdf.geometry.union_all()
    if geom.is_empty:
        raise ValueError("The region geometry is empty after validation.")
    xmin, ymin, xmax, ymax = geom.bounds
    return RegionSpec(geom, shapefile_region_code(path), Path(path).stem,
                      "shapefile", str(Path(path).resolve()), xmin, ymin, xmax, ymax)


def load_iho_names(path: str) -> list[str]:
    p = Path(path)
    if p.suffix.lower() != ".shp":
        raise ValueError("The IHO database must be an ESRI Shapefile (.shp).")
    with fiona.open(p) as src:
        fields = list(src.schema["properties"].keys())
        name_field = next((f for f in fields if f.lower() == "name"), None)
        if name_field is None:
            raise ValueError("The IHO Shapefile does not contain a NAME/Name field.")
        names = [str(feat["properties"][name_field]) for feat in src if feat["properties"].get(name_field)]
    return sorted(names, key=str.casefold)


def load_iho_sea(path: str, sea_name: str) -> RegionSpec:
    p = Path(path)
    with fiona.open(p) as src:
        fields = list(src.schema["properties"].keys())
        name_field = next((f for f in fields if f.lower() == "name"), None)
        if name_field is None:
            raise ValueError("The IHO Shapefile does not contain a NAME/Name field.")
        for feat in src:
            value = feat["properties"].get(name_field)
            if str(value).casefold() == str(sea_name).casefold():
                geom = shape(feat["geometry"])
                geom = geom if geom.is_valid else geom.make_valid()
                if geom.is_empty:
                    raise ValueError(f"The selected IHO sea geometry is empty: {sea_name}")
                xmin, ymin, xmax, ymax = geom.bounds
                return RegionSpec(
                    geom, sanitize_region_code(str(sea_name)), str(sea_name),
                    "iho_sea", f"{p.resolve()} | NAME={sea_name}",
                    float(xmin), float(ymin), float(xmax), float(ymax)
                )
    raise ValueError(f"The sea '{sea_name}' was not found in the selected IHO database.")


MARINE_REGIONS_WFS = "https://geo.vliz.be/geoserver/MarineRegions/wfs"
MARINE_REGIONS_DATASET = "IHO Sea Areas v3"
MARINE_REGIONS_CITATION = "Flanders Marine Institute (2018). IHO Sea Areas, version 3. DOI: 10.14284/323"

def _marine_regions_session():
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": f"GODAS Regional Data Tool/{SOFTWARE_VERSION}",
        "Accept": "application/json,text/csv,application/xml;q=0.9,*/*;q=0.8",
    })
    return session


def _parse_catalog_json(text: str) -> list[dict]:
    import json
    payload = json.loads(text.lstrip("\ufeff").strip())
    features = payload.get("features", []) if isinstance(payload, dict) else []
    catalog = []
    for feature in features:
        props = feature.get("properties", {}) or {}
        name = props.get("NAME", props.get("name", props.get("Name")))
        mrgid = props.get("MRGID", props.get("mrgid", props.get("Mrgid")))
        if name and mrgid is not None:
            try:
                catalog.append({"name": str(name), "mrgid": int(mrgid)})
            except (TypeError, ValueError):
                continue
    catalog.sort(key=lambda item: item["name"].casefold())
    return catalog


def _parse_catalog_csv(text: str) -> list[dict]:
    import csv
    from io import StringIO
    rows = list(csv.DictReader(StringIO(text.lstrip("\ufeff"))))
    if not rows:
        return []
    fields = {str(k).strip().lower(): k for k in rows[0].keys() if k is not None}
    name_key = next((fields[k] for k in ("name",) if k in fields), None)
    mrgid_key = next((fields[k] for k in ("mrgid",) if k in fields), None)
    if name_key is None or mrgid_key is None:
        return []
    catalog = []
    for row in rows:
        name = row.get(name_key)
        mrgid = row.get(mrgid_key)
        if name and mrgid:
            try:
                catalog.append({"name": str(name).strip(), "mrgid": int(float(mrgid))})
            except (TypeError, ValueError):
                continue
    catalog.sort(key=lambda item: item["name"].casefold())
    return catalog


def _read_catalog_cache(cache: Path) -> list[dict]:
    import json
    if not cache.exists():
        return []
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            cleaned = [
                {"name": str(x["name"]), "mrgid": int(x["mrgid"])}
                for x in data
                if isinstance(x, dict) and x.get("name") and x.get("mrgid") is not None
            ]
            cleaned.sort(key=lambda item: item["name"].casefold())
            return cleaned
    except Exception:
        return []
    return []


def load_iho_catalog(cache_path: str | None = None, timeout: int = 20) -> list[dict]:
    """Load the authoritative IHO Sea Areas v3 name/MRGID catalog.

    The catalog is requested without geometry. JSON is attempted first; CSV is
    used as a lightweight standards-supported fallback because some institutional
    proxies/GeoServer configurations return a non-JSON response for GeoJSON.
    No hard-coded or approximate IHO catalog is used.
    """
    import json
    import requests

    cache = Path(cache_path) if cache_path else Path.home() / ".godas_regional_tool" / "iho_seas_v3_catalog.json"
    cached = _read_catalog_cache(cache)
    if cached:
        return cached

    base = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "iho",
        "propertyName": "name,mrgid",
        "maxFeatures": 150,
    }
    errors = []

    # Try both normal Windows proxy handling and a direct connection. This makes
    # the diagnostic useful on institutional networks while avoiding a hard lock.
    for trust_env in (True, False):
        session = _marine_regions_session()
        session.trust_env = trust_env
        for fmt, parser in (("application/json", _parse_catalog_json), ("csv", _parse_catalog_csv)):
            params = dict(base)
            params["outputFormat"] = fmt
            try:
                response = session.get(MARINE_REGIONS_WFS, params=params, timeout=(5, timeout))
                response.raise_for_status()
                catalog = parser(response.text)
                if catalog:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        cache.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
                    except OSError:
                        pass
                    return catalog
                errors.append(
                    f"trust_env={trust_env}, format={fmt}: empty/invalid catalog; "
                    f"HTTP {response.status_code}, content-type={response.headers.get('content-type','unknown')}, "
                    f"response={response.text[:160]!r}"
                )
            except (requests.RequestException, ValueError, UnicodeError) as exc:
                errors.append(f"trust_env={trust_env}, format={fmt}: {type(exc).__name__}: {exc}")

    cached = _read_catalog_cache(cache)
    if cached:
        return cached
    raise ConnectionError(
        "Could not retrieve the authoritative IHO Sea Areas v3 catalog from Marine Regions "
        "and no valid local catalog cache is available. " + " | ".join(errors)
    )


def fetch_iho_sea_from_marine_regions(name: str, mrgid: int, timeout: int = 30) -> RegionSpec:
    """Fetch exactly one authoritative IHO Sea Areas v3 geometry from Marine Regions."""
    import json
    import requests

    cache_dir = Path.home() / ".godas_regional_tool" / "iho_geometries"
    cache_file = cache_dir / f"mrgid_{int(mrgid)}.geojson"

    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            features = payload.get("features", [])
            if features and features[0].get("geometry"):
                geom = shape(features[0]["geometry"])
                if not geom.is_valid:
                    geom = geom.make_valid()
                if not geom.is_empty:
                    xmin, ymin, xmax, ymax = geom.bounds
                    return RegionSpec(
                        geom, sanitize_region_code(name), name, "iho_sea",
                        f"{MARINE_REGIONS_DATASET} | {MARINE_REGIONS_CITATION} | MRGID={int(mrgid)} | cached exact geometry",
                        float(xmin), float(ymin), float(xmax), float(ymax)
                    )
        except Exception:
            pass

    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "iho",
        "cql_filter": f"mrgid={int(mrgid)}",
        "outputFormat": "application/json",
    }
    errors = []
    for trust_env in (True, False):
        session = _marine_regions_session()
        session.trust_env = trust_env
        try:
            response = session.get(MARINE_REGIONS_WFS, params=params, timeout=(5, timeout))
            response.raise_for_status()
            payload = json.loads(response.text.lstrip("\ufeff").strip())
            features = payload.get("features", []) if isinstance(payload, dict) else []
            if not features:
                raise ValueError(f"No feature returned for MRGID {mrgid}.")
            geometry_json = features[0].get("geometry")
            if not geometry_json:
                raise ValueError(f"No geometry returned for MRGID {mrgid}.")
            geom = shape(geometry_json)
            if not geom.is_valid:
                geom = geom.make_valid()
            if geom.is_empty:
                raise ValueError(f"The Marine Regions geometry for '{name}' is empty.")

            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass

            xmin, ymin, xmax, ymax = geom.bounds
            return RegionSpec(
                geom, sanitize_region_code(name), name, "iho_sea",
                f"{MARINE_REGIONS_DATASET} | {MARINE_REGIONS_CITATION} | MRGID={int(mrgid)}",
                float(xmin), float(ymin), float(xmax), float(ymax)
            )
        except (requests.RequestException, ValueError, UnicodeError) as exc:
            errors.append(f"trust_env={trust_env}: {type(exc).__name__}: {exc}")

    raise ConnectionError(
        f"Could not retrieve the exact Marine Regions geometry for '{name}' (MRGID {mrgid}). "
        + " | ".join(errors)
    )


def make_bbox_region(west: float, east: float, south: float, north: float) -> RegionSpec:
    vals=(west,east,south,north)
    if not all(math.isfinite(v) for v in vals):
        raise ValueError("Bounding-box coordinates must be finite numbers.")
    if west < -180 or east > 180 or south < -90 or north > 90:
        raise ValueError("Longitudes must be between -180 and 180; latitudes between -90 and 90.")
    if west >= east:
        raise ValueError("West longitude must be smaller than East longitude. Dateline-crossing boxes are not supported in this version.")
    if south >= north:
        raise ValueError("South latitude must be smaller than North latitude.")
    geom=box(west,south,east,north)
    return RegionSpec(
        geom, bbox_region_code(west,east,south,north),
        f"Bounding Box: W {west:g}°, E {east:g}°, S {south:g}°, N {north:g}",
        "bounding_box", f"west={west}; east={east}; south={south}; north={north}",
        west,south,east,north
    )



def make_map_region(geometry, label="Map-selected Region") -> RegionSpec:
    """Create a RegionSpec from an interactively drawn EPSG:4326 geometry."""
    if geometry is None or geometry.is_empty:
        raise ValueError("The map-selected study region is empty.")
    geom = geometry if geometry.is_valid else geometry.make_valid()
    if geom.is_empty:
        raise ValueError("The map-selected study region is invalid or empty.")
    xmin, ymin, xmax, ymax = geom.bounds
    return RegionSpec(
        geom, "MAP_REGION", str(label), "map_polygon",
        "Interactive map selection (OpenStreetMap-backed picker)",
        float(xmin), float(ymin), float(xmax), float(ymax)
    )

def _lon360_to_lon180(x):
    return ((x + 180.0) % 360.0) - 180.0


def count_native_godas_grid_cells(geom) -> int:
    # Use the same 0–360 longitude convention as GODAS.
    godas_geom = geometry_to_godas_longitudes(geom)
    xmin, ymin, xmax, ymax = godas_geom.bounds
    lon_min = max(GODAS_LON_MIN, xmin)
    lon_max = min(GODAS_LON_MAX, xmax)
    lat_min = max(GODAS_LAT_MIN, ymin)
    lat_max = min(GODAS_LAT_MAX, ymax)
    if lon_min > lon_max or lat_min > lat_max:
        return 0

    all_lon = np.arange(GODAS_LON_MIN, GODAS_LON_MAX + 1e-9, GODAS_LON_STEP)
    all_lat = np.arange(GODAS_LAT_MIN, GODAS_LAT_MAX + 1e-9, GODAS_LAT_STEP)
    lons = all_lon[(all_lon >= lon_min) & (all_lon <= lon_max)]
    lats = all_lat[(all_lat >= lat_min) & (all_lat <= lat_max)]
    if len(lons) == 0 or len(lats) == 0:
        return 0
    xx, yy = np.meshgrid(lons, lats)
    return int(contains_xy(godas_geom, xx, yy).sum())


def validate_region_for_godas(region: RegionSpec) -> dict:
    xmin,ymin,xmax,ymax=region.geometry.bounds
    if ymax < GODAS_LAT_MIN or ymin > GODAS_LAT_MAX:
        raise ValueError(
            f"The selected region does not intersect the GODAS latitude domain ({GODAS_LAT_MIN}° to {GODAS_LAT_MAX}°)."
        )
    cells=count_native_godas_grid_cells(region.geometry)
    region.native_grid_cells=cells
    if cells==0:
        raise ValueError(
            "No GODAS native-grid cell centers fall inside the selected region. "
            "The region may be smaller than the GODAS grid or may lie outside the available ocean grid."
        )
    return {
        "native_grid_cells": cells,
        "warning": ("Only a small number of GODAS native-grid cell centers fall inside the region; "
                     "results may be sensitive to the coarse native spatial resolution." if cells < 3 else None)
    }
