"""Tests for the embedded web UI served at /ui.

These run against the live test server rather than the ASGI app: the UI is a
static export produced by the Dockerfile's `frontend-builder` stage, so only a
container built from the real Dockerfile actually has one. `Dockerfile.test` has
no Node stage, which is why every test here skips when the mount is absent
instead of failing.
"""

import pytest
import requests


@pytest.fixture(scope="module")
def ui_base(minilake_server: str) -> str:
    response = requests.get(f"{minilake_server}/ui/", timeout=10)
    if response.status_code == 404:
        pytest.skip("server was built without the web UI (no ui/out)")
    return minilake_server


@pytest.mark.smoke
def test_ui_index_is_served(ui_base: str):
    """`/ui/` returns the exported HTML shell."""
    response = requests.get(f"{ui_base}/ui/", timeout=10)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<html" in response.text.lower()


@pytest.mark.smoke
def test_root_redirects_to_ui(ui_base: str):
    """A bare http://localhost:8000 lands on the workspace."""
    response = requests.get(ui_base, allow_redirects=False, timeout=10)

    assert response.status_code in (301, 302, 307, 308)
    assert response.headers["location"].rstrip("/").endswith("/ui")


@pytest.mark.smoke
def test_static_assets_have_correct_mime_types(ui_base: str):
    """Fonts and scripts are served with types the browser will accept.

    A bare `python:slim` image has no /etc/mime.types, so without the explicit
    registrations in app.py a .woff2 goes out as application/octet-stream and the
    browser silently refuses to apply the font.
    """
    index = requests.get(f"{ui_base}/ui/", timeout=10).text

    script_paths = _extract_asset_paths(index, ".js")
    assert script_paths, "exported HTML referenced no scripts"
    script = requests.get(f"{ui_base}{script_paths[0]}", timeout=10)
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]

    for font_path in _extract_asset_paths(index, ".woff2"):
        font = requests.get(f"{ui_base}{font_path}", timeout=10)
        assert font.status_code == 200
        assert font.headers["content-type"] == "font/woff2"


@pytest.mark.smoke
def test_monaco_editor_is_bundled(ui_base: str):
    """The SQL editor loads from this server, not from a CDN.

    minilake's image is deliberately offline-capable (DuckDB extensions and Spark
    jars are baked in). @monaco-editor/react defaults to fetching Monaco from
    jsDelivr at runtime, which would put the editor — the main thing the UI is
    for — behind an internet connection.
    """
    loader = requests.get(f"{ui_base}/ui/monaco/vs/loader.js", timeout=10)

    assert loader.status_code == 200
    assert "javascript" in loader.headers["content-type"]


def _extract_asset_paths(html: str, suffix: str) -> list[str]:
    """Pull `/ui/...<suffix>` references out of the exported HTML."""
    import re

    return sorted(set(re.findall(rf"/ui/[\w\-./@]+{re.escape(suffix)}", html)))
