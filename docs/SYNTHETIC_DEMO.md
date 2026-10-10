# Synthetic multidomain demo profile

Fixed-seed, fixed-date synthetic profile for local viewing, safe screenshots and
agent UI checks (#358). Synthetic only: no Owner data, no provider calls, and
the runtime always stays outside the source checkout.

## Dataset

`seed-demo` writes one marked profile (`multidomain-synthetic-v2`) through the
accepted application services:

- the existing six-month Weight batch: 26 weigh-ins / 59 confirmed candidates
  (Xiaomi photo-import path, `Health-Check Synthetic Demo` label);
- 25 Garmin `Vivoactive 5` sleep nights (3 duration-only sparse nights and
  5 missing days) plus one nap;
- 26 Google `google-wearables` family sleep records (5 missing days, 1 manually
  edited night, 1 partial night without asleep minutes and naps);
- 6 Garmin activities: 3 cycling, 2 tennis and 1 walking session;
- 6 dated Context notes (date/instant/interval) tagged `synthetic-demo`.

Reproducibility: random seed `358` and anchor date `2026-10-10` make reruns
idempotent and two fresh seeds produce identical stored rows. Missing and
partial days stay missing; nothing is zero-filled.

Safety: `seed-demo` refuses symlink/junction targets (including aliases that
resolve into another Git workspace), targets inside any Git checkout or
workspace, and non-empty unmarked profiles (also with `--reset`). Before any
destructive reset it re-reads the persisted database through a private
read-only copy and validates it against the versioned fixed-seed manifest:
foreign content, extra records or a marker/content version mismatch are refused
without modifying any file. `--reset` then rebuilds only the positively
identified marked demo (v1 or v2).

## Prepare and run

```powershell
$env:HEALTHCHECK_DATA_DIR = Join-Path $env:LOCALAPPDATA "Health-Check\multidomain-synthetic-demo"
uv run python -m healthcheck.cli seed-demo
uv run python -m healthcheck.cli serve --app ui --port 8126
```

Open `http://127.0.0.1:8126/`. Re-running `seed-demo` is a safe no-op;
`seed-demo --reset` rebuilds the same marked profile. To clean up, stop the
server and remove only the confirmed dedicated demo directory above.

## Screen scenarios

- `/` and `/brief?start_date=2026-01-01&end_date=2026-07-31` — Weight history,
  EWMA trend and coverage; no observation is rendered as zero.
- `/sleep?wake_date=2026-10-10` — the default 30-day Garmin + Google duration
  timeline with separate exact-source rows and explicit gaps.
- `/sleep?wake_date=2026-10-10&view=garmin` — legacy Garmin night with duration,
  score and four stage intervals; `/sleep?wake_date=2026-10-08&view=garmin` — a
  missing night.
- `/sleep?wake_date=2026-10-04&view=google` and
  `/sleep?wake_date=2026-09-23&view=google` — the independent Google family
  label with present and partial nights.
- `/sleep?wake_date=2026-10-10&view=compare` — comparison boundary: pairs are
  persisted but no agreement run is published, so the page shows the explicit
  unavailable state instead of inventing numbers.
- `/garmin` — 3 cycling / 2 tennis / 1 walking sessions from the demo source.
- `/context` — six dated, clearly synthetic notes with `synthetic-demo` tags.

## Desktop browser evidence

Playwright must resolve for Node (for example via an agent browser runner).

```powershell
$env:HEALTHCHECK_BROWSER_BASE_URL = "http://127.0.0.1:8126"
$env:HEALTHCHECK_BROWSER_EVIDENCE_DIR = Join-Path $env:TEMP "hc358-demo-evidence"
# optional: $env:HEALTHCHECK_BROWSER_EXECUTABLE = "<chromium executable>"
node scripts/check_358_demo_browser.cjs
```

The script checks the screens above at 1024 and 1440 px, including the default
sleep timeline, blocks external requests, fails on page errors and horizontal
overflow, and writes screenshots plus `demo-browser.json` into the evidence
directory. That evidence is synthetic demo evidence only; it is not Owner UAT,
provider verification or a real-profile performance claim.
