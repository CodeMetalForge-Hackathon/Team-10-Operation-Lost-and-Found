#!/bin/bash
# Make the Pi a standalone T10 field box. Run ON THE PI, once, with sudo:
#   sudo bash ~/t10/deploy/pi/install.sh
# 1. installs Python packages (needs internet: run it while the Pi still has the venue Wi-Fi or Ethernet sharing)
# 2. installs + starts the services: t10-camera (:8080), t10-heatmap (fusion/server.py, :8000), t10-overlay (:8099)
# 3. turns wlan0 into the T10 hotspot (10.42.0.1) and stops it joining other Wi-Fi. Ethernet keeps working.
# Settings: deploy/pi/t10.env. Re-running is safe.
set -e
DIR=/home/t10pi/t10
get() { grep -E "^$1=" "$DIR/deploy/pi/t10.env" | head -1 | cut -d= -f2-; }

echo "== 1/3 packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-opencv python3-picamera2 python3-numpy python3-serial \
  python3-fastapi python3-uvicorn python3-websockets python3-httpx dnsmasq-base > /tmp/t10_apt.log 2>&1 || { tail -20 /tmp/t10_apt.log; exit 1; }

echo "== 2/3 services"
pkill -f "drone/[l]ive_mosaic.py" || true    # hand-started copies would hold the ports
pkill -f "fusion/[h]eatmap.py" || true
pkill -f "fusion[.]server" || true
pkill -f "fusion/[t]ak_overlay.py" || true
mkdir -p "$DIR/data" && chown t10pi:t10pi "$DIR/data"
for s in t10-camera t10-heatmap t10-overlay; do
  cp "$DIR/deploy/pi/$s.service" /etc/systemd/system/
done
systemctl daemon-reload
systemctl enable --now t10-camera t10-heatmap t10-overlay

echo "== 3/3 hotspot"
SSID=$(get T10_SSID); PSK=$(get T10_PSK); CH=$(get T10_CHANNEL)
nmcli connection delete t10-field >/dev/null 2>&1 || true
nmcli connection add type wifi ifname wlan0 con-name t10-field autoconnect yes ssid "$SSID" \
  802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel "$CH" \
  ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv6.method disabled \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" connection.autoconnect-priority 100 >/dev/null
# never rejoin client Wi-Fi networks on wlan0 (the hotspot owns it)
nmcli -t -f NAME,TYPE connection show | awk -F: '$2=="802-11-wireless" && $1!="t10-field" {print $1}' |
  while read -r c; do nmcli connection modify "$c" connection.autoconnect no; done
nmcli connection up t10-field >/dev/null
echo
echo "Done. Hotspot '$SSID' (password: $PSK) on channel $CH; the Pi is 10.42.0.1"
echo "  dashboard http://10.42.0.1:8000  heatmap http://10.42.0.1:8000/heatmap  TAK picture http://10.42.0.1:8000/tak"
echo "  camera  http://10.42.0.1:8080    TAK overlay link  http://10.42.0.1:8099/link.kml"
echo "  logs: journalctl -u t10-heatmap -f      restart all: sudo systemctl restart 't10-*'"
systemctl --no-pager --lines=0 status t10-camera t10-heatmap t10-overlay | grep -E "^\S|Active:"
