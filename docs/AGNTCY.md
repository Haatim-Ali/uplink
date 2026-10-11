# Uplink on AGNTCY

[AGNTCY](https://github.com/agntcy) is the open agent stack Cisco Outshift started (now a Linux Foundation
project). Uplink uses it for the part of the system where independent agents talk to each other.

## How it runs (default)

Every agent is **its own process** and **its own A2A agent over NATS**: 7 shelter agents, 6 driver agents
and the 3 negotiators (Speed, Cost, Need), plus any pantry or driver that joins mid-run (`mesh/`).

| Step of a donation | A2A message over NATS |
| --- | --- |
| Announce the food | one broadcast to every shelter agent that can safely take it (`offer.request`) |
| Collect bids | one broadcast to every driver agent with the trips it could make (`bid.batch`) |
| Negotiate | one broadcast to Speed, Cost and Need per step: `plan.evaluate`, then `plan.propose` and `plan.vote` for each round |

Each process serves its A2A AgentCard (`uplink/shelters/<id>`, `uplink/drivers/<id>`, `uplink/negotiators/<name>`)
with the AGNTCY app-sdk's `add_a2a_card`, and the negotiation table reaches them with the SDK's A2A client
(`broadcast_message`). Agents also register in our agent directory and heartbeat every 2 s, so a stopped
agent drops out and isn't consulted; the dashboard's Activity → Agent services can stop and restart any of
them live. `tests/test_mesh.py` checks all 9 scenarios give identical results over A2A/NATS and in-process
(about 1,100 A2A messages, 0 failed).

`python app.py` starts `nats-server` for you if it isn't running. `AGNTCY=0` keeps the agent processes on
HTTP; `MESH=0` runs everything in one process, where `AGNTCY=1` serves only the shelter and driver agents
over AGNTCY inside the app (`agntcy_bridge.py`, below).

## What runs on AGNTCY (in-process mode, `MESH=0 AGNTCY=1`)

| Uplink agent | AGNTCY / A2A role |
| --- | --- |
| Each **shelter agent** (7) | An A2A agent served over NATS with the AGNTCY app-sdk (`add_a2a_card`). Answers accept, counter-offer or decline for its own shelter. |
| Each **driver agent** (6) | An A2A agent over NATS. Bids on the trips addressed to it, or refuses one that's too far. |
| **Speed, Cost, Need** (coordinators) | The A2A client. They reach shelters and drivers only by message: one **A2A broadcast** announces a donation to every shelter that can safely take it, and one broadcast sends every candidate trip to the driver agents. Same pattern coffeeAGNTCY uses to ask its farms. |
| Every agent (business, shelters, drivers, coordinators) | Has an **A2A AgentCard** and an **OASF record**, converted with the SDK's `agent_card_to_oasf`. Served at `/agntcy/records` and `/agntcy/cards`, ready to push to an AGNTCY Directory. |

What we built vs what comes from AGNTCY: the agents, their decisions, the negotiation and the safety
rules are ours (`network.py`, `agents.py`, `world.py`). AGNTCY provides the transport (A2A over NATS,
broadcast pattern), the agent cards and the OASF record format (`agntcy_bridge.py` connects them).

Measured: the 18-donation "City mode" scenario gives identical results over AGNTCY and in-process
(49 A2A broadcasts, 248 network messages), at about 3 ms per broadcast on a laptop.

## Turn it on (Mac)

```bash
python3 --version                       # needs 3.12 or newer
brew install nats-server                # once
pip3 install -r requirements-agntcy.txt # once (agntcy-app-sdk)
nats-server &                           # leave it running
echo "AGNTCY=1" >> .env
PORT=5050 python3 app.py                # prints: Agent network: AGNTCY A2A over NATS (13 agents)
```

The dashboard's Agent network panel then shows `AGNTCY · A2A over NATS · 13 agents · 3 ms`.
Without the SDK or a NATS server, Uplink says why and runs the same agents in-process, so a demo
never depends on it.
