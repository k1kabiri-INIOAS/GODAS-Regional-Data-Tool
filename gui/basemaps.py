from __future__ import annotations

from dataclasses import dataclass
import requests
from xyzservices import TileProvider


@dataclass(frozen=True)
class BasemapSpec:
    key: str
    label: str
    requires_google_key: bool = False


# Keep the registry intentionally small for reliability and predictable UX.
BASEMAPS = (
    BasemapSpec("esri_street", "Esri World StreetMap"),
    BasemapSpec("google_satellite", "Google Satellite (API key)", True),
    BasemapSpec("offline_world", "Offline World Map (bundled)"),
    BasemapSpec("none", "No basemap"),
)

BASEMAP_LABELS = {item.key: item.label for item in BASEMAPS}

STATIC_PROVIDERS = {
    "esri_street": TileProvider(
        name="Esri World StreetMap",
        url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attribution="Tiles © Esri — Esri, DeLorme, NAVTEQ",
        max_zoom=19,
    ),
}


def labels() -> list[str]:
    return [item.label for item in BASEMAPS]


def key_for_label(label: str) -> str:
    for item in BASEMAPS:
        if item.label == label:
            return item.key
    return "esri_street"


def label_for_key(key: str) -> str:
    return BASEMAP_LABELS.get(key, key)


def google_tile_provider(map_type: str, api_key: str, *, language: str = "en-US", region: str = "US") -> TileProvider:
    key = str(api_key or "").strip()
    if not key:
        raise ValueError("A Google Maps Platform API key is required for this basemap.")
    if map_type != "satellite":
        raise ValueError(f"Unsupported Google map type: {map_type}")
    response = requests.post(
        "https://tile.googleapis.com/v1/createSession",
        params={"key": key},
        json={"mapType": map_type, "language": language, "region": region},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    session = payload.get("session")
    if not session:
        raise RuntimeError("Google Maps did not return a valid session token.")
    url = "https://tile.googleapis.com/v1/2dtiles/{z}/{x}/{y}" f"?session={session}&key={key}"
    return TileProvider(name="Google Satellite", url=url, attribution="© Google Maps", max_zoom=19)


def get_provider(key: str, google_api_key: str | None = None):
    if key in {"none", "offline_world"}:
        return None
    if key == "esri_street":
        return STATIC_PROVIDERS[key]
    if key == "google_satellite":
        return google_tile_provider("satellite", google_api_key or "")
    raise ValueError(f"Unknown basemap: {key}")
