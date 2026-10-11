# Devpost draft: Uplink

Paste each section into the matching Devpost field. Fill in the [bracketed] parts.

---

## Tagline

One photo of leftover food becomes a safe donation, decided by AI agents with competing goals, no boss, and the sense to ask a human when agreeing would be wrong.

## Inspiration

California's SB 1383 requires many food businesses to donate edible surplus food and keep records, yet much of it is still thrown away. Donating is a hassle full of real tradeoffs: the fastest driver costs money, the free volunteer might not show, and the nearest shelter may already have been fed today while another has waited four days. Cisco's challenge asked what happens when AI agents disagree. Food rescue is a problem where they should.

## What it does

- **For a business:** take a photo, video, or say what's left (or pick from your menu). Claude identifies and counts the food. Confirm it, and track the pickup until it's delivered, with the SB 1383 donation record generated automatically.
- **Set in Santa Cruz:** the demo uses real Santa Cruz businesses with items from their real menus (Pizza My Heart, Zoccoli's Deli, Kelly's French Bakery, the Dream Inn, Abbott Square, UCSC dining) and real shelters and food programs (Housing Matters, St. Francis Catholic Kitchen, Grey Bears, the Walnut Avenue center). Their capacities and needs, and the drivers, are simulated.
- **Behind the scenes:** every shelter and driver has its own agent. Shelters accept, take part, or decline; drivers bid or refuse trips beyond their range. Three negotiators with competing goals, **Speed** (fast and reliable), **Cost** (cheap) and **Need** (whoever waited longest), propose plans, vote, and concede over up to three rounds. No agent has the final say.
- **Safety is never negotiated:** code removes every plan that breaks a food-safety rule (fridge, allergens, capacity, hours, time to spoil) before any agent sees it.
- **Consensus is not always right:** each agent has a red line it won't cross. When the agents deadlock, when a majority wants a plan that crosses someone's red line, or when the decision depends on an unconfirmed fact (are there peanuts?), they stop and ask a coordinator or the business, with a "decide by" deadline so the food never spoils waiting.
- **It adapts:** a full shelter, a driver no-show, or a new pantry joining mid-run triggers a re-plan; each agent says whether the news changed its mind; agents that warned about an unreliable driver gain vote weight.
- **You can hear it:** with ElevenLabs, the agents speak the debate, and a dispatcher voice "calls" the chosen shelter; shelters can answer by voice.

## How we built it

- **Agents as services on AGNTCY:** every shelter, driver and negotiator runs as its own process and is an **A2A agent over NATS**, using Cisco Outshift's AGNTCY app-sdk. Each step of a donation is one A2A broadcast (to every shelter, every driver, or the three negotiators). An agent directory with heartbeats lets agents discover each other; a stopped agent drops out and the rest carry on. Every agent has an A2A AgentCard and an OASF record.
- **The negotiation:** each agent scores plans against its own goal, proposes, votes accept/object/veto with a reason, and concedes over three rounds. The shared table only relays messages and counts votes.
- **Vision:** Claude (Anthropic API) names and counts the food and gives a confidence level; our code turns counts into servings, weight and safe time, so the same count always gives the same numbers. An open model (Qwen2.5-VL on an NVIDIA Brev GPU via vLLM) is a backup.
- **Stack:** Python, Flask, AGNTCY app-sdk + A2A + NATS, Claude, ElevenLabs (voices and Scribe), Leaflet, YOLO-World for the counter camera, vanilla HTML/CSS/JS.

## Challenges we ran into

- **Our agents always agreed.** Each agent lowers its bar every round, so every negotiation ended in consensus. Real disagreement only appeared once each agent had a red line it would not trade away.
- **A fallback that spoiled the food.** Our first "nobody answered the coordinator" rule waited until 15 minutes before the food spoiled, when every option already took 25 minutes. It now acts at the last moment an option can still arrive safely.
- **Distributing without changing decisions.** Moving every agent into its own process, then onto A2A over NATS, had to give exactly the same decisions. We split each agent's logic into its own steps, sent each agent the facts it needs, and wrote a test that replays every scenario both ways.
- **Claude agents that agreed too easily.** With Claude speaking for each agent, Cost would cite the shelter's 5-day wait and accept a paid courier in round 1. Each agent now sees only the facts it cares about, and votes against a bar that drops each round (90%, 78%, 65% of its best option); if Claude accepts something far below the bar, the rules overrule that vote.
- **Honest evidence.** In our hand-written scenarios every safe policy looked equal. Only randomized scenarios with no-shows and scarcity showed where negotiation helps.

## Accomplishments that we're proud of

- On **100 random scenarios the system had never seen**, the negotiating team lost **67% less food than the best agent working alone** and **93% less than a nearest-shelter baseline**, delivered the most meals and reached the most shelters, and lost the least food (or tied) in 99 of 100 runs.
- The distributed agents on AGNTCY make **identical decisions** to the in-process version in every scenario (about 1,080 A2A messages, 0 failed), and keep working when an agent is stopped live.
- Two products from one system: a customer site a café manager can use in a minute (menu, voice or photo/video), and an ops dashboard that shows every message, vote and veto live, as each agent says it.

## What we learned

- Safety rules in code do most of the work against a naive approach; negotiation earns its keep under uncertainty (no-shows, scarcity).
- Each agent is right about something the others ignore. The team's value is that one agent can veto another's blind spot.
- Refusing to agree has a cost (the team asks a person about once every four scenarios), and it's the right cost.
- The protocol is separate from the decisions: the same agents decide the same way in one process, over HTTP, or over A2A/NATS.
- Model-driven agents cave unless you design against it. Our Claude agents first agreed in round 1 and argued each other's goals. Giving each agent only its own facts, and a numeric bar to vote against, turned that into real three-round negotiations that can end in a majority with dissent on record.

## What's next for Uplink

Real shelter and driver onboarding, a real phone line (outbound calls with ElevenLabs), routing on real roads, pushing our OASF records to a shared AGNTCY Directory, and an ablation study measuring what each mechanism (red lines, adaptation, concession) contributes.

## Built with

python · flask · agntcy · a2a · nats · anthropic-claude · elevenlabs · leaflet · yolo-world · nvidia-brev · vllm · html · css · javascript

## Links

- Code: [GitHub repo URL]
- Demo video: [video URL]
- How It Works guide (PDF): `docs/how-it-works/Uplink-How-It-Works.pdf`
- Results and lessons: `docs/RESULTS.md` · Architecture: `docs/ARCHITECTURE.md` · AGNTCY: `docs/AGNTCY.md`

## Submission checklist (Cisco's "what to submit")

- [ ] Working demonstration: live, plus the backup video
- [ ] Architecture overview: the diagram in the guide PDF / `docs/ARCHITECTURE.md`
- [ ] Technical implementation details: this page + `docs/AGNTCY.md`
- [ ] Results and lessons learned: `docs/RESULTS.md`
