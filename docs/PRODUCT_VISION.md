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

### Owner direction — 2026-10-11 (after complete A+ integration)

[Accepted product main fa36dc5b](https://github.com/LTstripes/Health-Check/commit/fa36dc5b6402fe6e6e166091002faf4af1ec0993)
includes the earlier source-separated Sleep/Statistics A+ wave and #375
full-history Weight+composition, #376 first RHR reader/card, #343 precise
Google Sleep source selection, #347 readable labels, #380 bounded 365/year/YTD
Statistics and #377 Garmin saved-daily Steps projection/read-only UI.
[Post-main CI 38164560091](https://github.com/LTstripes/Health-Check/actions/runs/38164560091)
SUCCESS. This is **engineering**, not Stable deployment or Owner final UAT.

Human [Owner UAT #330](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6113161066)
is **PARTIAL** on the verified but historical Oct 8 disposable copy of real
data. The Owner likes the general A+ direction but calls out noisy technical
source/UI details, unformatted Weight-derived floats/dates, five Google
identities, source selection friction, verbose RHR/Data, and the missing
normal Garmin/Google daily Steps experience. First/repeat Overview 23.098s/
9.470s with uncontrolled cache; fresh full-clone DB integrity UNVERIFIED.
Separate guarded Stable code rollout recommended; no private/live provider
status is proven by these stored clone errors.

[Detailed UAT handoff and remaining issue owners](OWNER_UAT_CHECKPOINT_2026-10-11.md)
and [current backlog](ROADMAP.md#current-backlog) replace superseded
planning-status assumptions below.

**Product-first decisions:**
- One chronological full saved Weight+composition table and a single selected
  composition-metric chart, retaining incompatibility labels and original
  observed dates (#375).
- Normal wearable concept is **Garmin and Google**, not multiple unrelated
  Fitbit/Google brands; retain exact origin devices/sources and do not merge
  overlapping observations without eligibility/identity evidence (#342/#343/#347).
- **Last eligible saved value + actual observation date/age** can be a useful
  default when a day lacks data. It is not today's value, a new provider
  success or a silent rewrite of explicitly selected windows (#376).
- Statistics now has human labels and bounded 7/30, 365, calendar-year and YTD
  windows; full all-history remains separately gated (#380). Garmin saved daily
  Steps evidence/UI are integrated (#377), but routine projector wiring #395
  and Google Steps source/ingestion #392 are not. Calories/BMR remain BLOCKED
  under #319; Google activity/session parity is not yet collected.
- Add **Комментарии** to primary navigation; normal time input selects one
  human city/IANA zone and the exact UTC offset is derived and persisted
  internally. Date-only remains date-only and DST ambiguity is validated (#294).
- Show preserved saved measurements separately from provider auth/refresh
  failures (#305); apply the accepted A+ system consistently to forms/tables
  throughout the application (#379).
- Future Activity value/design questions are deliberately read-only Owner-led
  discovery (#378), not automatic cards, provider features or a second analytics
  engine (#346).

Additional follow-ups: [#393](https://github.com/LTstripes/Health-Check/issues/393)
requires exact eligible-day/source semantics for a compact period-mean resting
pulse; [#394](https://github.com/LTstripes/Health-Check/issues/394)
requires proof before using Body Battery day maximum instead of last snapshot;
[#379](https://github.com/LTstripes/Health-Check/issues/379)
addresses human Weight-table dates and floating-point display. No new calculation,
health score, source pooling or provider calls are authorized by these UI requests.

[R06 health evidence exporter](https://github.com/LTstripes/Health-Check/issues/341)
and Context v0 are built, but direct ChatGPT access is paused. Routine notes
need an explicitly selected durable Owner profile, not an UAT clone. The
[roadmap](ROADMAP.md#current-backlog) owns sequence; proposals do not
authorize implementation, live provider calls or Stable modification.

## Sources

- **Xiaomi Body Composition Scale S400:** the accepted operational path is historical/routine screenshot import; openScale/openScale-sync compatibility remains an optional delivered contract, with #153 closed as not planned.
- **Garmin Vivoactive 5 / Garmin Connect:** released ingestion, historical backfill, deterministic analytics and owner dashboard; current collection health still needs source-specific evidence.
- **Google Health API v4:** released ingestion for sleep and supported health metrics/measurements, with preserved source/device metadata and explicit source-family semantics.
- **Google wearable / Fitbit evidence:** device-level agreement requires explicit persisted Fitbit/device attribution. Broader wearable-family and account observations are not automatically device evidence.
- **Free-text context:** Context Capture v0 stores revisioned original text, dates/instants/intervals; integrated #294 Stage A adds the existing desktop portal adapter; discoverable primary 'Комментарии' navigation is a separately approved follow-up, not another note system.
- **Planned:** confirmed laboratory results and source documents under #348, then medication/supplement and other personal-health-record capabilities when separately scoped.

Every source value remains available. A canonical rule may select one value for one metric/period, but selection never deletes competing evidence.

## Source display is not a canonical-source decision

The implemented Sleep timeline and source-specific 7/30 Statistics can display
stored Garmin/Google values without new successful Agreement pairs. Normal
Owner UI should use the two provider concepts **Garmin** and **Google**, while
retaining every exact device/account/family source identity for source-bound
eligibility, provenance and transparent advanced selection. Fitbit entries and
Google family aggregates may represent overlapping evidence. No last-writer,
longest-night or summed/mean provider-wide winner may be assumed without a
separate reviewed identity/eligibility decision.

A source-specific value shows its **true date/eligible coverage/units**. A
missing observation can be supplemented by a clearly labelled *last eligible
saved* dated observation, but never silently backfilled into the requested
date or period. Two providers need matching compatible meanings/windows/
denominators for a numeric delta; side-by-side display alone proves neither
Agreement nor live provider reachability. Distinct missing, partial, zero,
excluded, disabled and reauth/failed states stay truthful.

The R05 canonical question remains **separate**: which source, if any, to
choose by reversible per-metric rule. Explore after 14 eligible paired nights;
a provisional device-pair decision needs 42 valid device nights over at least
six weeks plus coverage/stability. Correlation alone is insufficient; Garmin
remains accepted default pending explicit change. Presentation does not
weaken those gates.

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
- Keep owner secrets and real datasets outside Git and code fixtures. Owner-authorized read-only analysis and normal presentation in the AI conversation follow [Owner data workflow](OWNER_DATA_WORKFLOW.md); personal values do not require automatic masking.
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
