#!/bin/bash
# Expects this repo's fusion/ and drone/ folders under ~/t10 on the Pi. Log: ~/t10/data/heatmap.log; recording: ~/t10/data/live_*.jsonl
# Pi: start (or restart) the heatmap on the gateway plugged into this Pi, serving http://<pi>:8000 to the network,
# with the Pi's live camera mosaic (:8080) underneath. Extra args go to heatmap.py (e.g. --pos 1=0,0 --pos 2=3,0 ...).
cd ~/t10
mkdir -p data
GW=$(ls /dev/serial/by-id/*Espressif* 2>/dev/null | head -1)
[ -z "$GW" ] && { echo "no ESP32 gateway on USB"; exit 1; }
pkill -f "fusion/[h]eatmap.py" && sleep 1
nohup python3 fusion/heatmap.py --port "$GW" --bind 0.0.0.0 --mosaic :8080 "$@" > data/heatmap.log 2>&1 &
echo "started pid $! on $GW"
