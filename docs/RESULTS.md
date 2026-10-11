# Results and lessons learned

**The question (from the Cisco challenge):** can independent AI agents make better decisions together than they can individually?

**Short answer: yes, and we can show where and why.** On 100 random scenarios the system had never seen, the negotiating team lost **67% less food than the best agent deciding alone** and **93% less than a simple nearest-shelter baseline**, delivered the most meals and reached the most shelters. It is not the cheapest: the cost-minimizing agent alone spends less, and we say so.

All results are deterministic (rules mode, seeded scenarios) and reproducible with the commands at the end.

## How we tested

Every scenario runs the **same events** under five decision policies:

| Policy | What decides | Safety rules |
| --- | --- | --- |
| Nearest shelter (baseline) | Closest shelter that takes the food, closest free driver; no agents | **No** fridge, allergen, capacity, hours or timing checks |
| Speed alone | The Speed agent picks the plan by itself | Yes |
| Cost alone | The Cost agent picks the plan by itself | Yes |
| Need alone | The Need agent picks the plan by itself | Yes |
| **Team** | Speed, Cost and Need negotiate (proposals, votes, red lines, no boss) | Yes |

Three test sets:

- **Held-out random scenarios** (seeds 1001–1100): 3–6 donations each, driver no-shows, full shelters, new pantries. Never used while building. This is the headline.
- **Development random scenarios** (seeds 1–200): the same generator, used while building.
- **9 scripted scenarios**: hand-written cases, each built to show one behaviour (a full shelter, a deadlock, a veto, missing allergen information, a city-wide rush).

## Headline: together vs alone, on unseen scenarios

100 random scenarios, seeds 1001–1100.

| Policy | Servings lost | Meals delivered | Shelters fed | Paid-driver cost | Asked a human |
| --- | ---: | ---: | ---: | ---: | ---: |
| Nearest shelter | 2,415 | 15,039 | 292 | $719 | 0 |
| Speed alone | 494 | 16,960 | 325 | $2,298 | 10 |
| Cost alone | 610 | 16,844 | 315 | **$374** | 11 |
| Need alone | 843 | 16,611 | 407 | $1,154 | 15 |
| **Team** | **164** | **17,290** | **459** | $704 | 23 |

- **Least food lost:** 67% less than the best single agent (Speed) and 93% less than the baseline.
- **Most meals and most shelters:** 2% more meals than the best single agent; 13% more shelters reached than Need alone, the agent whose whole goal is fairness.
- **Consistent, not lucky:** the team lost the least food, or tied, in **99 of 100** runs. Against the baseline it lost less food in 53 runs, the same in 46, and more in 1.
- **Each agent alone fails on its blind spot.** Speed spends the most on couriers. Cost is cheapest but trusts unreliable volunteers, so more food spoils when they don't show. Need reaches more shelters but accepts slow, risky trips. Negotiation lets each agent veto the others' blind spots.
- **The trade-offs we accept:** the team spends 88% more than Cost alone ($704 vs $374), though about the same as the baseline ($719). And it asks a person more often (23 times in 100 runs, vs 10–15 for single agents), because it refuses to force a bad compromise.

The development seeds (1–200) agree: the team lost 229 servings vs 1,320 for the best single agent (83% less) and 5,086 for the baseline (95% less), and never lost more than the baseline in any of the 200 runs.

## The scripted scenarios: what each behaviour looks like

All 9 scenarios combined:

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Team |
| --- | ---: | ---: | ---: | ---: | ---: |
| Meals delivered safely | 859 | 914 | 934 | 934 | 934 |
| Servings lost | 75 | 20 | 0 | 0 | 0 |
| Money spent | $147.05 | $235.79 | $93.18 | $171.41 | $188.80 |
| Shelters fed | 18 | 20 | 20 | 22 | **23** |
| Asked a human | 0 | 2 | 0 | 0 | 7 |

How the team's 53 decisions ended: **consensus 42**, majority with dissent 5, unacceptable compromise 3, insufficient evidence 2, irreconcilable 1.

These scenarios are small and hand-built, so nearly every policy with the safety rules delivers everything (Speed alone loses 20 servings); they exist to show *behaviours* (a veto, a deadlock, a question to the business), not to rank policies. The random scenarios, with no-shows and scarcity, are where the policies separate.

## The agents as a distributed system

Every agent runs as its own process and is an **AGNTCY A2A agent over NATS** (Cisco's open agent stack). Each step of a donation is one A2A broadcast: to every shelter, to every driver, or to the three negotiators.

| Check (`tests/test_mesh.py`) | Result |
| --- | --- |
| All 9 scenarios, distributed over AGNTCY A2A/NATS vs in-process | Identical metrics and identical negotiations, every scenario |
| Messages | 1,078 A2A messages, 0 failed (all over A2A/NATS) |
| Same over plain HTTP | Identical; 1,711 messages, 0 failed. Broadcasting cut the message count by 37% |
| A shelter agent stopped mid-run | Drops out of the directory, is never consulted, the food is still delivered |
| A stopped agent restarted | Re-registers and is consulted again |
| A negotiator stopped | The negotiation still completes; the same logic stands in, and that is logged |
| Live, 18-donation city scenario | Drivers and a pantry that join mid-run start their own agent processes and are consulted at once |

## What we learned

1. **Safety rules first, negotiation second.** Most of the gap to the naive baseline comes from code that removes unsafe plans before anyone negotiates. Every policy with those rules beats the baseline by a wide margin. We would build the rules first again.

2. **Negotiation pays off under uncertainty, not in easy cases.** In our hand-written scenarios every safe policy delivered everything, so they looked equal. Only randomized scenarios with no-shows and scarcity showed the team losing a third as much food as the best single agent. Lesson: evaluate on stress you didn't design.

3. **Each agent is right about something the others ignore.** Cost alone is cheapest and Need alone is fairest, but each loses more food. The team's advantage is that one agent can stop another's blind spot (Speed vetoes an unreliable driver Cost wanted; Need vetoes a shelter that was just fed).

4. **Without red lines, agents always agree.** Before we gave each agent a veto, every negotiation ended in full agreement, because each agent lowers its bar every round. Real disagreement, and the cases where agreeing would be wrong, only appeared once each agent had something it would not trade away.

5. **Refusing to agree has a cost, and it's worth it.** The team asks a person about once every four random scenarios, more than any single agent. Those are the deadlocks, vetoed majorities and missing facts where a forced decision would have been worse. The fallback rule acts in time if nobody answers.

6. **The protocol is separate from the decisions.** Moving every agent into its own process, then onto AGNTCY A2A over NATS, changed nothing about what the agents decided: identical results in every scenario. Broadcasting also cut the number of messages by a third.

7. **Model-driven agents agreed more readily.** When Claude played the three agents (LLM_AGENTS=1), it compromised sooner than the rules-based agents, showing less of the disagreement this track is about. We demo the rules-based agents and keep the model option; each Claude agent now sees only its own goal's facts and votes against the same per-round bar, so it stays in character.

8. **Fallbacks need deadlines computed from the plan.** Our first "nobody answered" rule waited until 15 minutes before the food spoiled, when every option was already too slow, so food arrived spoiled. It now acts at the last moment an option can still arrive safely.

## Limits

- The city is simulated. The shelters, businesses and menus are real Santa Cruz places (see `data/SOURCES.md`), but their capacities, hours, fridges and needs are made up; the drivers are fictional; travel is straight-line; events are scripted.
- The random generator is ours. Held-out seeds guard against tuning to specific runs, not against a generator that favours our design.
- Results are for the rules-based agents. Model-driven agents use the same protocol and red lines, but their output varies run to run.
- In scripted and random runs, a simulated coordinator answers when the agents ask a human. It picks the agents' top-ranked option, which a real coordinator might not.

## Reproduce

```bash
python scenarios.py                                    # scripted scenarios: every table below
python -c "import scenarios as s; r = s.compare_random(100, first_seed=1001, solo=True); r.pop('runs'); print(r)"   # held-out
python -c "import scenarios as s; r = s.compare_random(200, solo=True); r.pop('runs'); print(r)"                   # development
python tests/test_mesh.py                              # distributed agents over HTTP and AGNTCY A2A/NATS
python tests/test_core.py                              # 39 behaviour checks
```

## Full output of `python scenarios.py`

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 859 | 914 | 934 | 934 | 934 |
| Servings lost | 75 | 20 | 0 | 0 | 0 |
| Money spent ($) | 147.05 | 235.79 | 93.18 | 171.41 | 188.8 |
| Shelters fed | 18 | 20 | 20 | 22 | 23 |
| Avg minutes to spare (perishable food) | 78 | 73 | 71 | 72 | 75 |
| Asked a human | 0 | 2 | 0 | 0 | 7 |

**How the team's negotiations ended:** consensus 42, majority 5, unacceptable 3, insufficient evidence 2, irreconcilable 1

**Lunch rush: four donations, a full shelter and a no-show**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 142 | 142 | 142 | 142 | 142 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 9.36 | 22.56 | 9.36 | 19.18 | 9.77 |
| Shelters fed | 3 | 3 | 3 | 4 | 4 |
| Avg minutes to spare (perishable food) | 77 | 77 | 76 | 75 | 77 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: consensus 5

**Volunteer no-show: two volunteers cancel on short-lived hot food**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 69 | 69 | 69 | 69 | 69 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 18.4 | 23.51 | 9.23 | 25.31 | 10.57 |
| Shelters fed | 3 | 3 | 2 | 3 | 3 |
| Avg minutes to spare (perishable food) | 74 | 75 | 73 | 71 | 75 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: consensus 5

**Standoff: every safe option is expensive, so the agents ask a coordinator**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 120 | 120 | 120 | 120 | 120 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 26.86 | 27.29 | 26.86 | 25.02 | 47.03 |
| Shelters fed | 1 | 1 | 1 | 1 | 2 |
| Avg minutes to spare (perishable food) | 0 | 0 | 0 | 0 | 0 |
| Asked a human | 0 | 0 | 0 | 0 | 2 |

Team outcomes: unacceptable 2

**City mode: 18 donations across Santa Cruz in 45 minutes**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 433 | 413 | 433 | 433 | 433 |
| Servings lost | 0 | 20 | 0 | 0 | 0 |
| Money spent ($) | 64.14 | 101.16 | 47.73 | 82.75 | 86.92 |
| Shelters fed | 7 | 7 | 8 | 7 | 7 |
| Avg minutes to spare (perishable food) | 80 | 79 | 77 | 78 | 82 |
| Asked a human | 0 | 2 | 0 | 0 | 3 |

Team outcomes: consensus 25, majority 4

**New information: a pantry joins the directory mid-run**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 20 | 50 | 50 | 50 | 50 |
| Servings lost | 30 | 0 | 0 | 0 | 0 |
| Money spent ($) | 0.0 | 20.53 | 0.0 | 0.0 | 0.0 |
| Shelters fed | 1 | 1 | 1 | 2 | 2 |
| Avg minutes to spare (perishable food) | 42 | 58 | 58 | 60 | 61 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: consensus 4

**Majority with dissent: Cost is outvoted on a paid courier; its objection stays on record**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 25 | 25 | 25 | 25 | 25 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 14.81 | 14.81 | 0.0 | 0.0 | 15.36 |
| Shelters fed | 1 | 1 | 1 | 1 | 1 |
| Avg minutes to spare (perishable food) | 49 | 49 | 32 | 35 | 48 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: majority 1

**Unacceptable compromise: the majority's plan crosses an agent's red line**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 0 | 25 | 25 | 25 | 25 |
| Servings lost | 25 | 0 | 0 | 0 | 0 |
| Money spent ($) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Shelters fed | 0 | 1 | 1 | 1 | 1 |
| Avg minutes to spare (perishable food) | 0 | 47 | 47 | 45 | 45 |
| Asked a human | 0 | 0 | 0 | 0 | 1 |

Team outcomes: unacceptable 1, consensus 1

**Irreconcilable goals: no plan wins a majority, so a human decides**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 0 | 20 | 20 | 20 | 20 |
| Servings lost | 20 | 0 | 0 | 0 | 0 |
| Money spent ($) | 13.48 | 15.12 | 0.0 | 19.15 | 19.15 |
| Shelters fed | 0 | 1 | 1 | 1 | 1 |
| Avg minutes to spare (perishable food) | 0 | 17 | 6 | 11 | 11 |
| Asked a human | 0 | 0 | 0 | 0 | 1 |

Team outcomes: irreconcilable 1

**Insufficient evidence: agents ask the business instead of guessing**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 50 | 50 | 50 | 50 | 50 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 0.0 | 10.81 | 0.0 | 0.0 | 0.0 |
| Shelters fed | 2 | 2 | 2 | 2 | 2 |
| Avg minutes to spare (perishable food) | 97 | 96 | 95 | 97 | 83 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: insufficient evidence 2, consensus 2

## Photo reading accuracy

17 photos of countable food from Wikimedia Commons (`eval_photos/`, licenses and links in `sources.json`),
each counted by hand. Photos where we couldn't be sure of the true count ourselves (overlapping croissants,
a tiered cupcake stand) were left out. Two full runs with Claude:

| | Run 1 | Run 2 |
| --- | --- | --- |
| Named the right food | 16/17 (94%) | 17/17 (100%) |
| True count inside the model's range | 16/17 (94%) | 16/17 (94%) |
| Count within 10% | 16/17 (94%) | 17/17 (100%) |
| Average counting error | 1% | 1% |
| Average time per photo | 8.8 s | 8.7 s |

The same count came back in both runs for 15 of 17 photos. The two that changed: wrapped burritos
read as "mole tamales" once (count unmatched) and correctly as 3 burritos the other time; a 20-piece
sushi plate came back as 20, then 21.

What this does and doesn't show: on photos where the items can be told apart, counting is close to
exact, and the remaining errors are small run-to-run slips on ambiguous photos. It does not measure
food that has to be estimated rather than counted (a tray of curry, a pan of pasta); there, servings
come from the unit table and the business confirms them.

Re-run: `python scripts/vision_eval.py eval_photos/ eval_results/run.csv`
(per-photo results for both runs are in `eval_results/`).

### Re-reading only when unsure (and big spreads in halves)

`vision.analyze` reads each photo once. Only when that first reading isn't "high" confidence, fails, or
finds 20+ items (`VISION_SPLIT_MIN`) does it read the photo again, up to `VISION_READS` (3) times in total.
The middle reading is the best estimate; the range widens to cover readings that are close; a far-off
reading is treated as an outlier (lower confidence, range unchanged); allergens and "keep cold" are
combined on the safe side. Big spreads are also counted as two halves of the full-size photo, at the same
time as the re-reads.

Measured on the same 17 photos, two runs each:

| | 1 reading | Always 3 readings | Re-read only when unsure |
| --- | --- | --- | --- |
| Misses (true count outside the range or food not named) | 2/34 | 1/34 | both of the single-reading misses would be re-read |
| Model calls per photo | 1 | 3 (5 for big spreads) | 1.65 on average |
| Photos that get extra readings | none | all | 9/34 |
| Time per photo | ~9 s | ~11 s | ~9 s; 35 s for a big spread |

The "re-read only when unsure" numbers come from replaying the decision on the 34 single readings
we already had (no new paid runs), plus two live spot checks: a clear donut box took 1 call
(12, correct, high confidence); a 20-piece sushi plate took 5 calls (best estimate 21, flagged
medium confidence with "please check the count").

`VISION_READS=1` turns re-reading off entirely.
