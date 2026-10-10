"""Every tuning knob in one place. Change these to make the agents argue more or less."""

# --- world ---
SPEED_KMH = 28.0         # average city driving speed
HANDOFF_MIN = 2          # minutes to load or unload at each stop
SAFETY_MARGIN = 5        # food must arrive at least this many minutes before it's unsafe
START = 12 * 60          # sim clock starts at 12:00
RELIABILITY_PENALTY = 0.3  # how much a driver's reliability drops when they cancel

# --- humans in the loop ---
COST_LIMIT = 25          # plans costing more than this ($) need a human
HUMAN_TIMEOUT = 15       # if no human answers and food has this few minutes left, act anyway

# --- negotiation ---
THRESHOLDS = [0.9, 0.78, 0.65]  # per round: accept a plan scoring at least this share of your best
CONCESSION = [0.0, 0.45, 0.75]  # per round: how much an agent weighs the least-happy other agent
URGENT_MINUTES = 30      # below this, stop deliberating and act on the best-supported plan
WEIGHT_BONUS = 0.25      # extra vote weight for an agent whose warning proved right

# --- shelter phone page ---
SHELTER_TIMEOUT = 8      # sim minutes to wait for a shelter's reply on its phone before trying elsewhere
PHONE_ONLINE_SECONDS = 6 # a shelter phone counts as connected if its page checked in this recently
TIGHT_SLACK = 20         # with less margin than this (min), Speed also objects to drivers below 90% reliability
