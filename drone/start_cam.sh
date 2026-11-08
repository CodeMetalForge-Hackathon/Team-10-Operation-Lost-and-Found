#!/bin/bash
# Pi: start (or restart) the live camera mosaic in the background. Extra args go to live_mosaic.py, e.g.
#   ~/t10/start_cam.sh --record data/walk4 --out data/walk4_mosaic --mask-bottom 0.3 --shutter-us 6000
# Expects this repo's drone/ folder at ~/t10/drone. Log: ~/t10/data/live.log. Stop: pkill -f "drone/[l]ive_mosaic.py"
cd ~/t10
mkdir -p data
pkill -f "drone/[l]ive_mosaic.py" && sleep 1
nohup python3 drone/live_mosaic.py "$@" > data/live.log 2>&1 &
echo "started pid $!"
