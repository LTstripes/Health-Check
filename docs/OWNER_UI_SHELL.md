# Owner UI shell and thematic pages — #189

The shared interface follows the [accepted IA](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5854312903)
and the [frozen visual system](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5979374375).
Stages 1–6 are integrated: shell, Data, Overview, Weight, Sleep and Activity.
Stage 7 whole-product browser/responsive/loading/error acceptance remains pending.
Exact implementation/CI checkpoints live in [Current History](EXECUTION_HISTORY_CURRENT.md).

## Navigation and current routes

| Primary section | Route | Current surface |
| --- | --- | --- |
| Обзор | `/brief` | За период: deterministic Period Brief summary, notable facts, actions and limitations |
| Вес | `/` | Current confirmed weight, trend/change, configured goal, coverage and body composition |
| Сон | `/sleep` | Selected wake-date night and 30-day history |
| Сон, secondary mode | `/agreement` | Exploratory Garmin/Google comparison and diagnostic evidence |
| Активность | `/garmin#activity-journal` | Сессии: latest saved sessions and reference-session comparison |
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

## Responsive and request behavior

The sticky paper top bar has a hairline and an active-item underline. At <=800px navigation
stays one horizontal scrolling row and content becomes one column; controls keep 44px
targets. Wide tables/charts scroll locally in `.table-scroll`/`.chart`, not at page level.
Tables retain real table layout and sticky muted headers. Responsive overrides follow page
rules; narrow comparison tables remain locally scrollable rather than expanding the page.

Data reuses persisted source-freshness evaluation and separates source status from provider
calls. Activity panel submissions clear prior results/evidence, expose loading/error
states and reject late completions from older requests. These implemented paths still need
the Stage 7 whole-product acceptance matrix; a per-page pass is not a claim about every
browser, error mode or navigation sequence.

## Verification and remaining gate

Narrow Chromium checks are retained as `scripts/check_owner_{data,brief,weight,sleep,activity}_browser.cjs`.
The Weight check caught an initial-render temporal-dead-zone error before Stage 4 acceptance;
the render call now follows its state-map declarations. Per-stage focused tests and exact
candidate/PR/main CI are recorded in #189.

Stage 7 remains the final cross-browser/mobile/responsive/loading/error acceptance over the
combined product. Reuse existing checks and add concrete missing cases rather than blindly
rerunning all suites. Record tested browsers/viewports, findings and untested limitations
honestly. The Owner already dispatched this task; this documentation update does not launch
another Worker, change its pinned baseline or waive its gates.

Owner-local deployment and any genuinely required private UAT are separate from repository
integration. No local runtime update, new private-data test or whole-product completion is
implied by this document.
