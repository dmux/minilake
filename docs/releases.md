# Releases & CI/CD

## Continuous integration

Every push and pull request to `main` runs [`ci.yml`](../.github/workflows/ci.yml): `ruff`
lint plus the full test suite in Docker.

## Cutting a release

```bash
# 1. Bump the version — pyproject.toml is the single source of truth
#    (everything else reads it through importlib.metadata)
$EDITOR pyproject.toml
uv lock
git commit -am "chore(release): bump version to X.Y.Z"
git push

# 2. Tag it
git tag vX.Y.Z
git push origin vX.Y.Z
```

That triggers [`release.yml`](../.github/workflows/release.yml), which:

1. **Checks the tag matches `pyproject.toml`**, then runs the full test suite. Both gate
   everything downstream — a mismatch would ship an image labelled one version and a wheel
   containing another, and a PyPI upload cannot be replaced afterwards.
2. Builds a multi-arch image (`amd64` + `arm64`) and pushes it to GHCR as
   `ghcr.io/dmux/minilake:X.Y.Z`, `:X.Y` and `:latest`
3. Builds the sdist and wheel and **publishes them to PyPI**
4. Creates a [GitHub Release](https://github.com/dmux/minilake/releases) with generated notes

Tags must match `vX.Y.Z`.

## Publishing to PyPI

The workflow uses **Trusted Publishing**: PyPI verifies the workflow's identity through
GitHub's OIDC provider, so there is no API token to store, leak or rotate. Two things have
to exist for it to work, and both are one-time.

### 1. The publisher, on PyPI

For a project that does not exist on PyPI yet, register a **pending publisher** — this both
reserves the name and authorises the workflow:

1. Sign in at [pypi.org](https://pypi.org) → **Your account** → **Publishing**
2. Under *Add a new pending publisher*, choose **GitHub** and fill in:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `minilake` |
   | Owner | `dmux` |
   | Repository name | `minilake` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

3. Save.

Once the first release publishes, the pending publisher becomes a normal one, managed under
the project's own *Publishing* settings.

> **The environment name is part of what PyPI checks.** If it does not match the
> `environment: name:` in the workflow, the upload is rejected — it is not cosmetic.

### 2. The environment, on GitHub

Create it at **Settings → Environments → New environment**, named `pypi`.

It works with no configuration, but this is the right place to add protection given the
environment is what authorises publishing:

- **Deployment branches and tags** — restrict to tag pattern `v*`, so no other ref can
  publish
- **Required reviewers** — if you want a human to approve each upload

Nothing else is needed. The job requests `id-token: write` and no secrets at all.

### Verifying before the first real release

A PyPI version number can never be reused, so it is worth checking the artifact locally
first:

```bash
uv build
uvx twine check dist/*

# Install the built wheel into a clean environment and run it
uv venv /tmp/pkgtest && uv pip install --python /tmp/pkgtest/bin/python dist/*.whl
/tmp/pkgtest/bin/minilake --port 8127 &
curl http://localhost:8127/_minilake/health
```

If you would rather rehearse the whole pipeline, TestPyPI accepts the same Trusted
Publishing setup: register a pending publisher at [test.pypi.org](https://test.pypi.org)
with the same values, and add `repository-url: https://test.pypi.org/legacy/` to the
publish step.

## Versioning

Semantic versioning, with the caveat that minilake's contract is *fidelity to the Databricks
API*. A change that makes minilake behave more like real Databricks is a fix, even when it
changes what minilake used to return — for example, a duplicate `create` moving from a
silent `200` to `409 ALREADY_EXISTS`. Those go in the release notes.

## Badges

The badges in the README are live [shields.io](https://shields.io) badges querying the
GitHub API. They reflect the latest tag and workflow run with no README edit after a
release.
