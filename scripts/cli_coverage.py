#!/usr/bin/env python3
"""Measure how much of the Databricks API surface minilake actually emulates.

Drives the real ``databricks`` CLI against a running minilake and records, for every
API path the ``databricks-sdk`` is known to call, whether minilake answers it or falls
through to the ``catchall`` 501.

Two layers, because neither alone covers the surface:

* **CLI taxonomy** — ``databricks --help`` and ``databricks <group> --help`` give the
  canonical list of groups/commands a user actually types, grouped by the CLI's own
  section headers. This is what lets the report say "``databricks pipelines list``
  fails" instead of only naming a path.
* **Endpoint probe** — ``databricks api <verb> <path>`` is a generic escape hatch that
  reaches any endpoint without needing the high-level command to exist or fixtures
  (catalog names, cluster ids) to be set up. The endpoint list is extracted from the
  installed SDK, which is the source of truth the project's own tests use.

The unit of measurement is the ``(method, path)`` pair, not the path: probing everything
with GET would score POST-only endpoints like ``POST /api/2.1/unity-catalog/catalogs`` as
missing, since FastAPI falls through to the catchall when no method matches.

Safety: requests go only to the ``--host`` passed in, carry an empty JSON body, and use
synthetic ``__probe__`` path parameters that match nothing real; minilake state is reset
before and after the sweep. Point this at a disposable local minilake, never at a real
Databricks workspace.

Usage::

    uv run python scripts/cli_coverage.py --host http://localhost:8123
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# The catchall in services/catchall.py renders exactly this for anything unrouted.
NOT_IMPLEMENTED_MARKER = "is not implemented in minilake"

# catchall.py registers only GET/POST/PUT/PATCH/DELETE, so a HEAD or OPTIONS request to an
# unrouted path never reaches it and gets Starlette's bare 404 instead of minilake's 501.
# Same meaning for coverage purposes; recorded separately so the gap stays visible.
UNROUTED_MARKER = "Error: Not Found"

# Stand-in for a {path_param}. Any error other than the catchall's means the route
# exists and only rejected the value, which is all we need to distinguish.
PROBE_PLACEHOLDER = "__probe__"

# Paths the SDK builds dynamically; the literal never appears as a usable route.
JUNK_PATH_RE = re.compile(r"/api/[0-9.]+/\{")

STATUS_IMPLEMENTED = "implemented"
STATUS_MISSING = "missing"
STATUS_ERROR = "error"


# --------------------------------------------------------------------------- CLI


def find_cli() -> str:
    """Locate the databricks CLI, preferring a user-local install over the PATH."""
    local = Path.home() / ".local" / "bin" / "databricks"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    from shutil import which

    found = which("databricks")
    if not found:
        sys.exit(
            "databricks CLI not found. Install it with:\n"
            "  curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sudo sh"
        )
    return found


def cli_env(host: str) -> dict:
    env = dict(os.environ)
    env["DATABRICKS_HOST"] = host
    env["DATABRICKS_TOKEN"] = "dapi-minilake-local"
    # minilake has no auth; these keep the CLI from looking elsewhere for a profile.
    env.pop("DATABRICKS_CONFIG_PROFILE", None)
    env["DATABRICKS_CONFIG_FILE"] = os.devnull
    return env


def run_cli(cli: str, args: list[str], env: dict, timeout: int = 30) -> tuple[int, str, str]:
    proc = subprocess.run(
        [cli, *args, "--log-level=error"],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ----------------------------------------------------------------- layer A: help


# "  group-name    Description of the group." — two-space indent, no leading dash.
HELP_ENTRY_RE = re.compile(r"^ {2}([a-z][a-z0-9-]+)\s{2,}(.*)$")
# Section headers are flush-left and not "Usage:"-style keys.
HELP_SECTION_RE = re.compile(r"^([A-Z][A-Za-z0-9 &/-]+)$")


def discover_groups(cli: str, env: dict) -> dict[str, list[dict]]:
    """Parse ``databricks --help`` into {section header: [{name, description}]}."""
    _, out, err = run_cli(cli, ["--help"], env)
    text = out + err
    sections: dict[str, list[dict]] = defaultdict(list)
    current: Optional[str] = None
    for line in text.splitlines():
        if line.startswith("Usage:") or line.startswith("Flags:"):
            current = None
            continue
        header = HELP_SECTION_RE.match(line.rstrip())
        if header:
            current = header.group(1).strip()
            continue
        entry = HELP_ENTRY_RE.match(line.rstrip())
        if entry and current:
            sections[current].append({"name": entry.group(1), "description": entry.group(2).strip()})
    return dict(sections)


COMMAND_HEADER_RE = re.compile(r"^[A-Z][A-Za-z ]*Commands:?$")


def discover_commands(cli: str, env: dict, group: str) -> list[str]:
    """Parse ``databricks <group> --help`` into the list of subcommand names."""
    try:
        _, out, err = run_cli(cli, [group, "--help"], env)
    except subprocess.TimeoutExpired:
        return []
    text = out + err
    commands = []
    in_block = False
    for line in text.splitlines():
        stripped = line.rstrip()
        # Groups head their command lists with "Main Commands", "All Commands" or
        # "Available Commands:" depending on the group; all three start a block.
        if COMMAND_HEADER_RE.match(stripped):
            in_block = True
            continue
        if in_block:
            if not stripped:
                continue
            if not stripped.startswith("  "):
                in_block = False
                continue
            entry = HELP_ENTRY_RE.match(stripped)
            if entry:
                commands.append(entry.group(1))
    return commands


# ------------------------------------------------------------- layer B: SDK paths


def sdk_service_dir() -> Path:
    """Locate databricks/sdk/service/ in the project venv, falling back to imports."""
    for candidate in sorted(REPO_ROOT.glob(".venv/lib/python*/site-packages")):
        service = candidate / "databricks" / "sdk" / "service"
        if service.is_dir():
            return service
    try:
        import databricks.sdk as sdk  # noqa: PLC0415
    except ImportError:
        sys.exit("databricks-sdk not importable and not found under .venv/. Run `uv sync`.")
    return Path(sdk.__file__).parent / "service"


# ``self._api.do("GET", f"/api/2.1/unity-catalog/catalogs/{name}", ...)`` — method and
# path are adjacent, sometimes split across lines by the formatter.
API_CALL_RE = re.compile(r'\.do\(\s*"([A-Z]+)"\s*,\s*f?"(/api/[0-9.]+/[^"]+)"', re.S)


def extract_sdk_endpoints(service_dir: Path) -> dict[str, set[tuple[str, str]]]:
    """Map each SDK service module to the (method, path) endpoints it calls."""
    by_module: dict[str, set[tuple[str, str]]] = {}
    for path in sorted(service_dir.glob("*.py")):
        if path.name.startswith("_") or path.name == "__init__.py":
            continue
        found = set()
        for method, raw in API_CALL_RE.findall(path.read_text()):
            if JUNK_PATH_RE.match(raw):
                continue
            normalized = re.sub(r"\{[^}]+\}", PROBE_PLACEHOLDER, raw).rstrip("/")
            found.add((method, normalized))
        if found:
            by_module[path.stem] = found
    return by_module


# ------------------------------------------------------------ minilake's own routes


ROUTER_PREFIX_RE = re.compile(r'APIRouter\(\s*prefix="([^"]*)"')
ROUTE_RE = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"')


def minilake_routes() -> dict[str, set[tuple[str, str]]]:
    """Read the (method, path) routes minilake registers, per service module."""
    by_service: dict[str, set[tuple[str, str]]] = {}
    services = REPO_ROOT / "src" / "minilake" / "services"
    for path in sorted(services.glob("*.py")):
        if path.name in {"__init__.py", "catchall.py"}:
            continue
        src = path.read_text()
        prefix_match = ROUTER_PREFIX_RE.search(src)
        prefix = prefix_match.group(1) if prefix_match else ""
        found = set()
        for method, route in ROUTE_RE.findall(src):
            full = (prefix + route).rstrip("/")
            found.add((method.upper(), re.sub(r"\{[^}]+\}", PROBE_PLACEHOLDER, full)))
        if found:
            by_service[path.stem] = found
    return by_service


# ------------------------------------------------------------------------ probing


def probe_endpoint(cli: str, env: dict, method: str, path: str) -> dict:
    """Issue one request through the CLI and classify the answer."""
    verb = method.lower()
    args = ["api", verb, path]
    if verb in {"post", "put", "patch"}:
        args += ["--json", "{}"]
    try:
        rc, out, err = run_cli(cli, args, env)
    except subprocess.TimeoutExpired:
        return {"method": method, "path": path, "status": STATUS_ERROR, "detail": "timeout"}
    combined = (err + out).strip()
    if NOT_IMPLEMENTED_MARKER in combined:
        return {
            "method": method,
            "path": path,
            "status": STATUS_MISSING,
            "detail": "501 NOT_IMPLEMENTED",
        }
    if combined == UNROUTED_MARKER:
        return {
            "method": method,
            "path": path,
            "status": STATUS_MISSING,
            "detail": "404 — unrouted (catchall does not cover this method)",
        }
    if "unknown command" in combined.lower():
        return {
            "method": method,
            "path": path,
            "status": STATUS_ERROR,
            "detail": f"CLI cannot issue {method}",
        }
    detail = "2xx OK" if rc == 0 else (combined.splitlines() or ["error"])[0][:120]
    # Anything that is not the catchall means the route matched and merely rejected the
    # probe's synthetic arguments — the endpoint exists.
    return {"method": method, "path": path, "status": STATUS_IMPLEMENTED, "detail": detail}


def probe_all(cli: str, env: dict, endpoints: list[tuple[str, str]], workers: int) -> list[dict]:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = pool.map(lambda e: probe_endpoint(cli, env, e[0], e[1]), endpoints)
        for i, result in enumerate(futures, 1):
            results.append(result)
            if i % 100 == 0:
                print(f"  probed {i}/{len(endpoints)}", file=sys.stderr)
    return results


# Read-only, argument-free commands worth trying per CLI group, in preference order.
# If none exists for a group, the group is reported from its API-path coverage instead.
SAFE_COMMANDS = (
    "list",
    "list-scopes",
    "list-all",
    "me",
    "list-node-types",
    "spark-versions",
)

# The CLI rejects these before it ever issues a request, so they say nothing about
# minilake's coverage — the command just needs arguments we deliberately do not invent.
USAGE_ERROR_MARKERS = ("accepts ", "required flag", "requires at least", "unknown flag")


def probe_cli_group(cli: str, env: dict, group: str, commands: list[str]) -> dict:
    """Run one safe read-only command for a CLI group and report what happened."""
    # Preferred names first, then any other list-style command the group happens to
    # expose (pipelines calls it list-pipelines, experiments list-experiments, ...).
    candidates = [c for c in SAFE_COMMANDS if c in commands]
    candidates += [c for c in commands if c.startswith("list") and c not in candidates]
    for candidate in candidates:
        try:
            rc, out, err = run_cli(cli, [group, candidate], env)
        except subprocess.TimeoutExpired:
            return {"probe": f"{group} {candidate}", "result": "timeout"}
        combined = (err + out).strip()
        if NOT_IMPLEMENTED_MARKER in combined:
            return {"probe": f"{group} {candidate}", "result": "501"}
        if rc == 0:
            return {"probe": f"{group} {candidate}", "result": "ok"}
        first = (combined.splitlines() or [""])[0]
        if any(marker in combined for marker in USAGE_ERROR_MARKERS):
            continue  # needs arguments; try the next candidate rather than mis-scoring
        return {"probe": f"{group} {candidate}", "result": "error", "detail": first[:100]}
    return {"probe": None, "result": "no argument-free command"}


# ------------------------------------------------------------------------- report


def path_group(path: str) -> str:
    """Collapse a path to its API group, e.g. /api/2.1/unity-catalog."""
    parts = path.split("/")
    return "/".join(parts[:4]) if len(parts) >= 4 else path


CLI_STATUS_LABEL = {
    "ok": "✅ works",
    "501": "🚫 501",
    "error": "⚠️ reaches minilake, errors",
    "timeout": "⚠️ timeout",
    "no argument-free command": "— not probed",
}


def build_markdown(data: dict) -> str:
    totals = data["totals"]
    lines: list[str] = []
    add = lines.append

    add("# Databricks API coverage map")
    add("")
    add(
        f"Generated by `scripts/cli_coverage.py` on {data['generated']} using "
        f"{data['cli_version']} against a local minilake ({data['sdk_version']})."
    )
    add("")
    add(
        "Every row is measured, not hand-written: the real `databricks` CLI is pointed at a "
        "disposable minilake and each endpoint the `databricks-sdk` is known to call is "
        "issued through `databricks api <verb> <path>`. An endpoint counts as **missing** "
        "only when minilake answers with the `catchall` 501; any other reply (including a "
        "400 or 404 on the probe's synthetic arguments) means the route exists."
    )
    add("")

    add("## Summary")
    add("")
    add(
        "Note on the answered count: `services/permissions.py` registers a single wildcard "
        "route `/{object_type}/{object_id}`, so it answers every concrete permissions "
        "endpoint the SDK enumerates. That is real emulation, but allow-all — see the "
        "Permissions caveat in `FEATURES.md`."
    )
    add("")
    add("| | Count |")
    add("|---|---:|")
    add(f"| Endpoints the `databricks-sdk` calls | {totals['endpoints']} |")
    add(f"| Answered by minilake | {totals['implemented']} |")
    add(f"| Returning `501 NOT_IMPLEMENTED` | {totals['missing']} |")
    add(f"| **Coverage** | **{totals['coverage_pct']}%** |")
    add(f"| Routes registered in `src/minilake/services/` | {totals['minilake_routes']} |")
    if totals["errors"]:
        add(f"| Not probeable | {totals['errors']} |")
    add("")

    add("## CLI command groups")
    add("")
    add(
        "What `databricks --help` exposes, under the CLI's own section headers. The status "
        "column is the result of actually running that group's argument-free read command "
        "against minilake."
    )
    add("")
    add(
        "`— not probed` means the group has no list-style command that runs without "
        "arguments (`databricks tables list` needs `--catalog-name`), or the command is "
        "local to the CLI and issues no request at all (`auth`, `bundle`, `sync`, "
        "`configure`). Those groups are not unmeasured — see the API-group table below, "
        "which covers every endpoint regardless of how the CLI exposes it."
    )
    add("")
    for section, groups in data["cli_sections"].items():
        add(f"### {section}")
        add("")
        add("| Command group | Subcommands | Probe | Result |")
        add("|---|---:|---|---|")
        for grp in groups:
            probe = f"`databricks {grp['probe']}`" if grp["probe"] else "—"
            label = CLI_STATUS_LABEL.get(grp["result"], grp["result"])
            add(f"| `{grp['name']}` | {len(grp['commands'])} | {probe} | {label} |")
        add("")

    add("## Coverage by API group")
    add("")
    add("Ordered by number of missing endpoints. `—` means no minilake service owns the group.")
    add("")
    add("| API group | Answered | Missing | minilake service |")
    add("|---|---:|---:|---|")
    for row in data["groups"]:
        owner = ", ".join(f"`{s}`" for s in row["services"]) or "—"
        add(f"| `{row['group']}` | {row['implemented']} | {row['missing']} | {owner} |")
    add("")

    add("## Missing endpoints, by group")
    add("")
    for row in data["groups"]:
        if not row["missing_endpoints"]:
            continue
        add(f"<details><summary><code>{row['group']}</code> — {row['missing']} missing</summary>")
        add("")
        for method, path in row["missing_endpoints"]:
            add(f"- `{method} {path}`")
        add("")
        add("</details>")
        add("")

    add("## Regenerating")
    add("")
    add("```bash")
    add("docker compose -f docker-compose.test.yml up -d minilake-test-server")
    add("uv run python scripts/cli_coverage.py --host http://localhost:8123")
    add("```")
    add("")
    add(
        "The probe mutates nothing that survives it — minilake's state is reset through "
        "`POST /_minilake/reset` before and after the sweep. Never point `--host` at a real "
        "Databricks workspace."
    )
    add("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- main


def reset_minilake(cli: str, env: dict) -> None:
    try:
        run_cli(cli, ["api", "post", "/_minilake/reset", "--json", "{}"], env)
    except subprocess.TimeoutExpired:
        print("warning: reset timed out", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://localhost:8123", help="running minilake")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--json-out", type=Path, help="also write the raw results here")
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=REPO_ROOT / "docs" / "CLI_COVERAGE.md",
    )
    parser.add_argument("--skip-probe", action="store_true", help="static analysis only")
    args = parser.parse_args()

    cli = find_cli()
    env = cli_env(args.host)
    _, version_out, _ = run_cli(cli, ["--version"], env)
    cli_version = version_out.strip() or "unknown CLI"
    print(f"Using {cli} ({cli_version}) against {args.host}", file=sys.stderr)

    print("Reading minilake's registered routes...", file=sys.stderr)
    routes_by_service = minilake_routes()
    all_routes = {r for routes in routes_by_service.values() for r in routes}

    print("Extracting endpoints from the installed databricks-sdk...", file=sys.stderr)
    service_dir = sdk_service_dir()
    sdk_by_module = extract_sdk_endpoints(service_dir)
    endpoints = sorted({e for found in sdk_by_module.values() for e in found})
    print(f"  {len(endpoints)} distinct (method, path) endpoints", file=sys.stderr)

    if args.skip_probe:
        results = [
            {
                "method": m,
                "path": p,
                "status": STATUS_IMPLEMENTED if (m, p) in all_routes else STATUS_MISSING,
                "detail": "static analysis only",
            }
            for m, p in endpoints
        ]
    else:
        reset_minilake(cli, env)
        print(f"Probing {len(endpoints)} endpoints through the CLI...", file=sys.stderr)
        results = probe_all(cli, env, endpoints, args.workers)
        reset_minilake(cli, env)

    # Which minilake service owns each API group, for the report's last column.
    owners: dict[str, set[str]] = defaultdict(set)
    for service, routes in routes_by_service.items():
        for _method, route in routes:
            owners[path_group(route)].add(service)

    grouped: dict[str, dict] = defaultdict(lambda: {"implemented": 0, "missing": [], "error": 0})
    for result in results:
        bucket = grouped[path_group(result["path"])]
        if result["status"] == STATUS_IMPLEMENTED:
            bucket["implemented"] += 1
        elif result["status"] == STATUS_MISSING:
            bucket["missing"].append((result["method"], result["path"]))
        else:
            bucket["error"] += 1

    groups = [
        {
            "group": group,
            "implemented": bucket["implemented"],
            "missing": len(bucket["missing"]),
            "missing_endpoints": sorted(bucket["missing"]),
            "errors": bucket["error"],
            "services": sorted(owners.get(group, set())),
        }
        for group, bucket in grouped.items()
    ]
    groups.sort(key=lambda g: (-g["missing"], g["group"]))

    print("Reading the CLI command taxonomy...", file=sys.stderr)
    sections = discover_groups(cli, env)
    cli_sections: dict[str, list[dict]] = {}
    for section, entries in sections.items():
        rows = []
        for entry in entries:
            commands = discover_commands(cli, env, entry["name"])
            probe = (
                probe_cli_group(cli, env, entry["name"], commands)
                if commands and not args.skip_probe
                else {"probe": None, "result": "no argument-free command"}
            )
            rows.append({**entry, "commands": commands, **probe})
        if rows:
            cli_sections[section] = rows

    counts = Counter(r["status"] for r in results)
    implemented = counts[STATUS_IMPLEMENTED]
    try:
        sdk_version = (service_dir.parent / "version.py").read_text().split('"')[1]
        sdk_version = f"databricks-sdk {sdk_version}"
    except (OSError, IndexError):
        sdk_version = "databricks-sdk (version unknown)"

    data = {
        "generated": date.today().isoformat(),
        "cli_version": cli_version,
        "sdk_version": sdk_version,
        "host": args.host,
        "totals": {
            "endpoints": len(endpoints),
            "implemented": implemented,
            "missing": counts[STATUS_MISSING],
            "errors": counts[STATUS_ERROR],
            "minilake_routes": len(all_routes),
            "coverage_pct": round(100 * implemented / len(endpoints), 1) if endpoints else 0.0,
        },
        "groups": groups,
        "cli_sections": cli_sections,
        "minilake_routes_by_service": {k: sorted(f"{m} {p}" for m, p in v) for k, v in routes_by_service.items()},
        "sdk_endpoints_by_module": {k: sorted(f"{m} {p}" for m, p in v) for k, v in sdk_by_module.items()},
        "probes": results,
    }

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(data, indent=2) + "\n")
        print(f"Wrote {args.json_out}", file=sys.stderr)

    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.write_text(build_markdown(data))
    print(f"Wrote {args.markdown_out}", file=sys.stderr)

    t = data["totals"]
    print(
        f"\nCoverage: {t['implemented']}/{t['endpoints']} endpoints "
        f"({t['coverage_pct']}%), {t['missing']} returning 501.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
