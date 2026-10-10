# Vision model on an NVIDIA Brev GPU

We don't have a Claude API key, so photo reading runs on an open vision model,
**Qwen2.5-VL-7B-Instruct**, served by **vLLM** on a rented Brev GPU. The app talks to it through
vLLM's OpenAI-compatible API (`llm.py` already supports that). The agents stay on their
rules-based reasoning; only the photo step uses the model.

```
Phone photo -> laptop (app.py) -> localhost:8000 --brev tunnel--> L4 GPU running vLLM + Qwen2.5-VL
```

## Cost

| Instance | Running | Stopped |
| --- | --- | --- |
| `uplink-2026`: 1x NVIDIA L4 (24 GB), GCP `g2-standard-4` | ~$0.90/hr | ~$0.05/hr (storage only) |

Each teammate can redeem one $25 Brev coupon. **Stop the instance whenever you're not using it.**
A stopped instance may fail to restart if no L4 is free in its region, so on demo day start it early
and leave it on through judging.

## Daily use (from the repo on your Mac)

```bash
brew install brevdev/homebrew-brev/brev   # once
brev login                                # once; opens the browser

scripts/start_vision.sh                   # starts the GPU, launches the model, opens the tunnel (~2-5 min)
source scripts/vision_env.sh && PORT=5050 python app.py
...
scripts/stop_vision.sh                    # closes the tunnel and stops billing for compute
```

The business page shows a green "Read by AI" banner when the model is working, a yellow
"Demo mode" banner when no model is connected, and a red banner if the call failed.

## Measure accuracy before the demo

Photograph 15-20 real food spreads with known counts, list them in `eval_photos/answers.csv`
(`file,item,count`), then:

```bash
source scripts/vision_env.sh && python scripts/vision_eval.py eval_photos/
```

It reports how often the model named the food, how often the true count fell inside its range,
and the average counting error. Quote those numbers in the Devpost.

## One-time setup on a new instance

Already done on `uplink-2026`. For a fresh instance (any 24 GB GPU, "VM Mode", no setup script):

```bash
brev copy scripts/brev_setup.sh <instance>:/home/ubuntu/brev_setup.sh
brev exec <instance> "tmux new -d -s setup 'bash ~/brev_setup.sh > ~/brev_setup.log 2>&1'"
brev exec <instance> "tail -3 ~/brev_setup.log"      # repeat until it prints SETUP_DONE (~15 min)
```

It installs the Ubuntu `python3-venv` package if missing, creates `~/vllm-env`, installs vLLM,
and downloads the model to `~/hf-models` on the persistent disk. Then set
`BREV_INSTANCE=<instance>` before running the start/stop scripts.

## How photo reading works (`vision.py`)

1. The photo is shrunk to 1568 px on the long edge in the browser, and again on the server
   (which also fixes rotation and converts iPhone HEIC to JPEG).
2. The model lists each kind of food, counts the units it can see (a range if some are hidden),
   says how it counted, and gives a confidence level.
3. Code, not the model, turns counts into servings, weight and safe time using a unit table
   (1 bagel = 1 serving, about 0.25 lb; 1 tray = about 10 servings; and so on).
4. The business always checks and can fix every field before confirming. Low-confidence counts
   are highlighted.
5. If the call fails or the photo isn't food, the form comes back empty with the reason. It
   never shows made-up food.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `instance ... not found` | `brev ls` for the exact name; set `BREV_INSTANCE` |
| Model never becomes healthy | `brev exec uplink-2026 "tail -40 ~/vllm.log"` |
| Out-of-memory loading the model | Lower `--max-model-len` in `start_vision.sh`, or use a quantized model via `VISION_MODEL` |
| Tunnel fails | `cat scripts/.tunnel.log`; rerun `scripts/start_vision.sh` |
| Restart fails (no capacity) | Wait and retry, or create a new instance and run the one-time setup |
