# SNIPER — Minecraft 4-Letter Name Radar

## The goal

Watch Mojang's API around the clock for **claimable readable 4-letter Minecraft
usernames** (English words, first names, brands, natural double-letter patterns)
and surface them on a **private dashboard** the moment they are truly claimable —
so you can grab them from your Minecraft profile without ever walking into a
"username unavailable" surprise.

Runs 100% on GitHub's free tier. Your PC is never needed. No billing, no card,
no phone notifications — everything lands on the panel only.

---

## The essentials

| Thing | Value |
|---|---|
| Repo | https://github.com/exo-clipper/tbhjustamcuserhunter |
| Panel | https://exo-clipper.github.io/tbhjustamcuserhunter/ |
| Live data | branches `feed-0` … `feed-17`, each holding one encrypted `frag.txt` |
| Panel passphrase | stored ONLY in the `DASH_PASSPHRASE` secret — never in this repo |
| Cost | $0 forever |

GitHub secrets: `DASH_PASSPHRASE` (panel key). Optional: `EXTRA_NAMES`
(comma-separated) adds personal names, `BLOCK_EXTRA` (comma-separated) hides
words Minecraft's profanity filter refuses without waiting for a commit.
Phone pushes were removed by choice.

---

## How it works

1. A GitHub Action keeps **18 parallel shards** alive ~165 min each, one job per
   shard, each with its own runner IP. Every shard job is pinned to its own
   `watcher-<n>` concurrency group and a 15-min cron keeps proposing a fresh
   wave: GitHub parks each proposal behind the shard that is still running and
   discards any older pending one, so **exactly one successor is always waiting**
   and a dead shard is picked back up within ~15 min. Nothing to restart by hand.
   18 (not 20) because GitHub Free allows 20 concurrent jobs and the panel
   deploy must not queue behind the fleet — that is what broke it before.
2. Each shard checks **batches of 10 names per POST** against two official
   bulk endpoints (`api.mojang.com` and `api.minecraftservices.com`), politely:
   ~1 POST/s per IP → **~180 names/s fleet-wide**.
3. Three lanes per loop iteration:
   - **Drop strikes** — names we watched get abandoned are locked for exactly
     **37 days** (Mojang rule). They are fast-polled starting 90 s before their
     unlock second and appear on the panel the moment they turn claimable.
   - **Hot lane** — best ~160 names (ranked word frequency / brands) re-checked
     every **~10 s**.
   - **Full sweep** — all ~4,100 watched names at least every ~30–60 s.
4. Any throttle signal (429, or 8 junk responses in a row) trips a **circuit
   breaker** that pauses that shard with escalating cooldowns (5 min → 6 h max).
5. **Findings go live in seconds, not hours.** Each shard encrypts its own
   snapshot (**AES-256-CBC**, PBKDF2-SHA256 1.2M iterations) and force-pushes it
   to its own branch `feed-<n>` as a single file `frag.txt`, the instant its
   visible picture changes (floor: 15 s apart) plus a 4-min heartbeat so the
   "last scan" pill stays honest. The panel polls all 18 branches straight off
   `raw.githubusercontent.com` every **12 s** and decrypts in the browser.
   **There is no GitHub Pages build in the data path** — Pages only ships the
   HTML, and only when the HTML itself changes.
6. The panel shows **only names verified claimable right now** — nothing else,
   and never a name Minecraft's profanity filter would refuse.

### Why some free-looking names don't show immediately

An ownerless name is either *claimable now* or *in its 37-day lock*. The API
cannot tell those apart directly, so first-sighting an ownerless name parks it
as "locked" until one of two things proves it safe to show:

- it was watched flipping from taken → gone (exact drop time known), or
- a `?at=` history probe shows no owner existed 45 days ago either.

Worst case for a genuinely-free name: it appears after one probe cycle
(~15 min). A mid-cooldown name never leaks onto the panel early.

### Speed expectations

| Event | Delay |
|---|---|
| Hot-lane name frees | ≤ ~10–15 s |
| Any other name frees | ≤ ~30–60 s (sweep period) |
| Watched drop unlocks | strike window starts T-90 s |
| **Detected → visible on the panel** | **~20–40 s** (≤15 s push floor + ~3 s push + ≤12 s poll) |
| Panel "last scan" pill | never older than ~4 min while a shard lives |

### Blocked words

Minecraft's own profanity filter refuses to hand out names like `shag`, `tits`,
`orgy`, `damn`, `jerk`, `fuck`, `bdsm` — watching them wastes sweep time and
showing them wastes yours. `sniper/data/blocked.txt` is the single list, and
it is applied in four places so nothing can leak: the wordlist builder, the
`valid_for()` name rule, `main.py init` (which sweeps blocked names out of
restored state), and the exporter (so even a legacy DB row can't reach the
panel). Matching is **exact, never substring** — `anal` on the list does not
hide `canal`, and ordinary words like `horn` (a Minecraft item) and `scum`
stay watchable on purpose.

Add words two ways: `python main.py block <name>...` then commit
`sniper/data/blocked.txt`, or paste them into the `BLOCK_EXTRA` secret for
immediate effect with no commit.

---

## Security model (read this before changing the passphrase)

**What is public, unavoidably:** the repo, the panel HTML, the Actions logs, and
the `feed-*` branches. Those branches hold the finds, so they are encrypted —
but the *ciphertext* is downloadable by anyone. Going private is not an option:
private repos are capped at ~2,000 Actions minutes/month, which cannot run
18 shards around the clock for free.

**Therefore the passphrase is the entire defence, and it is attacked offline.**
Nobody has to talk to the panel to guess: they grab a blob and grind at their
own hardware's speed. Measured on one ordinary CPU core:

| Passphrase | Time to try every possibility |
|---|---|
| 4-digit PIN (10,000 options) | **~77 min on one CPU core; seconds on a gaming GPU** |
| 4 random lowercase letters | ~2 days on one core |
| 3 random words + a digit | longer than the universe has been around |

The panel currently uses a 4-digit PIN by request. That is a *deliberate*
trade of secrecy for convenience, and it is survivable because the worst case
is someone learning which names are claimable — no account, payment method or
credential is behind that door. If a competitor sniping your finds matters,
switch `DASH_PASSPHRASE` to three random words; the panel remembers it per
device, so it is typed once, not daily.

**What is done to make the rest tight:**

- PBKDF2-SHA256 at **1.2M iterations** (`settings.KDF_ITERATIONS`, mirrored by
  `PBKF_ITER` in `docs/index.html` — change both or nothing decrypts). Ten
  times the old cost per guess. The KDF salt is fixed on purpose
  (`settings.FEED_SALT`): with one target, a random salt would buy nothing while
  forcing the browser to re-derive on every 12 s poll, which is what capped the
  work factor before. The IV is still fresh per push.
  (`LEGACY_ITER` in the panel is a temporary shim that also accepts blobs from a
  shard still running pre-hardening code, so a slow rollout cannot blank the
  panel. Delete it once every `feed-*` branch has been rewritten.)
- The panel derives the key **once per session** and caches it, so the poll is
  free and unlock stays ~0.2 s.
- Every subprocess line printed by `main.py` goes through `_redact()`. The push
  URL carries `x-access-token:<token>`, git quotes URLs back in errors, and
  Actions logs on a public repo are world-readable — GitHub's own masking is
  treated as a backstop, not the defence.
- The passphrase is remembered in `localStorage` so you are not retyping it.
  **LOCK** in the panel header forgets it and reloads, dropping the derived key
  and every decrypted payload out of memory. Use it on a shared machine.
- `tests/offline_test.py::test_no_secrets_in_tree` greps the working tree for
  real credential shapes (`gh*_`, `github_pat_`, PEM private keys, AWS/Slack/
  Telegram tokens, hardcoded `password = "..."`) and asserts the `.gitignore`
  rules that keep DBs, `.env`, `secrets/`, keys and logs out of the repo.
- Repo secrets are exactly one: `DASH_PASSPHRASE`. `ALERT_NTFY` was deleted
  with the notification feature. Pages enforces HTTPS, the default workflow
  token is read-only, and there are no deploy keys or webhooks.

**Verified clean** (full-history audit, every ref, every commit): no token, key,
`.db`, `.env` or `secrets/` file has ever been committed, and every fragment
ever published was ciphertext.

---

## Reality checks worth remembering

- **Minecraft usernames are 3–16 chars** ([a-z0-9_]); we watch exactly-4-letter
  alphabetic names only. Even random doubles like `zzqq` are usually taken —
  the space is heavily squatted, which is precisely why watching pays.
- When someone changes off a name, the old name is locked **37 days**
  (30-day rename cooldown + 7-day grace) before anyone can claim it.
- The panel gate is client-side only: fragments are AES-256 encrypted and the
  key lives solely in the GitHub secret. Treat panel contents as "behind a
  locked door", not a vault — see the security-model section for the actual
  brute-force numbers.
- The `feed-*` branches are **public ciphertext**. That is fine (that is the
  point of encrypting them) but it is also why the passphrase length matters
  more than anything else in this project.
- **20 concurrent jobs is the hard ceiling** on GitHub Free. Never raise the
  shard count to 20: the panel deploy then has nowhere to run and the whole
  publish path silently queues forever. That exact mistake caused the outage
  where the panel froze at "70m ago".
- Never `git switch` branches inside a runner's own checkout mid-run — it
  deletes `main.py` and `sniper/` out from under the process that is running.
  Feed pushes happen in a throwaway `tempfile.mkdtemp()` repo for that reason.
- api.mojang.com occasionally throws **sporadic 403s** (known Mojang quirk);
  the checker tolerates them and only breaker-trips on sustained junk or 429s.
- One shard occasionally dies to a transient GitHub runner error ("Set up job").
  It self-heals within ~15 min — that's what the LOGS tab is for.
- Detecting is free; **claiming needs your own paid Minecraft account**, done
  manually at minecraft.net → profile. Automated claiming violates Mojang rules.

## What was built (history)

1. Telegram 5-letter radar (t.me heuristics, ntfy pushes) — fully replaced.
2. Minecraft conversion: batch×10 lookups against two official bulk hosts;
   37-day lifecycle tracking (flip timestamps, drop strikes, reclaim detection);
   history probes to disambiguate cooldown vs claimable; notifications removed.
3. Wordlists rebuilt: ~2,150 dictionary words + 588 four-letter first names +
   curated brands/terms + up to 1,500 scored adjacent-double-letter patterns
   (`xxli` yes, `xlxi` never). Builder: `sniper/build_wordlists.py`.
4. Persistence stays race-free artifact storage; nothing sensitive hits git.
5. Workflow switched from 5-min cron bursts to chained ~50-min loops
   (public repo = unlimited Actions minutes).
6. **Latency rewrite.** The old path (encrypt → artifact → merge job → Pages
   build) meant a find took 30–70 min to appear, and it had died outright: the
   flush step was switching branches inside the live checkout, 20 shards had
   eaten every concurrency slot so the publish job could never start, and the
   mutual `workflow_run` chain self-skipped once either side was cancelled.
   Replaced with per-shard `feed-<n>` branches + a 12 s browser poll (seconds
   end to end), 18 shards, and per-shard concurrency groups instead of a chain.
7. **Profanity blocklist** (`sniper/data/blocked.txt` + `BLOCK_EXTRA`): names
   Mojang's filter refuses are no longer watched or shown.
8. **Security hardening.** Full-history credential audit (clean); KDF raised
   120k → 1.2M iterations with a fixed salt and a cached key so the panel got
   *faster* while each guess got 10x dearer; `_redact()` on all subprocess
   output so the push token cannot reach a public log; a LOCK button; a
   credential-shape tripwire in the test suite; broader `.gitignore`; stale
   `ALERT_NTFY` secret deleted.

## File map

```
main.py                     CLI: init / run / stats / free / add / block / remove / test / pace / export
sniper/
  settings.py               batch size/delay, lane intervals, breaker + feed config
  engine.py                 batch scheduler, hot lane, drop strikes, circuit breaker
  store.py                  SQLite state (per-shard DBs, flip_ts lifecycle)
  platforms/minecraft.py    bulk POST checker (two hosts) + ?at= history probe
  exporter.py               builds + encrypts panel payloads (claimable-only) + fingerprints
  blocklist.py              the one place a name is judged offensive
  data/blocked.txt          the curated list (exact match, one word per line)
  aeslite.py                pure-python AES-256 (verified vs FIPS-197 vector)
  wordlists.py              validity rules + list loading (+ shard hot slice)
  build_wordlists.py        rebuilds sniper/data/four.txt + hot.txt
docs/index.html             the entire dashboard (single file, polls feed-* branches)
tests/                      offline checker/store/exporter/blocklist/feed tests + AES vector
_paneltest.py               builds a fake local feed so the panel can be browser-tested
_verify_panel.py            decrypts the live feed branches from the CLI
.github/workflows/watch.yml the 18-shard fleet (the whole cloud operation)
.github/workflows/publish.yml  deploys docs/index.html via Actions deploy-pages
                               (panel only, no data; legacy gh-pages builder
                               fails on this repo)
```

## Local commands (optional — PC not required)

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install aiohttp
.venv\Scripts\python.exe -m sniper.build_wordlists   # rebuild four.txt/hot.txt
.venv\Scripts\python.exe main.py init          # rebuild local DB from four.txt
.venv\Scripts\python.exe main.py test zelda    # live-check one name
.venv\Scripts\python.exe main.py block shag    # never watch/show this name again
.venv\Scripts\python.exe main.py stats
.venv\Scripts\python.exe main.py pace          # show current safety config
.venv\Scripts\python.exe tests\offline_test.py # offline test suite
$env:PANEL_PASS="..."; .venv\Scripts\python.exe _verify_panel.py   # is the live feed fresh?
```

## Maintenance cheat-sheet

- **Is it alive?** Open the panel: the "last scan" pill should read seconds or a
  few minutes, never hours, and it should say `18/18 shards`. From the CLI,
  `_verify_panel.py` prints per-shard freshness.
- **Add names to watch:** Settings → Secrets → Actions → update `EXTRA_NAMES`
  (e.g. `myname, othername`). Unknown ones get history-probed before showing.
- **Hide a word Minecraft rejects:** add it to the `BLOCK_EXTRA` secret for
  instant effect, or `main.py block <word>` + commit `blocked.txt` to make it
  permanent.
- **Change panel password:** update `DASH_PASSPHRASE`. Each shard re-encrypts
  under the new key on its next push (seconds to ~4 min). The old passphrase
  stops working on every device at that moment; press LOCK, then enter the new
  one. Longer is strictly better — see the security-model section.
- **Stop everything:** Settings → Actions → Disable workflows. Disabling the
  `watch` workflow is enough — the successor waves come from its own cron, so
  there is no chain to break separately.
- **Panel says "no data yet"?** The `feed-*` branches don't exist until a shard
  has run for ~45 s with `DASH_PASSPHRASE` set. Check the run log for
  `[flush] DASH_PASSPHRASE unset` — that means the secret is missing.
- **Panel empty but runs green?** Early after (re)init most names sit in
  taken/locked while the first sweeps classify them; claimable finds accumulate
  over the following cycles.
