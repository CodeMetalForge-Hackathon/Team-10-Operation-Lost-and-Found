#!/bin/bash
# Usage on the Pi: ~/t10/fps_ramp.sh   or   CFGS="10:2 14:3" VMIN=4.70 EXTRA="--record /tmp/r" ~/t10/fps_ramp.sh
# (Pi 5 flags undervoltage at ~4.63 V; steps are FPS:THREADS. Stops the camera service; restart it after.)
# Ramp camera fps/threads on the current power supply; stop a step early on undervoltage or V < VMIN.
cd ~/t10
VMIN=${VMIN:-4.80}
pkill -f "drone/[l]ive_mosaic.py"; sleep 2
volt() { vcgencmd pmic_read_adc EXT5V_V | sed 's/.*=\([0-9.]*\)V/\1/'; }
echo "idle: $(volt) V  $(vcgencmd get_throttled)"
for cfg in ${CFGS:-5:2 8:2 10:2 10:3 12:3 14:4}; do
  set -- ${cfg/:/ }; FPS=$1; TH=$2
  python3 drone/live_mosaic.py --fps $FPS --threads $TH --mask-bottom 0.3 --shutter-us 6000 --port 8081 ${EXTRA} > /tmp/ramp.log 2>&1 &
  PID=$!; sleep 4
  vmin=9; bad=""; t0=$(date +%s)
  while [ $(( $(date +%s) - t0 )) -lt 20 ]; do
    v=$(volt); vmin=$(echo "$v $vmin" | awk '{print ($1<$2)?$1:$2}')
    th=$(vcgencmd get_throttled | cut -d= -f2)
    if [ $(( th & 0x1 )) -ne 0 ]; then bad="UNDERVOLTAGE flag"; break; fi
    if awk "BEGIN{exit !($v < $VMIN)}"; then bad="V=$v below $VMIN"; break; fi
    sleep 0.2
  done
  st=$(curl -s -m 2 localhost:8081/status)
  kill $PID; wait $PID 2>/dev/null
  echo "fps=$FPS threads=$TH -> achieved $(echo "$st" | python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["fps"], "fps, lost", s["lost"], "/", s["frames"])' 2>/dev/null) | min V $vmin | temp $(vcgencmd measure_temp | cut -d= -f2) | $(vcgencmd get_throttled) ${bad:+ STOPPED: $bad}"
  [ -n "$bad" ] && break
  sleep 3
done
