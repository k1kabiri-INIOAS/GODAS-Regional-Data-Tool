from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import json
import math
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer

from gui.basemaps import get_provider, label_for_key
from core.reporting import SOFTWARE_VERSION

TILE_SIZE = 256
MAX_MOSAIC_TILES = 64
WGS84_TO_WEB = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
WEB_TO_WGS84 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
WEB_HALF_WORLD = 20037508.342789244
OFFLINE_WORLD_RESOURCE = Path(__file__).resolve().parent.parent / "resources" / "offline_world_coastlines.json"


class BasemapFetchError(RuntimeError):
    pass


def _tile_xy_from_lonlat(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2 ** zoom
    lat = max(-85.05112878, min(85.05112878, lat))
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    lat_rad = math.radians(lat)
    y = int(math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n))
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _lonlat_from_tile_xy(x: float, y: float, zoom: int) -> tuple[float, float]:
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
    lat = math.degrees(lat_rad)
    return lon, lat


def _tile_bounds_for_web_bounds(bounds_web, zoom: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bounds_web
    lon0, lat0 = WEB_TO_WGS84.transform(x0, y0)
    lon1, lat1 = WEB_TO_WGS84.transform(x1, y1)
    left_lon, right_lon = min(lon0, lon1), max(lon0, lon1)
    south_lat, north_lat = min(lat0, lat1), max(lat0, lat1)
    tx0, ty1 = _tile_xy_from_lonlat(left_lon, south_lat, zoom)
    tx1, ty0 = _tile_xy_from_lonlat(right_lon, north_lat, zoom)
    return tx0, ty0, tx1, ty1


def _tile_count(bounds_web, zoom: int) -> int:
    tx0, ty0, tx1, ty1 = _tile_bounds_for_web_bounds(bounds_web, zoom)
    return (tx1 - tx0 + 1) * (ty1 - ty0 + 1)


def choose_zoom(bounds_web, max_zoom: int, max_tiles: int = MAX_MOSAIC_TILES) -> int:
    max_zoom = max(0, min(int(max_zoom or 0), 19))
    for zoom in range(max_zoom, -1, -1):
        if _tile_count(bounds_web, zoom) <= max_tiles:
            return zoom
    return 0


def square_web_bounds(bounds_web, min_span: float = 100000.0) -> tuple[float, float, float, float]:
    """Expand Web-Mercator bounds to a square footprint around the same center."""
    x0, y0, x1, y1 = map(float, bounds_web)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Map bounds must have positive width and height.")
    width = max(x1 - x0, float(min_span))
    height = max(y1 - y0, float(min_span))
    span = max(width, height)
    cx = (x0 + x1) * 0.5
    cy = (y0 + y1) * 0.5
    half = span * 0.5
    return (cx - half, cy - half, cx + half, cy + half)


def _format_tile_url(template: str, x: int, y: int, z: int) -> str:
    return template.format(x=x, y=y, z=z, s="a")


def _fetch_tile(session: requests.Session, url: str, timeout: float = 12.0) -> Image.Image:
    try:
        response = session.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise BasemapFetchError(str(exc)) from exc
    if response.status_code != 200:
        raise BasemapFetchError(f"HTTP {response.status_code}")
    try:
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except Exception as exc:
        raise BasemapFetchError("Invalid tile image") from exc


def _render_provider(ax, provider, bounds_web, *, session: requests.Session | None = None, progress: Callable[[str], None] | None = None) -> dict:
    if provider is None:
        raise BasemapFetchError("No online basemap selected")
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", f"GODAS Regional Data Tool/{SOFTWARE_VERSION} (research visualization)")

    zoom = choose_zoom(bounds_web, min(int(getattr(provider, "max_zoom", 18) or 18), 19))
    tx0, ty0, tx1, ty1 = _tile_bounds_for_web_bounds(bounds_web, zoom)
    total = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
    if total > MAX_MOSAIC_TILES:
        raise BasemapFetchError(f"Too many tiles requested ({total})")

    canvas = Image.new("RGBA", ((tx1 - tx0 + 1) * TILE_SIZE, (ty1 - ty0 + 1) * TILE_SIZE), (255, 255, 255, 0))
    failures: list[str] = []
    success = 0
    completed = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            n = 2 ** zoom
            wx = tx % n
            url = _format_tile_url(provider.url, wx, ty, zoom)
            if progress is not None:
                try:
                    progress(f"Loading map tiles {completed}/{total} …")
                except Exception:
                    pass
            try:
                tile = _fetch_tile(session, url)
                if tile.size != (TILE_SIZE, TILE_SIZE):
                    tile = tile.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.LANCZOS)
                canvas.paste(tile, ((tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE))
                success += 1
                completed += 1
                if progress is not None:
                    try:
                        progress(f"Loading map tiles {completed}/{total} …")
                    except Exception:
                        pass
            except BasemapFetchError as exc:
                completed += 1
                if progress is not None:
                    try:
                        progress(f"Loading map tiles {completed}/{total} …")
                    except Exception:
                        pass
                failures.append(f"z{zoom}/{wx}/{ty}: {exc}")

    if success == 0:
        detail = failures[0] if failures else "no tiles returned"
        raise BasemapFetchError(detail)
    if success < max(1, math.ceil(total * 0.5)):
        detail = failures[0] if failures else "too many missing tiles"
        raise BasemapFetchError(f"Only {success}/{total} tiles loaded ({detail})")

    lon_a, lat_b = _lonlat_from_tile_xy(tx0, ty1 + 1, zoom)
    lon_b, lat_a = _lonlat_from_tile_xy(tx1 + 1, ty0, zoom)
    x_left, y_bottom = WGS84_TO_WEB.transform(lon_a, lat_b)
    x_right, y_top = WGS84_TO_WEB.transform(lon_b, lat_a)

    ax.imshow(np.asarray(canvas), extent=(x_left, x_right, y_bottom, y_top), origin="upper", zorder=0, interpolation="bilinear")
    return {
        "zoom": zoom,
        "tiles_requested": total,
        "tiles_loaded": success,
        "attribution": getattr(provider, "attribution", ""),
    }


@lru_cache(maxsize=1)
def _load_offline_world() -> tuple[tuple[tuple[float, float], ...], ...]:
    if not OFFLINE_WORLD_RESOURCE.exists():
        raise BasemapFetchError(f"Bundled offline world map resource not found: {OFFLINE_WORLD_RESOURCE}")
    try:
        payload = json.loads(OFFLINE_WORLD_RESOURCE.read_text(encoding="utf-8"))
        return tuple(tuple((float(p[0]), float(p[1])) for p in seg) for seg in payload.get("segments", []))
    except Exception as exc:
        raise BasemapFetchError("Could not read the bundled offline world map resource.") from exc


def render_offline_world(ax, bounds_web) -> dict:
    """Render the bundled coarse-resolution world coastline without network access."""
    segments = _load_offline_world()
    drawn = 0
    for segment in segments:
        if len(segment) < 2:
            continue
        lons = np.asarray([p[0] for p in segment], dtype=float)
        lats = np.asarray([p[1] for p in segment], dtype=float)
        x, y = WGS84_TO_WEB.transform(lons, lats)
        ax.plot(x, y, linewidth=0.7, color="#66737f", alpha=0.85, zorder=1)
        drawn += 1
    ax.set_facecolor("#edf2f5")
    ax.grid(True, linewidth=0.5, alpha=0.28, zorder=0)
    return {"attribution": "Bundled coarse-resolution world coastline"}


def render_with_fallback(ax, requested_key: str, bounds_web, google_api_key: str = "", progress: Callable[[str], None] | None = None) -> tuple[str, dict, str | None]:
    if requested_key == "none":
        if progress is not None:
            progress("No basemap selected.")
        return "none", {}, None
    if requested_key == "offline_world":
        try:
            if progress is not None:
                progress("Preparing offline world map …")
            return "offline_world", render_offline_world(ax, bounds_web), None
        except Exception as exc:
            return "offline_world", {}, str(exc)

    # Only the requested online provider is attempted. The sole fallback is the
    # bundled offline map, so the application never silently jumps between
    # unrelated online services.
    try:
        provider = get_provider(requested_key, google_api_key)
        session = requests.Session()
        session.headers.update({
            "User-Agent": f"GODAS Regional Data Tool/{SOFTWARE_VERSION} (research visualization)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        })
        info = _render_provider(ax, provider, bounds_web, session=session, progress=progress)
        return requested_key, info, None
    except Exception as online_error:
        try:
            if progress is not None:
                progress("Online basemap unavailable — switching to offline map …")
            info = render_offline_world(ax, bounds_web)
            return "offline_world", info, str(online_error)
        except Exception as offline_error:
            return requested_key, {}, f"Online basemap failed: {online_error}; offline basemap failed: {offline_error}"


def diagnose_basemaps(keys: Iterable[str], google_api_key: str = "") -> list[tuple[str, bool, str]]:
    session = requests.Session()
    session.headers.update({"User-Agent": f"GODAS Regional Data Tool/{SOFTWARE_VERSION} (diagnostic)"})
    results: list[tuple[str, bool, str]] = []
    for key in keys:
        if key == "offline_world":
            try:
                _load_offline_world()
                results.append((key, True, "Bundled map is available locally; no internet required."))
            except Exception as exc:
                results.append((key, False, str(exc)))
            continue
        try:
            provider = get_provider(key, google_api_key)
            if provider is None:
                results.append((key, True, "No basemap selected"))
                continue
            url = _format_tile_url(provider.url, 2, 1, 2)
            _fetch_tile(session, url, timeout=8)
            results.append((key, True, "Tile request succeeded"))
        except Exception as exc:
            results.append((key, False, str(exc)))
    return results
