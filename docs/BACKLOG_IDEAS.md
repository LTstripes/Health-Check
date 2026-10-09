# Backlog Ideas

This document is a parking lot for future capabilities not yet in an implementation
slice. When promoted, an idea is owned by its explicit issue/contract; do not treat
this file as a second automatic Worker queue.

## Promoted Owner work — 2026-10-09

The Owner chose functionality and data availability before further cosmetic work.
The [roadmap](ROADMAP.md#current-backlog) owns the full order; finish documentation
reconciliation before launching the next tasks.

| Direction | Owning task / current boundary |
| --- | --- |
| **P1 source availability first** | #342 diagnosis; existing #340 RHR surface rule, #319 activity-field evidence and #295 speed remain distinct |
| Portal comments with date/optional time | #294 Stage A over accepted Context v0; weight-goal settings remain later Stage B |
| Discuss health + comments in ChatGPT | #341 bounded export first, then verified authenticated read-only connection; Telegram optional |
| Two-source Sleep history | #343 independently labelled Garmin/Google 7/30-day chart; no pairing prerequisite merely to display sources |
| Overview readability | #344 thin honest Weight connectors, intermediate Sleep ticks and concise disclosure; no formula changes |
| Activity details / period recovery cards | #345 and #346; additional metric evidence stays #319 |
| Statistics | #347: **left source / right source, both visible**, source-specific units/windows/coverage; no combined total, numeric delta only when compatible |
| Laboratory document intake | #348 first R09 contract: original document, extracted candidates, explicit confirmation and traceable results |

These capabilities are planned, not declared implemented. The Context UI and export
module have compatible write scopes; #342 is parallel read-only research. Deeper
context inference, medicines/supplements, scheduled reports and autonomous provider
operations are not implicitly included.

## Medication & Supplement Timeline

Future goal: keep a longitudinal record of vitamins, supplements and medicines
alongside wearable, body-composition, context and laboratory data.

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

Medication/supplement use is an **exposure interval/event**, not a permanent
profile field. Historical dose changes must remain reconstructable. This timeline
is not bundled into #348's first document-intake slice.

## Lab-guided interpretation and advice

After confirmed laboratory data exists, Health-Check should be able to combine it
with medication/supplement history and relevant wearable/body-composition trends.

Example questions:

- How did vitamin D change before/after supplementation?
- Did ferritin/B12/other confirmed analytes change across treatment periods?
- Which current supplements are relevant to the latest confirmed lab panel?
- Are there values worth rechecking or discussing with a clinician?
- Did a medication/supplement period coincide with a meaningful change in sleep, resting HR, HRV, weight or body composition?

The deterministic layer aligns dates, doses/exposure periods, lab values, coverage
and changes. The LLM may explain evidence, surface uncertainty, suggest follow-up
questions/tests and help prepare questions for a clinician. It must not silently
diagnose disease, independently start/stop prescription medicines, or present
association as proof of a treatment effect.

## Medication / supplement safety support

Potential later capability, only with current trustworthy drug/reference sources
and explicit uncertainty:

- duplicate active-ingredient detection;
- basic dose/unit sanity checks;
- known interaction/contraindication warnings;
- reminders that may matter around specific lab tests;
- identifying questions to ask a clinician or pharmacist;
- highlighting when a new lab result may be relevant to a recorded medicine/supplement.

This is decision support, not autonomous prescribing, and remains future work.

## Future UX ideas

- Fast add/update from dashboard; ordinary free-text Context capture is now #294.
- Optional later Telegram capture of an exposure into a candidate event with low-friction confirmation when materially ambiguous; Telegram is no longer a prerequisite for chat analysis.
- Import medication/supplement lists from photo/PDF with field-level extraction and confirmation, separately from the first lab-result slice.
- Timeline overlays on lab/wearable charts.
- Before/during/after exposure comparisons when sample size, timing and coverage allow them.

## Context analytics — observation eligibility and cohort truth

Future context/journal analysis must distinguish what was recorded from whether a
day is analytically usable. #341's first evidence envelope does not implement
causal/matched-control analytics merely by including comments.

Direction to preserve before comparisons:

- keep **explicit present**, **explicit absent**, and **not recorded / unknown** distinct;
- never put a missing context entry into a negative comparison group by default;
- keep freshness separate from observation quality: current can still mean partial-day/non-wear/unsuitable;
- define comparison eligibility with versioned rules and expose exclusions;
- show usable observation count and date/period coverage;
- align actual calendar/source semantics, not array position or the host's current offset;
- preserve insufficient/unknown when evidence is weak, without manufacturing a score;
- treat lag/correlation scans as exploratory and account for multiple comparisons/autocorrelation;
- never turn association into a causal health claim.

Evidence for these failure classes is in
[Reference Project Refresh](audits/REFERENCE_PROJECT_REFRESH_2026-09-25.md).
Donor thresholds/heuristics are not Health-Check policy. Promote deeper analysis
into its own explicit contract after the capture/read boundary is stable.

## AI / MCP — compact deterministic evidence packets

The bounded first implementation is now **#341**, not an unassigned future idea.
Model-facing tools should return only the evidence needed to explain a selected
result:

- requested metric/comparison and deterministic result;
- usable observation count and effective date/period coverage;
- freshness/data-quality disposition;
- source/provenance at the level needed for interpretation;
- analytics/policy/version and evidence identity;
- exclusions/withholding reasons;
- compact supporting values/series and current dated Context revisions when requested.

Preserve typed task-specific reads, not generic raw SQL/database access. Analytical
access stays read-only and does not gain sync/import/restore/provider-write rights.
Reuse accepted query/Period Brief/freshness/Context services instead of model-only
semantics. Synthetic, disposable real-clone and durable-profile origins must be
explicit; copied stale evidence is not live recovery. Notes/documents are untrusted
data, not executable instructions.

The first transport is an Owner-selected private export with explicit period and
contents. A sharing UI follows the accepted Context adapter. Direct ChatGPT read
access then requires a verified authenticated connection and actual account/host
capability; a skill does not make localhost reachable. No connection is currently
claimed by this document, and publishing the whole portal/SQLite is not authorized.
External service selection, tunnel/setup and consent belong to #341's later stage.

## Relationship to roadmap

#294/#341 promote the useful first part of R06; P1 #342 protects the data basis for
it. #343–#347 are bounded source-preserving product views and descriptive summaries,
not permission for a new health-score engine. **#347 defaults to both source columns
side by side**, not single-source-only toggles. Values with different windows or
incompatible meanings can remain visible separately without a numerical delta.
Missing data are not zero, and no combined Garmin+Google steps/energy total is made.

#348 promotes the first **R09 Laboratory and document data** contract. Wider
medication/supplement timelines can remain R09 follow-up or be split if necessary.
Do not pull them, deeper causal context analytics or scheduled delivery into the
first comment/export/document slice merely because the data model can anticipate
those future needs.
