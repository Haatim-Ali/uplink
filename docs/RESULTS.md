# Results and lessons learned

**Question (from the Cisco challenge):** can independent AI agents make better decisions together than they can individually?

**Setup.** 7 scripted scenarios, each run under 5 policies with the same events (see [ARCHITECTURE.md](ARCHITECTURE.md#baselines)):

- **Nearest shelter:** no agents and no safety checks.
- **Speed alone, Cost alone, Need alone:** same safety rules as the team, but one agent decides by itself.
- **Agents together:** the full negotiation.

Rules mode, deterministic. Regenerate with `python scenarios.py` (the tables at the bottom are its output).

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

## Full output of `python scenarios.py`

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 276 | 381 | 381 | 381 | 381 |
| Servings lost | 105 | 0 | 0 | 0 | 0 |
| Money spent ($) | 57.9 | 115.63 | 20.78 | 62.73 | 57.67 |
| Shelters fed | 7 | 10 | 11 | 14 | 14 |
| Avg minutes to spare (perishable food) | 74 | 65 | 61 | 61 | 59 |
| Asked a human | 0 | 0 | 0 | 0 | 2 |

**How the team's negotiations ended:** consensus 17, insufficient evidence 2, majority 1, unacceptable 1, irreconcilable 1

**Lunch rush: four donations, a full shelter and a no-show**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 102 | 142 | 142 | 142 | 142 |
| Servings lost | 40 | 0 | 0 | 0 | 0 |
| Money spent ($) | 8.06 | 21.29 | 11.23 | 10.93 | 10.93 |
| Shelters fed | 2 | 3 | 3 | 4 | 4 |
| Avg minutes to spare (perishable food) | 74 | 71 | 68 | 71 | 68 |
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

**New information: a pantry joins the directory mid-run**

| Metric | Nearest shelter | Speed alone | Cost alone | Need alone | Agents together |
|---|---:|---:|---:|---:|---:|
| Meals delivered safely | 50 | 50 | 50 | 50 | 50 |
| Servings lost | 0 | 0 | 0 | 0 | 0 |
| Money spent ($) | 0.0 | 20.91 | 0.0 | 0.0 | 0.0 |
| Shelters fed | 1 | 1 | 1 | 2 | 2 |
| Avg minutes to spare (perishable food) | 62 | 60 | 58 | 55 | 57 |
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
| Money spent ($) | 0.0 | 20.91 | 0.0 | 0.0 | 0.0 |
| Shelters fed | 1 | 1 | 2 | 2 | 2 |
| Avg minutes to spare (perishable food) | 98 | 94 | 94 | 94 | 76 |
| Asked a human | 0 | 0 | 0 | 0 | 0 |

Team outcomes: insufficient evidence 2, consensus 2

