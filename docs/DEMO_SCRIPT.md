# Uplink: demo script for three speakers

About **4 minutes**, plus optional extensions if you have time and a 2-minute cut if you don't.

| Speaker | Owns | Drives the laptop during |
| --- | --- | --- |
| **Sara** | the problem, the agents arguing, the close | Chelsi's part |
| **Chelsi** | the business side (Say it, photo/video), ElevenLabs, the phone call | her own Say it, then Sara's part |
| **Haatim** | how it's built (AGNTCY), when agents can't agree, the evidence | his own part |

Swap names freely: what matters is that each person owns a part and someone else's hands are on the laptop while they talk.

**How to read the lines:**
- **bold** = lean on the word
- `/` = a half-second beat
- `[PAUSE]` = stop talking, let the screen work
- *(italics)* = an action on the laptop

Speak to the judges, not the screen. Point at the screen with your hand when a line says "here".

---

## Before you walk up (5 minutes earlier)

1. App running from `~/uplink`; the terminal shows **Claude key OK**, **Voice: ElevenLabs** and **16 agents … AGNTCY A2A over NATS**. Then hide the terminal.
2. Browser, full screen (Cmd+Ctrl+F), zoom 110% if the room is big. Only two tabs, in this order:
   - **Tab 1:** http://localhost:5050/#/schedule with **Donating as: Pizza My Heart (Pacific Ave)** selected and the **Say it** tab open. Test the mic once (allow microphone access), then refresh.
   - **Tab 2:** http://localhost:5050/ops in dark mode. Under Demo controls: **Empty world** (so it's clean), **Voices on**, and **Majority with dissent** selected in the scenario list but not run yet.
3. Laptop volume at about 70%, Do Not Disturb on, notifications off, phone silenced.
4. Scroll Tab 2 to the top. The Negotiation panel should show the three agents and their goals, with no donation yet.

---

## The script

### 0:00 · Sara · The problem

**On screen:** Tab 2, the top of `/ops`: the three agent cards (Speed, Cost, Need) and the empty Agent network.

> Hi, we're Sara, Chelsi and Haatim, and this is **Uplink**.
>
> Every night, restaurants in Santa Cruz throw away food that's **perfectly good**. / California's SB 1383 actually **requires** many of them to donate it. / But at closing time, donating is a pile of tradeoffs nobody has time for.
>
> The **fast** courier costs money. / The **free** volunteer might not show up. / And the closest shelter might have already eaten today, while another one has waited **five days**.
>
> Cisco asked us: *what happens when AI agents disagree?* / Food rescue is a problem where they **should**.

*(Sara hands off with a look; the driver switches to Tab 1.)*

---

### 0:35 · Chelsi · The business side: just say it

**On screen:** Tab 1, the customer site: "What's left over?", **Donating as: Pizza My Heart**, the **Say it** tab.

> This is what a restaurant sees. No forms. / I'm the manager at Pizza My Heart, it's closing time, and I just **say** what's left.

*(Chelsi taps the mic and says clearly, facing the laptop:)*

> "We've got **two** pepperoni pizzas, a **dozen** chocolate chip cookies, and **five** bananas."

*(Tap to stop.)* `[PAUSE: let the order fill in]`

**On screen:** the transcript appears, then the order: pizzas, cookies, bananas, with quantities and allergens.

> **ElevenLabs Scribe** turned my voice into text, / and **Claude** matched it to *our own menu*, so the allergens come from our recipes, not a guess.
>
> If I'd rather, I can snap a **photo**, or pan a short **video** over the counter, and Claude counts the food. / Or just tap items on the menu.

*(The driver clicks **Schedule pickup**, then **Confirm pickup**.)*

**On screen:** the pickup tracking page.

> That's it. / That's everything a manager has to do. / Now, what happens **behind the scenes**?

*(Switch to Tab 2.)*

---

### 1:15 · Sara · The agents argue

**On screen:** Tab 2, `/ops`. If Chelsi's pizza donation is already being negotiated, point at it: "there's our pizza." Otherwise go straight on.

> This is the operations view, where the AI agents work. / Here are three agents, and there is **no boss**.
>
> *(Point at each card.)* **Speed** cares about getting food there fast, with a reliable driver. / **Cost** cares about money. / **Need** cares about one thing: whoever has waited **longest**.
>
> And each one has a **red line** it will not cross.
>
> Let me give them a **hard** case. / It's 6 PM, couriers have surge pricing, and there's only **one** volunteer left, across town.

*(The driver: Demo controls → **Majority with dissent** → **Run scenario**.)*

**On screen:** "Agents are deliberating…". Proposals stream into the Negotiation panel one by one, with voices on.

`[PAUSE: let the first proposals play out loud, about 5 seconds]`

> Listen to them. / **Speed** wants the reliable paid courier. / **Cost** wants the free volunteer. / And **Need** wants Walnut Avenue, the shelter that's waited **five days**.

**On screen:** objections appear in red.

> Now they **object** to each other. / Speed says the volunteer is only **50% reliable**: "a no-show would spoil this food." / Cost says why pay **fifteen dollars** when a volunteer route is free.

`[PAUSE: let round 2 stream]`

> They don't just fold. / Each round, the bar to accept drops a little, so they give ground **slowly**, like people would.

**On screen:** the result: **"Majority 2 of 3 (Cost disagrees, kept on record)"**.

> Round three: Speed and Cost both move toward Need's shelter, from **opposite** sides. / Two of three agree, / and Cost's objection stays **on the record**.
>
> We don't force a consensus that isn't there.

*(Hand to Haatim.)*

---

### 2:20 · Haatim · How it's built: real agents, real messages

**On screen:** the **Agent network** graph (top right) lit up: business → shelter agents → driver agents → coordinators.

> Everything you just watched is **real message passing**. / *(Point at the graph.)* Every shelter, every driver, and each of the three negotiators is its **own agent**, / running as its **own process**: **sixteen** of them.
>
> They talk over **Cisco's AGNTCY** framework, / the **A2A** protocol on **NATS**. / *(Point at the badge "AGNTCY · A2A over NATS · 16 agent processes".)*
>
> The business announces the food; / every shelter agent answers *yes*, *only part*, or *no*; / every driver agent **bids**, or refuses a trip that's too far; / and then the negotiators vote.
>
> And one thing is **never** up for debate: **food safety**. / Code removes any plan without a fridge, with the wrong allergens, or that arrives too late, **before** any agent even sees it.

*(Hand to Chelsi.)*

---

### 2:55 · Chelsi · The phone call (ElevenLabs)

**On screen:** the **Phone line** panel under the graph: "Ringing…", then the dispatcher and the shelter talking, with the transcript filling in. The status pill at the top reads "Dispatcher calling · driver waits".

> Once they decide, / a **dispatcher agent** calls the shelter. / Listen.

`[PAUSE: let the whole call play, about 15 seconds. Don't talk over it.]`

> Two agents, two **ElevenLabs** voices. / And the shelter's answer is its agent's **real** reply. / Shelter staff can also answer by **voice** from their phone.
>
> *Only* after the call does the driver set off.

*(The driver scrolls down to the map.)*

**On screen:** the map: the courier's dot leaves the restaurant toward Walnut Avenue; the message log on the left.

> *(Point at the map.)* There it goes.

*(Hand to Haatim.)*

---

### 3:25 · Haatim · Evidence

*(Optional extension A goes here if you have time: see below.)*

*(The driver clicks the **Evidence** tab.)*

**On screen:** Evidence: "82% less food lost", "49% less than the best single agent", "95 of 100".

> Does arguing actually **help**? / We tested it on **100** random scenarios the system had **never seen**: driver no-shows, full shelters, new pantries.
>
> Compared to the simple approach, nearest shelter and nearest driver, / the team lost **82% less** food.
>
> And here's the part we're proudest of: / compared to **any one agent deciding alone**, / the team lost **49% less**. / Speed alone overspends. / Cost alone trusts volunteers who don't show. / Need alone takes risky trips.
>
> **Together, they veto each other's blind spots.**

---

### 3:50 · Sara · Close

**On screen:** go back to the Live tab, showing the result and the agent cards.

> So that's **Uplink**. / Agents with **competing goals**, / that disagree **out loud**, / never compromise on **safety**, / and ask a human when agreeing would be **wrong**.
>
> Thank you. `[PAUSE]` We'd love your questions.

---

## Optional extensions (add one or two if you have 5+ minutes)

**A · When they can't agree (Haatim, 40 s, before Evidence).**
*(Demo controls → **Irreconcilable goals** → Run.)* While it streams:
> Sometimes the goals **can't** be reconciled. / Watch: each agent's pick is blocked by the other two, round after round.

When "Asking a coordinator" appears, click **Decisions**:
> Instead of forcing a bad deal, / they **stop** and ask a person, with options and a **decide-by** time, so the food never spoils waiting. / If nobody answers in time, the best-supported safe option goes.

*(Click **Approve** on an option.)*

**B · The world changes (Sara, 30 s).** During any running scenario: *(Demo controls → **Shelter says full**.)*
> A shelter just called: they're full. / The agents re-plan, / and each one tells us whether the news **changed its mind**. *(Point at "That changes my pick…".)*

**C · Pull an agent's plug (Haatim, 30 s).** *(Activity → **Agent services** → **Stop** on a shelter agent, run a scenario, then **Restart**.)*
> Each agent is its own service. / If one goes down, / it drops out of the directory and the others **carry on**.

**D · Photo or video (Chelsi, 25 s).** Tab 1 → **Photo / video** → upload a real photo of food.
> Claude names and counts it. / A video becomes four frames, so nothing is counted twice.

---

## The 2-minute cut

| Time | Who | Screen | Say |
| --- | --- | --- | --- |
| 0:00 | Sara | `/ops`, the three agent cards | The problem, in two sentences; "food rescue is where agents **should** disagree." |
| 0:20 | Chelsi | Tab 1 → **Say it** | Say the order; "**ElevenLabs** heard it, **Claude** matched our menu." Confirm. |
| 0:50 | Sara | `/ops` → Majority with dissent | Name the three goals and red lines; narrate the objections; "Majority 2 of 3, dissent **on record**." |
| 1:25 | Haatim | Agent network graph | "Sixteen agents, each its own process, on **AGNTCY** A2A over NATS. Safety is never negotiated." |
| 1:40 | Chelsi | Phone line | Let 5 seconds of the call play: "the dispatcher **calls** the shelter." |
| 1:50 | Haatim | Evidence | "**82%** less food lost than the simple approach; **49%** less than any one agent alone." |
| 2:00 | Sara | Live | The closing line. |

---

## If something goes wrong on stage

Keep talking. The judges remember calm more than a glitch.

| What happens | Who covers | What to say or do |
| --- | --- | --- |
| The mic doesn't pick up the voice | Chelsi | Switch to the **Menu** tab and tap the three items: "Same result by tapping; voice works the same way." |
| The debate takes longer than expected | Sara | Fill with the goals and red lines, or: "Each of those is a real model call; the clock waits for them so no food-safety time is lost." |
| A Claude call fails | nobody needs to | The agents fall back to their rules automatically after 20 s; keep narrating. |
| No sound | Chelsi | Read the call lines from the transcript; mention the voices are ElevenLabs. |
| The app freezes | the driver | Hard refresh (Cmd+Shift+R). If it's still frozen, switch to the backup video. |
| Ran out of time | Sara | Jump straight to the close. |

## Who answers which question

- **Agents, negotiation, "isn't this just a weighted score?"** → Sara
- **AGNTCY, A2A, architecture, "what's real vs simulated?"** → Haatim
- **ElevenLabs, voice, the customer experience, the business model** → Chelsi
- **Results, "does it cost more?"** → Haatim

Ready-made answers are in `docs/DEMO_DAY.md`, section 5.
