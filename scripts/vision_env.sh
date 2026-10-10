# Point the app at the vision model on Brev (opened by scripts/start_vision.sh).
# Usage:  source scripts/vision_env.sh && PORT=5050 python app.py
# The agents stay on rules; only photo reading uses the model.
export OPENAI_API_KEY=unused   # vLLM doesn't check it, but the app needs one set to use the model
export OPENAI_BASE_URL="http://localhost:${VISION_PORT:-8000}/v1"
export OPENAI_MODEL="${VISION_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
unset LLM_AGENTS
echo "Vision: $OPENAI_MODEL via $OPENAI_BASE_URL"
