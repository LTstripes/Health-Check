<a id="book--product-vision"></a>
# Product Vision

This book defines the product, its boundaries and the complete Owner desktop
experience. It is the product source of truth, not an execution queue or a claim
that a provider is currently healthy. Read [Architecture](ARCHITECTURE.md) for
data/algorithm contracts, [Development](DEVELOPMENT_PROCESS.md) for delivery,
[Owner Operations](OWNER_OPERATIONS.md) for actions and [Project Wiki](PROJECT_WIKI.md)
for the single dated main/installed/UAT snapshot and remaining work.

<a id="book--contents"></a>
## Contents

- [Product definition](#product-definition)
- [Priorities and accepted product decisions](#product-decisions)
- [Sources](#sources)
- [Source display and canonical selection](#source-display-is-not-a-canonical-source-decision)
- [Usage modes](#core-usage-modes) and [life context](#life-context-without-diary-friction)
- [Evidence, safety and boundaries](#evidence-and-safety-principles)
- [Owner desktop interface](#owner-interface)
- [Dates and session values](#date-and-session-values)
- [Static design reference](#design-reference)

<a id="book--product-definition"></a>
## Product definition

Health-Check is a **single-user, local-first personal health observatory** for one person using a Windows laptop. It combines long-term source evidence, deterministic/reproducible analytics, life context, and a bounded local laboratory-document intake. A visual dashboard and a conversational AI interface are equal product surfaces over the same evidence layer.

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


<a id="product-decisions"></a>

<a id="product-decisions--priorities-and-accepted-product-decisions"></a>
## Priorities and accepted product decisions


The health-domain order is Weight/body composition → Sleep → physical activity
and fitness → recovery and general wellbeing. It is distinct from the next
implementation task. Observe sustainable trends/recomposition with algorithm
boundaries; compare sleep sources honestly; preserve activities and make saved
session/cycling comparison useful; interpret source recovery metrics without
inventing a universal score.

The accepted product decisions are:

- One chronological full saved Weight+composition table and a single selected
  composition-metric chart retain true measurement identities, observed dates,
  incompatible-method groups and original evidence. Derived fat and lean mass
  are complementary; source muscle mass is not lean mass.
- Normal wearable concepts are **Garmin and Google**. Exact device/account/family
  identities remain available for eligibility and advanced selection; overlapping
  observations are not implicitly pooled, summed or selected by display label.
- A clearly labelled last eligible saved value, with its actual date and age,
  can be useful when the selected day lacks evidence. It is not today's value,
  a successful provider call or permission to rewrite a selected query window.
- Statistics offers bounded 7/30-day, trailing-365, calendar-year and YTD
  source-specific views. The separate **Steps-only** all-time choice reads one
  explicit Garmin source's saved completed days; it does not make every metric
  all-time or establish complete Garmin account history. Other metric periods
  stay independent. Full saved-search and provider coverage are different claims.
- Comments are a primary navigation section. Normal instant input selects a
  human city/IANA zone; the exact UTC offset is derived and persisted internally.
  Date-only stays date-only; DST ambiguity must be validated.
- Saved measurements stay visible separately from auth/refresh failures. The A+
  visual/language system applies across forms and tables; it is not a request
  for another global redesign or a second analytics engine.
- New Activity value/design questions are bounded, read-only Owner-led discovery,
  not automatic cards, provider features or invented aggregations. A request for
  a screen never authorizes provider calls, runtime deployment or new mathematics.

The decision lineage is the dated Owner direction in the
[original product record](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/PRODUCT_VISION.md#owner-direction--2026-10-11-after-complete-a-integration),
[#321](https://github.com/LTstripes/Health-Check/issues/321),
[#322](https://github.com/LTstripes/Health-Check/issues/322) and their accepted
source-specific deltas. Delivered versus remaining issue work, the partial human
UAT and separate installed-version evidence have one current home in
[Project Wiki](PROJECT_WIKI.md#current-canonical-state). Old dated status does not
reassign completed implementation. The all-time Steps delta is
[PR #458](https://github.com/LTstripes/Health-Check/pull/458); its bounded semantics
are owned by [Architecture](ARCHITECTURE.md#garmin-steps).

<a id="product-decisions--sources"></a>
## Sources

- **Xiaomi Body Composition Scale S400:** the accepted operational path is historical/routine screenshot import; openScale/openScale-sync compatibility remains an optional delivered contract, with #153 closed as not planned.
- **Garmin Vivoactive 5 / Garmin Connect:** released ingestion, historical backfill, deterministic analytics and owner dashboard; current collection health still needs source-specific evidence.
- **Google Health API v4:** released ingestion for sleep and supported health metrics/measurements, with preserved source/device metadata and explicit source-family semantics.
- **Google wearable / Fitbit evidence:** device-level agreement requires explicit persisted Fitbit/device attribution. Broader wearable-family and account observations are not automatically device evidence.
- **Free-text context:** Context Capture v0 stores revisioned original text, dates/instants/intervals; the existing desktop portal, primary Comments navigation and city/IANA input are delivered. This is one revisioned note system; direct conversation access is a separate connection decision.
- **Laboratory documents (#348):** the local PDF plus structured transcription draft intake is integrated, with review/correction, explicit confirmation, revisions and original download. Real Owner UAT and chat-to-local transport remain unverified; medication/supplement and other personal-health-record capabilities remain separately scoped.

Every source value remains available. A canonical rule may select one value for one metric/period, but selection never deletes competing evidence.

<a id="product-decisions--source-display-is-not-a-canonical-source-decision"></a>
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

<a id="product-decisions--core-usage-modes"></a>
## Core usage modes

<a id="product-decisions--automatic-reviews"></a>
### Automatic reviews

Planned recurring reviews remain Sunday weekly, month-end and annual reviews.
Each review is computed from deterministic evidence, then rendered for the selected
dashboard/chat/email/delivery channel. Missing coverage remains part of the result,
not something hidden by prose. Scheduled delivery is not implemented by this plan.

<a id="product-decisions--ad-hoc-investigation"></a>
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

<a id="product-decisions--life-context-without-diary-friction"></a>
## Life context without diary friction

The primary context object is an event/exposure interval, not a mandatory daily
questionnaire. Preserve the Owner's original wording, explicit date/time precision,
capture source and optional confirmed tags. Event time and recorded-at are distinct;
date-only input must not acquire invented midnight/UTC. Revisions preserve history.

The portal is the delivered convenient capture path; ChatGPT is the requested
conversation surface. Telegram remains optional. Obsidian is optional and not a
canonical health store. Routine notes must ultimately be recorded in the durable
Owner profile: a note in a disposable UAT clone is not automatically a Stable note.

<a id="product-decisions--evidence-and-safety-principles"></a>
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
- Keep owner secrets and real datasets outside Git and code fixtures. Owner-authorized read-only analysis and normal presentation in the AI conversation follow [Owner data workflow](OWNER_OPERATIONS.md#owner-data-boundary); personal values do not require automatic masking.
- Distinguish synthetic fixtures, a disposable copy of real data and the durable live profile. A code update does not refresh copied source data.

<a id="product-decisions--product-boundaries"></a>
## Product boundaries

Dashboard and AI are equal interfaces, but analytics truth lives below both.
UI/LLM code must not become a second mathematics engine. New source fields,
aggregations, persistence and connection boundaries require their owning task's
accepted contract; a request for useful cards is not permission to guess units,
average categorical statuses or add overlapping rolling-load snapshots.

No custom Health-Check Recovery Score is scheduled until R05+ evidence demonstrates
a concrete unmet need. Any future score must be transparent, versioned,
component-attributed and explicitly non-medical.

<a id="product-decisions--future-personal-health-record"></a>
## Future personal health record

The first R09 laboratory/document slice under #348 is integrated in
[PR #474](https://github.com/LTstripes/Health-Check/pull/474): an unchanged PDF plus
a versioned structured manual/assistant transcription draft enters local staging,
review/correction and explicit confirmation, followed by a report list, original
download and full-snapshot revisions. The [v1 contract](LAB_INTAKE_V1.md) preserves
raw/exact values, nullable units/ranges, distinct source/date roles and honest
provenance. One PDF must contain one report for one patient; unresolved linkage
blocks confirmation. Confirming selected rows may be explicitly partial and does
not imply field-by-field source verification.

#348 remains OPEN pending real Owner UAT. Chat-to-local transport is unverified;
Stable rollout has not been performed. OCR, interpretation, charts, cloud bridge,
#341 export, medication/supplement timelines and longitudinal analysis remain
outside this delivered slice. Transcribed or accepted data is not a diagnosis.

<a id="product-decisions--repository-rule"></a>
## Repository rule

Code, schemas, tests, synthetic fixtures and sanitized engineering evidence belong
in Git. Real health data, screenshots, raw provider payloads, credentials/tokens,
databases, generated private reports and personal documents do not.

<a id="owner-interface"></a>

<a id="owner-interface--owner-desktop-interface"></a>
## Owner desktop interface


The Owner approved Overview A+ on **2026-10-07** in
[#322](https://github.com/LTstripes/Health-Check/issues/322), with the text-only
synthetic reference below. It supersedes the conflicting #189 visual freeze:
the older canvas/surface/ink/muted/separator/sunken/interaction colors,
sans-only prominent heading, 1100px content limit and quieter selected navigation
are historical. The following tokens are the current visual contract. Source,
state, accessibility and privacy boundaries remain binding; visual approval does
not certify implementation, provider health or every later Owner UAT.

<a id="owner-interface--navigation-and-current-routes"></a>
### Navigation and current routes

| Primary section | Route | Current surface |
| --- | --- | --- |
| Обзор | `/brief` | A+ Weight/Sleep/Activity readings and source-backed graphs, secondary metrics, compact actions and disclosed evidence |
| Вес | `/` | Confirmed Weight/trend, one all-history Weight+composition table and selectable chart with distinct methods (#375) |
| Сон | `/sleep` | Primary 7/30-day Garmin + Google duration timeline over exact saved sources, with display toggles, point details and an accessible date table; Garmin / Google / Compare selected-date modes remain |
| Сон, secondary mode | `/agreement` | Exploratory Garmin/Google comparison and diagnostic evidence |
| Статистика | `/statistics` | Garmin/Google 7/30, trailing365, calendar-year/YTD; saved completed Garmin daily Steps and a separate exact-source Steps-only all-time selector; Google Steps not collected |
| Активность | `/garmin#activity-journal` | Five recent saved sessions, full existing history disclosure and five-column A/B comparison |
| Активность, secondary mode | `/garmin#training-recovery` | Garmin dated snapshots, period series and exploratory lagged associations |
| Данные | `/imports` | Compact provider freshness/actions with stream details; upload/review queue and `/imports/{id}` |
| Комментарии | `/context` | Revisioned Context with primary navigation and city/IANA timezone chooser |

The brand opens Overview at `/brief`; the legacy root remains Weight. Existing
API/query/import contracts are not redefined by navigation. The Data queue describes
its bounded recent-batch inventory, not an exhaustive count of all history.
The `/context` primary navigation and city/IANA chooser are delivered. Statistics
also includes saved-session drilldown; completed navigation/timezone/drilldown
must not be reassigned. Provider-first presentation is integrated, while general
per-metric eligible-source discovery/autoselection remains open.

<a id="owner-interface--one-a-visual-and-language-system"></a>
### One A+ visual and language system

Warm editorial paper, dark ink, dark green actions and thin section rules; no dark
theme, shadows, gradients, full pills, ordinary card accent stripes or health grades.
Use existing variables in `dashboard.css`:

| Role | Variable | Accepted value |
| --- | --- | --- |
| Canvas | `--bg` | `#f6f2e9` |
| Surface | `--card` | `#fdfbf6` |
| Main text | `--ink` | `#292d27` |
| Supporting text | `--muted` | `#686c61` |
| Fine separators | `--line` | `#dcdccc` |
| Actions, selected navigation and focus | `--accent`, `--owner-focus` | `#31584b` |

The supporting sunken surface is `#efeee5`, light enough to keep A+ muted text
above 4.5:1 contrast. Stronger line `#c9c0b3` and accent-soft `#e6f1ef` are retained.
Hairlines organize sections; they are not the sole focus or selection cue.
Text must retain accessible contrast on each shared surface.
State fills remain attention `#f6efe2` / ink `#6b4510`, unavailable `#f3e4d4` /
ink `#6b320c`, and request error `#f8eceb` / ink `#7a2424`.
Series retain their roles: observed `#1d4e89`, derived trend `#9a4f1a`, reference
`#5c4d86`, comparison source `#3f5f73`. Do not recolor every graph with the action
green or confuse observations, trends and references. Colors do not score health.

Use local Georgia / Times New Roman / serif for the prominent desktop page `h1`
(42px, weight 400, line-height 1.1). Prominent page values use the accepted A+
page-specific hierarchy. Body, controls, tables, section headings and metadata
use local Segoe UI / Helvetica Neue / Arial / sans-serif, body line-height 1.5
and ordinary hierarchy weight 600. Values/tables retain tabular numerals.
Page hierarchy stays primary section (`h1`), current screen/sections (`h2`),
subsection (`h3`). Uppercase small editorial kickers are optional; never uppercase
all headings or ordinary copy. No external fonts/assets are loaded.

The desktop shell has a 1440px maximum content width and 48px horizontal gutters;
the top bar aligns with that content, is at least 83px tall, and stays sticky.
Navigation uses one row with 24px gaps. Its selected link has green text, weight
600 and a square 2px underline, plus `aria-current="page"`. Prominent titles and
the footer have 1px section rules. Existing 4/8/12/16/24/32px spacing and 8/6/4px
card/button/chip radii remain available; top-navigation links have square corners.
Legend samples stay 8px squares with a dashed configured goal/reference sample.
Later pages reuse these tokens rather than inventing local design systems.

The shell and redesigned primary pages are Russian under `html lang="ru"`. Proper
names and exact technical codes remain unchanged. Legacy batch-review bodies can
retain an explicit English boundary until separately translated; do not claim all
legacy routes are localized. Frozen shell copy includes `К содержимому`, navigation
label `Основные разделы`, and the footer:

> Интерфейс только на этом компьютере. Потребительский BIA — не клиническое измерение. Нет диагнозов и утверждений о причинах.


<a id="owner-interface--visible-evidence-and-request-states"></a>
### Visible evidence and request states

Interpretation-changing limitations stay visible. Missing/unknown/unavailable
evidence is not zero; a genuine source zero remains a real observation. Loading
and error describe requests. “No change” needs an explicit comparison, not absent
evidence. Detailed provenance, hashes, exclusions, algorithms and diagnostics stay
available through keyboard-accessible native disclosures; a disclosure is a
presentation pattern, never a privacy/access boundary. Informational canonical or
algorithm banners are status, not request errors. Failed refresh does not erase
saved history, and HTTP success does not prove healthy collection.

The full shared state keys and domain-specific evidence limits have one technical
home in [Architecture — UI evidence states](ARCHITECTURE.md#ui-evidence-states).
Source-specific summaries are not automatically interchangeable. Sleep does not
substitute a previous night for an explicitly selected wake date, pool ambiguous
same-date records or change Agreement/canonical gates. Activity adds no causal
claim, invented recovery-time unit or best-lag ranking.

<a id="owner-interface--desktop-scope-and-request-behavior"></a>
### Desktop scope and request behavior

The [Owner decision #321, 2026-10-07](https://github.com/LTstripes/Health-Check/issues/321)
sets desktop/laptop CSS viewports **1024px and wider** as the supported target.
Phone, tablet and windows below 1024px have no design, browser-test or Owner UAT
requirement. Earlier #189/390px expectations are historical. Existing small-window
CSS fallbacks remain without a new support obligation.

Controls, navigation/brand links and information summaries keep at least 44px hit
targets and visible 3px green keyboard focus. Preserve tab order, the first Tab skip
link, its focus transfer to content, and native Enter/Space disclosures. Wide tables
and charts scroll locally in `.table-scroll`/`.chart`, not at page level. Tables keep
real table layout and sticky muted headers. Accessibility/security evidence remains
required at desktop widths.

Data uses persisted-source evaluation, not provider calls. #305 exposes sanitized
failure classes and honest extractor configuration. Dated performance observations are retained in Wiki/history; they do not define a portable response-time promise.


Activity clears prior evidence on submissions and rejects late completions. One usable Garmin source needs no redundant selector; multiple identities require explicit selection. This Activity rule does not establish universal per-metric source autoselection.

<a id="owner-interface--saved-evidence-and-source-specific-page-behavior"></a>
### Saved evidence and source-specific page behavior

Everyday cards may offer **“Последние доступные: DD.MM.YYYY (несколько дней назад)”**
from the most recent eligible current saved observation, retaining exact
source-local date, coverage/age and snapshot-origin disclosure. Still state when
the queried day has no observation. Never present an older saved value as measured
today or imply its provider is healthy. Explicit dates/periods stay fixed; numeric
provider deltas require compatible actual windows and denominators. Ambiguous
eligible identities and unavailable sources are not zero.

Weight/composition uses one full saved confirmed-measurement table and one selected
metric chart. Align by persisted measurement identity, not coincident date/weight.
Absent metrics stay blank. The global date axis does not connect incompatible
methods; compact details retain exact rows/provenance rather than duplicating
per-group tables.

Sleep retains the exact-source 7/30 timeline, role/ambiguity/missing states, native
Garmin score detail and secondary Compare. Google Fitbit/device and wearable-family
aggregate identities may overlap; Sleep-only source selection cannot become a
guessed device preference or a default for all physiology/Steps. Advanced choices
retain every original identity and evidence, without an R05 canonical switch.

Statistics keeps exact selectors/provenance in native details while ambiguity and
incomplete warnings remain visible when closed. Inventory is not proof of metric
availability. The Steps completion display policy is Europe/Moscow, excludes the
current/future days, and retains repeats, lower corrections, ties and latest
missing states. It does not claim Garmin finality. The five-second guard is
cooperative, not a hard SQL/lock/I/O deadline or a performance guarantee. Steps-only
all-time and the v2 bounded view remain separate versioned contracts.

Data has one compact provider action/status with stream details. Stream chronology,
refresh attempts, eligible metric values/dates and clone age are different facts.
Comments retains revision, date-only/DST/offset semantics; UI delivery does not
automatically establish a durable real-profile save/edit acceptance result.

Use one shared A+ system across Data/Context/Activity/Weight/Statistics. Shared CSS,
shell and templates have one writer. Existing session history/details/A–B are not
a reason to reimplement old cards. Detailed delivered/remaining status is only in
[Project Wiki](PROJECT_WIKI.md#current-canonical-state). UI and source architecture stay
distinct from deployment, real provider recovery and human Owner UAT.


<a id="date-and-session-values"></a>

<a id="date-and-session-values--date-and-session-value-presentation"></a>
## Date and session-value presentation


Presentation uses the existing Russian human-date style
for Comments list/detail/revision history, Statistics period/Steps labels, Overview
point titles, Weight current date, import-review dates and Data chronology. Native
form values, API fields, data attributes and technical evidence retain ISO values.
The shared JS helper validates Gregorian days/leap years, clock fields and numeric
offset bounds before display. Absent values show «Дата не указана»; supplied invalid
values show «Некорректная дата/время», without normalizing or converting the source string.
Comments keep event-local date/time, explicit offset, IANA zone when saved and
minute/second/fraction precision. Automatically recorded time is labelled separately
in UTC; it is never substituted for event time. Date-only never acquires midnight.

Statistics saved-session rows and Activity detail display native seconds as hours,
minutes and residual seconds, and native metres as kilometres. They reuse the
Statistics headline rounding (half-up to 0.01 second / 0.01 km); positive values
below display precision read `<0,01 с` / `<0,01 км`, while true zero stays zero.
Extreme values of at least a billion hours or kilometres use an explicitly
approximate, three-significant-digit scientific label (≈… × 10^… ч / км), keeping
primary text bounded. Formatting has its own magnitude-sized Decimal context;
exact native values and units remain in technical disclosure. Missing, invalid,
wrong-unit and partial states retain their existing meanings.


<a id="date-and-session-values--verification-meaning"></a>
### Verification meaning

Desktop acceptance uses representative **1024/1440px** widths. It retains source
truth, chart points/endpoints, readable axes, focus, pointer/keyboard behavior,
imports/unconfigured extraction, native disclosures, comparisons, tables and
request races/errors. #321 retired phone-target/breakpoint/tick-density loops,
not functional/security/privacy coverage, CI, Windows or product guards.
Pytest retains viewport/skip-link/focus/hit-target/table contracts. Focused script
selection and exact-candidate evidence belong to
[Development UI verification](DEVELOPMENT_PROCESS.md#owner-ui-verification).

Synthetic browser evidence and CI do not prove human Owner UAT. Static-reference
approval is a design decision, not acceptance of every later implementation.
The latest dated human result and any unperformed private gates are separated in
[Project Wiki](PROJECT_WIKI.md#current-canonical-state); unperformed gates stay UNVERIFIED.


<a id="design-reference"></a>

<a id="design-reference--static-a-design-reference"></a>
## Static A+ design reference


One proposed visual reference for [#322](https://github.com/LTstripes/Health-Check/issues/322), following the desktop-only decision in [#321](https://github.com/LTstripes/Health-Check/issues/321). This does not change the production visual or data contract.

Open [index.html](design/owner-overview-a-plus/index.html) directly from disk. All CSS and SVG are inline; there are no scripts, fonts, external assets, servers or data connections. The page explicitly labels every observation and date as synthetic. The fixed example covers **1–7 June 2099**, as of 7 June at 18:10 in a fictional UTC+03:00 context.

> **Preview policy:** render `index.html` locally to see the design. The synthetic 1440px PNG was produced for Worker-local review but is deliberately **not committed**: the existing repository privacy/hygiene gate forbids image binaries, even synthetic ones.

<a id="design-reference--approved-decisions-in-the-reference"></a>
### Approved decisions in the reference

| Decision | Location |
| --- | --- |
| Astra A: warm paper, dark green accent, serif heading and main values | Page palette `#f6f2e9` / `#fdfbf6`, ink `#292d27`, green `#31584b`; Georgia heading and values; fine separators, no nested cards, shadows or gradients |
| Compact navigation and period | Single top navigation, 7/30/90-day controls and alternative date range; no introductory hero |
| Action only when needed | One short row for the illustrated failed Garmin freshness check; explicitly keeps saved data available |
| Grok: immediately useful readings and charts | Weight, last Garmin night and saved sessions in three equal desktop columns; observed weight points separate from the trend, sleep history, dated daily activity strip and types |
| A+: quieter supporting metrics | Resting pulse, nightly HRV, stress and Body Battery below the primary row, each with its own source/date/window and small history graphic |
| Context on demand | Three keyboard-operable `ⓘ` disclosures, one source table and one technical disclosure; source/date/units and material gaps remain visible in the main view |
| Honest availability | Missing weight/sleep observations; unknown activity coverage on 04 June; explicit zero saved sessions on covered days; explicit Google zero steps separately from absent Google pulse |
| Source and window separation | Garmin and Google never pooled; provider sleep score separate from duration; last HRV night differs from last sleep night; partial-day stress differs from point-in-time Body Battery |

The weight trend is a manually authored illustration of three-observation means (74.70, 74.57, 74.43 kg), not application analytics. All SVGs have accessible numeric descriptions. Gap marks and a dashed interval distinguish missing observations from measured values. Color conveys no health assessment or threshold.

<a id="design-reference--static-and-functional-parts"></a>
### Static and functional parts

- **Functional without JavaScript:** native disclosure open/close, keyboard focus and skip-to-content link.
- **Non-functional by design:** navigation, period buttons and alternative dates. The page labels them as a mockup; buttons expose `aria-disabled`. There are no other pages, imports or refresh actions.
- **Desktop only:** minimum 1024 CSS px. No phone/tablet design, screenshots or acceptance checks.

<a id="design-reference--focused-local-verification"></a>
### Focused local verification

Checked in Chromium **151.0.7922.34** with an offline browser context and page JavaScript disabled, loading `index.html` via `file:`. The Worker-local PNG (outside this Git revision) is a full-page capture from a **1440 × 1000 CSS px** viewport (1440 × 1231 image pixels, device scale 1). The same page was also rendered and inspected at **1024 × 1000**; its diagnostic capture is local evidence, not another design option.

| Check | 1440 px | 1024 px |
| --- | --- | --- |
| Three primary columns retained | Pass | Pass |
| Page/content horizontal clipping or overflow | None | None |
| Source table and technical disclosure expanded | Pass; no horizontal overflow | Pass; no horizontal overflow |
| All five native disclosures via Tab / Enter / Space | Pass | Pass |
| Visible focus; buttons and summaries at least 44 px high | Pass | Pass |
| Computed paper background and layout CSS loaded | Pass | Pass |
| External page requests / script errors | 0 / 0 | 0 / 0 |
| Visual reading hierarchy, gaps, labels and expanded content | Inspected | Inspected |

The HTML artifact is retained byte-identically; its explanatory contract is in this chapter. generated PNG evidence must remain outside Git. No production UI, API, analytics, provider, database, tests or shared UI policy changed. No private data or real screenshots were used. Product tests and Owner UAT were not run for this static reference. CI status is reported separately for the pushed commit; local browser checks are not CI or Integrator acceptance.

The optional CBM policy creates no used/skipped bookkeeping duty.
