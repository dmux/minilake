"""Embedded JupyterLab tests — the /jupyter proxy and its status endpoint.

These drive the proxy over HTTP rather than importing the module, so they exercise
the same path a browser takes. The kernel WebSocket is not covered here: it needs a
live JupyterLab, which the test image does start but which would make the suite
depend on a multi-second startup race for little added signal.
"""

import json
import urllib.error
import urllib.request

import pytest


def _get(url: str) -> tuple[int, dict]:
    try:
        response = urllib.request.urlopen(url, timeout=10)
        return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


@pytest.mark.smoke
def test_notebook_status_reports_capability(minilake_server: str):
    """GET /jupyter/_status describes whether notebooks are usable."""
    status, body = _get(f"{minilake_server}/jupyter/_status")
    assert status == 200

    # Always present, so the UI can branch without guessing.
    assert set(body) >= {"enabled", "installed", "running", "path"}
    assert isinstance(body["enabled"], bool)
    assert isinstance(body["installed"], bool)
    assert isinstance(body["running"], bool)
    assert body["path"] == "/jupyter/"


@pytest.mark.smoke
def test_notebook_status_is_not_swallowed_by_the_proxy(minilake_server: str):
    """`_status` must answer itself, not be forwarded into Jupyter.

    It is registered before the catch-all proxy route; if that order ever flips,
    this returns Jupyter's 404 page instead of a JSON capability report.
    """
    status, body = _get(f"{minilake_server}/jupyter/_status")
    assert status == 200
    assert "installed" in body


@pytest.mark.error
def test_notebook_proxy_reports_unavailable_cleanly(minilake_server: str):
    """A proxied path with no notebook server behind it fails as JSON, not a 500.

    When JupyterLab is running this is a normal Jupyter response instead — either
    way the caller gets a structured answer rather than a stack trace.
    """
    _, status_body = _get(f"{minilake_server}/jupyter/_status")

    try:
        response = urllib.request.urlopen(f"{minilake_server}/jupyter/lab", timeout=15)
        code = response.status
    except urllib.error.HTTPError as e:
        code = e.code
        if code == 503:
            assert json.loads(e.read().decode())["error_code"] == "NOT_AVAILABLE"

    if status_body.get("running"):
        # Jupyter answers /lab with the Lab page (or a redirect to it).
        assert code in (200, 302), f"unexpected status {code} from a running JupyterLab"
    else:
        assert code == 503


@pytest.mark.smoke
def test_api_catchall_is_unaffected_by_the_notebook_mount(minilake_server: str):
    """The proxy lives off /api/*, so the 501 catch-all still owns that namespace."""
    status, body = _get(f"{minilake_server}/api/2.0/definitely-not-implemented")
    assert status == 501
    assert body["error_code"] == "NOT_IMPLEMENTED"
