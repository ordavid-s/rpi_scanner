# bt-gps-panel

Minimal Raspberry Pi project that:

- serves a small HTTPS admin panel over Ethernet
- reads GPS from `gpsd`
- scans Bluetooth devices via `bluetoothctl`
- stores observations in SQLite

## What this MVP does

- Connect your computer to the Pi over Ethernet
- Open `https://192.168.7.1:8443`
- Log in with the admin password from `config.env`
- Start/stop Bluetooth scanning
- See live GPS and recent device sightings
- Export observations as CSV

## Hardware assumptions

- Raspberry Pi with working Ethernet interface `eth0`
- Bluetooth controller
- GPS module exposed to `gpsd`

## Quick start

1. Copy this folder to the Pi, for example to `/opt/bt-gps-panel`.
2. Edit `config.env`.
3. Run:
   ```bash
   sudo bash setup_pi.sh
