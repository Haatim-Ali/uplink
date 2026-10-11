# Results and lessons learned

**The question (from the Cisco challenge):** can independent AI agents make better decisions together than they can individually?

**Short answer: yes, and we can show where and why.** On 100 random scenarios the system had never seen, the negotiating team lost **49% less food than the best agent deciding alone** and **82% less than a simple nearest-shelter baseline**, delivered the most meals and reached the most shelters. It is not the cheapest: the cost-minimizing agent alone spends less, and we say so.

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
| Nearest shelter | 3,834 | 13,620 | 254 | $2,927 | 0 |
| Speed alone | 1,336 | 16,118 | 309 | $3,228 | 36 |
| Cost alone | 1,726 | 15,728 | 292 | **$1,305** | 46 |
| Need alone | 1,459 | 15,995 | 386 | $2,581 | 42 |
| **Team** | **676** | **16,778** | **440** | $2,115 | 101 |

- **Least food lost:** 49% less than the best single agent (Speed) and 82% less than the baseline.
- **Most meals and most shelters:** 4% more meals than the best single agent; 14% more shelters reached than Need alone, the agent whose whole goal is fairness.
- **Consistent, not lucky:** the team lost the least food, or tied, in **95 of 100** runs, and was never worse than the baseline (less food lost in 65 runs, the same in 35, more in 0).
- **Each agent alone fails on its blind spot.** Speed spends the most on couriers. Cost is cheapest but trusts unreliable volunteers, so more food spoils when they don't show. Need reaches more shelters but accepts slow, risky trips. Negotiation lets each agent veto the others' blind spots.
- **The trade-offs we accept:** the team spends 62% more than Cost alone ($2,115 vs $1,305), though 28% less than the baseline. And it asks a person about once per scenario (101 times in 100 runs, vs 36–46 for single agents), because it refuses to force a bad compromise.

The development seeds (1–200) agree: the team lost 1,570 servings vs 2,887 for the best single agent (46% less) and 7,212 for the baseline (78% less). There, it lost more than the baseline in 1 run of 200.

## The scripted scenarios: what each behaviour looks like

All 9 scenarios combined:

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Team |
| --- | ---: | ---: | ---: | ---: | ---: |
| Meals delivered safely | 763 | 934 | 934 | 934 | 934 |
| Servings lost | 171 | 0 | 0 | 0 | 0 |
| Money spent | $186.47 | $259.99 | $84.45 | $185.01 | $228.59 |
| Shelters fed | 17 | 20 | 20 | 22 | **23** |
| Asked a human | 0 | 1 | 1 | 1 | 6 |

How the team's 48 decisions ended: **consensus 39**, unacceptable compromise 4, majority with dissent 2, insufficient evidence 2, irreconcilable 1.

These scenarios are small and hand-built, so every policy with the safety rules delivers everything; they exist to show *behaviours* (a veto, a deadlock, a question to the business), not to rank policies. The random scenarios, with no-shows and scarcity, are where the policies separate.

## The agents as a distributed system

Every agent runs as its own process and is an **AGNTCY A2A agent over NATS** (Cisco's open agent stack). Each step of a donation is one A2A broadcast: to every shelter, to every driver, or to the three negotiators.

| Check (`tests/test_mesh.py`) | Result |
| --- | --- |
| All 9 scenarios, distributed over AGNTCY A2A/NATS vs in-process | Identical metrics and identical negotiations, every scenario |
| Messages | 1,107 A2A messages, 0 failed (all over A2A/NATS) |
| Same over plain HTTP | Identical; 1,727 messages, 0 failed. Broadcasting cut the message count by 36% |
| A shelter agent stopped mid-run | Drops out of the directory, is never consulted, the food is still delivered |
| A stopped agent restarted | Re-registers and is consulted again |
| A negotiator stopped | The negotiation still completes; the same logic stands in, and that is logged |
| Live, 18-donation city scenario | 21 agent processes (including ones that joined mid-run), 512 A2A messages, 0 failed, about 5 ms per reply |

## What we learned

1. **Safety rules first, negotiation second.** Most of the gap to the naive baseline comes from code that removes unsafe plans before anyone negotiates. Every policy with those rules beats the baseline by a wide margin. We would build the rules first again.

2. **Negotiation pays off under uncertainty, not in easy cases.** In our hand-written scenarios every safe policy delivered everything, so they looked equal. Only randomized scenarios with no-shows and scarcity showed the team losing half as much food as any single agent. Lesson: evaluate on stress you didn't design.

3. **Each agent is right about something the others ignore.** Cost alone is cheapest and Need alone is fairest, but each loses more food. The team's advantage is that one agent can stop another's blind spot (Speed vetoes an unreliable driver Cost wanted; Need vetoes a shelter that was just fed).

4. **Without red lines, agents always agree.** Before we gave each agent a veto, every negotiation ended in full agreement, because each agent lowers its bar every round. Real disagreement, and the cases where agreeing would be wrong, only appeared once each agent had something it would not trade away.

5. **Refusing to agree has a cost, and it's worth it.** The team asks a person about once per scenario. Those are the deadlocks, vetoed majorities and missing facts where a forced decision would have been worse. The fallback rule acts in time if nobody answers.

6. **The protocol is separate from the decisions.** Moving every agent into its own process, then onto AGNTCY A2A over NATS, changed nothing about what the agents decided: identical results in every scenario. Broadcasting also cut the number of messages by a third.

7. **Model-driven agents agreed more readily.** When Claude played the three agents (LLM_AGENTS=1), it compromised sooner than the rules-based agents, showing less of the disagreement this track is about. We demo the rules-based agents and keep the model option.

8. **Fallbacks need deadlines computed from the plan.** Our first "nobody answered" rule waited until 15 minutes before the food spoiled, when every option was already too slow, so food arrived spoiled. It now acts at the last moment an option can still arrive safely.

## Limits

- The city is simulated: fictional shelters and drivers, straight-line travel, scripted events.
- The random generator is ours. Held-out seeds guard against tuning to specific runs, not against a generator that favours our design.
- Results are for the rules-based agents. Model-driven agents use the same protocol and red lines, but their output varies run to run.
- In scripted and random runs, a simulated coordinator answers when the agents ask a human. It picks the agents' top-ranked option, which a real coordinator might not.

## Reproduce

```bash
python scenarios.py                                    # scripted scenarios: every table below
python -c "import scenarios as s; r = s.compare_random(100, first_seed=1001, solo=True); r.pop('runs'); print(r)"   # held-out
python -c "import scenarios as s; r = s.compare_random(200, solo=True); r.pop('runs'); print(r)"                   # development
python tests/test_mesh.py                              # distributed agents over HTTP and AGNTCY A2A/NATS
python tests/test_core.py                              # 38 behaviour checks
```

## Full output of `python scenarios.py`

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 763 | 934 | 934 | 934 | 934 |
| Servings lost | 171 | 0 | 0 | 0 | 0 |
| Money spent ($) | 186.47 | 259.99 | 84.45 | 185.01 | 228.59 |
| Shelters fed | 17 | 20 | 20 | 22 | 23 |
| Avg minutes to spare (perishable food) | 76 | 73 | 69 | 66 | 68 |
| Asked a human | 0 | 1 | 1 | 1 | 6 |

**How the team's negotiations ended:** consensus 39, unacceptable 4, majority 2, insufficient evidence 2, irreconcilable 1

**Lunch rush: four donations, a full shelter and a no-show**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 102 | 142 | 142 | 142 | 142 |
| Servings lost | 40 | 0 | 0 | 0 | 0 |
| Money spent ($) | 8.06 | 21.29 | 11.23 | 14.69 | 12.97 |
| Shelters fed | 3 | 3 | 3 | 4 | 4 |
| Avg minutes to spare (perishable food) | 71 | 71 | 68 | 72 | 67 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: consensus 5

**Volunteer no-show: two volunteers cancel on short-lived hot food**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 49 | 69 | 69 | 69 | 69 |
| Servings lost | 20 | 0 | 0 | 0 | 0 |
| Money spent ($) | 21.98 | 23.8 | 9.55 | 29.84 | 9.55 |
| Shelters fed | 2 | 2 | 2 | 3 | 3 |
| Avg minutes to spare (perishable food) | 76 | 72 | 69 | 66 | 69 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: consensus 4

**Standoff: every safe option is expensive, so the agents ask a coordinator**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 120 | 120 | 120 | 120 | 120 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 32.55 | 32.55 | 17.55 | 15.04 | 72.4 |
| Shelters fed | 1 | 1 | 1 | 1 | 2 |
| Avg minutes to spare (perishable food) | 0 | 0 | 0 | 0 | 0 |
| Asked a human | 0 | 0 | 0 | 0 | 2 |

Team outcomes: unacceptable 2

**City mode: 18 donations across Santa Clara in 45 minutes**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 367 | 433 | 433 | 433 | 433 |
| Servings lost | 66 | 0 | 0 | 0 | 0 |
| Money spent ($) | 96.02 | 111.51 | 46.12 | 103.48 | 96.48 |
| Shelters fed | 8 | 8 | 8 | 7 | 7 |
| Avg minutes to spare (perishable food) | 78 | 79 | 76 | 71 | 76 |
| Asked a human | 0 | 1 | 1 | 1 | 2 |

Team outcomes: consensus 22, majority 1, unacceptable 1

**New information: a pantry joins the directory mid-run**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 50 | 50 | 50 | 50 | 50 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 0.0 | 20.91 | 0.0 | 0.0 | 0.0 |
| Shelters fed | 1 | 1 | 1 | 2 | 2 |
| Avg minutes to spare (perishable food) | 62 | 60 | 58 | 55 | 56 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: consensus 5

**Majority with dissent: Cost is outvoted on a paid courier; its objection stays on record**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 25 | 25 | 25 | 25 | 25 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 14.93 | 14.93 | 0.0 | 0.0 | 15.23 |
| Shelters fed | 1 | 1 | 1 | 1 | 1 |
| Avg minutes to spare (perishable food) | 48 | 48 | 35 | 36 | 48 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: majority 1

**Unacceptable compromise: the majority's plan crosses an agent's red line**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 0 | 25 | 25 | 25 | 25 |
| Servings lost | 25 | 0 | 0 | 0 | 0 |
| Money spent ($) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Shelters fed | 0 | 1 | 1 | 1 | 1 |
| Avg minutes to spare (perishable food) | 0 | 33 | 35 | 33 | 33 |
| Asked a human | 0 | 0 | 0 | 0 | 1 |

Team outcomes: unacceptable 1, consensus 1

**Irreconcilable goals: no plan wins a majority, so a human decides**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 0 | 20 | 20 | 20 | 20 |
| Servings lost | 20 | 0 | 0 | 0 | 0 |
| Money spent ($) | 12.93 | 13.79 | 0.0 | 21.96 | 21.96 |
| Shelters fed | 0 | 1 | 1 | 1 | 1 |
| Avg minutes to spare (perishable food) | 0 | 22 | 10 | 10 | 10 |
| Asked a human | 0 | 0 | 0 | 0 | 1 |

Team outcomes: irreconcilable 1

**Insufficient evidence: agents ask the business instead of guessing**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 50 | 50 | 50 | 50 | 50 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 0.0 | 21.21 | 0.0 | 0.0 | 0.0 |
| Shelters fed | 1 | 2 | 2 | 2 | 2 |
| Avg minutes to spare (perishable food) | 98 | 94 | 94 | 94 | 76 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: insufficient evidence 2, consensus 2

