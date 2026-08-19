# Build the embedded web UI (Next.js static export). Its `prebuild` step also copies
# Monaco out of node_modules into public/, so the SQL editor is served by minilake
# rather than fetched from a CDN at runtime — the image is meant to work offline.
FROM node:24-slim AS frontend-builder
WORKDIR /app/ui
RUN corepack enable
COPY ui/package.json ui/pnpm-lock.yaml ui/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY ui/ ./
RUN pnpm run build

# Resolve the Delta and Unity Catalog connector jars at build time, using the same Ivy
# resolver spark-submit uses at runtime, so a job container never needs Maven Central.
# Reusing spark-submit (rather than curl-ing jars by hand) is deliberate: it writes the
# ivy-*.xml metadata alongside the jars, and without that metadata Ivy goes back to the
# network even when the jar is already on disk.
#
# --platform=$BUILDPLATFORM: jars are architecture-independent, so this stage does not need
# to run under QEMU during the multi-arch release build.
FROM --platform=$BUILDPLATFORM apache/spark:3.5.3-scala2.12-java17-python3-ubuntu AS sparkjars

USER root

# Keep these in step with docker_executor.DEFAULT_DELTA_PACKAGE and the connector coordinate
# documented for spark.table() resolution.
ARG DELTA_PACKAGE=io.delta:delta-spark_2.12:3.2.1
ARG UC_PACKAGE=io.unitycatalog:unitycatalog-spark_2.12:0.2.1

RUN mkdir -p /opt/ivy/cache /opt/ivy/jars && \
    echo 'pass' > /tmp/warmup.py && \
    /opt/spark/bin/spark-submit \
        --packages "${DELTA_PACKAGE},${UC_PACKAGE}" \
        --conf spark.jars.ivy=/opt/ivy \
        /tmp/warmup.py && \
    ls /opt/ivy/jars/*.jar > /dev/null

FROM python:3.11-slim

WORKDIR /opt/minilake

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml pyproject.toml
COPY src/ src/
COPY README.md README.md
# Inside the package, not beside it: `app.py` looks for `minilake/ui_static` first,
# which is also where the wheel's force-include puts it — so the container and a
# `pip install minilake` resolve the UI the same way.
COPY --from=frontend-builder /app/ui/out /opt/minilake/src/minilake/ui_static

# Install minilake with the MCP and notebook extras. Both are baked into the image so
# MINILAKE_MCP=1 is all that's needed to turn the MCP server on and JupyterLab is there
# by default; the extras stay optional for PyPI installs.
#
# The notebook extra brings JupyterLab but deliberately no pyspark: notebooks reach real
# Spark through the Jobs API, in the same sibling containers a job uses, so the image
# never carries a second Spark.
RUN pip install --no-cache-dir -e ".[mcp,notebook]"

# Pre-install DuckDB's `delta` extension. Without this the server downloads it from
# extensions.duckdb.org on every first boot, into a $HOME path that is not a volume — so it
# is re-fetched for each new container, and fails outright with no internet access.
# The directory is explicit rather than $HOME/.duckdb so it survives `docker run --user`, and
# sits outside WORKDIR so a bind-mount over the source tree cannot shadow it.
ENV MINILAKE_DUCKDB_EXTENSION_DIR=/opt/duckdb-extensions
RUN python -c "import duckdb, os; duckdb.connect(config={'extension_directory': os.environ['MINILAKE_DUCKDB_EXTENSION_DIR']}).execute('INSTALL delta')" && \
    find "$MINILAKE_DUCKDB_EXTENSION_DIR" -name 'delta.duckdb_extension' | grep -q . && \
    chmod -R a+rX "$MINILAKE_DUCKDB_EXTENSION_DIR"

# Delta / Unity Catalog jars resolved in the sparkjars stage above. Copied into the volume
# shared with job containers on first use (see docker_executor._seed_ivy_cache).
COPY --from=sparkjars /opt/ivy /opt/ivy-cache
ENV MINILAKE_IVY_SEED=/opt/ivy-cache

# Create data directory
RUN mkdir -p /data

# Expose ports (HTTP + HTTPS)
EXPOSE 8000 8443

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MINILAKE_DATA_DIR=/data
ENV MINILAKE_HOST=0.0.0.0
ENV MINILAKE_PORT=8000
# Native HTTPS is opt-in: set MINILAKE_TLS=1 to also serve TLS on :8443 (an
# auto-generated self-signed cert lands under /data/certs). To bring your own
# cert, set MINILAKE_SSL_CERTFILE / MINILAKE_SSL_KEYFILE.

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/_minilake/health || exit 1

# Run minilake server
CMD ["minilake", "--host", "0.0.0.0", "--port", "8000"]
