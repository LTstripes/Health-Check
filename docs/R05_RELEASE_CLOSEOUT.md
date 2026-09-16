# R05 Release Closeout — Garmin / Google wearable sleep agreement

R05 is released to canonical `main`.

This document is the durable sanitized release record. It intentionally contains no owner health values, private payloads, credentials, tokens, screenshots, databases, or other owner-private evidence.

## Stable release

- Canonical `main` SHA: `46e59327e394ae6dbc5a4ecdf42913200124b9e9`
- Exact-main CI: GitHub Actions run `35130647037` — SUCCESS
- Owner UAT / closeout tracker: #106 — CLOSED / completed
- Design freeze: #97
- Implementation graph: #100–#104, #122 (exploratory uncertain account cohort); #105 deferred

## What R05 delivered

- Night pairing / source eligibility with strict fail-closed legacy cohorts
- Comparable sleep metric projection over immutable evidence
- Versioned agreement-run persistence and replay
- Agreement statistics with exploratory (14-night) and stronger (42-night) gates
- Owner-facing exploratory agreement report / overlays
- Explicit exploratory-only uncertain account/wearable observations cohort (`account_wearables_sleep_observations_v1`)

## Cohort and attribution dispositions

- Accepted legacy `device_pair` / `family_pair` semantics remain **strict / fail-closed**
- Owner-live provider-attribution evidence was **insufficient for a canonical source switch**
- `account_wearables_sleep_observations_v1` is an explicitly **uncertain / exploratory-only** cohort and must stay labeled as such; it is never eligible for canonical selection or the 42-night gate
- **#105** remains deferred / **NOT_ELIGIBLE** on this closeout
- **Garmin remains the canonical / default** sleep source until a reviewed versioned per-metric rule changes that

## Residual limitations

- Provider-attribution depth remains insufficient to promote family-only evidence to Fitbit-device agreement
- A provisional canonical-source change was not justified by the accepted live evidence
- Post-R05 product follow-up starts from this canonical `main` (for example #119 deterministic period brief), not from staging integration branches

## Privacy

No owner health values, identifiers, raw payloads, tokens, or precise identifying health timestamps are recorded in this closeout.
