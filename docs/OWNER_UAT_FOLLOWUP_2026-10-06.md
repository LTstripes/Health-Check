# Owner UAT follow-up — 2026-10-06

This document is the compact product handoff from the first real Owner review after the October Owner-UI remediation wave. GitHub issues remain the task contracts; this file keeps the cross-screen reasoning and routing in one place.

## Accepted checkpoint

- Canonical main: `e806d81fc38093931113ab0790cab120cacf8c10`.
- PR #304 (#292 Owner clarity) merged on exact head; PR CI `37511547552` SUCCESS.
- Exact post-main CI: `37512216796` SUCCESS.
- #302 previously pinned Linux quality/test/checks to one exact Python patch while keeping the fail-closed environment-equality gate strict.
- #189 is closed; this follow-up wave does not reopen the redesign umbrella.

## Real Owner deployment

The Owner updated the clean control checkout `D:\HealthCheck\main` to the accepted checkpoint and started the UI against the durable private profile:

```powershell
.\scripts\start.ps1 -DataDir 'D:\HealthCheck\stable'
```

Runtime migration preparation and loopback UI startup reported success. The Owner then reviewed the real Stable profile. Screenshots/health values remain private Owner evidence and are not copied into Git.

## What improved

- Data now opens; the previous import-history persistence failure is resolved.
- Weight v2 is substantially clearer than the earlier technical surface.
- Overview/Sleep/Activity are calmer after #292.
- Human-readable dates and progressive disclosure improved the general direction.

The remaining problem is no longer the basic shell. It is product synthesis: some screens still expose source/contract machinery instead of answering the Owner's question, and Google/Garmin values are not yet consistently presented side-by-side where comparison is meaningful.

## Follow-up contracts

### #305 — Data v2

First priority because it includes a real functional failure.

- Diagnose why persisted-source freshness currently returns the generic failed-request state on the real profile.
- Do not trigger provider collection or weaken the existing source-freshness policy.
- Distinguish endpoint/runtime failure from client response validation before changing code.
- Make Xiaomi upload → extraction → candidate review → confirm/reject understandable and show honestly whether the vision extractor is configured.
- Humanize timestamps; prioritize pending/action-required imports; fold/demote completed history.

### #306 — Weight v3

- Add human/intermediate time ticks to Weight and composition charts.
- Keep exact dates in detail/table views.
- Make short/long composition series understandable as method/compatibility boundaries rather than an apparent one-week filter.
- Never connect incompatible composition methods as one continuous line.
- No formula, canonical or compatibility-policy change.

### #307 — Overview v2

- Show useful available domains from Garmin, Google and Weight.
- When a metric exists in both providers, show explicit source values; never silently average/pool.
- Keep Garmin-only metrics such as Stress/Body Battery/training explicit.
- Reduce generic hint blocks and use sensible Owner precision.
- Missing data must say which source/metric is missing.

### #308 — Sleep v2

- One row per wake date with duration and score where available.
- Garmin / Google / Compare views on one coherent Sleep surface.
- Overlay only genuinely compatible metric/time semantics; incompatible daily-vs-sleep metrics stay separate with a short explanation.
- Fully Russian Owner copy for Agreement; routine research caveats folded.
- One technical disclosure with source/comparison subsections.
- Prefer human time/one-decimal presentation over raw second/long-float output.

### #309 — Activity v2

- Current accepted Google ingestion has no activity/session stream; Activity must remain honestly Garmin-backed until a separate provider-evidence contract exists.
- Determine the real persisted Garmin type/subtype behind Owner tennis sessions via sanitized readback; do not infer tennis from dates/calories.
- Hide/demote redundant source selection when one Garmin source is usable.
- Replace the confusing multi-select-first comparison with an obvious Session A / Session B flow (or equally clear equivalent).
- One technical disclosure.

## Existing follow-ups that remain valid

- #294 — Owner Settings & Context.
- #295 — measure real route latency before caching/optimization.
- #298 — sanitized Garmin stress persisted-vs-excluded diagnosis on a disposable verified clone.
- #228 parked; #167 Owner-deferred; #126 Owner/admin; #105 NOT_ELIGIBLE.
- Dependabot #270/#271 remain independent proposals and are not housekeeping merges.

## Ordering / parallelism

Recommended current order:

`#305 first + #306 optionally in parallel → #307 → #308 → #309 → consolidated Owner UAT`

#305 and #306 are conceptually independent. Shared CSS/template ownership must remain explicit; if either task needs the same shared file, integrate one first and refresh the other mechanically rather than resolving competing product changes in one PR.

Do not start #307/#308/#309 in parallel by default: they can overlap shared Owner presentation/templates and each later screen benefits from the source-presentation decisions settled before it.

After this wave, use the resulting stable surface for #294/#295/#298 rather than optimizing or adding settings against a moving UI.

## Product principle reinforced by this UAT

The evidence-first architecture is working; the next work is not to hide uncertainty or collapse sources. The UI should make evidence useful:

- answer the Owner's question first;
- keep Garmin/Google/source identity explicit;
- compare only compatible evidence;
- move implementation vocabulary to technical disclosure;
- prefer human dates, durations and bounded numeric precision;
- preserve missing/null/unknown/zero distinctions underneath the simpler presentation.
