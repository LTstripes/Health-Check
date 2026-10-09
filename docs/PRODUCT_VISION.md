# Product Vision

## Product definition

Health-Check is a **single-user, local-first personal health observatory** for one person using a Windows laptop. It combines long-term source evidence, deterministic/reproducible analytics, life context, and later laboratory data. A visual dashboard and a conversational AI interface are equal product surfaces over the same evidence layer.

Health-Check is not:

- a SaaS or multi-user platform;
- a workout generator or daily wearable dashboard replacement;
- a mandatory diary or nutrition tracker;
- a medical diagnosis or treatment system;
- a universal wearable-integration framework.

Local-first means the owner controls the runtime, provenance and history. It does not prohibit explicitly selected compact evidence packets from being sent to an external model.

The Owner browser UI targets desktop/laptop CSS viewports **1024px and wider**
([Owner decision #321, 2026-10-07](https://github.com/LTstripes/Health-Check/issues/321)).
Phone, tablet and windows below 1024px are outside design, browser acceptance and
Owner UAT scope. Earlier mobile/responsive acceptance in #189 and UI briefs is
historical. Existing harmless CSS fallbacks remain; functional, accessibility,
security/privacy and complete CI requirements still apply. The approved A+
visual language is retained; new capabilities do not restart the redesign.

## Priority and current outcome

The product's health domains remain:

1. **Weight and body composition.** Observe sustainable trend/recomposition while preserving provenance and algorithm boundaries.
2. **Sleep.** Understand long-term change and compare sources honestly.
3. **Physical activity and fitness.** Preserve activities and make cycling/session comparison useful.
4. **Recovery and general wellbeing.** Interpret source metrics without inventing a premature universal score.

Released R01–R05, deterministic Period Brief, durable Owner Runtime, Context Capture v0,
Garmin Training/Recovery and the A+ shell/Overview, Sleep v3 and Activity v4 are in
canonical history. Engineering integration, local deployment and human acceptance
are different outcomes. The latest real Owner UAT is **PARTIAL**, not a blanket PASS.
See [Project Wiki](PROJECT_WIKI.md) and [Current History](EXECUTION_HISTORY_CURRENT.md).

### Owner execution priority — 2026-10-09

**Data first:** [#342](https://github.com/LTstripes/Health-Check/issues/342) is a P1
first-wave investigation, alongside [#294](https://github.com/LTstripes/Health-Check/issues/294)
portal comments and [#341](https://github.com/LTstripes/Health-Check/issues/341)
bounded health-plus-context evidence for discussion in ChatGPT. Diagnose absent,
excluded, stale, disabled and failed sources before claiming useful complete
analytics. This is not permission to invent missing data or trigger provider work.

Comments and the evidence exporter can be developed on synthetic fixtures in
parallel with that read-only investigation. Cosmetic work is secondary. Complete
documentation reconciliation before the Owner starts the new assignments; the
[roadmap](ROADMAP.md#current-backlog) owns sequencing and shared-file boundaries.

The next useful end-to-end outcome is: the Owner records a comment with an explicit
event date and optional time, reads it back durably, and discusses the selected
measurements and context here in ChatGPT. Telegram is optional/later, not a
prerequisite. First deliver a bounded export; direct authenticated read tools need
their own verified connection. A skill is not network reachability, and this plan
does not claim that ChatGPT currently reads the Owner's loopback application.

## Sources

- **Xiaomi Body Composition Scale S400:** the accepted operational path is historical/routine screenshot import; openScale/openScale-sync compatibility remains an optional delivered contract, with #153 closed as not planned.
- **Garmin Vivoactive 5 / Garmin Connect:** released ingestion, historical backfill, deterministic analytics and owner dashboard; current collection health still needs source-specific evidence.
- **Google Health API v4:** released ingestion for sleep and supported health metrics/measurements, with preserved source/device metadata and explicit source-family semantics.
- **Google wearable / Fitbit evidence:** device-level agreement requires explicit persisted Fitbit/device attribution. Broader wearable-family and account observations are not automatically device evidence.
- **Free-text context:** Context Capture v0 already stores revisioned original text, dates/instants/intervals; #294 adds its portal adapter, not another note system.
- **Planned:** confirmed laboratory results and source documents under #348, then medication/supplement and other personal-health-record capabilities when separately scoped.

Every source value remains available. A canonical rule may select one value for one metric/period, but selection never deletes competing evidence.

## Source display is not a canonical-source decision

The Owner wants independent source observations visible together. Planned Sleep
history (#343) shows Garmin/Google duration series over 7/30 days with source
selection and point detail; it does not require successful Agreement pairing simply
to display the observations.

Planned **Statistics (#347)** shows the same metric in **left-source / right-source
columns**, both visible by default, with actual source names, units, dates and
coverage. A missing side remains explicitly missing. Compatible sides may have a
labelled right-minus-left difference; incompatible windows, meanings or denominators
remain visible but do not receive a misleading numerical difference. Sources are
never summed into a combined total or silently pooled across devices. The same
accepted aggregates can later feed Overview and chat evidence.

R05's separate empirical question remains: which source should be canonical for
which metric? Pair eligible sessions, project comparable metrics, compute versioned
agreement statistics and only then consider a reversible per-metric rule. The
exploratory gate is 14 paired nights; a provisional canonical-source decision needs
42 valid device-pair nights across at least six weeks plus coverage/stability.
Correlation alone is insufficient. Garmin remains the default until an explicitly
reviewed rule changes it. Ordinary side-by-side display does not satisfy those gates.

## Core usage modes

### Automatic reviews

Planned recurring reviews remain Sunday weekly, month-end and annual reviews.
Each review is computed from deterministic evidence, then rendered for the selected
dashboard/chat/email/delivery channel. Missing coverage remains part of the result,
not something hidden by prose. Scheduled delivery is not implemented by this plan.

### Ad-hoc investigation

The user should be able to ask questions such as:

- What happened over the last 10 days, including my comments?
- How is weight changing, and at similar weight what happened to estimated fat and lean mass?
- Compare recent bicycle rides and the Garmin/Google sleep observations.
- What changed around travel, alcohol, illness, stress or unusual training?
- Which source has usable data for this period, and what is still missing?

Typed analytics services compute summaries, comparisons, agreement, trends, coverage
and provenance. The LLM explains those results and uncertainty; it does not calculate
years of raw samples or diagnose disease. Original comments and imported documents
are evidence, not instructions for autonomous tool use.

## Life context without diary friction

The primary context object is an event/exposure interval, not a mandatory daily
questionnaire. Preserve the Owner's original wording, explicit date/time precision,
capture source and optional confirmed tags. Event time and recorded-at are distinct;
date-only input must not acquire invented midnight/UTC. Revisions preserve history.

The portal is the first planned convenient capture path; ChatGPT is the requested
conversation surface. Telegram remains optional. Obsidian is optional and not a
canonical health store. Routine notes must ultimately be recorded in the durable
Owner profile: a note in a disposable UAT clone is not automatically a Stable note.

## Evidence and safety principles

- Preserve raw evidence where practical and always preserve source provenance.
- Keep physical device, provider/input method and measurement algorithm distinct.
- Do not silently compare or merge body-composition series produced by different algorithms.
- Do not label source-family aggregates as a specific device without explicit metadata.
- Prefer repeated observations and agreement over single measurements.
- Treat consumer BIA/wearables as observational instruments, not clinical truth.
- Treat association as exploratory evidence, not causation.
- Expose coverage, freshness, disagreement and computability alongside conclusions.
- Represent unavailable/missing evidence honestly; never convert it to zero.
- Keep proprietary provider scores separate from Health-Check-derived metrics.
- Permit historical reprocessing under new parser/canonical versions without destroying prior evidence.
- Keep owner secrets, raw payloads and private runtime data outside Git and worker environments.
- Distinguish synthetic fixtures, a disposable copy of real data and the durable live profile. A code update does not refresh copied source data.

## Product boundaries

Dashboard and AI are equal interfaces, but analytics truth lives below both.
UI/LLM code must not become a second mathematics engine. New source fields,
aggregations, persistence and connection boundaries require their owning task's
accepted contract; a request for useful cards is not permission to guess units,
average categorical statuses or add overlapping rolling-load snapshots.

No custom Health-Check Recovery Score is scheduled until R05+ evidence demonstrates
a concrete unmet need. Any future score must be transparent, versioned,
component-attributed and explicitly non-medical.

## Future personal health record

#348 scopes the first R09 laboratory/document slice: original PDF/image, extracted
candidates, explicit Owner confirmation, reported labels/values/units/reference
ranges, sample/report dates and traceable revisions. It is planned, not implemented.
Later medication/supplement timelines and longitudinal analysis remain separately
scoped. Uncertain extraction is not confirmed medical evidence or a diagnosis.

## Repository rule

Code, schemas, tests, synthetic fixtures and sanitized engineering evidence belong
in Git. Real health data, screenshots, raw provider payloads, credentials/tokens,
databases, generated private reports and personal documents do not.
