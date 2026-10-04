# Owner UI shell — #189, stage 1

The shared shell follows the [accepted IA](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5854312903)
and the [frozen visual system](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5979374375).
It provides navigation, one page heading, an existing-screen mode label, focus/skip navigation,
responsive layout and reusable presentation states/details. Individual page contents remain
the existing implementations; the thematic redesign is deferred to stages 2–6.

| Primary section | Existing route | Current mode |
| --- | --- | --- |
| Обзор | `/brief` | За период |
| Вес | `/` | Вес и состав тела |
| Сон | `/agreement` | Сравнение сна |
| Активность | `/garmin` | Тренировки и восстановление |
| Данные | `/imports` (including batch review) | Проверка импорта |

Visual freeze: warm paper tokens, sticky paper navigation with a horizontal scrolling
row at <=800px, 8/6/4px radii, no shadows/gradients/pills/stripes, table-scroll wrappers
instead of `display:block` tables, Russian shell/navigation/footer/error labels with
`html lang="ru"` (existing English bodies stay explicitly `lang="en"`), algorithm/canonical
banners as `status` rather than errors, and the ten frozen state treatments.

The brand opens Overview. The legacy root remains Weight, and existing URLs, query
parameters, forms, scripts and API contracts remain intact. Data is an entry to the
existing import review, not yet the consolidated source/freshness surface. Overview
currently offers the existing period view; no new daily overview is implied.

`templates/owner_ui.html` supplies `state_chip(state)` and the native, initially closed
`technical_details()` caller block. States are explicit inputs, never inferred from
values or availability of unrelated sections. Unrecognized states display as unknown.
The common vocabulary separates present, partial, confirmed empty, unknown, unavailable,
insufficient evidence, not requested, loading, error and no detected change. Loading/error
describe a request; no change requires an explicit comparison result, never missing evidence.
This stage adopts the helpers in Brief section chips and error presentation, and documents
the vocabulary in a collapsed footer guide. Existing page-specific status logic stays intact.

Page hierarchy is primary section (`h1`), current screen/sections (`h2`), subsection (`h3`).
Interpretation-changing limitations stay visible. Technical details preserve their full
content, remain keyboard accessible without JavaScript, and are used for Brief provenance
and the error reason code. They are a disclosure pattern, not a privacy/access boundary.

Responsive overrides follow page rules so narrow Brief layouts cannot be overwritten by
later desktop declarations. Navigation stays one horizontal scrolling row at <=800px,
controls keep 44px targets, and wide tables/charts scroll locally in `.table-scroll`/`.chart`
while retaining their evidence and real table layout with sticky muted headers. Stage 7 still owns complete cross-browser acceptance
and the existing page-specific asynchronous loading/filter lifecycle redesign.
