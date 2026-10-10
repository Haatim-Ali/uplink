#!/bin/bash
# One-time setup ON the Brev GPU instance: install vLLM and download the vision model.
# Does not start the model server. Safe to re-run; it skips what's already done.
#   brev copy scripts/brev_setup.sh uplink-2026:/home/ubuntu/brev_setup.sh
#   brev exec uplink-2026 "nohup bash ~/brev_setup.sh > ~/brev_setup.log 2>&1 &"
set -e
MODEL="${VISION_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
export HF_HOME="$HOME/hf-models"   # on the persistent disk, so the model survives a stop

if [ ! -x "$HOME/vllm-env/bin/vllm" ]; then
  rm -rf "$HOME/vllm-env"   # clear any half-made environment from an earlier failed run
  # Brev's Ubuntu image lacks the venv package; install it if needed
  python3 -m venv "$HOME/vllm-env" 2>/dev/null || {
    sudo apt-get update -qq && sudo apt-get install -y -qq "python3.$(python3 -c 'import sys; print(sys.version_info.minor)')-venv"
    rm -rf "$HOME/vllm-env"
    python3 -m venv "$HOME/vllm-env"
  }
  "$HOME/vllm-env/bin/pip" install -q --upgrade pip
  "$HOME/vllm-env/bin/pip" install -q vllm
fi
"$HOME/vllm-env/bin/python" -c "import vllm; print('vllm', vllm.__version__)"

"$HOME/vllm-env/bin/python" - "$MODEL" <<'PY'
import sys
from huggingface_hub import snapshot_download
print("model at", snapshot_download(sys.argv[1]))
PY
du -sh "$HF_HOME"
echo SETUP_DONE
