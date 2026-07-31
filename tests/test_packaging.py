"""Guards on what gets published, which cannot be checked after the fact.

A PyPI release is immutable: the rendered README of a published version can never be
corrected, only superseded by a new version. So the cheap structural checks belong here,
where they fail before a tag is pushed rather than on the project page afterwards.
"""

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

# Markdown links and HTML src/href attributes, capturing the target.
_TARGETS = re.compile(r'\]\(([^)]+)\)|(?:src|href)="([^"]+)"')

_ABSOLUTE = ("http://", "https://", "mailto:", "#")


def _readme_targets() -> list[str]:
    text = README.read_text(encoding="utf-8")
    return [markdown or html for markdown, html in _TARGETS.findall(text)]


@pytest.mark.skipif(not README.exists(), reason="running outside a source checkout")
def test_readme_has_no_relative_links():
    """PyPI renders the README with no base URL, so a relative path resolves to nothing.

    The logo and the whole documentation index were dead on the project page for exactly
    this reason — the file is correct on GitHub, where relative paths do resolve, which is
    what makes the breakage invisible until it is permanent.
    """
    relative = [t for t in _readme_targets() if not t.startswith(_ABSOLUTE)]

    assert not relative, (
        "README.md must use absolute URLs so it renders on PyPI. Relative targets found: "
        f"{relative}"
    )


@pytest.mark.skipif(not README.exists(), reason="running outside a source checkout")
def test_readme_image_is_served_raw():
    """A github.com/blob URL returns an HTML page, not an image; only raw. does."""
    images = re.findall(r'<img[^>]+src="([^"]+)"', README.read_text(encoding="utf-8"))
    repo_images = [i for i in images if "github.com/dmux/minilake" in i]

    assert not repo_images, f"Serve repository images from raw.githubusercontent.com: {repo_images}"
