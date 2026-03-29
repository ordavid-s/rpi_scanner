#!/usr/bin/env bash
set -euo pipefail

CERT_DIR="${1:-/opt/bt-gps-panel/certs}"
mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout "$CERT_DIR/server.key" \
  -out "$CERT_DIR/server.crt" \
  -subj "/CN=192.168.7.1"

chmod 600 "$CERT_DIR/server.key"
chmod 644 "$CERT_DIR/server.crt"

echo "Certificate written to $CERT_DIR"
