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
Owner UAT scope. Functional, accessibility and security/privacy requirements still apply. New capabilities use the [Observatory visual system](#owner-interface--observatory-visual-system).


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
- Saved measurements stay visible separately from auth/refresh failures. The
  Observatory visual/language system applies across forms and tables; it is not a
  request for another global redesign or a second analytics engine.
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
- **Laboratory documents (#348):** the local PDF plus structured transcription draft intake is integrated, with review/correction, explicit confirmation, revisions and original download. The bounded real-document isolated-copy flow and Owner screen acceptance are complete; generic chat-attachment transport and durable Stable import remain separate. Current receipts are in [Project Wiki](PROJECT_WIKI.md#current-canonical-state); medication/supplement and other personal-health-record capabilities remain separately scoped.

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

Saved Google Steps in Statistics is an observed interval count for one exact
family/source and civil date, separate from Garmin completed-day Steps. Only 7/30
dates are supported; the provider timezone, full-day coverage, pagination and finality
remain unknown. Observed-day summary v1 shows an exact sum of saved eligible
observations and a mean over observed days (including explicit zero), with N of D
and unconfirmed full-day coverage visible. It never presents that sum as a proved
complete provider-period total. Garmin and Google have separate compact daily
plots and keyboard/day selection; full tables and source evidence are closed
by default and available without JavaScript. Missing days remain gaps. No
cross-provider sum/delta is introduced. Invalid/current conflicts and partial overlapping intervals withhold
values; absence is never silently zero. This read-only view adds no acquisition
or automatic refresh. [Technical contract](ARCHITECTURE.md#saved-google-steps-read-392).

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

Еженедельный дайджест доставляется внешней автоматизацией по воскресеньям в 20:00 МСК; первая доставка — 25.10.2026. Адаптер формирует данные, но не содержит расписания. Месячные и годовые обзоры относятся к «Дальше» в [Wiki](PROJECT_WIKI.md). Неполное покрытие остаётся частью результата.

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

Локальный приём лабораторного документа включает исходный PDF, структурированный черновик транскрипции, проверку, исправление, явное подтверждение и историю изменений. [Контракт v1](LAB_INTAKE_V1.md) сохраняет исходные значения, неизвестные единицы и диапазоны и происхождение данных. Один PDF содержит один отчёт одного пациента; неразрешённая связь блокирует подтверждение. Частичное подтверждение и `source_match=unverified` не удостоверяют каждое поле. Транскрипция не является диагнозом; лекарства, добавки и продольный анализ требуют отдельного решения.

<a id="product-decisions--repository-rule"></a>
## Repository rule

Code, schemas, tests, synthetic fixtures and sanitized engineering evidence belong
in Git. Real health data, screenshots, raw provider payloads, credentials/tokens,
databases, generated private reports and personal documents do not.

<a id="owner-interface"></a>

<a id="owner-interface--owner-desktop-interface"></a>
## Owner desktop interface


Интерфейс Observatory объединяет основные разделы в боковой навигации. Он показывает сохранённые данные и их ограничения; внешний вид не подтверждает состояние источника или установленной версии.

<a id="owner-interface--navigation-and-current-routes"></a>
### Navigation and current routes

Основные разделы: «Обзор», «Вес», «Сон», «Активность», «Статистика», «Данные» и «Комментарии». Бренд и корневой адрес без параметров открывают обзор, вес находится на `/weight`; старые ссылки на корень с параметрами ведут на вес с сохранением строки запроса. [Таблица маршрутов и совместимости](ARCHITECTURE.md#presentation) находится в Architecture. Очередь данных описывает ограниченный набор последних загрузок, а не всю историю.

Overview detail retains the selected Garmin Sleep window
for supported 7/30 completed days and returns through the original Overview
selection. Unsupported windows explain the limit. Activity summaries open the
existing period/source-bounded session list and details; Statistics retains its own
return path. Journal, detail and comparison labels share the same activity names.
The recent journal is not a claim of complete history.

Overview prioritizes readings and period selection. Its download link opens the
existing Data page at `/imports#analysis-export`; export controls do not occupy
the Overview. The ordinary download flow is end date, 7/30 days and **Скачать**,
including the full existing supported manifest and clearly labelled current
comments. Source choice, JSON and evidence details remain accessible. Ambiguous
identities require explicit selection; providers are not pooled. Existing
eligibility, privacy scope, frozen packet and size limits remain binding.

В основном виде всегда видны источник, дата или период и неполное покрытие («N из D дней»). Метод, идентификаторы и уточнения могут находиться в доступном с клавиатуры раскрытии; неполный период никогда не скрывается за ним. Это требование владельца: некоторые существующие компактные карточки пока помещают детали источника или знаменателя в раскрытие заголовка. Отсутствующее значение не равно нулю; округление при показе не меняет сохранённые значения и расчёты.

<a id="owner-interface--one-a-visual-and-language-system"></a>
<a id="owner-interface--observatory-visual-system"></a>
### Observatory visual and language system

Интерфейс использует тёмную и светлую темы, боковую навигацию и общие обозначения для источников и состояний. Переключатель «Авто / Тёмная / Светлая» сохраняет выбор оформления в браузере; без JavaScript применяется системная цветовая схема. Цвета не оценивают здоровье. Роли и значения токенов определены в [Architecture](ARCHITECTURE.md#presentation).

Оболочка и основные страницы используют русский язык; отдельные старые страницы проверки загрузок могут оставаться на английском. В обоих режимах, loopback и home-server, раскрытие в подвале дословно сообщает: «Интерфейс только на этом компьютере. Потребительский BIA — не клиническое измерение. Нет диагнозов и утверждений о причинах». В home-server дополнительно доступен выход. Эта надпись сама по себе не определяет сетевую доступность и не подтверждает настройку home-server.

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

Поддерживаемая область интерфейса — настольные окна шириной от **1024 CSS px**. Меньшие окна не входят в обязательную область дизайна и приёмки.

Controls, navigation/brand links and information summaries keep at least 44px hit
targets and visible 3px keyboard focus in the theme accent colour. Preserve tab order, the first Tab skip
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
availability. The Garmin Steps completion display policy is Europe/Moscow, excludes the
current/future days, and retains repeats, lower corrections, ties and latest
missing states. It does not claim Garmin finality. The five-second guard is
cooperative, not a hard SQL/lock/I/O deadline or a performance guarantee. Steps-only
all-time and the v2 bounded view remain separate versioned contracts.

Data has one compact provider action/status with stream details. Stream chronology,
refresh attempts, eligible metric values/dates and clone age are different facts.
Comments retains revision, date-only/DST/offset semantics; UI delivery does not
automatically establish a durable real-profile save/edit acceptance result.

Use one shared Observatory system across Data/Context/Activity/Weight/Statistics. Shared CSS,
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

Owner Sleep, Activity, Training duration series and comparison labels display native
seconds as hours/minutes, half-up to the nearest minute. True zero reads `0 мин`;
positive values below one minute read `<1 мин`, including signed comparison deltas.
Native metres display as kilometres (half-up to 0.01 km; tiny positives `<0,01 км`).
Only presentation rounds: calculations, saved evidence and exports retain exact units.
Sleep endpoints use their own persisted typed offset independently, or show UTC;
missing end offsets never borrow start offsets. Legacy scalar-valid nights remain in
calculations with «границы не проверены». Activity type aliases are display labels
only. Raw codes, quality and provenance remain available in closed details.
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

Synthetic browser evidence and CI do not prove human Owner UAT. The latest dated
human result and any unperformed private gates are in
[Project Wiki](PROJECT_WIKI.md#current-canonical-state).
