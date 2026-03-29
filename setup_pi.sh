#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/bt-gps-panel"
VENV_DIR="$INSTALL_DIR/.venv"
ETH_IFACE="eth0"
ETH_IP="192.168.7.1/24"
GPS_DEVICE_DEFAULT="/dev/ttyAMA0"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash setup_pi.sh"
  exit 1
fi

apt-get update
apt-get install -y \
  python3-venv python3-pip rsync \
  bluez gpsd gpsd-clients \
  openssl

mkdir -p "$INSTALL_DIR"
rsync -a --delete "$PROJECT_DIR/" "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/certs"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

ETH_CONN_NAME="${ETH_CONN_NAME:-Wired connection 1}"

nmcli connection modify "$ETH_CONN_NAME" \
  ipv4.method manual \
  ipv4.addresses 192.168.7.1/24 \
  ipv4.gateway "" \
  ipv4.dns "" \
  ipv6.method ignore \
  connection.autoconnect yes

nmcli connection up "$ETH_CONN_NAME" || true

# gpsd defaults
GPS_DEVICE="${GPS_DEVICE:-$GPS_DEVICE_DEFAULT}"
cat > /etc/default/gpsd <<GPSD
START_DAEMON="true"
GPSD_OPTIONS="-n"
DEVICES="${GPS_DEVICE}"
USBAUTO="false"
GPSD_SOCKET="/var/run/gpsd.sock"
GPSD

# App service
install -m 644 "$INSTALL_DIR/systemd/bt-gps-panel.service" /etc/systemd/system/bt-gps-panel.service
systemctl daemon-reload

# Self-signed cert
bash "$INSTALL_DIR/scripts/gen_cert.sh" "$INSTALL_DIR/certs"

# Restart/enable services
systemctl restart dhcpcd || true
systemctl enable gpsd
systemctl restart gpsd || true
systemctl enable bt-gps-panel.service
systemctl restart bt-gps-panel.service

echo
echo "Setup complete."
echo "Connect Ethernet to the Pi."
echo "Set your computer manually to 192.168.7.2/24 if using direct cable."
echo "Then browse to: https://192.168.7.1:8443"
