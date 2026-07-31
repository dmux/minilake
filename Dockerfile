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

# Install minilake with the MCP extra. Baked into the image so MINILAKE_MCP=1 is all that's
# needed to turn the MCP server on; the extra stays optional for PyPI installs.
RUN pip install --no-cache-dir -e ".[mcp]"

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
