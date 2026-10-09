# Current Execution History

## History continuity

The previous current-history edition is preserved in Git at the exact product
checkpoint, with every dated outcome, failed attempt, source link and earlier
handoff intact: [history through the 2026-10-07 UI/UAT reconciliation](https://github.com/LTstripes/Health-Check/blob/013482ec3a51d89fd57c3a55ab9b09d1d2228e25/docs/EXECUTION_HISTORY_CURRENT.md).
It is historical evidence, not today's task queue. This compact current edition
continues it; no old commit, issue comment or review has been rewritten.

Earlier indexes also remain:
- [History through 2026-09-27](EXECUTION_HISTORY_THROUGH_2026-09-27.md).
- [Reliability/correction history through 2026-10-01](EXECUTION_HISTORY_THROUGH_2026-10-01_RELIABILITY.md).
- [Verbose historical engineering log](EXECUTION_HISTORY.md).

## 2026-10-09 — integrated A+ product checkpoint

Audited product main before the documentation closeout:
`013482ec3a51d89fd57c3a55ab9b09d1d2228e25`. Exact post-main
[CI 37884822270](https://github.com/LTstripes/Health-Check/actions/runs/37884822270)
SUCCESS attempt 1: quality, three Linux lanes, Windows smoke and final checks.
Documentation publication has separate candidate/PR/post-main evidence; no
self-referential future docs SHA or new local product test is guessed here.

| Work | Integrated outcome / primary record |
| --- | --- |
| #321 / PR #325 | Desktop-only 1024px+ acceptance; phone-only checks retired, functional coverage retained |
| #322 / PR #324 | Owner-approved A+ reference; original PNG-bearing PR #323 remained unmerged, clean text-only delivery kept repository hygiene |
| #326 / PR #327 | Shared A+ palette, typography, navigation and contract |
| #328 / PR #329 | Real Overview readings/charts; saved-activity state, actual Sleep-date link and series-role fixes reviewed before merge |
| #318 / PR #331 | Five-column Activity A/B, human duration, optional-field thinning and unchanged comparisons |
| #317 / PR #332 | Garmin/Google source-only Sleep, including unpaired account observations; source/role/native-field corrections independently accepted |
| #335 / PR #336 | Activity v4 five recent sessions and existing full history disclosure |
| #295 / PR #337 | Indexed per-source Google freshness queries with equivalent facts; engineering accepted, real Overview latency still open |
| #334 / PR #338 | Sparse Overview Weight-chart dates/ticks/legend and honest gaps |
| #333 / PR #339 | Compact source attention without changes to packet/actions/source semantics |

#317's original independent FIXES REQUIRED was corrected at
`dc5dc1b801297ce60df081a9fdd638331269fe7f`; the
[independent re-review](https://github.com/LTstripes/Health-Check/pull/332#issuecomment-6064746852)
accepted existing account eligibility, uncertain singleton roles and consistent
Garmin native/primary-table gates. Its passing amended push/PR CI did not erase
the initial findings. Existing Compare/Agreement was preserved. New requested
Sleep history is #343, not unfinished original #317 delivery.

Detailed candidates, failed attempts, reviews and exact gates remain in their
issue/PR histories. #295's former not-planned closure was followed by reopening
on new real evidence; the earlier dated disposition remains preserved, not relabelled.

## Real-clone activation and Owner UAT — separate evidence

[Owner-local report 6074940976](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6074940976)
records a controlled launch from the product checkpoint using an existing verified
disposable **copy of real Owner data**. Code/clone identity and integrity were
checked. No Stable/provider/scheduler change or new backup was performed. This
is neither a synthetic fixture nor an automatically refreshed Stable profile.

Bounded direct-loopback observations, all HTTP 200:

| Request | Total time |
| --- | --- |
| /brief 30-day, first | 18.402 s |
| /brief 30-day, one repeat | 11.983 s |
| /brief 7-day | 9.345 s |
| /api/source-freshness | 1.846 s |

Cache state was not controlled; these are not matched before/after benchmarks.
Overview is still slow (#295). Freshness request completion is not successful
provider collection. The report classified selected-source RHR as otherwise
usable but excluded by Overview's surface filter (#340), and weekly Garmin HRV
as missing in the inspected window even ignoring that filter. No Google daily
metric was substituted and no upstream cause was invented.

Later the Owner supplied real screenshots and concrete feedback. The
[human UAT/priority record](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6084375341)
sets **PARTIAL / NOT overall PASS**: A+ style, dedicated Weight and shorter Activity
history were liked; source availability, Sleep experience, useful detail/summary
views and comments/chat analysis still need work. Human inspection is no longer
unperformed; individual unaccepted capabilities remain unverified. Private images
and health values are not copied into repository documentation.

## Owner decisions — data-first functionality, documentation before launch

The Owner explicitly requested this documentation reconciliation before submitting
new tasks, and raised **#342 data availability to P1 in the first wave** with
#294 Stage A portal Context and #341 Stage A bounded health/context export.
Data is not deferred behind cosmetic polish.

Compatible parallel roles after documentation closeout:
- #342: read-only code/contracts diagnosis; private runtime work stays separately authorized.
- #294: sole UI/Context writer, preserving original text, event-time precision and revisioned history; weight-goal Settings remains Stage B.
- #341: separate exporter/module/script/tests consuming the existing Context interface, with no competing edits to its service/models or shared UI.

Heavy local verification remains serialized on the shared machine. Integrator
reconciles additive test-manifest changes and exact candidate/PR/main gates;
separate branches alone are not proof of independent scope. Workspaces and external
synthetic roots are assigned in #294/#341. No feature Worker is launched by this
record, and no private data are copied into a development tree.

The immediate useful flow is durable dated comments and selected evidence for
conversation in ChatGPT. Export comes first; direct authenticated read access
requires a verified connection. A skill alone does not reach the Owner's localhost;
Telegram is optional. A note in disposable UAT is not automatically a Stable note.

Planned #343–#348 retain the Owner's requests: dual-source Sleep history, Overview
chart/disclosure polish, session details, period recovery cards, Statistics and
lab-document candidate confirmation. The new Statistics clarification is explicit:
**left source / right source, both visible by default**, each with units, effective
window, denominator/count and coverage. Compatible sides may have a numeric delta;
incompatible or absent sides stay independently visible without pooling, combined
totals or fabricated zeros. This is a planned view, not newly delivered analytics.

## Documentation and handoff

README, Project Wiki, Product Vision, Roadmap, Owner UI, Context Capture, Backlog
Ideas and Decisions are reconciled by responsibility: implemented versus planned,
source data versus clone/runtime, CI versus local/human UAT, P1 data availability,
Context/chat priorities, side-by-side Statistics and preserved data contracts.
Old detailed history remains accessible by the pinned link above rather than being
copied into another long active queue.

The first-wave short prompts for #294/#341/#342 remain valid: each locates the
updated issue and starts from live main. #347's later prompt now explicitly includes
left/right source visibility and compatibility-bound deltas. No new feature issue
was needed for the priority/layout clarification. The
[roadmap](ROADMAP.md#current-backlog) is the sequencing map, not an automatic queue.

The documentation PR must record its own diff/link/privacy review and actual CI
results. No new Owner UAT, local deployment, provider call, schema/runtime change
or model benchmarking is implied. Existing unperformed gates stay unverified.
