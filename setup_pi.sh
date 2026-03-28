#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/bt-gps-panel"
VENV_DIR="$INSTALL_DIR/.venv"
WLAN_IFACE="wlan0"
AP_IP="192.168.50.1/24"
GPS_DEVICE_DEFAULT="/dev/ttyAMA0"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash setup_pi.sh"
  exit 1
fi

apt-get update
apt-get install -y \
  python3-venv python3-pip rsync \
  bluez gpsd gpsd-clients \
  hostapd dnsmasq openssl

systemctl unmask hostapd || true
systemctl stop hostapd || true
systemctl stop dnsmasq || true

mkdir -p "$INSTALL_DIR"
rsync -a --delete "$PROJECT_DIR/" "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/certs"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Copy AP configs
install -m 644 "$INSTALL_DIR/config/hostapd.conf" /etc/hostapd/hostapd.conf
install -m 644 "$INSTALL_DIR/config/dnsmasq.conf" /etc/dnsmasq.conf

# Ensure hostapd uses our config
if grep -q '^#*DAEMON_CONF=' /etc/default/hostapd 2>/dev/null; then
  sed -i 's|^#*DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
else
  echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd
fi

# Static IP for AP interface via dhcpcd
if ! grep -q 'bt-gps-panel begin' /etc/dhcpcd.conf; then
  cat >> /etc/dhcpcd.conf <<DHCPCD

# bt-gps-panel begin
interface ${WLAN_IFACE}
static ip_address=${AP_IP}
nohook wpa_supplicant
# bt-gps-panel end
DHCPCD
fi

# gpsd defaults
GPS_DEVICE="${GPS_DEVICE:-$GPS_DEVICE_DEFAULT}"
cat > /etc/default/gpsd <<GPSD
START_DAEMON="true"
GPSD_OPTIONS="-n"
DEVICES="${GPS_DEVICE}"
USBAUTO="false"
GPSD_SOCKET="/var/run/gpsd.sock"
GPSD

# Enable IPv4 local routing knobs only if you later want to add forwarding.
cat > /etc/sysctl.d/99-bt-gps-panel.conf <<'SYSCTL'
net.ipv4.ip_forward=0
SYSCTL
sysctl --system >/dev/null || true

# App service
install -m 644 "$INSTALL_DIR/systemd/bt-gps-panel.service" /etc/systemd/system/bt-gps-panel.service
systemctl daemon-reload

# Self-signed cert
bash "$INSTALL_DIR/scripts/gen_cert.sh" "$INSTALL_DIR/certs"

# Restart/enable services
systemctl enable gpsd
systemctl restart gpsd || true
systemctl enable hostapd
systemctl enable dnsmasq
systemctl restart hostapd
systemctl restart dnsmasq
systemctl enable bt-gps-panel.service
systemctl restart bt-gps-panel.service

echo
echo "Setup complete."
echo "Connect to AP SSID configured in /etc/hostapd/hostapd.conf"
echo "Then browse to: https://192.168.50.1:8443"
