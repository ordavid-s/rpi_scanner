# bt-gps-panel

Minimal Raspberry Pi project that:

- starts a local Wi-Fi AP on boot
- serves a small HTTPS admin panel
- reads GPS from `gpsd`
- scans Bluetooth devices via `bluetoothctl`
- stores observations in SQLite

## Layout

- `app/` - Python web app + worker loops
- `config/` - AP and DHCP config files to install on the Pi
- `systemd/` - service unit
- `scripts/` - helper scripts
- `setup_pi.sh` - one-time setup script for Raspberry Pi OS

## What this MVP does

- Connect to the Pi's AP
- Open `https://192.168.50.1:8443`
- Log in with the admin password from `config.env`
- Start/stop Bluetooth scanning
- See live GPS and recent device sightings
- Export observations as CSV

## Hardware assumptions

- Raspberry Pi with working Wi-Fi interface `wlan0`
- Bluetooth controller `hci0`
- GPS module exposed to `gpsd`

## Quick start

1. Copy this folder to the Pi, for example to `/opt/bt-gps-panel`.
2. Edit `config.env`.
3. Run:
   ```bash
   sudo bash setup_pi.sh
   ```
4. Reboot.
5. Connect to the AP and browse to:
   ```
   https://192.168.50.1:8443
   ```

## Default credentials/network

- AP SSID: `PiSensor`
- AP subnet: `192.168.50.0/24`
- Panel URL: `https://192.168.50.1:8443`

## Notes

- The first HTTPS visit will show a certificate warning because this project uses a self-signed certificate.
- The app is intentionally simple: plain SQLite, one FastAPI app, one background scan loop, one GPS loop.
- If your Wi-Fi interface name is not `wlan0`, update `config/hostapd.conf`, `config/dnsmasq.conf`, and `setup_pi.sh`.
