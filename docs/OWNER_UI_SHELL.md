# Owner UI — approved A+ desktop shell

On **2026-10-07 the Owner visually approved Overview A+** in [#322](https://github.com/LTstripes/Health-Check/issues/322).
The canonical [text-only synthetic reference](design/owner-overview-a-plus/index.html)
and its [explanation](design/owner-overview-a-plus/README.md) govern the shared desktop
appearance under [Stage A #326](https://github.com/LTstripes/Health-Check/issues/326).
This supersedes the conflicting #189 visual freeze: the previous canvas, surface,
ink, muted, separator, sunken and interaction colors, sans-only prominent heading,
1100px content limit and quieter selected navigation. The values below remain the
single current visual contract; old values in Git history are historical.

The accepted source/state/accessibility/privacy boundaries remain binding. A+ shared
shell and actual Overview (#326/#328), Sleep v3 (#317), Activity A/B v3 (#318),
Activity v4 (#335), Overview Weight clarity (#334) and compact source attention
(#333) are now integrated. Do not describe their page content as still awaiting
Stage A. Human UAT #330 is **PARTIAL**: positive design/Weight/Activity-history
feedback and unresolved source/Sleep/functionality requests coexist. Exact
implementation/CI and local evidence live in [Current History](EXECUTION_HISTORY_CURRENT.md).

## Navigation and current routes

| Primary section | Route | Current surface |
| --- | --- | --- |
| Обзор | `/brief` | A+ Weight/Sleep/Activity readings and source-backed graphs, secondary metrics, compact actions and disclosed evidence |
| Вес | `/` | Confirmed Weight/trend, one all-history Weight+composition table and selectable chart with distinct methods (#375) |
| Сон | `/sleep` | Primary 7/30-day Garmin + Google duration timeline over exact saved sources, with display toggles, point details and an accessible date table; Garmin / Google / Compare selected-date modes remain |
| Сон, secondary mode | `/agreement` | Exploratory Garmin/Google comparison and diagnostic evidence |
| Статистика | `/statistics` | Garmin/Google 7/30, trailing365, calendar-year/YTD; saved Garmin daily Steps; all-history and Google Steps pending |
| Активность | `/garmin#activity-journal` | Five recent saved sessions, full existing history disclosure and five-column A/B comparison |
| Активность, secondary mode | `/garmin#training-recovery` | Garmin dated snapshots, period series and exploratory lagged associations |
| Данные | `/imports` | Persisted freshness/actions plus upload/review queue; batch details under `/imports/{id}` |

The brand opens Overview at `/brief`; the legacy root remains Weight. Existing
API/query/import contracts are not redefined by navigation. The Data queue describes
its bounded recent-batch inventory, not an exhaustive count of all history.
The implemented `/context` page is presently a secondary link; **Owner-approved next UI** promotes **Комментарии** to a discoverable primary navigation item, retaining the same revisioned route. Statistics `/statistics` already implements 7/30 and bounded 365/calendar-year/YTD; all-history and meaningful provider-first source defaults remain follow-ups.

## One A+ visual and language system

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

## State and evidence contract

`templates/owner_ui.html` supplies `state_chip(state)` and the native, initially
closed `technical_details()` caller block. The ten shared keys are `present`,
`partial`, `confirmed_empty`, `unknown`, `unavailable`, `insufficient`,
`not_requested`, `loading`, `error` and `no_change`. Unrecognized states display as
unknown. Loading/error describe requests; no-change requires an explicit comparison,
never missing evidence. Missing values are not zero; explicit source zero is real.

Interpretation-changing limitations stay visible. Detailed provenance, hashes,
exclusions, algorithm names and diagnostic statistics remain accessible behind
disclosure. Disclosure is a presentation pattern, not a privacy/access boundary.
It stays keyboard accessible without JavaScript. Informational algorithm/canonical
banners are `status`, not request errors. A failed refresh does not erase stored
history; an HTTP-successful check does not imply healthy collection.

Overview presentation does not pool sleep groups or change packet/hash semantics.
Weight retains canonical/algorithm boundaries. Sleep never substitutes a previous
night for the selected wake date or silently combines ambiguous same-date/source
evidence. Agreement remains exploratory and cannot choose a canonical source.
Activity does not add thresholds, recovery-time units, causal claims or best-lag
ranking. Source-specific aggregates are not automatically interchangeable.

Integrated boundaries include:
- #307 bounds only the Google daily-vitals display read to the trailing 400 inclusive days for longer custom periods and visibly discloses that scope; full Period Brief/Garmin period unchanged.
- #317 source-only account observations reuse accepted R05 eligibility, uncertain roles, exact wake dates and evidence. They do not loosen legacy device/family Compare or canonical rules. Google daily vitals are not within-sleep measurements; Google vendor-score availability is not promised.
- #318 preserves B−A and percent-to-A, blocks self-comparison, clears stale evidence and retains exact seconds in technical output. Power/cadence are hidden only when both sides lack eligible values. #335 folds history, not data.
- Only evidenced `tennis_v2` maps to Теннис; no generic `_v2` normalization or persistence change follows.

## Desktop scope and request behavior

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
failure classes and honest extractor configuration. Its earlier 15-second timeout
was real; the later observed endpoint and screen result are progress, not proof
that copied Garmin/Google collection errors have been recovered. Activity clears
prior evidence on submissions and rejects late completions. One usable Garmin
source needs no redundant selector; multiple identities require explicit selection.

## Accepted engineering and Owner UAT decisions — 2026-10-11

Latest accepted **product** before these documentation edits:
[`main fa36dc5b…`](https://github.com/LTstripes/Health-Check/commit/fa36dc5b6402fe6e6e166091002faf4af1ec0993);
[post-main CI 38164560091](https://github.com/LTstripes/Health-Check/actions/runs/38164560091)
SUCCESS attempt 1. It includes #343 eligible Google Sleep, #345 Activity
session detail, #344 Overview connectors/Sleep ticks, #375 Weight all-history,
#376 latest eligible RHR, #347 readable Statistics sources, #380 365/calendar
year/YTD and #377 Garmin typed Steps saved projection/window/Statistics UI.
Do not relaunch completed functionality.

The latest [Owner UAT #330](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6113161066)
used the accepted code with a verified *as-of-2026-10-08 disposable clone of
real saved data*, not a refreshed Stable profile. A+ direction positively
received, but **Owner UAT PARTIAL**: Weight table exposes binary float
tails/ISO row dates, Statistics has five technical Google identities,
Overview RHR is too verbose and Body Battery is last snapshot rather than a
certified day maximum; Data repeats copied reauth/refresh warnings and
Comments is a small link on every heading. Fresh full clone integrity is
UNVERIFIED; first/repeat `/brief` 23.098/9.470s with uncontrolled cache.
See [UAT checkpoint and exact issue owners](OWNER_UAT_CHECKPOINT_2026-10-11.md).
The product deltas below are **not automatically shipped** by this decision.

### Historical evidence and dates versus today's data

Default everyday reading cards can offer **"Последнее доступное: DD.MM.YYYY
(несколько дней назад)"** from the most recent **eligible current saved**
observation, with exact source-local date, coverage/age and snapshot-origin
disclosure; still state if there was no observation on the queried day. Never
say that a saved older value was measured *today* or that its originating
provider is currently healthy. Explicitly selected dates/periods remain fixed:
do not silently change the user's query window, compute a numeric provider
delta between mismatched actual windows or hide a missing day. An unavailable
source or ambiguous eligible identity is not a zero. The reusable contract is
[#376](https://github.com/LTstripes/Health-Check/issues/376); today's
#376 first Overview RHR last-eligible consumer is already merged; broader metric-specific defaults and other cross-screen adapters still need their separate contracts.

### Weight / composition

[#375](https://github.com/LTstripes/Health-Check/issues/375) **already delivered** the Owner's
chosen simplification: **one longitudinal full-history table** for confirmed
measurements, weight, body-fat % (source), derived fat/lean kg and separate
muscle kg (source), with understandable source/method labels. Align by real
persisted measurement identity, not coincident date/weight; absent metric
remains blank. One selectable-metric chart shares a global date axis, while
different incompatible method groups remain distinct/never connected.
Compact details preserve exact rows and provenance, not per-group duplicate
tables. Derived fat+lean is complementary; the vendor muscle estimate does
not equal lean mass.

### Sleep and Statistics

The **already delivered** 7/30 Sleep chart, source-only role/ambiguity/missing
states, native Garmin score detail and secondary Compare stay. Normal Owner
display should have the two conceptual providers **Garmin and Google**.
A Google Fitbit data source and Google family-aggregate are internal saved
identities; require an evidence-backed default/exact eligible overlap decision
under [#342](https://github.com/LTstripes/Health-Check/issues/342) before
reducing visible source lines. Neither a guessed Fitbit preference nor an
implicit family/device pool is acceptable. Advanced display retains every
exact identity and original evidence; no R05/canonical switch.

Statistics already supports source-specific **7/30, trailing 365,
calendar-year and year-to-date** windows; all-history is still a separately
bounded #380 scope. Human source labels were delivered under #347, but
five exact Google identities and empty entries remain **Owner UAT friction**.
Follow-up [#347](https://github.com/LTstripes/Health-Check/issues/347)
must offer normal Garmin/Google provider choices and evidence-backed exact
metric-specific defaults/advanced selection without source pooling. The
[#342](https://github.com/LTstripes/Health-Check/issues/342)
`google-wearables` family preference is valid for **Sleep only**, never
applied automatically to all Google physiology or Steps.

**Garmin observed daily Steps #377** are already typed over saved
`calendarDate/totalSteps` and visible in Statistics through an exact-source,
bounded read-only reader. Normal successful Garmin post-save projector wiring
is #395 and full historical UAT-clone projection remains a separate authorized
operation; Google Steps acquisition/type evidence is #392. Never turn missing
or `projection_unavailable` into zero. **Calories #319** remain blocked by
energy/BMR meaning. Source-specific per-period averages (RHR #393) and Body
Battery day max vs last-snapshot (#394) require acceptance before changing
existing values; provenance/error detail remains accessible.

### Data, Comments and common style

- Data keeps saved-measurement date/age apart from provider **refresh**
  success/failed/reauth and snapshot origin; copy of old failed sync does not
  establish present-day upstream failure. One concise provider action and
  expandable per-stream details; [#305](https://github.com/LTstripes/Health-Check/issues/305).
- The Owner wants **Комментарии** in the **primary navigation**. The current
  `/context` CRUD is delivered but too hidden; primary form should use one
  **human city/IANA timezone selector** with local event date/optional time.
  Store the derived exact UTC offset and zone as before; no required UTC
  textbox in routine UI. Date-only has no timezone/midnight instant; DST
  ambiguous/nonexistent times need strict validation, explicit disambiguation
  only when actually needed. [#294](https://github.com/LTstripes/Health-Check/issues/294).
- Maintain one A+ system throughout the app; Data/Context/Activity/Weight/
  Statistics tables and forms need proportionate shared typography,
  spacing, controls and readable source labels. [#379](https://github.com/LTstripes/Health-Check/issues/379)
  owns the cross-screen audit, not a new full redesign or mobile test suite.
  Only one writer at a time for shared CSS/shell and impacted templates.
- Current Activity detail and A/B work. Owner-requested **future functional
  analytics discovery** [#378](https://github.com/LTstripes/Health-Check/issues/378)
  takes precedence over duplicate #346 four-card implementation. #348
  laboratory documents, #357 personal stress baseline and weight-goal Settings
  remain separately gated future slices.
- #341 standalone export/MCP code exists, while direct authenticated ChatGPT
  connection stays deferred. UAT clone notes do not become durable Stable
  notes automatically.

Do not equate CI, synthetic browser success and Owner UAT. No reference screenshot,
working runtime, Saved data, provider credentials or private profile is moved to
GitHub through this document.

## Verification and post-UAT follow-up

Focused `scripts/check_owner_{data,brief,weight,sleep,activity}_browser.cjs`, shared
`check_owner_acceptance_browser.cjs` and relevant page-specific checks use
representative **1024/1440px** desktop widths. No suite/CI lane/Windows/guard is
removed and no skip/xfail replaces functional coverage. Exact gates follow
[Development Process](DEVELOPMENT_PROCESS.md#13-ci-evidence-and-complete-suite-gates).

#321 retired only phone-target loops, one-column/breakpoint ordering, forced
narrow-table/phone tick-density expectations. Desktop checks retain source truth,
chart points/date endpoints, readable axes, focus, pointer/keyboard, imports,
unconfigured extraction, disclosures, comparison, tables and request race/errors.
Pytest retains viewport/skip-link/focus/targets/table contracts. Legacy Brief packet
checks select `.brief-packet`; Google-vitals checks use its source view/disclosure;
the missing Garmin night check remains separately source-specific.

Synthetic browser evidence and CI do not prove human Owner UAT. #330 records the
latest **partial real review**, including the requested Sleep experience and data
questions. New candidates' unperformed private gates remain UNVERIFIED. The static
reference approval was a design choice, not automatic acceptance of every later
implementation. Historical #189 and #305–#309 checks/failures are retained in their
issue/PR records. #295 was reopened for new latency evidence; #298 remains not planned.

## Date and session-value presentation (#379 / #378 candidate)

The 2026-10-12 presentation candidate uses the existing Russian human-date style
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
Exact native values and units remain in technical disclosure; missing, invalid,
wrong-unit and partial states retain their existing meanings.

This describes a candidate on baseline `aca4b8f65eb276dddb3ae5de718a734afd19f369`,
not an integrated main or Stable release. Independent acceptance, integration,
rollout and real Owner UAT are pending. Steps availability is a separate diagnosis.
