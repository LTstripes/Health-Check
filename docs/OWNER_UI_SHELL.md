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
| Вес | `/` | Current confirmed weight, trend/change, configured goal, timelines and separate composition-group spans |
| Сон | `/sleep` | Garmin / Google / Compare; selected-date source-only sessions, including eligible unpaired account observations, plus separate Google daily vitals |
| Сон, secondary mode | `/agreement` | Exploratory Garmin/Google comparison and diagnostic evidence |
| Активность | `/garmin#activity-journal` | Five recent saved sessions, full existing history disclosure and five-column A/B comparison |
| Активность, secondary mode | `/garmin#training-recovery` | Garmin dated snapshots, period series and exploratory lagged associations |
| Данные | `/imports` | Persisted freshness/actions plus upload/review queue; batch details under `/imports/{id}` |

The brand opens Overview at `/brief`; the legacy root remains Weight. Existing
API/query/import contracts are not redefined by navigation. The Data queue describes
its bounded recent-batch inventory, not an exhaustive count of all history.
Context and Statistics are planned entries below, not currently delivered routes.

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

## Planned Owner direction — 2026-10-09, not yet implementation

Keep the accepted A+ appearance. **P1 #342 source availability**, #294 Stage A
comments and #341 Stage A chat evidence are the first wave after documentation
closeout. Do not launch multiple conflicting page writers or treat this section
as an automatic queue. Detailed scope/workspace assignments live in those issues.

- **#294 Context:** a compact secondary portal entry for original comments, visible editable event date, optional time/range, list/revise/history. Recorded-at is separate; no invented midnight. Routine use must target a durable Owner profile, not silently disposable UAT data.
- **#341 evidence:** selected period/domain/current-context export first; its later small share UI follows #294 integration. Direct authenticated ChatGPT tools require a verified connection; no skill-only localhost access, automatic private upload or Telegram prerequisite.
- **#343 Sleep:** primary 7/30-day duration chart with Garmin and Google together, source toggles and pointer/focus/click details. X = wake dates, Y = human hour ticks. Independent source display does not require Agreement pairs. Competing observations stay ambiguous; no longest/latest winner or invented gap values. Statistical Compare is secondary.
- **#344 Overview:** Owner-approved thin connectors between measured Weight daily medians, with visually distinct unmeasured spans and no interpolated data/points; preserve EWMA. Human intermediate Sleep ticks and quieter long freshness explanation, while necessary source/date/action cues stay visible.
- **#345/#346 Activity:** saved-session detail cards and meaningful 7/30-day summaries beside dated native recovery snapshots. Only supported fields; #319 owns new calories/max-HR/dual-effect evidence. No averaging categorical status or summing overlapping rolling loads.
- **#347 Statistics:** **left source / right source, both visible by default** for each metric. Stable names, units, effective periods, denominator/count/coverage on each side; missing side remains labelled. Optional right-minus-left delta only for compatible meanings/windows/units/denominators. Independent display remains allowed without statistical pairing; no pooled/combined source total. Optional selectors customize the pair, not hide it by default. Reuse aggregates later in Overview/chat.
- **#348 labs:** source PDF/image → extraction candidates → Owner-confirmed results with original labels/units/report ranges/sample date and revision provenance. Planned contract, not an implemented route or diagnosis.

Repeated source-warning prose may move into accessible detail, but genuine absence,
ambiguity, stale dates and necessary actions cannot be deleted merely for aesthetics.
A trusted runtime-origin cue must distinguish real clone/synthetic/durable profile;
never infer origin or freshness from displayed values or a directory name.

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
