# Devpost: Uplink

Paste each section into the matching Devpost field (Devpost accepts this Markdown). Fill in the [bracketed] parts.
Every number here is reproducible from the repo: `docs/RESULTS.md` has the commands.

---

## Name

Uplink

## Tagline (Devpost's short description)

AI agents with competing goals argue over where tonight's leftover food should go, call the shelter out loud, and ask a human when agreeing would be wrong.

## Thumbnail / gallery suggestions

1. `/ops` mid-debate: the Negotiation panel with the three agents' cards beside the Agent network graph lighting up
2. The Phone line: the dispatcher agent on a call with the shelter agent (ElevenLabs voices)
3. Customer site: the **Say it** tab ("we've got two trays of pasta and a dozen bagels") turned into a menu order
4. A "Majority 2 of 3 (Cost disagrees, kept on record)" result
5. The Evidence page: team vs each agent alone

---

## Inspiration

> **Food rescue is a problem where AI agents *should* disagree.**

California's SB 1383 requires many food businesses to donate edible surplus food and keep records of it, yet most of that food is still thrown away. The reason is not that people don't care. Donating at 9 PM is a pile of tradeoffs nobody has time for: the fastest courier costs money, the free volunteer might not show, the closest shelter already got food today while another has waited five days, and pasta has two hours before it isn't safe.

Cisco's challenge asked *what happens when AI agents disagree?* We built the system where they have to.

---

## What it does

Uplink has two sides: a **customer site** a café manager can use in under a minute, and an **ops dashboard** that shows every message, vote and veto between the agents, live.

### 1. The business says what's left: three ways, no typing

| Way | What happens |
| --- | --- |
| **Say it** (ElevenLabs Scribe) | Tap the mic: "we've got two pepperoni pizzas, a dozen cookies and five bananas." Scribe transcribes it, Claude maps it onto the business's own menu, and the quantities and allergens fill in. |
| **Photo or video** (Claude vision) | Snap a photo or pan a short video over the leftovers. Claude names and counts the food; a video becomes four frames so nothing is counted twice. Items on the menu bring their known allergens. |
| **Menu** | Tap items from the business's menu. Something not on it? Add it once and it's there next time. |

They confirm, and track the pickup to delivery. The SB 1383 donation record is generated automatically.

### 2. Three agents argue over where it goes

Every shelter and driver has its own agent. Shelters accept, take part, or decline; drivers bid, or refuse trips beyond their range. Then three negotiators with **competing goals** decide, with **no boss**:

| Agent | Cares only about | Red line it won't cross |
| --- | --- | --- |
| **Speed** | arrival time and driver reliability | under 10 min to spare, or a driver under 50% reliable |
| **Cost** | what the trip costs | over $20 for one donation |
| **Need** | whoever has waited longest | feeding a shelter that already ate today while another waits |

They propose, vote with a reason, object or veto, and revise, over up to three rounds. Each round the bar to accept drops (90%, 78%, then 65% of their own best option), so they give ground slowly instead of folding. From our *Majority with dissent* demo (25 servings of pasta from Jack O'Neill Restaurant, Dream Inn, at 6 PM):

> **Speed:** Proposes Salvation Army via Rapid Courier A (paid). "Arrives in 11 min with 49 min to spare (95% reliable)."
> **Cost:** Proposes the free volunteer, Sam. "Costs nothing."
> **Need:** Proposes Walnut Avenue Family & Women's Center. "It has waited 5 days for food and has room for 50 more servings. Which shelter matters to me, not which driver."
> **Speed, objecting to Sam:** "Only 50% reliable and there's just 35 min of margin; a no-show would spoil this food."
> **Round 3:** Speed and Cost each move toward Need's shelter, from opposite sides.
> **Result:** Walnut Avenue via Rapid Courier A, **Majority 2 of 3 (Cost disagrees, kept on record)**: "$15.36 when a volunteer route costs $0.00 and is also safe."

**Consensus is not always right.** A negotiation can end six ways: consensus, majority with dissent on record, acting fast when food is about to spoil, or stopping to ask a person because the only compromise crosses someone's red line, the goals are truly irreconcilable, or the decision depends on an unconfirmed fact (*are there peanuts in that?*). A person gets a "decide by" deadline so the food never spoils waiting.

**Safety is never negotiated.** Code removes every plan that breaks a food-safety rule (fridge, allergens, capacity, hours, time to spoil) before any agent sees it.

### 3. You can hear them: ElevenLabs

- **The debate, out loud.** Speed, Cost and Need each speak their lines in their own ElevenLabs voice (Flash v2.5) as the debate plays.
- **The phone call.** Once they agree, a **dispatcher agent calls the shelter agent**. Two voices, ringing, a live transcript: "Hi Walnut Avenue Family & Women's Center, this is the Uplink dispatcher. Jack O'Neill Restaurant has 25 servings of pasta trays… can you take it?" The shelter's answer is its agent's real reply. The driver sets off on the map only after the call ends.
- **Voice in, too.** Businesses donate by voice, and shelter staff can answer a request by speaking on the shelter's phone page; ElevenLabs Scribe turns both into text.

### 4. It adapts when the world changes

A shelter says it's full, a driver cancels, a new pantry joins mid-run: the agents re-plan, and each says whether the news changed its mind ("That changes my pick…" / "Still Walnut Avenue…"). An agent that warned about an unreliable driver who then no-showed **gains vote weight**.

---

## How we built it

- **Every agent is its own service, on AGNTCY.** 16 agents (7 shelters, 6 drivers, 3 negotiators), each in its own process, each an **A2A agent over NATS** using Cisco Outshift's AGNTCY app-sdk. Each step of a donation is one A2A broadcast, to every shelter, every driver or the three negotiators. An agent directory with heartbeats lets agents find each other; a stopped agent drops out and the rest carry on. Every agent publishes an A2A AgentCard and an **OASF record** (served at `/agntcy/records`).
- **The negotiation table only relays.** It passes messages and counts votes; it never picks a plan.
- **Claude (Anthropic API)** does four jobs: speaks for each negotiator (each sees *only* the facts its goal cares about, and votes against a numeric bar), reads photos and videos of food, turns a spoken sentence into a menu order, and falls back to deterministic rules if a call fails or times out, so the demo never stalls.
- **ElevenLabs:** Flash v2.5 text-to-speech with a distinct voice per agent, plus Scribe speech-to-text for voice donations and spoken shelter answers.
- **Live by design.** The dashboard streams each proposal and objection the moment an agent says it, with who's still thinking. The simulated clock pauses while agents deliberate, so no food-safety time is lost to model latency.
- **Stack:** Python, Flask, AGNTCY app-sdk + A2A + NATS, Claude, ElevenLabs, Leaflet, YOLO-World for an optional counter camera, Qwen2.5-VL on an NVIDIA Brev GPU as a backup vision model, vanilla HTML/CSS/JS. 56 automated tests.

---

## Challenges we ran into

- **Our agents always agreed.** With rules alone, every agent lowered its bar each round and every negotiation ended in consensus. Real disagreement only appeared once each agent had a red line it would not trade away.
- **Then our Claude agents agreed even faster.** With Claude speaking for each agent, Cost would cite the shelter's 5-day wait and accept a paid courier in round 1; Speed argued about price. **Fix:** each agent now sees only the facts it cares about, votes against a bar that drops each round, and if Claude accepts something far below the bar, the rules overrule that vote. Result: real three-round negotiations that can end in a majority with dissent on record.
- **A fallback that spoiled the food.** Our first "nobody answered the coordinator" rule waited until 15 minutes before spoilage, when every option already needed 25. It now acts at the last moment an option can still arrive safely.
- **Distributing without changing a single decision.** Moving every agent into its own process, then onto A2A over NATS, had to give exactly the same decisions. A test replays all 9 scenarios both ways: identical, 1,107 A2A messages, 0 failed.
- **Model latency on stage.** A full Claude debate takes several seconds. Instead of hiding it, we stream it: the audience watches each agent speak while the next one is still thinking.

---

## Accomplishments that we're proud of

- On **100 random scenarios the system had never seen**, the negotiating team lost **82% less food than a nearest-shelter baseline** and **49% less than the best agent working alone**. It lost the least food (or tied) in **95 of 100** runs, reached **440 shelters vs 386** for the fairness agent alone, and was never worse than the baseline in any run.
- **Each agent alone fails on its blind spot**: Speed overspends on couriers, Cost trusts volunteers who don't show, Need accepts risky trips. Together they veto each other's blind spots.
- We disclose the cost: the team spends more than Cost alone ($2,115 vs $1,305), though 28% less than the baseline, and asks a person about once per scenario, because it refuses to force a bad compromise.
- **16 agents on AGNTCY** make identical decisions to the in-process version, and keep working when an agent is stopped live.
- A customer flow a café manager can finish **by voice in one sentence**.

---

## What we learned

> **Agreement is cheap. A good decision sometimes needs a dissent on the record, or a human.**

- Safety rules in code do most of the work against a naive approach; negotiation earns its keep under uncertainty: no-shows, scarcity, unconfirmed allergens.
- LLM agents cave unless you design against it. Giving each one only its own facts, and a number to vote against, kept them in character.
- Each agent is right about something the others ignore. The team's value is that one can veto another's blind spot.
- The protocol is separate from the decisions: the same agents decide the same way in one process, over HTTP, or over A2A/NATS.

---

## What's next for Uplink

- Real phone calls: the dispatcher agent dialing shelters with ElevenLabs voices, and shelters answering by phone.
- Onboarding real shelters and drivers in Santa Cruz, with routing on real roads.
- Publishing our OASF records to a shared AGNTCY Directory so other food-rescue agents can discover ours.
- An ablation study measuring what each mechanism (red lines, concession, adaptive vote weight) contributes.

---

## Built with

python · flask · agntcy · a2a · nats · anthropic-claude · elevenlabs · leaflet · yolo-world · nvidia-brev · vllm · html · css · javascript

## Links

- Code: https://github.com/saraxjain/uplink
- Demo video: [video URL]
- How it works (PDF): `docs/how-it-works/Uplink-How-It-Works.pdf`
- Results and lessons: `docs/RESULTS.md` · Architecture: `docs/ARCHITECTURE.md` · AGNTCY: `docs/AGNTCY.md`

## Submission checklist (Cisco's "what to submit")

- [ ] Working demonstration: live, plus the backup video
- [ ] Architecture overview: the guide PDF / `docs/ARCHITECTURE.md`
- [ ] Technical implementation details: this page + `docs/AGNTCY.md`
- [ ] Results and lessons learned: `docs/RESULTS.md`
- [ ] Opt in to **Best Use of ElevenLabs** and the **Cisco** track on Devpost
