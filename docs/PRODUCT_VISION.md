# Product Vision

## Product definition

Health-Check is a **single-user, local-first personal health observatory** for one person using a Windows laptop. It combines long-term source evidence, reproducible analytics, life context, and later laboratory data. A visual dashboard and a conversational AI/LLM interface are equal product surfaces over the same deterministic evidence.

Health-Check is not:

- a SaaS or multi-user platform;
- a workout generator or daily wearable dashboard replacement;
- a mandatory diary or nutrition tracker;
- a medical diagnosis or treatment system;
- a universal wearable integration platform.

Local-first means simple ownership, reproducibility, and operation. It is not an absolute prohibition on sending explicitly selected data or compact evidence packets to an external LLM.

## Priority and current outcome

The priority order is fixed:

1. **Weight and body composition.** The configurable personal target belongs in runtime data outside Git; the product goal is to reduce estimated fat while preserving lean/muscle mass and observe recomposition at similar weight.
2. **Sleep.** Understand long-term change and links with activity, context, and recovery.
3. **Physical activity and fitness.** Preserve activities and make cycling comparisons useful.
4. **Recovery and general wellbeing.** Interpret source metrics without inventing a premature universal score.

R01 therefore starts with weight and body composition while building the provider-neutral core needed by Garmin and Fitbit. It is one Health-Check product, not a separate weight application.

## Sources

- Xiaomi Body Composition Scale S400: historical screenshots/photo import and an openScale/openScale-sync live path.
- Garmin Vivoactive 5 / Garmin Connect: later automated history, health metrics, activities, and device-specific scores where the account actually provides them.
- Google Fitbit Air: later Google health-data integration; sleep is a candidate preferred source only after paired comparison with Garmin.
- Free-text context: short events or exposure intervals entered through dashboard or Telegram.
- Later: laboratory results and other personal health documents.

Every source value remains available. A canonical rule may select one value for a particular metric and period, but selection never deletes competing evidence.

## Core usage modes

### Automatic reviews

- Sunday weekly review.
- Month-end review on the last calendar day.
- Annual review at year end.

Each review is computed once from a versioned evidence packet, retained in the dashboard archive, and rendered for Telegram and email. Missing coverage is part of the report. A daily briefing is not currently needed.

### Ad-hoc investigation

The user should be able to ask questions such as:

- What happened over the last 10 days?
- How is weight changing?
- At similar weight, what happened to estimated fat and lean mass?
- Compare recent bicycle rides.
- How are sleep and activity related?
- What happened around travel, alcohol, illness, stress, or poor sleep?
- How far apart are Garmin and Fitbit?
- What changed over a year?

Typed analytics tools compute summaries, comparisons, agreement, trends, coverage, and provenance. The LLM explains those results, highlights uncertainty, and suggests practical next steps. It does not calculate years of raw samples or diagnose disease.

## Life context without diary friction

The primary object is an event/exposure interval, not a boolean daily questionnaire. The system stores the user's original words, time or date range, capture source, and optional tags. Suggested dates/tags may be accepted or corrected; an unambiguous note should be saved without a confirmation ritual for every tag.

Primary capture paths are dashboard and Telegram. Obsidian is optional later and is not a canonical store. Detailed calorie/macronutrient tracking remains outside the first releases; relevant food or alcohol can be context events.

## Evidence and health-safety principles

- Preserve raw evidence where practical and always preserve source provenance.
- Keep physical device, provider/input method, and measurement algorithm distinct.
- Do not silently compare or merge body-composition series produced by different algorithms.
- Prefer trends and repeated observations over a single BIA reading.
- Treat consumer BIA outputs as estimates, not lab measurements.
- Treat association as exploratory evidence, not causation.
- Expose coverage, freshness, disagreement, and confidence alongside conclusions.
- Represent unavailable evidence as unavailable, never as zero.
- Keep proprietary provider scores separate from Health-Check-derived metrics.
- Require human confirmation before uncertain image extraction becomes a measurement.
- Permit historical reprocessing under new parsers or canonical rules without destroying original evidence.

## Product boundaries

Dashboard and AI are equal interfaces, but they do not need to arrive in the same release. The dashboard starts in R01. The read-only typed AI/MCP interface follows once several useful deterministic analytics tools exist. Telegram and email are delivery adapters, not analytics dependencies.

No custom Health-Check Recovery Score is scheduled until enough cross-source personal data exists and a concrete unmet need is demonstrated. Any future score must be versioned, transparent, component-attributed, and explicitly non-medical.

## Future personal health record

Later releases may ingest bloodwork, vitamin/mineral panels, and medical/laboratory documents. The original document stays linked to confirmed structured results, including analyte, result, unit, date, source, and lab-provided reference range. External vision/LLM extraction is permitted, but uncertain fields require confirmation and unsupported diagnoses remain out of scope.

## Repository rule

Code, schemas, tests, and synthetic fixtures belong in Git. Real health data, screenshots, raw payloads, tokens, databases, reports, and personal documents do not.
