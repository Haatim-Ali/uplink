# Uplink

**Uplink notices leftover food on its own, and a network of AI agents negotiates where it goes.**

A camera at the business spots surplus at closing time, with no photo or form. Every business, shelter and driver has its own agent: shelters accept, decline or counter-offer ("we'll take 20 of 40"), drivers bid for the pickup, and three coordinator agents (Speed, Cost, Need) negotiate over the offers with no boss. Safety rules in code remove unsafe options before anyone argues, and a real person can answer for a shelter from their phone. When the agents truly can't agree, a plan crosses one agent's red line, or the decision hinges on a fact nobody has confirmed, they stop and ask a person instead of forcing a consensus.

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
- Camera at the business: `python3 camera.py --business campus-cafe` (see below)
- Donation records (SB 1383): http://localhost:5050/records

It runs with **no API key**: vision returns a demo pizza result and the agents use rules-based reasoning. The map needs internet for its tiles.

### Turn on the AI model

```bash
export ANTHROPIC_API_KEY=...      # or OPENAI_API_KEY=... (OPENAI_BASE_URL works for NVIDIA NIM)
python app.py                      # vision now uses the model
LLM_AGENTS=1 python app.py         # agents also propose, vote and explain with the model
```

Optional: `ANTHROPIC_MODEL`, `OPENAI_MODEL`, and `AGENT_MODEL` (a faster model for the agents). Any failed model call falls back to rules, so the demo never hangs on an error. The clock pauses while agents deliberate. Red lines are enforced in code in both modes; the model is told about them but can't override them.

## Camera at the business

```bash
pip3 install ultralytics opencv-python requests   # one time; models download on first run
python3 camera.py --business campus-cafe          # with the server already running
python3 camera.py --business campus-cafe --image test.jpg   # test with a photo
```

Two models, each doing what it's good at:

- **Watch (all day, on the laptop):** a fast detector counts food live, smoothed over ~15 frames so a passing hand doesn't count. By default it's **YOLO-World**, which is told by name to look for 25 foods (pizza, sandwiches, salads, popcorn bags, chips, cookies, bread, fruit...). If it can't load, it falls back to the standard detector, which only knows 10 foods. Labels that are often false alarms need more confidence (the standard model calls snack bags "cake").
- **Identify (once, at closing time):** the snapshot goes to the vision AI model, which names the food, splits it into one donation per food type (safety rules differ) and lists likely allergens. The detector's guess is passed along only as a hint. Without an AI key, the detector's counts are used and allergens are marked unconfirmed, so the agents ask before ruling shelters in or out.

Trigger closing time with **C** in the camera window or **Closing time (camera)** on the dashboard. Video never leaves the laptop. Tune servings per item in the `FOOD` table in `camera.py`.

## Demo script

0. Point the webcam at real leftover food and start `camera.py`. Click **Closing time (camera)**: the camera's donation appears and the network starts negotiating with no one touching anything.
1. A teammate opens the **Shelter** page on their phone and picks a shelter.
2. Pick **Lunch rush** and click **Run scenario**. The debate plays back message by message; objections shake; "Agreed 3 of 3" lands.
3. When the agents pick the teammate's shelter, their phone shows the request. They tap **Take part** (a counter-offer): the donation splits and the rest goes back to the network. Next time they tap **We're full** and the agents renegotiate.
4. Walk the judges through the **Agent network** panel: the business announces, each shelter agent answers (accept, counter-offer, decline), drivers bid, coordinators decide.
5. Press **Driver cancels** and **New pantry joins** to show adaptation. Pop-ups call out each event.
6. Show the three ways the team refuses a bad consensus:
   - **Unacceptable compromise**: two agents want a plan, the third vetoes it. The coordinator box explains why.
   - **Irreconcilable goals**: no plan wins a majority after 3 rounds. A human picks from the agents' top two.
   - **Insufficient evidence**: the agents ask the business "is this free of peanuts?" before committing. Answer with the buttons, or wait and watch them act on what they know.
7. Run **Standoff** to show the agents asking a coordinator to approve an over-budget plan.
8. Run **City mode** (set speed to 4×): 18 donations from 8 businesses, volunteers starting shifts, a no-show, a full shelter and a new pantry. Point out a combined trip, and the food hall moment where Cost wanted to combine trips but Need objected that Grace Kitchen was already getting food, so they compromised.
9. Send a real photo from the Business view on a phone (tick "Not sure about allergens" to trigger the question).
10. Click **Evidence** for the 50-run comparison chart, and open the scripted table for team vs each agent alone.

Click any past negotiation (D1, D2...) and **Replay debate** to walk judges through one decision, including vetoes.

## How it works

| File | What it does |
| --- | --- |
| `world.py` | Simulated city: capability directory, **safety rules**, drivers, clock, events, impact, records, the nearest-shelter **baseline** and the **single-agent** policies |
| `network.py` | **Shelter agents** (accept, counter-offer, decline) and **driver agents** (bid or refuse) |
| `agents.py` | Speed, Cost, Need coordinator agents, their **red lines**, the **negotiation protocol** (rules or LLM) and the **evidence check** |
| `camera.py` | **Camera at the business**: webcam food detection that donates at closing time |
| `scenarios.py` | Scripted scenarios, the comparison of 5 policies (`python scenarios.py`), and a seeded random-scenario generator |
| `vision.py` / `llm.py` | Photo → food details; thin model wrapper (Anthropic, OpenAI, or OpenAI-compatible) |
| `config.py` | Every tuning knob in one place: speeds, safety margin, cost limit, negotiation thresholds |
| `app.py` | Flask server, live clock, planner thread, API |
| `static/dashboard.{html,css,js}` | Dashboard layout, styles and behavior, in separate files |
| `static/business.html`, `shelter.html`, `records.html` | Phone pages for the business and the shelter; SB 1383 records page |
| `tests/test_core.py` | Safety rules, negotiation, adaptation, shelter phone and evidence checks |
| `data/` | Fictional nonprofits, drivers, businesses near the venue |

**The network protocol.** For each donation: the business agent announces it; the directory finds shelters that can safely take it; each shelter agent answers from its own point of view (accept, counter-offer for part of it, or decline, based on its room and daily limits); each driver agent bids on each trip or refuses if it's beyond its range; the coordinators negotiate over the resulting offer × bid plans. If a counter-offer wins, the rest of the food is split off and announced again, so nothing is stranded.

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

**Combined trips (city mode).** If a driver is already heading to the same pickup, the agents can add the new donation to that trip, as long as the shelter passes the safety rules for the new food and the vehicle has room (150 servings). Cost values this because it keeps another driver free; Need can still object if that shelter is already well supplied.

**Contacting shelters.** If someone has a shelter's phone page open, the agents ask before dispatching and hold that driver and that shelter's room while waiting. "We're full" marks the shelter full and triggers a renegotiation; no answer within 8 minutes means they try elsewhere.

**Fallback rules (disclosed, not decision-makers).** In scripted runs nobody is at the keyboard, so a simulated coordinator picks the agents' top-ranked option when asked. In the live demo, if no human answers an escalation before the food has 15 minutes left, the agents' top-ranked option goes. Both are labeled as such in the feed.

## Tests

```bash
python3 tests/test_core.py      # or: python3 -m pytest
```

27 checks: cold food never goes somewhere without a fridge, allergens and capacity are respected, every plan arrives in time, the three agents genuinely disagree, short time forces a decision, cancellations lower reliability and trigger a replan, a new pantry is discoverable, the standoff escalates, the shelter phone flow works, pending requests hold capacity, scenarios are repeatable, the agents never lose more food than the baseline, shelter agents accept, counter-offer and decline correctly, counter-offers split without losing food, drivers refuse trips beyond their range, network messages are logged, camera counts become separate donations by food type, the camera ignores low-confidence false alarms, and the vision model's answer wins over the detector's guess. Run them before every push.

## Results

**The baseline** is what a busy coordinator with a phone list would do: nearest shelter that takes this food type, is open, isn't full and has room, with the nearest free driver, never retrying a shelter that turned the food away. It skips fridge, allergen and timing checks, driver reliability, cost and fairness, and doesn't negotiate.

**All 9 scripted scenarios, team vs each agent alone** (`python scenarios.py`). Full per-scenario tables: [docs/RESULTS.md](docs/RESULTS.md).

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 763 | 934 | 934 | 934 | 934 |
| Servings lost | 171 | 0 | 0 | 0 | 0 |
| Money spent ($) | 186.47 | 259.99 | 99.38 | 200.24 | 228.59 |
| Shelters fed | 17 | 20 | 20 | 22 | 23 |
| Avg minutes to spare (perishable food) | 76 | 73 | 69 | 66 | 68 |
| Asked a human | 0 | 1 | 1 | 1 | 6 |

**How the team's negotiations ended:** consensus 40, unacceptable 4, insufficient evidence 2, majority 1, irreconcilable 1

With shelter and driver agents, the team fed the most shelters (23) and lost no food, but it is no longer the cheapest policy on these scripted cases ($228.59 vs $99.38 for Cost alone). The difference is mostly *Standoff*: Need and Speed wanted to send produce to the pantry that had waited 6 days, Cost vetoed the $35 courier as over its $20 red line, and the scripted stand-in coordinator chose the agents' top-ranked option, which split the food and needed a second paid trip. On the 100 random runs below, the team is still 28% cheaper than the baseline.

**100 random lunch rushes the rules were never tuned on** (`python3 -c "import scenarios; print(scenarios.compare_random(100, 1001)['totals'])"`):

| Metric | Baseline | Agent network | Change |
| --- | --- | --- | --- |
| Meals delivered safely | 13,620 | 16,778 | +23% |
| Servings lost | 3,834 | 676 | −82% |
| Money spent on paid drivers | $2,927 | $2,115 | −28% (−41% per meal) |
| Runs where agents lost more food | | 0 of 100 | |

The dashboard's **Evidence** button shows the same comparison on 50 runs (seeds 1–50): −77% food lost, +22% meals, −14% cost, never worse.

**Lessons learned (for Devpost).** Testing on random runs surfaced two failures we fixed. (1) A baseline that retried the same closed shelter forever made us look better than we were; we made the baseline fair. (2) The agents trusted an 80%-reliable volunteer with sandwiches that had 10 minutes of margin; he cancelled and the food spoiled. Speed now objects to anything below 90% reliable when the margin is under 20 minutes. A third bug: a nonprofit's van couldn't deliver elsewhere after its own shelter filled up. (3) When drivers became agents that refuse trips beyond their range, the baseline was still allowed to send volunteers anywhere; we made it respect the same refusals. Counter-offers were the biggest single gain: food that used to be stranded because no shelter had room for all of it now gets split across shelters.

## Team split

- **Agent network and coordinators:** `network.py`, `agents.py`, `world.py`, `config.py` (shelter and driver behavior, scores, red lines, LLM prompts)
- **Camera:** `camera.py` (tune servings per item and detection with real food)
- **Data and scenarios:** `data/`, `scenarios.py`, `tests/` (make goals clash more; add scenarios)
- **Frontend and pitch:** `static/` (mostly `dashboard.js` and `dashboard.css`), demo script, backup video, Devpost

Each person owns different files, so merges stay clean.

## Next ideas

Give each agent private information it has to share as evidence; LLM agents as the demo default with saved responses as a fallback; ElevenLabs voices for each agent and an AI voice call to the shelter phone; agent memory across donations; AGNTCY integration.
