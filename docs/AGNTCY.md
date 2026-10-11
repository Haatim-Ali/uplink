# Uplink on AGNTCY

[AGNTCY](https://github.com/agntcy) is the open agent stack Cisco Outshift started (now a Linux Foundation
project). Uplink uses it for the part of the system where independent agents talk to each other.

## What runs on AGNTCY

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
