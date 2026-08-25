# SNIPER — Telegram Username Radar

## The goal

Watch Telegram around the clock for **claimable 5-letter usernames** (real English words,
Web3/crypto slang, brand names, first names) and get **notified on your phone within minutes**
of one becoming free — plus a **private dashboard** to browse everything found.

Runs 100% on GitHub's free tier. Your PC is never needed.

---

## The essentials

| Thing | Value |
|---|---|
| Repo | https://github.com/randomcharstohideprof/thetelehunter |
| Panel | https://randomcharstohideprof.github.io/thetelehunter/ |
| Panel passphrase | `8008` |
| Phone alerts (ntfy topic) | `tlh-jE2LsHToH7Lt` |
| Cost | $0 forever |

GitHub secrets already configured: `DASH_PASSPHRASE` (panel key), `ALERT_NTFY` (push topic).
Optional secret `EXTRA_NAMES` (comma-separated) adds personal names to watch — every shard
checks them each cycle, so they're scanned extra often.

---

## How it works

1. A GitHub Action fires **every 5 minutes** (`*/5` cron).
2. It fans out into **20 parallel "shards"**, each with its own runner IP, each politely
   checking its slice of the watchlist (~1 request / 0.75s ± jitter).
3. A name is FREE when `t.me/<name>` serves no owner page. Any throttle signal trips a
   **circuit breaker** that pauses that shard with escalating cooldowns (15 min → 6 h max).
4. Each shard encrypts its findings (**AES-256-CBC**, PBKDF2-SHA256 120k iterations) and
   uploads them as private artifacts.
5. When all shards finish, a `publish` job merges the encrypted fragments and deploys them
   to GitHub Pages alongside the single-file dashboard.
6. Your phone receives ntfy pushes the *instant* a flip is detected during any scan:
   `new 5 letter username available` + the handle + link.

### Speed expectations

| Event | Delay |
|---|---|
| Word frees → scanner notices | avg **~5 min**, worst ~10–15 min |
| Detected → phone push | seconds |
| Detected → visible on panel | next publish (~every 10–15 min) |

Panel cards show `✓ confirmed Xm ago` = last time a scan verified the handle is still free.
This resets every cycle. The LOGS tab records every find, throttle warning, breaker pause,
and run summary.

---

## Reality checks worth remembering

- **Telegram forbids usernames shorter than 5 characters.** 3–4 letter handles can only be
  bought via fragment.com auctions — that's why this project watches 5-letter words, which
  are directly claimable in-app for free the moment they free up.
- The panel passphrase is only 4 digits, so it can be brute-forced offline by a determined
  attacker. Treat panel contents as behind a locked door, not a vault.
- One shard occasionally dies to a transient GitHub runner error ("Set up job"). It
  self-heals next cycle — that's what the logs tab is for.
- Most of the watchlist is free most of the time (thousands of entries). The valuable signal
  is **change over time** — newest finds sort first.

---

## What was built (history)

1. Multi-platform checker (Telegram / Instagram / Discord) — Discord dropped by decision;
   Instagram dropped because datacenter IPs got flagged and using your real login cookie
   from cloud IPs risks account checkpoints.
2. Wordlists rebuilt twice: 3-letter combos + readable 4-letter words → replaced with
   4,241 quality 5-letter handles (common-English frequency lists + first-names database +
   curated Web3/brand/slang sets). Builder: `sniper/build_wordlists.py`.
3. Persistence went through a git-committed SQLite DB (raced when 20 shards finished at
   once) → redesigned to race-free artifact storage; nothing sensitive ever lands in git.
4. Panel deployed via official GitHub Pages actions; cron tightened 20 min → 5 min to kill
   dead zones between scans.
5. Panel performance rebuilt: no more accumulating script tags, GPU-heavy blur removed,
   rendering capped (newest 400 cards), decryption parallelized.

## File map

```
main.py                     CLI: init / run / stats / free / add / remove / test / pace / export
sniper/
  settings.py               pacing, jitter, breaker config (all safety knobs)
  engine.py                 scheduler, circuit breaker, alerting
  store.py                  SQLite state (per-shard DBs)
  platforms/telegram.py     t.me checker (title-page heuristic)
  notifier.py               ntfy push + optional Telegram bot DMs
  exporter.py               builds + encrypts dashboard fragments
  aeslite.py                pure-python AES-256 (verified vs FIPS-197 vector)
  wordlists.py              validity rules + list loading
  build_wordlists.py        rebuilds sniper/data/five.txt
docs/index.html             the entire dashboard (single file)
tests/                      offline checker tests + AES vector test
.github/workflows/watch.yml the whole cloud operation
```

## Local commands (optional — PC not required)

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install aiohttp
.venv\Scripts\python.exe main.py init          # rebuild local DB from five.txt
.venv\Scripts\python.exe main.py test zelda    # live-check one name
.venv\Scripts\python.exe main.py stats
.venv\Scripts\python.exe main.py pace          # show current safety config
```

## Maintenance cheat-sheet

- **Is it alive?** Repo → Actions tab → latest `watch` run green? Or open the panel and
  check the "last scan" pill (should read minutes, not hours).
- **Add names to watch:** Settings → Secrets → Actions → update `EXTRA_NAMES`
  (e.g. `myname, othername`).
- **Change panel password:** update `DASH_PASSPHRASE` secret. Next run re-encrypts all
  fragments under the new key; unlock the panel with the new passphrase after that run.
- **Stop everything:** Settings → Actions → Disable workflows (or disable schedule).
- **Pushes stopped?** Check ntfy app still subscribed to the topic; check Actions runs are
  succeeding; LOGS tab will show breaker pauses if Telegram throttled us.
