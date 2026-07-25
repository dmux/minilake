#!/bin/bash

# Generate self-signed SSL certificates for minilake
# Used for local testing with Terraform and other clients

set -e

CERTS_DIR="${1:-.certs}"
DAYS="${2:-3650}"  # 10 years

echo "🔐 Generating self-signed SSL certificates for minilake..."

mkdir -p "$CERTS_DIR"

# Generate private key
openssl genrsa -out "$CERTS_DIR/key.pem" 2048

# Generate certificate
openssl req -new -x509 -key "$CERTS_DIR/key.pem" -out "$CERTS_DIR/cert.pem" -days "$DAYS" \
  -subj "/C=US/ST=Local/L=Local/O=minilake/CN=localhost"

# Create combined PEM for some clients
cat "$CERTS_DIR/cert.pem" "$CERTS_DIR/key.pem" > "$CERTS_DIR/combined.pem"

echo "✅ Certificates generated successfully!"
echo "   Certificate: $CERTS_DIR/cert.pem"
echo "   Private Key: $CERTS_DIR/key.pem"
echo "   Combined: $CERTS_DIR/combined.pem"
echo ""
echo "📝 For Terraform, configure:"
echo '   provider "databricks" {'
echo '     host  = "https://localhost:8443"'
echo '     token = "dev"'
echo '     insecure = true  # Required for self-signed certs'
echo '   }'
