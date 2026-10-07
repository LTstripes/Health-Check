# Owner UI shell and thematic pages — #189

The shared interface follows the [accepted IA](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5854312903)
and the [frozen visual system](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5979374375).
Stages 1–7 are integrated and #189 is closed. The post-UAT Weight v3, Overview v2, Sleep v2 and Activity v2 wave (#306–#309) is also integrated. #305 diagnostics/import presentation is integrated, with the real freshness timeout still open. Consolidated Owner UAT on 2026-10-07 generated the next bounded follow-ups; it does not silently reopen the frozen shell/IA contract.
Exact implementation/CI checkpoints and recorded Owner UAT live in [Current History](EXECUTION_HISTORY_CURRENT.md).

## Navigation and current routes

| Primary section | Route | Current surface |
| --- | --- | --- |
| Обзор | `/brief` | За период: deterministic Period Brief plus source-explicit Garmin/Google values, facts, actions and limitations |
| Вес | `/` | Current confirmed weight, trend/change, configured goal, readable timelines and separate composition-group spans |
| Сон | `/sleep` | Garmin / Google / Compare views; selected wake-date Garmin night/history and separate source-explicit Google daily vitals |
| Сон, secondary mode | `/agreement` | Exploratory Garmin/Google comparison and diagnostic evidence |
| Активность | `/garmin#activity-journal` | Сессии: saved Garmin sessions and explicit Session A / Session B comparison |
| Активность, secondary mode | `/garmin#training-recovery` | Тренировки и восстановление: Garmin snapshots, period series and exploratory lagged associations |
| Данные | `/imports` | Source freshness/actions plus the existing upload/review queue; batch details remain under `/imports/{id}` |

The brand opens Overview at `/brief`; the legacy root remains Weight. The new `/sleep`
route is the primary Sleep destination, while `/agreement` remains available. Existing
API/query/import contracts are not redefined by navigation. The Data queue describes its
bounded recent-batch inventory, not an exhaustive count of all history.

## One frozen visual and language system

Warm light paper, dark ink and one interaction accent; no dark theme, shadows, gradients,
full pills or ordinary card accent stripes. Primary tokens are canvas `#f3f1ec`, card
`#fffcf8`, sunken `#e8e4dc`, ink `#1c1916`, muted `#5e584e`, line `#ddd6cb`, stronger line
`#c9c0b3`, accent `#1f5c57` and accent-soft `#e6f1ef`. Series colors retain their frozen
roles: observed `#1d4e89`, derived trend `#9a4f1a`, reference `#5c4d86`, comparison source
`#3f5f73`. Colors do not score health; genuine request errors, evidence limitations and
unavailable evidence remain different treatments.

Use local Segoe UI / Helvetica Neue / sans-serif, tabular numerals, body line-height 1.5
and ordinary hierarchy weight 600. Spacing follows 4/8/12/16/24/32px; content max-width is
1100px. Card/button/chip radii are 8/6/4px. Page hierarchy is primary section (`h1`),
current screen/sections (`h2`), subsection (`h3`). Legend samples are 8px squares with a
dashed configured goal/reference sample. Later pages reuse these tokens rather than
inventing page-local design systems.

The shell and redesigned primary pages are Russian under `html lang="ru"`. Proper names
and exact technical codes remain unchanged. Legacy batch-review bodies can retain an
explicit English boundary until separately translated; do not claim all legacy routes
are localized. Frozen shell copy includes `К содержимому`, navigation label
`Основные разделы`, and the footer:

> Интерфейс только на этом компьютере. Потребительский BIA — не клиническое измерение. Нет диагнозов и утверждений о причинах.

## State and evidence contract

`templates/owner_ui.html` supplies `state_chip(state)` and the native, initially closed
`technical_details()` caller block. The ten shared keys are `present`, `partial`,
`confirmed_empty`, `unknown`, `unavailable`, `insufficient`, `not_requested`, `loading`,
`error` and `no_change`. Unrecognized states display as unknown. Loading/error describe
requests; no-change requires an explicit comparison, never missing evidence. Missing
values are not zero; explicit source zero remains a real value.

Interpretation-changing limitations stay visible. Detailed provenance, hashes, exclusions,
algorithm names and diagnostic statistics remain accessible behind disclosure. Disclosure
is a presentation pattern, not a privacy/access boundary. It remains keyboard accessible
without JavaScript. Informational algorithm/canonical banners are `status`, not request
errors.

Overview presentation does not pool sleep groups or change packet/hash semantics. Weight
retains canonical/algorithm boundaries. Sleep never substitutes a previous night for the
selected wake date or silently combines ambiguous same-date/source evidence. Agreement
remains exploratory and cannot choose a canonical source. Activity uses existing Garmin
results, with explicit source/reference selections; it does not add load/readiness
thresholds, recovery-time units, causal claims or a best-lag ranking.

The integrated post-UAT views preserve these boundaries:
- #307 bounds only the Google daily-vitals display read to the trailing 400 inclusive days for longer custom periods and visibly discloses that scope; the full Period Brief/Garmin period is unchanged.
- #308 Compare consumes only compatible accepted persisted Agreement evidence. Daily auxiliary values are not relabelled within-sleep measurements, and a source tab does not establish feature parity; fuller nightly source views belong to #317.
- #309 keeps B−A and percent-to-A semantics, blocks comparing a session with itself and clears stale pair evidence. Only the evidenced `tennis_v2` alias becomes `Теннис`; no generic `_v2` normalization or persistence change is authorized.

## Responsive and request behavior

The sticky paper top bar has a hairline and an active-item underline. At <=800px navigation
stays one horizontal scrolling row and content becomes one column; controls keep 44px
targets. Wide tables/charts scroll locally in `.table-scroll`/`.chart`, not at page level.
Tables retain real table layout and sticky muted headers. Responsive overrides follow page
rules; narrow comparison tables remain locally scrollable rather than expanding the page.

Data reuses persisted source-freshness evaluation and separates source status from provider
calls. #305 exposes sanitized request-failure classes and honest extractor configuration;
its observed real Stable `timeout` after 15 seconds is not a healthy freshness result.
Activity panel submissions clear prior results/evidence, expose loading/error states and
reject late completions from older requests. A single usable Garmin source does not need
a redundant selector; multiple sources still require explicit selection.

## Verification and post-UAT follow-up

Narrow Chromium checks are retained as `scripts/check_owner_{data,brief,weight,sleep,activity}_browser.cjs`.
The Weight check caught an initial-render temporal-dead-zone error before Stage 4 acceptance;
the render call now follows its state-map declarations. Per-stage focused tests and exact
candidate/PR/main CI are recorded in #189 and the subsequent #305–#309 issue/PR records.

Audited product checkpoint before this documentation closeout:
`main @ 29cc9fcf53c508fa5f4994e3170e697726c0514c`; exact post-main CI
`37658045395`, attempt 1, is SUCCESS. The documentation change has separate gates.
Repository gates still do not substitute for Owner-local use.

The consolidated Owner UAT on this product checkpoint is already recorded in GitHub:
#305 remains a real timeout; #317/#318 capture further Sleep/Activity presentation needs;
#319 gates new activity metrics on evidence. #295/#298 were closed as not planned rather
than kept as mandatory private probes. No new browser or private-runtime UAT was performed
by the documentation reconciliation itself.

Review the Owner's forthcoming design answers before the next UI implementation. Until
an explicit decision is recorded, the frozen tokens, IA and evidence contracts above remain
unchanged. Reuse existing browser checks with focused new cases rather than recreating Stage 7.

See [Current History](EXECUTION_HISTORY_CURRENT.md), the [current backlog](ROADMAP.md#current-backlog)
and the [historical Owner UAT handoff — 2026-10-06](OWNER_UAT_FOLLOWUP_2026-10-06.md).
