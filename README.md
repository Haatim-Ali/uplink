# Food Rescue Agents

One photo of leftover food becomes a completed donation. Three AI agents with competing goals (Speed, Cost, Need) negotiate where the food goes and who drives it, with no boss. Safety rules in code remove unsafe plans before anyone argues. When something breaks, they renegotiate on their own. When they truly can't agree, a plan crosses one agent's red line, or the decision hinges on a fact nobody has confirmed, they stop and ask a person instead of forcing a consensus.

Built for the Cisco Cloud AI track, "When AI Agents Disagree" (Level 3).

- **Architecture and technical details:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Results and lessons learned:** [docs/RESULTS.md](docs/RESULTS.md)

## Run it (2 minutes)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PORT=5001 python app.py      # macOS: port 5000 is often taken by AirPlay Receiver
```

- Dashboard: http://localhost:5001
- Business view (open on a phone on the same Wi-Fi): http://YOUR-LAPTOP-IP:5001/business
- Donation records (SB 1383): http://localhost:5001/records

It runs with **no API key**: vision returns a demo pizza result and the agents use rules-based reasoning. The map needs internet for its tiles.

### Turn on the AI model

```bash
export ANTHROPIC_API_KEY=...      # or OPENAI_API_KEY=... (OPENAI_BASE_URL works for NVIDIA NIM)
python app.py                      # vision now uses the model
LLM_AGENTS=1 python app.py         # agents also propose, vote and explain with the model
```

Optional: `ANTHROPIC_MODEL`, `OPENAI_MODEL`, and `AGENT_MODEL` (a faster model for the agents). Any failed model call falls back to rules, so the demo never hangs on an error. The clock pauses while agents deliberate. Red lines are enforced in code in both modes; the model is told about them but can't override them.

## Demo script

1. Pick **Lunch rush** and click **Run scenario**. Watch the agents argue in the negotiation panel and feed.
2. Click a past negotiation (D1, D2...) and step through R1 → R2 to show proposals, objections, vetoes and concessions.
3. Press **Shelter says full**, **Driver cancels**, **New pantry joins** to show adaptation live.
4. Show the three ways the team refuses a bad consensus:
   - **Unacceptable compromise**: two agents want a plan, the third vetoes it. The coordinator box explains why.
   - **Irreconcilable goals**: no plan wins a majority after 3 rounds. A human picks from the agents' top two.
   - **Insufficient evidence**: the agents ask the business "is this free of peanuts?" before committing. Answer with the buttons, or wait and watch them act on what they know.
5. Send a real photo from the Business view on a phone (tick "Not sure about allergens" to trigger the question).
6. Click **Team vs baselines** for the evidence table.

## How it works

| File | What it does |
| --- | --- |
| `world.py` | Simulated city: capability directory, **safety rules**, drivers, clock, events, impact, records, the nearest-shelter **baseline** and the **single-agent** policies |
| `agents.py` | Speed, Cost, Need agents, their **red lines**, the **negotiation protocol** (rules or LLM) and the **evidence check** |
| `scenarios.py` | 7 repeatable scripted scenarios and the comparison of 5 policies (`python scenarios.py`) |
| `vision.py` / `llm.py` | Photo → food details; thin model wrapper (Anthropic, OpenAI, or OpenAI-compatible) |
| `app.py` | Flask server, live clock, planner thread, API |
| `static/` | Dashboard, phone business page, records page |
| `data/` | Fictional nonprofits, drivers, businesses near the venue |

**Negotiation (no central decision-maker).** Each round every agent proposes a plan, then votes accept/object on every plan on the table, with reasons. Round 1 is each agent's favourite; later rounds concede toward plans the others can live with and steer clear of plans someone vetoed. A plan everyone accepts wins.

**When the team should not agree.** Consensus is not always right, so the negotiation can end six ways:

| Outcome | When | What happens |
| --- | --- | --- |
| Consensus | All three accept a plan | Act on it |
| Majority | After 3 rounds, 2 of 3 (by vote weight) accept and nobody vetoes it | Act; the loser's objection is kept on record |
| Time is short | Under 30 minutes until the food is unsafe | Stop and act on the best-supported plan nobody vetoed |
| Unacceptable compromise | A majority wants a plan that crosses the third agent's red line | Ask a human, with the reason and the top two options |
| Irreconcilable | No plan has majority support after 3 rounds | Ask a human |
| Insufficient evidence | An agent's best plan is ruled out only by an unconfirmed fact (allergens) and there are 45+ minutes left | Ask the business; wait up to 15 minutes; then act on what is known |

Plans over $25 also go to a human.

**Red lines (an agent's veto).** Speed: under 10 minutes to spare, or a driver under 50% reliable. Cost: over $20 for one donation. Need: feeding a shelter that already got food today while another has waited 4+ days. A veto holds in every round and a majority cannot override it.

**Safety (never negotiated).** Food type accepted, fridge for cold food, allergens (unconfirmed allergens count as present), capacity (including food already on the way), opening hours, and arrival at least 5 minutes before the food becomes unsafe.

**Adaptation.** A driver who cancels loses 30 points of reliability, which every agent sees. An agent that warned about that driver (objection or veto) gains vote weight (+0.25).

**Discovery.** Agents search the directory by capability. A new pantry can register mid-run; waiting and not-yet-picked-up donations are reconsidered.

**Fallback rules (disclosed, not decision-makers).** In scripted runs nobody is at the keyboard, so a simulated coordinator picks the agents' top-ranked option when asked. In the live demo, if no human answers an escalation before the food has 15 minutes left, the agents' top-ranked option goes. Both are labeled as such in the feed.

## Results (rules mode, `python scenarios.py`)

Totals across all 7 scenarios. Full per-scenario tables and what we learned: [docs/RESULTS.md](docs/RESULTS.md).

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 276 | 381 | 381 | 381 | 381 |
| Servings lost | 105 | 0 | 0 | 0 | 0 |
| Money spent ($) | 57.9 | 115.63 | 20.78 | 62.73 | 57.67 |
| Shelters fed | 7 | 10 | 11 | 14 | 14 |
| Avg minutes to spare (perishable food) | 74 | 65 | 61 | 61 | 59 |
| Asked a human | 0 | 0 | 0 | 0 | 2 |

How the team's 22 decisions ended: consensus 17, insufficient evidence 2, majority 1, unacceptable compromise 1, irreconcilable 1.

Re-run after changing data or rules; quote whatever it prints.

## Team split

- **Agents and backend:** `agents.py`, `world.py` (tune scores, thresholds, red lines, LLM prompts)
- **Data and scenarios:** `data/`, `scenarios.py` (make goals clash more; add scenarios)
- **Frontend and pitch:** `static/`, demo script, backup video, Devpost

## Next ideas

Give each agent private information it has to share as evidence; LLM agents as the demo default with saved responses as a fallback; ask the shelter to accept before dispatch (ElevenLabs voice call); more donations at once.
