# --- batch checking ---------------------------------------------------------
BATCH_SIZE = 10        # names per POST (mojang bulk limit)
BATCH_DELAY = 1.05     # seconds between POSTs per shard (~0.95 req/s per IP)
JITTER = 0.25          # +/- fraction applied to BATCH_DELAY

# --- re-check intervals (seconds) -------------------------------------------
SWEEP_INTERVAL = 30.0  # min gap between checks of the same name
HOT_RECHECK = 10.0     # fast-lane: hot names at least this often
FREE_RECHECK = 900.0   # confirm still-free every 15 min
PROBE_EVERY = 900.0    # re-probe unknown-history names every 15 min

# --- mojang name lifecycle ---------------------------------------------------
COOLDOWN = 37 * 86400.0  # dropped names are locked for exactly 37 days
STRIKE_LEAD = 90.0       # fast-poll a pending drop this many seconds early

# --- circuit breaker ----------------------------------------------------------
BREAKER_THRESHOLD = 3    # throttle signals before pausing the shard
BREAKER_START = 300.0    # first pause: 5 min, doubles per trip...
BREAKER_MAX = 21600.0    # ...capped at 6 h
UNKNOWN_STRIKE_LIMIT = 8 # consecutive junk responses -> treat as throttling

HOT_MAX = 160            # size of the fast lane

# --- live panel publishing ----------------------------------------------------
FLUSH_FIRST_DELAY = 150.0   # seconds after boot: first guaranteed snapshot push
FLUSH_MIN_GAP = 75.0        # min seconds between pushes of this shard
FLUSH_HEARTBEAT = 900.0     # push even without new finds every 15 min
STAGGER_PER_SHARD = 25.0    # offset each shard so fleet pushes spread out

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
