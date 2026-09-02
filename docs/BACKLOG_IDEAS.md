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

## Relationship to roadmap

The natural home is **R09 — Laboratory and document data**, with medication/supplement timeline support either introduced in R09 or split into a follow-up release if it would make R09 too large.

Do not pull these capabilities into R01–R08 merely because the data model can anticipate exposure intervals.
