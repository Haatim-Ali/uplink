# Demo day

Devpost closes **1:30 PM Sunday** (late submissions aren't judged). **Submit by 12:30.** Awards 5:15 PM.

The story in one line: *a business says what's left, three AI agents with competing goals argue over where it goes, the dispatcher calls the shelter out loud, and the driver sets off.*

---

## 1. Set up the demo laptop (once)

Keep the code **outside iCloud** (not on the Desktop or in Documents): iCloud locks git files and makes `git pull` hang.

```bash
cd ~ && git clone https://github.com/saraxjain/uplink && cd uplink     # later: cd ~/uplink && git pull
pip3 install -r requirements.txt
pip3 install -r requirements-agntcy.txt     # AGNTCY app-sdk
brew install nats-server                    # the app starts NATS and the 16 agents for you
```

`.env` in the `uplink` folder (never commit it, never show it on screen):

```
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=...
LLM_AGENTS=1                  # Claude speaks for each agent
AGENT_MODEL=claude-haiku-5-5  # fast model for agent turns (also the default)
```

Start it:

```bash
cd ~/uplink && PORT=5050 python3 app.py
```

The first lines must say:

- `Agent network: 16 agents, each its own process, talking over AGNTCY A2A over NATS`
- `Claude: Claude key OK`
- `Agents: LLM · Vision: anthropic · Voice: ElevenLabs`

---

## 2. Five-minute check before you present

Open http://localhost:5050/ops and hard-refresh (Cmd+Shift+R).

- [ ] Agent network badge: **AGNTCY · A2A over NATS · 16 agent processes**
- [ ] Demo controls → **Voices** on, laptop volume up
- [ ] Run **Majority with dissent**: the debate streams in, ends "Majority 2 of 3 (Cost disagrees, kept on record)", the dispatcher calls, then the driver moves on the map
- [ ] Customer site (http://localhost:5050) → Schedule a pickup → **Say it**: the mic works (allow microphone access)
- [ ] **Photo / video**: one real photo of food reads correctly
- [ ] Close other tabs and notifications (Do Not Disturb on)

### If something goes wrong

| Problem | Fix |
| --- | --- |
| "Address already in use" | `lsof -ti :5050 \| xargs kill`, then start again |
| `git pull` hangs or "index.lock" | `rm -f .git/*.lock`, then pull again (and move the folder out of iCloud) |
| "Claude key rejected" | check `.env`: the key starts `sk-ant-` (one s) |
| A debate stalls | wait: Claude falls back to the rules after 20 s on its own |
| AGNTCY/NATS trouble on stage | `MESH=0 PORT=5050 python3 app.py`: same decisions, one process |
| No sound | Demo controls → Voices; check the laptop output device |

---

## 3. The 3-minute demo

Two people works best: one drives the laptop, one talks.

**1. Problem (20 s).** "California requires many food businesses to donate edible leftovers, but at closing time donating is a pile of tradeoffs: the fast courier costs money, the free volunteer might not show, and the closest shelter already ate today while another has waited five days."

**2. The business side (35 s).** Customer site → Schedule a pickup.
- **Say it:** tap the mic and say *"we've got two pepperoni pizzas, a dozen cookies and five bananas."* ElevenLabs Scribe transcribes it; Claude maps it onto the café's menu with allergens.
- Or **Photo / video:** pan the phone over real food; Claude counts it.
- Confirm. "That's all a café manager does. Now let's see what happens behind the scenes."

**3. The agents argue (60 s).** Switch to `/ops` (already open), Demo controls → **Majority with dissent** → Run. Voices on.
- Point at the empty Negotiation panel first: "Three agents, no boss. **Speed** cares about getting there reliably, **Cost** about money, **Need** about whoever has waited longest. Each has a red line it won't cross."
- As lines stream in: "Speed wants the reliable paid courier. Cost wants the free volunteer. Need wants the shelter that has waited five days. Speed objects to the volunteer: 50% reliable, a no-show would spoil the food."
- Point at the **Agent network** graph: "Every one of these is its own process, talking over Cisco's AGNTCY A2A protocol on NATS. The shelters answered, the drivers bid, and now the coordinators are voting."
- Result: "Round 3, Speed and Cost both move toward Need's shelter. Majority two of three, and **Cost's objection stays on the record**. Agreement isn't forced."

**4. The phone call (20 s).** Let the **Phone line** play: the dispatcher agent calls the shelter agent in ElevenLabs voices. "Only after the call does the driver set off." Scroll down to the map as it starts moving.

**5. When they can't agree (25 s).** Run **Irreconcilable goals**: "Sometimes no compromise is acceptable. Instead of forcing one, they ask a person, with a decide-by deadline so the food never spoils waiting." Optional: Demo controls → **Shelter says full** and watch them re-plan, each saying whether it changed its mind.

**6. Evidence (20 s).** Evidence tab: "On 100 scenarios it had never seen, the team lost **82% less food than the simple approach** and **49% less than the best agent working alone**, and lost the least food in 95 of 100. Each agent alone fails on its blind spot; together they veto each other's."

**7. Close (10 s).** "Uplink: agents that disagree out loud, never compromise on safety, and ask a human when agreeing would be wrong."

---

## 4. What we improved during the hackathon (good for Q&A and the video)

| Before | After |
| --- | --- |
| Every negotiation ended in round-1 consensus | Red lines and a dropping acceptance bar: real 3-round debates, majority with dissent on record |
| Claude agents caved and argued each other's goals | Each agent sees only its own facts and votes against a numeric bar; rules overrule a far-below-bar accept |
| Agents ran inside one program | 16 agents, each its own process, on AGNTCY A2A over NATS; identical decisions, 0 failed messages |
| One way to donate: a photo | Say it (ElevenLabs Scribe + Claude), photo, video, or tap the menu |
| The debate appeared all at once at the end | Streams live as each agent speaks; the clock waits so no food-safety time is lost |
| Silent decisions | ElevenLabs voices for each agent, plus a dispatcher-to-shelter phone call |
| The map raced ahead of the story | The driver sets off after the call |
| One busy screen for everyone | A simple customer site for businesses; a separate ops dashboard for judges |
| "Need never matters" | Data: Need's first choice became the decision most often; it vetoes unfair splits |

---

## 5. Likely judge questions

- **"Isn't this just a weighted score?"** No single score picks the plan. Each agent scores against its own goal, proposes, votes with a reason, and can veto. The table only counts votes. It can end in consensus, majority with dissent, or asking a human, and we show all three.
- **"What happens when they can't agree?"** Three cases stop and ask a person: the only compromise crosses a red line, the goals are irreconcilable, or a fact is unconfirmed (allergens). The person gets options and a deadline.
- **"Why multiple agents instead of one model?"** We tested it: on 100 unseen scenarios each agent alone loses 1,336 to 1,726 servings; the team loses 676. Each one catches the others' blind spot.
- **"What's real and what's simulated?"** Real: the negotiation, the safety rules, Claude reading photos, video and speech, ElevenLabs voices, the AGNTCY agents. Simulated: the city, the drivers' movement and the clock.
- **"How do you use AGNTCY?"** Every shelter, driver and negotiator is an A2A agent on NATS with an AgentCard and an OASF record (`/agntcy/records`). A test replays every scenario in-process and over A2A: identical decisions.
- **"How do you use ElevenLabs?"** Speech-to-text (Scribe) for voice donations and shelter answers; text-to-speech (Flash v2.5) with a distinct voice per agent for the debate and the dispatcher's phone call.
- **"Does it cost more?"** Yes, compared with Cost alone ($2,115 vs $1,305 over 100 runs). It's still 28% cheaper than the simple approach, and it loses far less food. We disclose it.

---

## 6. Backup video shot list (2–3 minutes; record before submitting)

QuickTime → File → New Screen Recording, voices on, volume up.

1. Terminal: `python3 app.py` with the "AGNTCY A2A over NATS" and "Claude key OK" lines (5 s)
2. Customer site: **Say it** → the order fills in → confirm → tracking (25 s)
3. Photo or video upload read by Claude (15 s)
4. `/ops`: Majority with dissent, debate streaming, network graph lighting up, result with dissent (45 s)
5. The Phone line call, then scroll to the map as the driver sets off (25 s)
6. Irreconcilable goals → Decisions → approve an option before the deadline (20 s)
7. Evidence page: team vs each agent alone (15 s)

---

## 7. Submit (by 12:30)

Paste `docs/DEVPOST.md` into Devpost section by section. Add the repo link, the video and the guide PDF, and opt in to **Best Use of ElevenLabs** and the **Cisco** track. Never paste API keys or sponsor codes anywhere.
