# Demo day checklist

Devpost closes **1:30 PM Sunday** (late submissions aren't judged). Feature freeze **10:30 AM**.

## 1. Set up the demo laptop (once, about 15 minutes)

```bash
git clone https://github.com/saraxjain/uplink && cd uplink     # or git pull if already cloned
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-agntcy.txt      # AGNTCY app-sdk
pip install ultralytics opencv-python         # counter camera (large download)
brew install nats-server                     # the app starts it for you
```

Create `.env` in the `uplink` folder with the keys (never commit it):

```
ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...
```

## 2. Check it before you present

```bash
python app.py
```

The first lines must say:

- `Agent network: 16 agents, each its own process, talking over AGNTCY A2A over NATS` (if it says HTTP, NATS or the SDK is missing)
- `Vision: anthropic` and `Voice: ElevenLabs`

Then open http://localhost:5050/ops and confirm:

- [ ] The Agent network badge says **AGNTCY · A2A over NATS · 16 agent processes**
- [ ] Demo controls → Lunch rush → Run scenario: the debate plays and trucks move
- [ ] Activity → Agent services: messages marked **A2A/NATS**, 0 unanswered
- [ ] Stop a shelter agent, run a scenario, restart it
- [ ] Demo controls → Sound and look → Voices on: you hear the agents (laptop volume up)
- [ ] Customer site (http://localhost:5050): schedule a pickup with a real photo
- [ ] Counter camera: in a second terminal, `python camera.py --business corner-bakery` (allow camera access for Terminal the first time). Point the webcam at baked goods; the Live page says "Camera at Kelly's French Bakery sees: …". Click Demo controls → **Closing time (camera)** and the leftovers become donations. No webcam? Add `--image eval_photos/box_of_donuts_0.jpg`

Run the tests if there's time: `python tests/test_core.py` and `python tests/test_mesh.py`.

If anything misbehaves on stage: `AGNTCY=0 python app.py` (HTTP), or `MESH=0 python app.py` (one process). The decisions are identical in all three.

## 3. The 3-minute demo

1. **Problem (30 s).** Food businesses throw away edible food; California now requires many to donate it, but donating is a hassle full of tradeoffs.
2. **Photo (20 s).** On the customer site, photograph real leftovers. Claude counts them; confirm.
3. **Agents negotiate (40 s).** On /ops: shelters answer, drivers bid, Speed, Cost and Need argue (voices on), the safety rules remove an unsafe shelter, a plan wins, the Phone line calls the shelter.
3b. **Counter camera (20 s).** The webcam on the counter has been counting all day. Click **Closing time (camera)**: Claude identifies the leftovers and they become donations, one per food type, with nobody taking a photo.
4. **Things change (45 s).** Shelter says full → they reroute. Driver cancels → reliability drops, the agent that warned gains weight. Run *Irreconcilable goals* → they ask a human with a deadline. Activity → Agent services → **stop a shelter's agent** → it drops out, the next donation goes elsewhere.
5. **Evidence (25 s).** "On 100 scenarios it had never seen, the team lost a third as much food as the best agent working alone, and 93% less than the simple approach."
6. **Close (20 s).** "Every agent is its own service on AGNTCY. They negotiate real tradeoffs with no boss, safety is never up for debate, and they ask a human when they truly can't agree."

## 4. Backup video shot list (record before 10:30 AM; 2–3 minutes)

Record the screen (QuickTime → File → New Screen Recording) with voices on.

1. Terminal: `python app.py` and the "AGNTCY A2A over NATS" line (5 s)
2. Customer site: photo → "Does this look right?" → scheduled → tracking (25 s)
3. /ops Live: run Lunch rush; the network diagram fills, the agents argue, the Phone line plays (40 s)
4. Shelter says full / Driver cancels: the re-plan (25 s)
5. Decisions: an irreconcilable case with "Decide by"; approve an option (20 s)
6. Activity → Agent services: A2A/NATS messages; stop an agent, show it drop out; restart it (25 s)
7. Evidence page and the held-out results table (15 s)

## 5. Submit by 12:30 PM (buffer before 1:30)

Paste `docs/DEVPOST.md` into Devpost, add the repo link and the video, attach the guide PDF.
