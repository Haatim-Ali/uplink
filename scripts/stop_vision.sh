#!/bin/bash
# Close this Mac's tunnel, and stop the Brev instance so it stops billing for compute.
#   scripts/stop_vision.sh             tunnel + GPU (stops it for EVERY teammate)
#   scripts/stop_vision.sh --keep-gpu  only this Mac's tunnel; the GPU keeps running for others
# The disk (venv + model) is kept; only storage is billed while stopped (~$0.05/hr).
INSTANCE="${BREV_INSTANCE:-uplink-2026}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$HERE/.tunnel.pid"

if [ -f "$PIDFILE" ]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null && echo "Tunnel closed."
  rm -f "$PIDFILE"
fi
if [ "${1:-}" = "--keep-gpu" ]; then
  echo "GPU left running for the team. Whoever finishes last: scripts/stop_vision.sh"
  exit 0
fi
brev stop "$INSTANCE" && echo "$INSTANCE stopping (for everyone). Check with: brev ls"
