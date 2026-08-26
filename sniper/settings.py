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

# --- live panel feed -----------------------------------------------------------
# Each shard force-pushes its own encrypted blob to its own `feed-N` branch and
# the panel fetches those branches directly (raw.githubusercontent.com), so a
# find never waits on a GitHub Pages build. Pushing costs a commit, so quiet
# shards only heartbeat; a shard with news pushes within seconds.
FEED_BRANCH = "feed-{idx}"   # one branch per shard = force-push, never a race
FEED_FILE = "frag.txt"
FLUSH_POLL = 5.0            # how often a shard checks whether it has news
FLUSH_FIRST_DELAY = 45.0    # first snapshot goes out this soon after boot
FLUSH_MIN_GAP = 15.0        # floor between pushes when finds keep landing
FLUSH_HEARTBEAT = 240.0     # push anyway, so "last scan" stays honest
STAGGER_PER_SHARD = 3.0     # spread the fleet's heartbeats out a little

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
