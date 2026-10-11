# Results and lessons learned

**Question (from the Cisco challenge):** can independent AI agents make better decisions together than they can individually?

**Setup.** 7 scripted scenarios, each run under 5 policies with the same events (see [ARCHITECTURE.md](ARCHITECTURE.md#baselines)):

- **Nearest shelter:** no agents and no safety checks.
- **Speed alone, Cost alone, Need alone:** same safety rules as the team, but one agent decides by itself.
- **Agents together:** the full negotiation.

Rules mode, deterministic. Regenerate with `python scenarios.py` (the tables at the bottom are its output).

## Together vs each agent alone (Sat 7 PM)

The challenge asks: *can independent AI agents make better decisions together than they can individually?*
We ran the same 100 seeded random scenarios (3–6 donations, driver no-shows, full shelters, new pantries)
through the negotiating team, through each agent deciding alone with the same safety rules, and through
the nearest-shelter baseline. Reproduce with `python -c "import scenarios; print(scenarios.compare_random(100, solo=True)['totals'])"`.

| Policy | Servings lost | Meals delivered | Shelters fed | Paid-driver cost |
| --- | ---: | ---: | ---: | ---: |
| Baseline (nearest shelter) | 3,502 | 12,823 | 247 | $2,804 |
| Speed alone | 1,210 | 15,115 | 296 | $3,294 |
| Cost alone | 1,503 | 14,822 | 288 | **$1,372** |
| Need alone | 1,856 | 14,469 | 375 | $2,724 |
| **Team (negotiating)** | **695** | **15,630** | **420** | $2,154 |

- The team loses **43% less food than the best single agent** (Speed) and 63% less than the worst (Need).
- It loses the least food, or ties, in **93 of 100** runs, and delivers the most meals and feeds the most shelters overall.
- **Each agent alone fails on its blind spot.** Speed spends the most. Cost is cheapest but picks unreliable
  volunteers, so more food spoils when they don't show. Need feeds more shelters but takes slow, risky trips.
- **Trade-off we disclose:** Cost alone is cheaper ($1,372 vs $2,154). The team pays more to lose half as much food.
- Against the baseline: 80% less food lost, 22% more meals, 23% lower cost, and never worse in any of the 100 runs.

## Update after adding shelter and driver agents (Sat 1:40 PM)

The findings below were written before the agent network was merged (shelter agents that accept, counter-offer or decline; driver agents that bid or refuse trips beyond their range; counter-offers that split a donation). The tables at the bottom are regenerated on the merged code. **Haatim: please re-check findings 2 and 5 against the new numbers.** What changed:

- **Totals across the 9 scenarios:** the team lost 0 servings and fed the most shelters (23, vs 20–22 for single agents), but it is no longer the cheapest: $228.59 vs $99.38 for Cost alone. Finding 2 ("as cheap as the cost-minimizer") no longer holds on the full set.
- **Why:** mostly *Standoff*. Need and Speed wanted the pantry that had waited 6 days; Cost vetoed the $35 courier (over its $20 red line); the scripted stand-in coordinator took the top-ranked option, which split the food and needed a second paid trip ($72 vs $33 for one trip to the food bank). A real coordinator could choose the single trip.
- **Random runs (100, unseen seeds 1001–1100):** vs the baseline, the network lost 82% less food (676 vs 3,834 servings), delivered 23% more meals, and spent 28% less (41% less per meal). Never worse in any run.
- **Biggest single gain:** counter-offers. Food that used to be stranded because no shelter had room for all of it now gets split across shelters.

## What we found

1. **The safety rules matter most, and we say so.** Nearest shelter lost 105 servings across the scenarios. Every policy with the safety rules lost 0, including a single agent deciding alone. Most of the gap against the simple baseline comes from the rules, not from negotiation.

2. **The team's real advantage is balance: no single agent matched it on everything.** In the three everyday scenarios (lunch rush, volunteer no-show, new pantry):

   | | Money spent | Shelters fed |
   |---|---:|---:|
   | Speed alone | $66.00 | 6 |
   | Cost alone | $20.78 | 6 |
   | Need alone | $40.77 | 9 |
   | **Agents together** | **$20.48** | **9** |

   The team was as cheap as the cost-minimizer *and* fed as many shelters as the need-maximizer. Each single agent was strong on its own goal and weak on the others.

3. **Together, the agents find plans none of them would pick alone.** In *Majority with dissent*, Cost alone and Need alone both used Sam, a 50%-reliable volunteer. Speed alone sent the food to the shelter that needed it less. The team combined Need's shelter (waited 5 days) with Speed's reliable courier. Cost was outvoted, and its objection about the $15.23 is kept on record. (In this run Sam happened to show up, so the gamble would have paid off; the team chose not to take it.)

4. **Asking beats guessing, at a cost in time.** In *Insufficient evidence*, only the team got food to Northside Youth Shelter (waited 5 days). Every single-agent policy treated the unconfirmed allergens as present and quietly sent the food elsewhere. Asking the business cost time: the team's food arrived with 76 minutes to spare on average, vs 94 for each single agent. When the second business never answered, the agents stopped waiting after 15 minutes and acted safely on what they knew.

5. **Refusing a bad consensus costs money and human time, and we think that's correct.** In the two stress scenarios built around conflict, the team asked a human twice, where every single agent just acted. In *Irreconcilable goals* the coordinator chose the $21.96 courier to the food bank that had waited 6 days. That's over Cost's budget, which is exactly why the agents didn't decide it themselves. Across all 7 scenarios the team spent $57.67, nearly 3× Cost alone ($20.78) but half of Speed alone ($115.63), and it fed the most shelters (14 vs 11 for Cost alone).

6. **Without red lines, our agents always agreed.** Before we added vetoes, all 14 negotiations in the original three scenarios ended in 3-of-3 consensus. Each agent's acceptance bar drops every round (90% → 78% → 65% of its best option), so any two goals eventually meet. Real disagreement only appeared when each agent had something it would not trade away. Even now, 17 of 22 decisions are consensus; the other 5 are the cases that matter.

7. **Tradeoffs we accept.** The team had the smallest average safety margin on perishable food (59 minutes vs 61–65 for single agents), because it trades a little time for cost and fairness. Every delivery still arrived at least 5 minutes before the food became unsafe, which the safety rules guarantee.

## Limits

- The world is simulated: fictional shelters and drivers, straight-line routes, scripted events.
- Results are from rules mode. LLM mode uses the same protocol and red lines, but model outputs vary run to run.
- Scenarios 4–7 were designed to produce each kind of disagreement. They show the mechanism works, not how often these situations happen in real life.
- In scripted runs a simulated coordinator stands in for the human (see [fallback rules](ARCHITECTURE.md#fallback-rules-disclosed)).

## Full output of `python scenarios.py` (regenerated on the merged code)

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 763 | 934 | 934 | 934 | 934 |
| Servings lost | 171 | 0 | 0 | 0 | 0 |
| Money spent ($) | 186.47 | 259.99 | 99.38 | 200.24 | 228.59 |
| Shelters fed | 17 | 20 | 20 | 22 | 23 |
| Avg minutes to spare (perishable food) | 76 | 73 | 69 | 66 | 68 |
| Asked a human | 0 | 1 | 1 | 1 | 6 |

**How the team's negotiations ended:** consensus 40, unacceptable 4, insufficient evidence 2, majority 1, irreconcilable 1

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
| Money spent ($) | 14.93 | 14.93 | 14.93 | 15.23 | 15.23 |
| Shelters fed | 1 | 1 | 1 | 1 | 1 |
| Avg minutes to spare (perishable food) | 48 | 48 | 48 | 48 | 48 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: consensus 1

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
