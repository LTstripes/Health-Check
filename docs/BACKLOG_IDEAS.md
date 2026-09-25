# Backlog Ideas

This document is a parking lot for useful future capabilities that should not expand the current release scope. Items here are ideas, not committed release requirements. When an idea becomes implementation work, move it into the owning release spec/ADR with evidence, acceptance criteria and data-model implications.

## Medication & Supplement Timeline

Future goal: keep a longitudinal record of vitamins, supplements and medicines alongside wearable, body-composition, context and laboratory data.

Potential fields:

- product / active ingredient;
- type: prescription medicine, OTC medicine, vitamin, mineral, supplement;
- dose and unit;
- formulation / route when relevant;
- intended schedule;
- start/end dates and temporal precision;
- dose changes, pauses and discontinuations as versioned events rather than destructive edits;
- reason / user note;
- prescribing clinician/source when the user wants to record it;
- provenance of the entry (`dashboard`, `telegram`, `document_import`, `manual`);
- optional adherence observations without requiring a daily compliance diary.

Important modeling principle: medication/supplement use is an **exposure interval/event**, not a permanent profile field. Historical dose changes must remain reconstructable.

## Lab-guided interpretation and advice

After laboratory data exists, Health-Check should be able to combine confirmed lab results with medication/supplement history and relevant wearable/body-composition trends.

Example questions:

- How did vitamin D change before/after supplementation?
- Did ferritin/B12/other confirmed analytes change across treatment periods?
- Which current supplements are relevant to the latest confirmed lab panel?
- Are there values worth rechecking or discussing with a clinician?
- Did a medication/supplement period coincide with a meaningful change in sleep, resting HR, HRV, weight or body composition?

The deterministic layer should align dates, doses/exposure periods, lab values, coverage and changes. The LLM may explain the evidence, surface uncertainty, suggest follow-up questions/tests and help prepare questions for a clinician.

The system must not silently diagnose disease, independently start/stop prescription medicines, or present an observed association as proof that a medicine/supplement caused a change.

## Medication / supplement safety support

Potential later capability, only with current trustworthy drug/reference sources and explicit uncertainty:

- duplicate active-ingredient detection;
- basic dose/unit sanity checks;
- known interaction/contraindication warnings;
- reminders that may matter around specific lab tests;
- identifying questions to ask a clinician or pharmacist;
- highlighting when a new lab result may be relevant to a recorded medicine/supplement.

This must be treated as decision support, not autonomous prescribing.

## Future UX ideas

- Fast add/update from dashboard.
- Telegram message such as: `Начал витамин D 2000 IU с 3 сентября` -> parsed candidate event -> low-friction confirmation only when materially ambiguous.
- Import medication/supplement lists from a photo, PDF or medical document with field-level extraction and confirmation.
- Timeline overlay on lab and wearable charts.
- Period comparison before/during/after an exposure when sample size and coverage allow it.

## Context analytics — observation eligibility and cohort truth

Future context/journal analysis must distinguish what was recorded from whether a day is analytically usable.

Direction to preserve before implementing comparisons:

- keep **explicit present**, **explicit absent**, and **not recorded / unknown** as different states;
- never put a missing context entry into the negative comparison group by default;
- keep source freshness separate from observation quality: a current source can still be partial-day, non-wear or otherwise unsuitable for a comparison;
- define comparison eligibility with explicit versioned rules and expose why observations were excluded;
- show usable observation count and date/period coverage before presenting a comparison;
- align cohorts using actual calendar/source semantics rather than array position or a current-time offset shortcut;
- preserve `insufficient` / `unknown` when evidence is too weak instead of manufacturing a score;
- treat lag/correlation scans as exploratory evidence and account for multiple comparisons/autocorrelation before calling something a finding;
- never turn an association into a causal health claim.

Evidence for these failure classes is recorded in `docs/audits/REFERENCE_PROJECT_REFRESH_2026-09-25.md`. Donor thresholds and heuristics are not Health-Check policy.

Natural home: future Context analytics work after the accepted capture/read contracts are stable. Promote into an explicit issue/spec before implementation.

## AI / MCP — compact deterministic evidence packets

Future model-facing analytical tools should normally expose bounded deterministic results rather than bulk raw history.

A useful evidence packet should include only what the model needs to explain the result:

- requested metric/comparison and deterministic result;
- usable observation count;
- date/period coverage;
- freshness/data-quality disposition;
- source/provenance identity at the privacy-safe level needed for interpretation;
- analytics/policy/version identity;
- exclusions or withholding reasons such as insufficient evidence;
- compact supporting values/series only when the particular tool genuinely needs them.

Capability direction:

- prefer typed task-specific read tools over generic raw database/SQL access;
- keep the normal analytical reader **read-only**;
- do not grant sync, import, restore, provider-write or destructive capabilities just because the same runtime has those capabilities elsewhere;
- avoid large raw payloads that make the LLM reproduce deterministic calculations;
- reuse accepted Health-Check read, Period Brief and freshness layers rather than creating model-only semantics;
- make demo/synthetic stores explicitly identifiable so generated evidence cannot be presented as Owner measurements.

This is a future capability boundary, not permission to implement AI/Telegram/MCP now. Exact tools and product behavior belong in the owning release/spec.

## Relationship to roadmap

The natural home for medication/supplement capabilities is **R09 — Laboratory and document data**, with medication/supplement timeline support either introduced in R09 or split into a follow-up release if it would make R09 too large.

Context analytical eligibility belongs after Context capture/read contracts are stable. AI/MCP evidence packets belong in the future bounded model-facing surface over accepted deterministic services.

Do not pull these capabilities into an earlier release merely because the data model can anticipate them.
