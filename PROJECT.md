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
| Repo | https://github.com/randomcharstohideprof/thetelehunter |
| Panel | https://randomcharstohideprof.github.io/thetelehunter/ |
| Panel passphrase | `8008` |
| Cost | $0 forever |

GitHub secrets: `DASH_PASSPHRASE` (panel key). Optional secret `EXTRA_NAMES`
(comma-separated) adds personal names; unknown-history names are verified via
the history probe before they are shown. Phone pushes were removed by choice.

---

## How it works

1. A GitHub Action chain keeps **20 parallel shards** alive ~50 min each
   (self-restarting `workflow_run` chain + 15-min cron watchdog), each with its
   own runner IP.
2. Each shard checks **batches of 10 names per POST** against two official
   bulk endpoints (`api.mojang.com` and `api.minecraftservices.com`), politely:
   ~1 POST/s per IP → **~200 names/s fleet-wide**.
3. Three lanes per loop iteration:
   - **Drop strikes** — names we watched get abandoned are locked for exactly
     **37 days** (Mojang rule). They are fast-polled starting 90 s before their
     unlock second and appear on the panel the moment they turn claimable.
   - **Hot lane** — best ~160 names (ranked word frequency / brands) re-checked
     every **~10 s**.
   - **Full sweep** — all ~4,100 watched names at least every ~45–60 s.
4. Any throttle signal (429, or 8 junk responses in a row) trips a **circuit
   breaker** that pauses that shard with escalating cooldowns (5 min → 6 h max).
5. Findings are encrypted (**AES-256-CBC**, PBKDF2-SHA256 120k iterations),
   uploaded as private artifacts, merged and deployed to GitHub Pages with the
   single-file dashboard every cycle (~hourly).
6. The panel shows **only names verified claimable right now** — nothing else.

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
| Any other name frees | ≤ ~60 s (sweep period) |
| Watched drop unlocks | strike window starts T-90 s |
| Visible on panel | next publish (~hourly) |

---

## Reality checks worth remembering

- **Minecraft usernames are 3–16 chars** ([a-z0-9_]); we watch exactly-4-letter
  alphabetic names only. Even random doubles like `zzqq` are usually taken —
  the space is heavily squatted, which is precisely why watching pays.
- When someone changes off a name, the old name is locked **37 days**
  (30-day rename cooldown + 7-day grace) before anyone can claim it.
- The panel passphrase is only 4 digits — brute-forceable offline. Treat panel
  contents as behind a locked door, not a vault.
- api.mojang.com occasionally throws **sporadic 403s** (known Mojang quirk);
  the checker tolerates them and only breaker-trips on sustained junk or 429s.
- One shard occasionally dies to a transient GitHub runner error ("Set up job").
  It self-heals next cycle — that's what the LOGS tab is for.
- Detecting is free; **claiming needs your own paid Minecraft account**, done
  manually at minecraft.net → profile. Automated claiming violates Mojang rules.

## What was built (history)

1. Telegram 5-letter radar (t.me heuristics, ntfy pushes) — fully replaced.
2. Minecraft conversion: batch×10 lookups against two official bulk hosts;
   37-day lifecycle tracking (flip timestamps, drop strikes, reclaim detection);
   history probes to disambiguate cooldown vs claimable; notifications removed.
3. Wordlists rebuilt: 2,181 dictionary words + 588 four-letter first names +
   curated brands/terms + up to 1,500 scored adjacent-double-letter patterns
   (`xxli` yes, `xlxi` never). Builder: `sniper/build_wordlists.py`.
4. Persistence stays race-free artifact storage; nothing sensitive hits git.
5. Workflow switched from 5-min cron bursts to chained ~50-min loops
   (public repo = unlimited Actions minutes).

## File map

```
main.py                     CLI: init / run / stats / free / add / remove / test / pace / export
sniper/
  settings.py               batch size/delay, lane intervals, breaker config
  engine.py                 batch scheduler, hot lane, drop strikes, circuit breaker
  store.py                  SQLite state (per-shard DBs, flip_ts lifecycle)
  platforms/minecraft.py    bulk POST checker (two hosts) + ?at= history probe
  exporter.py               builds + encrypts dashboard fragments (claimable-only)
  aeslite.py                pure-python AES-256 (verified vs FIPS-197 vector)
  wordlists.py              validity rules + list loading (+ shard hot slice)
  build_wordlists.py        rebuilds sniper/data/four.txt + hot.txt
docs/index.html             the entire dashboard (single file)
tests/                      offline checker/store/exporter tests + AES vector test
.github/workflows/watch.yml the whole cloud operation
```

## Local commands (optional — PC not required)

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install aiohttp
.venv\Scripts\python.exe -m sniper.build_wordlists   # rebuild four.txt/hot.txt
.venv\Scripts\python.exe main.py init          # rebuild local DB from four.txt
.venv\Scripts\python.exe main.py test zelda    # live-check one name
.venv\Scripts\python.exe main.py stats
.venv\Scripts\python.exe main.py pace          # show current safety config
.venv\Scripts\python.exe tests\offline_test.py # offline test suite
```

## Maintenance cheat-sheet

- **Is it alive?** Repo → Actions tab → latest `watch` run green? Or open the
  panel and check the "last scan" pill (should read minutes, not hours).
- **Add names to watch:** Settings → Secrets → Actions → update `EXTRA_NAMES`
  (e.g. `myname, othername`). Unknown ones get history-probed before showing.
- **Change panel password:** update `DASH_PASSPHRASE`. Next cycle re-encrypts
  all fragments under the new key.
- **Stop everything:** Settings → Actions → Disable workflows (or disable the
  schedule AND delete the workflow file — the chain restarts itself otherwise).
- **Panel empty but runs green?** Early after (re)init most names sit in
  taken/locked while the first sweeps classify them; claimable finds accumulate
  over the following cycles.
