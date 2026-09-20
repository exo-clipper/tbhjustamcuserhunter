# --- batch checking ---------------------------------------------------------
BATCH_SIZE = 10        # names per POST (mojang bulk limit)
BATCH_DELAY = 1.05     # seconds between POSTs per shard (~0.95 req/s per IP)
JITTER = 0.25          # +/- fraction applied to BATCH_DELAY

# --- re-check intervals (seconds) -------------------------------------------
SWEEP_INTERVAL = 30.0  # min gap between checks of the same name
HOT_RECHECK = 10.0     # fast-lane: hot names at least this often
FREE_RECHECK = 45.0    # names marked free are re-verified at least this often,
                       # so a card can honestly claim "confirmed <1 min ago"
PROBE_EVERY = 900.0    # re-probe unknown-history names every 15 min

# --- panel freshness -----------------------------------------------------------
# The panel must never show a name the user cannot claim on the spot. A "free"
# verdict older than this is stale (it may have been claimed seconds later), so
# the exporter refuses to publish it and the panel refuses to draw it.
PANEL_FRESH = 60.0

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
# A re-confirmed free name must reach the panel quickly even when nothing else
# visibly changed: the fingerprint folds each confirmation time into a bucket
# of this many seconds, so any free re-check triggers a fresh push within
# roughly one bucket instead of waiting for the FLUSH_HEARTBEAT.
FP_REFRESH_BUCKET = 30.0

# --- panel crypto --------------------------------------------------------------
# The repo has to stay public (that is what makes 24/7 Actions free), so every
# feed blob is PUBLIC CIPHERTEXT. The passphrase is the only thing protecting
# it, which is why the work factor is high and why a short passphrase is a bad
# idea: an attacker with the blob can guess offline as fast as their hardware
# allows.
# The salt is deliberately CONSTANT rather than random-per-push. Salt only
# stops one attacker from amortising work across many targets, and there is
# exactly one target here - while a fresh salt every 15s would force the panel
# to re-run the KDF on every poll, capping how high the work factor could go.
# Constant salt + one derivation per browser session buys 10x the iterations.
#
# It must stay 16 bytes: the blob layout is salt(16) | iv(16) | ciphertext.
KDF_ITERATIONS = 1_200_000   # keep docs/index.html PBKF_ITER identical
FEED_SALT = bytes.fromhex("9f2b7c41a6d05e83b1c4f70926a8d35c")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
