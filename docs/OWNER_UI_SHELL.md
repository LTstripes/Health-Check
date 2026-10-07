# Owner UI — approved A+ desktop shell

On **2026-10-07 the Owner visually approved Overview A+** in [#322](https://github.com/LTstripes/Health-Check/issues/322).
The canonical [text-only synthetic reference](design/owner-overview-a-plus/index.html)
and its [explanation](design/owner-overview-a-plus/README.md) govern the shared desktop
appearance under [Stage A #326](https://github.com/LTstripes/Health-Check/issues/326).
This supersedes the conflicting #189 visual freeze: the previous canvas, surface,
ink, muted, separator, sunken and interaction colors, sans-only prominent heading,
1100px content limit and quieter selected navigation. The values below are the
single current visual contract; old values in Git history are historical.

The [accepted IA](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5854312903),
routes, data/source/state, accessibility, privacy and progressive-disclosure contracts
remain binding. Stages 1–7 of #189 and the post-UAT #306–#309 views are integrated;
#305 diagnostics/import presentation is integrated, with the real freshness timeout open.
Stage A changes the shared shell, not individual page content. Overview's three-column
values/graphs and the other page redesigns require separately assigned stages.
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
Hairlines organize sections; they are not the sole focus or
selection cue. Text must retain accessible contrast on each shared surface.
State fills remain attention `#f6efe2` / ink `#6b4510`, unavailable `#f3e4d4` /
ink `#6b320c`, and request error `#f8eceb` / ink `#7a2424`.
Series retain their roles: observed `#1d4e89`, derived trend `#9a4f1a`, reference
`#5c4d86`, comparison source `#3f5f73`. Do not recolor every graph with the action
green or confuse observations, trends and references. Colors do not score health.

Use local Georgia / Times New Roman / serif for the prominent desktop page `h1`
(42px, weight 400, line-height 1.1). The shared heading font token can support future
hero values when their page stage is assigned; Stage A adds no hero/KPI content.
Body, controls, tables, section headings and metadata use local Segoe UI /
Helvetica Neue / Arial / sans-serif, body line-height 1.5 and ordinary hierarchy
weight 600. Values/tables retain tabular numerals. Page hierarchy stays primary
section (`h1`), current screen/sections (`h2`), subsection (`h3`). Uppercase small
editorial kickers are optional; never uppercase all headings or ordinary copy.
No external fonts/assets are loaded.

The desktop shell has a 1440px maximum content width and 48px horizontal gutters;
the top bar aligns with that content, is at least 83px tall, and stays sticky.
Navigation uses one row with 24px gaps. Its selected link has green text, weight
600 and a square 2px underline, plus `aria-current="page"`. Prominent titles and
the footer have 1px section rules. Content layouts remain in their current page
contracts. Existing 4/8/12/16/24/32px spacing and 8/6/4px card/button/chip radii
remain available within those pages; top-navigation links have square corners.
Legend samples stay 8px squares with a dashed configured goal/reference sample.
Later page stages reuse these tokens rather than inventing local design systems.

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

## Desktop scope and request behavior

The [Owner decision #321, 2026-10-07](https://github.com/LTstripes/Health-Check/issues/321)
sets desktop/laptop CSS viewports **1024px and wider** as the supported target.
Phone, tablet and windows below 1024px have no design, browser-test or Owner UAT
acceptance requirement. Earlier #189/390px responsive expectations and UI briefs
are historical, superseded for current and future work. The approved Overview
A+ static reference is desktop-only. Existing small-window CSS fallbacks remain
without a new support obligation.

Controls, navigation/brand links and information summaries keep at least 44px
hit targets and visible 3px green keyboard focus. Preserve tab order, the first
Tab skip link, its focus transfer to content, and native Enter/Space disclosures.
Wide tables/charts scroll locally
in `.table-scroll`/`.chart`, not at page level. Tables retain real table layout
and sticky muted headers. Functional evidence, keyboard/accessibility and
security/privacy contracts remain required at desktop widths.

Data reuses persisted source-freshness evaluation and separates source status from provider
calls. #305 exposes sanitized request-failure classes and honest extractor configuration;
its observed real Stable `timeout` after 15 seconds is not a healthy freshness result.
Activity panel submissions clear prior results/evidence, expose loading/error states and
reject late completions from older requests. A single usable Garmin source does not need
a redundant selector; multiple sources still require explicit selection.

## Verification and post-UAT follow-up

Focused Chromium checks are retained as `scripts/check_owner_{data,brief,weight,sleep,activity}_browser.cjs`.
These, the shared multi-engine `check_owner_acceptance_browser.cjs`, and the
Overview/Google-vitals checks use representative **1024/1440px** desktop widths.
No test file, suite, CI job/lane, Windows smoke or guard is disabled, and no
skip/xfail replaces functional coverage. Complete exact-candidate CI remains
governed by [Development Process](DEVELOPMENT_PROCESS.md#13-ci-evidence-and-complete-suite-gates).

Under #321, retired mobile-only checks are the 320–800px loops/screenshots,
one-column/breakpoint ordering and phone-navigation CSS expectations, forced
narrow-table overflow/row-height expectations and the phone tick-density
comparison. Desktop checks retain source/availability honesty, chart points and
exact date endpoints, collision-free axes, resize focus, pointer/keyboard
interaction, import upload/preview/reject/confirm, unconfigured extraction,
disclosures, comparisons, table data/local scroll containers and request
loading/error/retry/race checks. The pytest shell contract keeps viewport
metadata, skip links, visible focus, target sizes, scrollers and real table
evidence without freezing obsolete responsive CSS.

The older Brief and Google-vitals checks also follow the integrated markup:
raw packet checks select `.brief-packet`; Google checks open the Google source
view and its shared technical disclosure. The missing Garmin night assertion
still runs in the Garmin view for the same date.

Synthetic browser evidence and CI are separate; neither proves private desktop
Owner UAT, which remains `UNVERIFIED` for a new candidate until the Owner runs it.

The Weight check caught an initial-render temporal-dead-zone error before Stage 4 acceptance;
the render call now follows its state-map declarations. Per-stage focused tests and exact
candidate/PR/main CI are recorded in #189 and the subsequent #305–#309 issue/PR records.

The consolidated Owner UAT before A+ is recorded in GitHub:
#305 remains a real timeout; #317/#318 capture further Sleep/Activity presentation needs;
#319 gates new activity metrics on evidence. #295/#298 were closed as not planned rather
than kept as mandatory private probes. No new browser or private-runtime UAT was performed
by that documentation reconciliation. The static-reference approval is a design
decision, not product A+ UAT or acceptance of a new implementation candidate.

Stage A verifies all five primary routes synthetically at 1024px and 1440px:
loaded palette/type, selected navigation, section rules, no clipping, unchanged
source/copy/controls, keyboard focus/disclosure and no unexpected console or
external network errors. Before/after screenshots remain outside the repository;
even synthetic PNG binaries must not be committed. Reuse existing browser checks
with focused A+ assertions. Complete CI, Integrator review and Owner desktop UAT
remain distinct gates; unperformed Owner-local UAT is `UNVERIFIED`.

See [Current History](EXECUTION_HISTORY_CURRENT.md), the [current backlog](ROADMAP.md#current-backlog)
and the [historical Owner UAT handoff — 2026-10-06](OWNER_UAT_FOLLOWUP_2026-10-06.md).
