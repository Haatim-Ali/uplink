#!/bin/bash
# Start the Brev GPU, launch the vision model on it, and connect this Mac to it.
#   scripts/start_vision.sh
#   source scripts/vision_env.sh && PORT=5050 python app.py
# Billing runs while the instance is on (~$0.90/hr for an L4). Stop with scripts/stop_vision.sh.
# One-time setup on a new instance first: see docs/BREV_SETUP.md.
set -euo pipefail
INSTANCE="${BREV_INSTANCE:-uplink-2026}"
MODEL="${VISION_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
PORT="${VISION_PORT:-8000}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$HERE/.tunnel.pid"
LOG="$HERE/.tunnel.log"

# brev prints spinner frames; keep only real output
quiet() { "$@" 2>&1 | tr '\r' '\n' | grep -v "waiting for" || true; }
status() { brev ls 2>/dev/null | awk -v n="$INSTANCE" '$1==n {print $2}'; }

echo "1/4 Starting $INSTANCE (billing starts now)..."
if [ "$(status)" != "RUNNING" ]; then
  brev start "$INSTANCE"
  brev refresh >/dev/null 2>&1 || true   # the address can change after a restart
fi

echo "2/4 Launching the model server..."
quiet brev exec "$INSTANCE" "tmux has-session -t vllm 2>/dev/null && echo 'already running' || \
  tmux new -d -s vllm 'VLLM_USE_FLASHINFER_SAMPLER=0 HF_HOME=\$HOME/hf-models \$HOME/vllm-env/bin/vllm serve $MODEL --port $PORT --max-model-len 8192 > \$HOME/vllm.log 2>&1'"

echo "3/4 Waiting for the model to load (usually 1-3 minutes)..."
for i in $(seq 1 40); do
  if quiet brev exec "$INSTANCE" "curl -sf localhost:$PORT/health >/dev/null && echo HEALTHY" | grep -q HEALTHY; then
    break
  fi
  if [ "$i" = 40 ]; then
    echo "The model didn't come up. See its log with:  brev exec $INSTANCE 'tail -40 ~/vllm.log'"
    exit 1
  fi
  sleep 10
done

echo "4/4 Opening the tunnel to localhost:$PORT..."
if [ -f "$PIDFILE" ]; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; fi
nohup brev port-forward "$INSTANCE" --port "$PORT:$PORT" > "$LOG" 2>&1 &
echo $! > "$PIDFILE"
for i in $(seq 1 30); do
  curl -sf "localhost:$PORT/v1/models" >/dev/null && break
  sleep 2
done
if ! curl -sf "localhost:$PORT/v1/models" >/dev/null; then
  echo "The tunnel didn't connect. See $LOG"
  exit 1
fi

echo
echo "Vision model ready at http://localhost:$PORT"
echo "Run the app:   source scripts/vision_env.sh && PORT=5050 python app.py"
echo "When done:     scripts/stop_vision.sh   (stops billing)"
