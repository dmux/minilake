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

# Install minilake
RUN pip install --no-cache-dir -e .

# Create data directory
RUN mkdir -p /data

# Expose ports (HTTP + HTTPS)
EXPOSE 8000 8443

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MINILAKE_DATA_DIR=/data
ENV MINILAKE_HOST=0.0.0.0
ENV MINILAKE_PORT=8000
ENV MINILAKE_SSL_CERT=/etc/minilake/cert.pem
ENV MINILAKE_SSL_KEY=/etc/minilake/key.pem

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/_minilake/health || exit 1

# Run minilake server
CMD ["minilake", "--host", "0.0.0.0", "--port", "8000"]
