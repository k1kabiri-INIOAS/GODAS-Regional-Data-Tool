"""Basemap registry and optional Google Maps integration smoke tests."""
from __future__ import annotations

from gui.basemaps import BASEMAPS, get_provider, google_tile_provider
import gui.basemaps as basemaps


def test_public_basemap_registry_is_intentionally_small():
    keys = [item.key for item in BASEMAPS]
    assert keys == ["esri_street", "google_satellite", "offline_world", "none"]
    assert get_provider("esri_street") is not None
    assert get_provider("offline_world") is None
    assert get_provider("none") is None


def test_google_provider_uses_session_token_and_does_not_embed_a_key_in_source():
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"session": "test-session"}

    called = {}
    def fake_post(url, **kwargs):
        called.update(url=url, **kwargs)
        return Response()

    old = basemaps.requests.post
    basemaps.requests.post = fake_post
    try:
        provider = google_tile_provider("satellite", "TEST_KEY")
    finally:
        basemaps.requests.post = old

    assert called["url"].endswith("/createSession")
    assert called["params"]["key"] == "TEST_KEY"
    assert called["json"]["mapType"] == "satellite"
    assert "test-session" in provider.url
    assert "TEST_KEY" in provider.url
