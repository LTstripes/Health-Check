# Product Vision

## What we are building

Healh-Check is a **single-user, local-first personal health observatory**.

The product should collect long-term data about one person from several health sources, keep the source data and provenance, compute reliable statistics outside the LLM, and let the user explore the results in two equal ways:

1. a visual dashboard with graphs and period comparisons;
2. an AI/LLM interface that can answer arbitrary questions, explain changes, find patterns, and give practical suggestions.

This is **not** intended to replace Garmin Connect, Fitbit/Google Health, or Xiaomi's daily dashboards. Those apps already handle day-to-day viewing well. Healh-Check is for longitudinal analysis, cross-source comparison, context, and interpretation.

## Primary user goals

Current priority order:

1. **Weight and body composition** — the main goal today.
   - Current working target: about **76 kg**.
   - The goal is not simply lower weight, but primarily lower body fat while preserving lean/muscle mass.
   - Track changes even when body weight remains roughly stable (body recomposition).
2. **Sleep** — especially its relationship with weight, recovery, and other metrics.
3. **Physical activity and fitness** — cycling, workouts, steps, load, recovery and longer-term fitness changes.
4. **General wellbeing and recovery** — interpreted from wearable metrics plus free-text life context.

## Core usage modes

### Automatic reports

The system should work without manual prompting and produce:

- **Weekly review** — every Sunday.
- **Monthly review** — at month end (30th/31st or the last calendar day).
- **Yearly review** — at year end.

Daily health briefing is **not a priority**. Garmin and Google/Fitbit already provide useful daily views.

### Ad-hoc questions

The user must also be able to ask arbitrary questions over any period, for example:

- "What happened over the last 10 days?"
- "Compare my last bicycle rides. What changed?"
- "How did my sleep change while travelling?"
- "Compare periods when I weighed 82 kg vs 77 kg."
- "What factors are most associated with my better HRV?"
- "How different are Garmin and Fitbit sleep estimates?"

The analytics API must therefore support more than a fixed set of reports.

## Advice, not just measurement

The product should go beyond reporting numbers and provide practical suggestions when the evidence supports them.

However:

- deterministic/statistical code calculates metrics, trends, anomalies, associations and confidence;
- the LLM interprets those results and explains them;
- association must not be presented as causation;
- the product is not a diagnostic medical system;
- persistent or clinically meaningful abnormalities should be framed as a reason to discuss the issue with a qualified clinician rather than as a diagnosis.

## Life context / journal

A structured daily mood/energy/stress diary is intentionally **not required**; the user has tried that workflow and does not want to maintain it.

Instead, support lightweight **free-text contextual events**, such as:

- travel;
- poor sleep on a train/plane;
- several days of alcohol;
- unusually large or late dinners;
- illness;
- stressful periods;
- vacation;
- unusual training or activity;
- schedule changes.

The system should timestamp these notes and make them available to analytics so that it can test whether recurring patterns exist around them.

## Data source philosophy

All source-specific values should be preserved. A canonical metric may choose a preferred source, but the original measurements must remain available for comparison and provenance.

Current source strategy:

- Garmin is expected to be the primary source for most wearable data and Garmin-specific scores.
- Fitbit/Google Health is a candidate primary source for sleep, but this should be decided only after a real statistical comparison with Garmin.
- Both Garmin and Fitbit values should remain visible even after a preferred source is selected.
- Periodic cross-device comparisons are a first-class feature, not an implementation detail.
- Xiaomi S400 is the primary source for weight/body composition.

## Historical depth

Backfill as much history as the providers reliably allow:

- Garmin: ideally multiple years/all available history.
- Fitbit/Google Health: all available history (currently much shorter than Garmin).
- Xiaomi S400: at least the existing roughly six months of historical measurements, including screenshot/photo import where needed.

Historical data is valuable because the product is explicitly about longitudinal analysis.

## Future direction: broader personal health record

The longer-term vision is broader than wearables.

Possible future inputs include:

- blood test results;
- vitamin/mineral panels;
- other laboratory tests;
- medical reports;
- structured results extracted from PDFs/images by an LLM with human confirmation.

The goal is to gradually become a **personal health data center**, where wearable trends, body composition, life context and laboratory data can be examined together.

This is a future phase, not MVP scope.

## Product principles

- **Single user only.** No organizations, workspaces or multi-tenancy.
- **Local first.** Primary use is on the user's laptop.
- **Sensitive data never belongs in Git.** Repository contains code/schema/docs only.
- **Automatic collection and analysis.** Routine operation should not depend on manual exports.
- **Dashboard and AI are equal interfaces.** Neither is merely a secondary feature.
- **LLM does not do the core math.** Python/SQL/statistical code produces reproducible results.
- **Keep raw/source-specific data and provenance.** Normalization must not erase the source truth.
- **Prefer simple infrastructure.** SQLite and a local service are preferred over Redis/Postgres/Kubernetes unless a concrete need appears.

## Explicit non-goals for the first releases

- Creating or scheduling Garmin workouts.
- Replacing Garmin/Fitbit daily dashboards.
- Daily mandatory journaling or wellness scoring by the user.
- Multi-user/SaaS support.
- A native mobile app.
- Nutrition/calorie tracking unless explicitly added later.
