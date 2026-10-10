# Food Rescue Agents

One photo of leftover food becomes a completed donation. Three AI agents with competing goals (Speed, Cost, Need) negotiate where the food goes and who drives it, with no boss. Safety rules in code remove unsafe plans before anyone argues. When something breaks, they renegotiate on their own. When they truly can't agree, a plan crosses one agent's red line, or the decision hinges on a fact nobody has confirmed, they stop and ask a person instead of forcing a consensus.

Built for the Cisco Cloud AI track, "When AI Agents Disagree" (Level 3).

- **Architecture and technical details:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Results and lessons learned:** [docs/RESULTS.md](docs/RESULTS.md)

## Run it (2 minutes)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PORT=5050 python app.py
```

On a Mac, use `PORT=5050` because macOS reserves port 5000 for AirPlay.

- Dashboard: http://localhost:5050
- Business view (open on a phone on the same Wi-Fi): http://YOUR-LAPTOP-IP:5050/business
- Shelter phone (a teammate plays the shelter): http://YOUR-LAPTOP-IP:5050/shelter?id=northside-youth
- Donation records (SB 1383): http://localhost:5050/records

It runs with **no API key**: vision returns a demo pizza result and the agents use rules-based reasoning. The map needs internet for its tiles.

### Turn on the AI model

```bash
export ANTHROPIC_API_KEY=...      # or OPENAI_API_KEY=... (OPENAI_BASE_URL works for NVIDIA NIM)
python app.py                      # vision now uses the model
LLM_AGENTS=1 python app.py         # agents also propose, vote and explain with the model
```

Optional: `ANTHROPIC_MODEL`, `OPENAI_MODEL`, and `AGENT_MODEL` (a faster model for the agents). Any failed model call falls back to rules, so the demo never hangs on an error. The clock pauses while agents deliberate. Red lines are enforced in code in both modes; the model is told about them but can't override them.

## Demo script

1. A teammate opens the **Shelter** page on their phone and picks a shelter.
2. Pick **Lunch rush** and click **Run scenario**. The debate plays back message by message; objections shake; "Agreed 3 of 3" lands.
3. When the agents pick the teammate's shelter, their phone shows the request. They tap **We're full**: the agents renegotiate live. Next time they tap **Accept**.
4. Press **Driver cancels** and **New pantry joins** to show adaptation. Pop-ups call out each event.
5. Show the three ways the team refuses a bad consensus:
   - **Unacceptable compromise**: two agents want a plan, the third vetoes it. The coordinator box explains why.
   - **Irreconcilable goals**: no plan wins a majority after 3 rounds. A human picks from the agents' top two.
   - **Insufficient evidence**: the agents ask the business "is this free of peanuts?" before committing. Answer with the buttons, or wait and watch them act on what they know.
6. Run **Standoff** to show the agents asking a coordinator to approve an over-budget plan.
7. Send a real photo from the Business view on a phone (tick "Not sure about allergens" to trigger the question).
8. Click **Evidence** for the 50-run comparison chart, and open the scripted table for team vs each agent alone.

Click any past negotiation (D1, D2...) and **Replay debate** to walk judges through one decision, including vetoes.

## How it works

| File | What it does |
| --- | --- |
| `world.py` | Simulated city: capability directory, **safety rules**, drivers, clock, events, impact, records, the nearest-shelter **baseline** and the **single-agent** policies |
| `agents.py` | Speed, Cost, Need agents, their **red lines**, the **negotiation protocol** (rules or LLM) and the **evidence check** |
| `scenarios.py` | Scripted scenarios, the comparison of 5 policies (`python scenarios.py`), and a seeded random-scenario generator |
| `vision.py` / `llm.py` | Photo → food details; thin model wrapper (Anthropic, OpenAI, or OpenAI-compatible) |
| `config.py` | Every tuning knob in one place: speeds, safety margin, cost limit, negotiation thresholds |
| `app.py` | Flask server, live clock, planner thread, API |
| `static/dashboard.{html,css,js}` | Dashboard layout, styles and behavior, in separate files |
| `static/business.html`, `shelter.html`, `records.html` | Phone pages for the business and the shelter; SB 1383 records page |
| `tests/test_core.py` | Safety rules, negotiation, adaptation, shelter phone and evidence checks |
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

**Contacting shelters.** If someone has a shelter's phone page open, the agents ask before dispatching and hold that driver and that shelter's room while waiting. "We're full" marks the shelter full and triggers a renegotiation; no answer within 8 minutes means they try elsewhere.

**Fallback rules (disclosed, not decision-makers).** In scripted runs nobody is at the keyboard, so a simulated coordinator picks the agents' top-ranked option when asked. In the live demo, if no human answers an escalation before the food has 15 minutes left, the agents' top-ranked option goes. Both are labeled as such in the feed.

## Tests

```bash
python3 tests/test_core.py      # or: python3 -m pytest
```

16 checks: cold food never goes somewhere without a fridge, allergens and capacity are respected, every plan arrives in time, the three agents genuinely disagree, short time forces a decision, cancellations lower reliability and trigger a replan, a new pantry is discoverable, the standoff escalates, the shelter phone flow works, pending requests hold capacity, scenarios are repeatable, and the agents never lose more food than the baseline. Run them before every push.

## Results

**The baseline** is what a busy coordinator with a phone list would do: nearest shelter that takes this food type, is open, isn't full and has room, with the nearest free driver, never retrying a shelter that turned the food away. It skips fridge, allergen and timing checks, driver reliability, cost and fairness, and doesn't negotiate.

**All 8 scripted scenarios, team vs each agent alone** (`python scenarios.py`). Full per-scenario tables: [docs/RESULTS.md](docs/RESULTS.md).

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 396 | 501 | 501 | 501 | 501 |
| Servings lost | 105 | 0 | 0 | 0 | 0 |
| Money spent ($) | 90.45 | 148.18 | 53.33 | 95.28 | 90.22 |
| Shelters fed | 9 | 11 | 12 | 15 | 15 |
| Avg minutes to spare (perishable food) | 73 | 65 | 61 | 61 | 59 |
| Asked a human | 0 | 0 | 0 | 0 | 3 |

How the team's negotiations ended: consensus 17, unacceptable 2, insufficient evidence 2, majority 1, irreconcilable 1

**100 random lunch rushes the rules were never tuned on** (`python3 -c "import scenarios; print(scenarios.compare_random(100, 1001)['totals'])"`):

| Metric | Baseline | Negotiating agents | Change |
| --- | --- | --- | --- |
| Meals delivered safely | 13,827 | 16,223 | +17% |
| Servings lost | 3,627 | 1,231 | −66% |
| Money spent on paid drivers | $2,045 | $888 | −57% |
| Runs where agents lost more food | | 0 of 100 | |

The dashboard's **Evidence** button shows the same comparison on 50 runs (seeds 1–50): −55% food lost, +15% meals, −49% cost, never worse.

**Lessons learned (for Devpost).** Testing on random runs surfaced two failures we fixed. (1) A baseline that retried the same closed shelter forever made us look better than we were; we made the baseline fair. (2) The agents trusted an 80%-reliable volunteer with sandwiches that had 10 minutes of margin; he cancelled and the food spoiled. Speed now objects to anything below 90% reliable when the margin is under 20 minutes. A third bug: a nonprofit's van couldn't deliver elsewhere after its own shelter filled up.

## Team split

- **Agents and backend:** `agents.py`, `world.py`, `config.py` (tune scores, thresholds, red lines, LLM prompts)
- **Data and scenarios:** `data/`, `scenarios.py`, `tests/` (make goals clash more; add scenarios)
- **Frontend and pitch:** `static/` (mostly `dashboard.js` and `dashboard.css`), demo script, backup video, Devpost

Each person owns different files, so merges stay clean.

## Next ideas

Give each agent private information it has to share as evidence; LLM agents as the demo default with saved responses as a fallback; city mode (15–20 donations at once with combined trips); ElevenLabs voices for each agent and an AI voice call to the shelter phone; agent memory across donations; AGNTCY integration.
