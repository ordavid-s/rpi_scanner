#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/bt-gps-panel"
VENV_DIR="$INSTALL_DIR/.venv"
GPS_DEVICE_DEFAULT="/dev/ttyAMA0"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash setup_pi.sh"
  exit 1
fi

apt-get update
apt-get install -y \
  python3-venv python3-pip rsync \
  bluez gpsd gpsd-clients \
  openssl ifupdown

mkdir -p "$INSTALL_DIR"
rsync -a --delete "$PROJECT_DIR/" "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/certs"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

cat > /etc/network/interfaces <<'EOF'
auto lo
iface lo inet loopback

auto eth0
allow-hotplug eth0
iface eth0 inet static
    address 192.168.7.1
    netmask 255.255.255.0
EOF

if ! grep -q '^denyinterfaces eth0$' /etc/dhcpcd.conf 2>/dev/null; then
  echo 'denyinterfaces eth0' >> /etc/dhcpcd.conf
fi

GPS_DEVICE="${GPS_DEVICE:-$GPS_DEVICE_DEFAULT}"
cat > /etc/default/gpsd <<EOF
START_DAEMON="true"
GPSD_OPTIONS="-n"
DEVICES="${GPS_DEVICE}"
USBAUTO="false"
GPSD_SOCKET="/var/run/gpsd.sock"
EOF

install -m 644 "$INSTALL_DIR/systemd/bt-gps-panel.service" /etc/systemd/system/bt-gps-panel.service
systemctl daemon-reload

bash "$INSTALL_DIR/scripts/gen_cert.sh" "$INSTALL_DIR/certs"

systemctl restart dhcpcd || true
ifdown eth0 2>/dev/null || true
ifup eth0

systemctl enable gpsd
systemctl restart gpsd || true
systemctl enable bt-gps-panel.service
systemctl restart bt-gps-panel.service

echo
echo "Setup complete."
echo "Connect by Ethernet."
echo "Set your computer manually to 192.168.7.2/24 if using a direct cable."
echo "Then browse to: https://192.168.7.1:8443"
