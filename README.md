# Food Rescue Agents

One photo of leftover food becomes a completed donation. Three AI agents with competing goals (Speed, Cost, Need) negotiate where the food goes and who drives it, with no boss. Safety rules in code remove unsafe plans before anyone argues. When something breaks, they renegotiate on their own, and when they truly can't agree, they ask a human.

Built for the Cisco Cloud AI track, "When AI Agents Disagree" (Level 3).

## Run it (2 minutes)

```bash
pip install flask requests
python app.py
```

- Dashboard: http://localhost:5000
- Business view (open on a phone on the same Wi-Fi): http://YOUR-LAPTOP-IP:5000/business
- Donation records (SB 1383): http://localhost:5000/records

It runs with **no API key**: vision returns a demo pizza result and the agents use rules-based reasoning. The map needs internet for its tiles.

### Turn on the AI model

```bash
export ANTHROPIC_API_KEY=...      # or OPENAI_API_KEY=... (OPENAI_BASE_URL works for NVIDIA NIM)
python app.py                      # vision now uses the model
LLM_AGENTS=1 python app.py         # agents also propose, vote and explain with the model
```

Optional: `ANTHROPIC_MODEL`, `OPENAI_MODEL`, and `AGENT_MODEL` (a faster model for the agents). Any failed model call falls back to rules, so the demo never hangs on an error. The clock pauses while agents deliberate.

## Demo script

1. Pick **Lunch rush** and click **Run scenario**. Watch the agents argue in the negotiation panel and feed.
2. Click a past negotiation (D1, D2...) and step through R1 → R2 to show proposals, objections and concessions.
3. Press **Shelter says full**, **Driver cancels**, **New pantry joins** to show adaptation live.
4. Send a real photo from the Business view on a phone.
5. Click **Agents vs baseline** for the evidence table.

## How it works

| File | What it does |
| --- | --- |
| `world.py` | Simulated city: capability directory, **safety rules**, drivers, clock, events, impact, records, and the nearest-shelter **baseline** |
| `agents.py` | Speed, Cost, Need agents and the **negotiation protocol** (rules or LLM) |
| `scenarios.py` | Repeatable scripted scenarios and the baseline comparison (`python scenarios.py`) |
| `vision.py` / `llm.py` | Photo → food details; thin model wrapper (Anthropic, OpenAI, or OpenAI-compatible) |
| `app.py` | Flask server, live clock, planner thread, API |
| `static/` | Dashboard, phone business page, records page |
| `data/` | Fictional nonprofits, drivers, businesses near the venue |

**Negotiation (no central decision-maker).** Each round every agent proposes a plan, then votes accept/object on every plan on the table, with reasons. Round 1 is each agent's favourite; later rounds concede toward plans the others can live with. A plan everyone accepts wins. If food has under 30 minutes left, they act on the best-supported plan. After 3 rounds a weighted majority wins and the dissent is recorded; otherwise a human decides. Any plan over $25 also goes to a human.

**Safety (never negotiated).** Food type accepted, fridge for cold food, allergens, capacity (including food already on the way), opening hours, and arrival at least 5 minutes before the food becomes unsafe.

**Adaptation.** A driver who cancels loses 30 points of reliability, which every agent sees. An agent that warned about that driver gains vote weight (+0.25).

**Discovery.** Agents search the directory by capability. A new pantry can register mid-run; waiting and not-yet-picked-up donations are reconsidered.

## Results (rules mode, `python scenarios.py`)

| Metric | Nearest-shelter baseline | Negotiating agents |
| --- | --- | --- |
| Meals delivered safely | 201 | 261 |
| Servings lost | 60 | 0 |
| Money spent | $30.04 | $20.48 |
| Shelters fed | 5 | 9 |

Re-run after changing data or rules; quote whatever it prints.

## Team split

- **Agents and backend:** `agents.py`, `world.py` (tune scores, thresholds, LLM prompts)
- **Data and scenarios:** `data/`, `scenarios.py` (make goals clash more; add scenarios)
- **Frontend and pitch:** `static/`, demo script, backup video, Devpost

## Next ideas

ElevenLabs voice for each agent or for the shelter call; more donations at once; the business correction flow on stage.
