# Overview A+ — static desktop reference

One proposed visual reference for [#322](https://github.com/LTstripes/Health-Check/issues/322), following the desktop-only decision in [#321](https://github.com/LTstripes/Health-Check/issues/321). This does not change the production visual or data contract.

Open [index.html](index.html) directly from disk. All CSS and SVG are inline; there are no scripts, fonts, external assets, servers or data connections. The page explicitly labels every observation and date as synthetic. The fixed example covers **1–7 June 2099**, as of 7 June at 18:10 in a fictional UTC+03:00 context.

> **Preview policy:** render `index.html` locally to see the design. The synthetic 1440px PNG was produced for Worker-local review but is deliberately **not committed**: the existing repository privacy/hygiene gate forbids image binaries, even synthetic ones.

## Approved decisions in the reference

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

## Static and functional parts

- **Functional without JavaScript:** native disclosure open/close, keyboard focus and skip-to-content link.
- **Non-functional by design:** navigation, period buttons and alternative dates. The page labels them as a mockup; buttons expose `aria-disabled`. There are no other pages, imports or refresh actions.
- **Desktop only:** minimum 1024 CSS px. No phone/tablet design, screenshots or acceptance checks.

## Focused local verification

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

Only the HTML and this README are committed; generated PNG evidence must remain outside Git. No production UI, API, analytics, provider, database, tests or shared UI policy changed. No private data or real screenshots were used. Product tests and Owner UAT were not run for this static reference. CI status is reported separately for the pushed commit; local browser checks are not CI or Integrator acceptance.

CBM: skipped — standalone design/documentation artifact; no codebase structural discovery required.
