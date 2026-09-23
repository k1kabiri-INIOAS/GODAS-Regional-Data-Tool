from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

import gui.basemap_renderer as br
from gui.basemaps import STATIC_PROVIDERS


class DummyResponse:
    status_code = 200
    content = None

    def __init__(self):
        im = Image.new("RGBA", (256, 256), (120, 150, 180, 255))
        bio = BytesIO()
        im.save(bio, format="PNG")
        self.content = bio.getvalue()


class DummySession:
    def __init__(self, fail=False):
        self.fail = fail
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=12.0):
        self.calls.append(url)
        if self.fail:
            raise br.requests.RequestException("network unavailable")
        return DummyResponse()


def test_tile_math_and_zoom_are_bounded():
    bounds = (-2_000_000, 2_000_000, 2_000_000, 7_000_000)
    zoom = br.choose_zoom(bounds, 19, 16)
    assert 0 <= zoom <= 19
    assert br._tile_count(bounds, zoom) <= 16


def test_render_provider_builds_mosaic(monkeypatch):
    provider = STATIC_PROVIDERS["esri_street"]
    sess = DummySession()
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(3, 2))
    bounds = (-7_000_000, 2_000_000, -6_000_000, 3_000_000)
    info = br._render_provider(ax, provider, bounds, session=sess)
    assert info["tiles_loaded"] == info["tiles_requested"]
    assert len(sess.calls) == info["tiles_requested"]
    plt.close(fig)



def test_render_with_fallback_uses_bundled_offline_after_online_failure(monkeypatch):
    import matplotlib.pyplot as plt

    def fake_render(ax, provider, bounds, session=None, progress=None):
        raise br.BasemapFetchError("blocked")

    monkeypatch.setattr(br, "_render_provider", fake_render)
    fig, ax = plt.subplots(figsize=(3, 3))
    used, info, err = br.render_with_fallback(ax, "esri_street", (-2e6, 2e6, 2e6, 7e6), "")
    assert used == "offline_world"
    assert "blocked" in (err or "")
    assert "attribution" in info
    plt.close(fig)


def test_offline_world_does_not_need_network(monkeypatch):
    import matplotlib.pyplot as plt

    def no_network(*args, **kwargs):
        raise AssertionError("network access should not be used by the offline basemap")

    monkeypatch.setattr(br, "_fetch_tile", no_network)
    fig, ax = plt.subplots(figsize=(3, 3))
    used, info, err = br.render_with_fallback(
        ax, "offline_world", (-2e6, 2e6, 2e6, 7e6), ""
    )
    assert used == "offline_world"
    assert err is None
    assert info["attribution"]
    plt.close(fig)


def test_square_web_bounds_are_square():
    bounds = br.square_web_bounds((0, 0, 4_000_000, 1_000_000))
    assert round(bounds[2] - bounds[0], 6) == round(bounds[3] - bounds[1], 6)
    assert round((bounds[0] + bounds[2]) / 2, 6) == 2_000_000
    assert round((bounds[1] + bounds[3]) / 2, 6) == 500_000


def test_diagnose_basemaps_reports_success_and_http_failure(monkeypatch):
    import requests
    from gui.basemap_renderer import diagnose_basemaps

    class Resp:
        def __init__(self, code, content=b""):
            self.status_code = code
            self.content = content

    png = DummyResponse().content
    sequence = [Resp(200, png), Resp(503, b"")]

    class S:
        def __init__(self):
            self.headers = {}
        def get(self, url, timeout=8):
            return sequence.pop(0)

    monkeypatch.setattr(requests, "Session", S)
    rows = diagnose_basemaps(["esri_street", "esri_street"])
    assert rows[0][1] is True
    assert rows[1][1] is False
    assert "HTTP 503" in rows[1][2]


def test_offline_resource_is_available_locally():
    segments = br._load_offline_world()
    assert len(segments) > 0
    assert all(len(seg) >= 2 for seg in segments[:10])
