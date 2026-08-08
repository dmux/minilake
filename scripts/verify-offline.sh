#!/usr/bin/env bash
#
# Proves the published image needs no network at runtime.
#
# `docker run --network none` leaves loopback up (so the server still boots and its health
# check still works) while making every outbound request fail immediately. Anything that
# would have been downloaded on first boot shows up here as a hard failure instead of a
# slow, silent degradation.
#
# Usage: ./scripts/verify-offline.sh [image-tag]

set -euo pipefail

IMAGE="${1:-minilake:offline-check}"

if [ -z "${1:-}" ]; then
    echo "==> Building ${IMAGE}"
    docker build -t "${IMAGE}" .
fi

echo "==> Checking the DuckDB delta extension loads with no network"
# -i is load-bearing: without stdin attached, `python -` reads nothing and exits 0, and the
# check passes without having checked anything.
docker run --rm -i --network none "${IMAGE}" python - <<'PY'
import os
import sys

import duckdb

extension_dir = os.environ["MINILAKE_DUCKDB_EXTENSION_DIR"]
conn = duckdb.connect(config={"extension_directory": extension_dir, "autoinstall_known_extensions": False})
conn.execute("LOAD delta")
name, loaded, installed, path = conn.execute(
    "SELECT extension_name, loaded, installed, install_path FROM duckdb_extensions() "
    "WHERE extension_name = 'delta'"
).fetchone()
if not (loaded and installed and path.startswith(extension_dir)):
    sys.exit(f"delta extension not served from the image: loaded={loaded} installed={installed} path={path}")
print(f"    delta {duckdb.__version__} loaded from {path}")
PY

echo "==> Checking the Spark Delta / Unity Catalog jars are in the image"
docker run --rm --network none "${IMAGE}" sh -c '
    set -e
    ls "$MINILAKE_IVY_SEED"/jars/*.jar > /dev/null
    printf "    %s jars under %s\n" "$(ls "$MINILAKE_IVY_SEED"/jars/*.jar | wc -l)" "$MINILAKE_IVY_SEED"
    # Ivy names jars <group>_<artifact>-<version>.jar in its jars/ dir.
    ls "$MINILAKE_IVY_SEED"/jars/ | grep -q "^io.delta_delta-spark" || { echo "delta-spark jar missing"; exit 1; }
    ls "$MINILAKE_IVY_SEED"/jars/ | grep -q "^io.unitycatalog_unitycatalog-spark" || { echo "unitycatalog-spark jar missing"; exit 1; }
'

echo "==> Booting the server with no network and checking it reports no extension failure"
container=$(docker run -d --rm --network none "${IMAGE}")
trap 'docker rm -f "${container}" > /dev/null 2>&1 || true' EXIT

for _ in $(seq 1 30); do
    if docker exec "${container}" curl -sf http://localhost:8000/_minilake/health > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

docker exec "${container}" curl -sf http://localhost:8000/_minilake/health > /dev/null
logs=$(docker logs "${container}" 2>&1)
if echo "${logs}" | grep -iE "failed to (load|install).*delta extension"; then
    echo "The server could not load the delta extension offline." >&2
    exit 1
fi

echo
echo "OK — ${IMAGE} boots and serves Delta reads with no network access."
echo "Note: running a Spark job still needs the Spark image locally:"
echo "  docker pull apache/spark:3.5.3-scala2.12-java17-python3-ubuntu"
