"""The agent mesh: every agent runs as its own service.

- directory.py  an agent directory: agents publish a record of who they are, what they can do and
                where to reach them (modeled on AGNTCY's Agent Directory and OASF records), and stay
                listed only while they send heartbeats
- agent.py      one agent's service: a shelter, a driver, or one of the negotiators (Speed, Cost, Need);
                it registers itself, then answers A2A-style JSON messages over HTTP
- view.py       the facts a message carries, so an agent in another process decides exactly as it
                would in-process
- client.py     how the coordinator discovers agents and messages them, with every message traced
- launcher.py   starts and stops the directory and the agent processes

The decisions are the same functions as in-process (agents.py, network.py); the mesh changes where
they run and how they talk, and adds discovery, liveness and a message trace.
"""
