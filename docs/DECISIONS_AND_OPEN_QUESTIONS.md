# Decisions and Open Questions

## Confirmed product decisions

### Purpose

- Build a personal health observatory, not a workout generator.
- Single user only.
- Primary use on a laptop.
- Dashboard and AI/LLM are equally important interfaces.
- Support automatic periodic reports and arbitrary ad-hoc analysis.

### Report cadence and delivery

- Weekly: Sunday.
- Monthly: last calendar day of the month.
- Annual: year end.
- No dedicated daily briefing in MVP.
- Automatic reports should be available in the local dashboard and proactively delivered through **email and Telegram**.

### Advice

- The AI should provide practical suggestions, not merely summarize measurements.
- Core calculations stay deterministic/reproducible outside the LLM.
- Avoid diagnoses and avoid presenting association as causation.

### Current priority order

1. Weight/body composition.
2. Sleep.
3. Physical activity/fitness.
4. General wellbeing/recovery.

### Weight/body composition

- Current working weight target: approximately 76 kg.
- Prefer fat loss while preserving lean/muscle mass.
- Track body recomposition even at stable weight.
- Current weighing cadence is roughly weekly.
- Keep useful core metrics; ignore low-value Xiaomi "body age"/overall proprietary ratings as primary analytic signals.
- Existing historical scale data is roughly six months and should be backfilled if possible.

### Hardware / sources

- **Garmin Vivoactive 5**: worn concurrently with Fitbit.
- **Google Fitbit Air**: worn concurrently with Garmin.
- **Xiaomi Body Composition Scale S400**.
- Garmin expected to provide most wearable/training data.
- Fitbit is a candidate primary sleep source, pending a real Garmin-vs-Fitbit comparison.
- Both sources should remain visible regardless of canonical-source choice.
- Periodic statistical comparison between devices is desired.
- Garmin proprietary scores (Body Battery, Training Readiness, Stress, etc.) should be retained as informative signals when available for the device/account.

### Xiaomi workflow

- Prefer automatic BLE ingestion through openScale/openScale-sync if stable with S400.
- Keep photo/screenshot import as fallback and historical import path.
- AI/vision-extracted measurements require confirmation before writing.

### Context/journal

- No mandatory structured daily energy/mood/stress diary.
- Do support spontaneous free-text life events and observations.
- Preferred capture channels: **Telegram + dashboard**.
- Analytics should be able to relate these events to health changes and recurring patterns.
- Obsidian is not a canonical health-event store in MVP. It may later be used as an optional import/reference source if that proves useful, but Health-Check should not depend on nightly parsing of Obsidian notes.

### Nutrition

- Detailed nutrition/calorie/macronutrient tracking is outside the first releases.
- The user already keeps a food diary in a ChatGPT project; Health-Check does not need to duplicate that workflow now.
- Food/alcohol can still appear as lightweight context events (for example: "large late dinners" or "three days drinking").
- A future optional weekly summary import from the existing food diary may be considered only if it adds useful analytical signal.

### History

- Backfill the maximum reliable history from each source.
- Garmin history may span several years.
- Fitbit history is currently much shorter.
- Xiaomi historical focus starts with roughly the last six months.

### Automation

- Sync should happen automatically.
- Analytics/baselines should recalculate automatically.
- Periodic reports should generate automatically and be delivered without manual action.

### External LLM / privacy boundary

- Local-first is an architectural preference for simplicity, control, reproducibility and direct ownership of the data; it is **not** a requirement to keep all health information away from external AI services.
- Selected raw data, normalized metrics, derived analytics and explicitly selected documents may be sent to OpenAI or another external LLM when useful for analysis.
- Avoid sending unnecessarily large raw datasets when a smaller derived/query result is sufficient, primarily for efficiency and clarity rather than secrecy.
- Real personal health data, screenshots, databases, provider tokens and lab documents must still never be committed to Git.

### Future lab / medical data

- Later expand beyond wearables into laboratory tests and other personal health documents.
- Possible inputs include bloodwork, vitamin/mineral results and other lab/medical reports.
- Store normalized values with analyte/result/unit/reference range/date and source provenance.
- Full PDFs/images may be analyzed by an external LLM when explicitly useful; strict local-only document handling is not required.
- Human confirmation remains important for uncertain extraction.

### Travel/timezone semantics

- Correct timezone semantics are valuable but **not an early-release blocker**.
- Preserve source timestamps/timezone metadata where practical from the beginning.
- Sophisticated travel/day-boundary/sleep-crossing-timezone logic belongs in the distant backlog unless real data exposes a concrete problem earlier.

### Repository name

- Canonical repository/project name is **Health-Check**.
- The earlier `Healh-Check` spelling was an accidental typo and should not be retained in code or documentation.

## Remaining open questions before implementation

These do not block R00 unless the technical audit reveals that they affect the base architecture.

1. **Email implementation.** Which delivery route should the local service use first: SMTP/application password, a provider API, or another simple local-friendly mechanism?
2. **Telegram implementation.** Reuse Telegram patterns from `garmin_ai`, use a simple bot directly, or isolate notifications behind a generic notifier interface from day one?
3. **Context-event grammar.** How much automatic extraction should happen from free text (date range, tags such as alcohol/travel/illness/activity) before asking for confirmation?
4. **LLM access path.** What is the simplest robust route for ChatGPT/Lera to query the local analytics layer later: remote read-only MCP/API, exported report/context bundles, or another secure bridge?
5. **Lab schema depth.** When lab ingestion begins, decide whether to model only analytes/results or also laboratory, specimen, fasting state, method and physician/context metadata.

## Default proposals if not otherwise decided

- Keep all practical raw/source payloads locally for reproducibility and future re-parsing.
- Store source-specific measurements indefinitely unless storage becomes a real problem.
- Use versioned canonical-source rules instead of destructive normalization.
- Present AI findings as: observation -> evidence -> likely interpretation -> suggestion -> confidence/caveat.
- Keep nutrition as free-text context initially.
- Use Telegram + dashboard as the first context-capture paths.
- Use dashboard + email + Telegram for periodic report delivery.
- Keep Obsidian optional/non-canonical rather than making Health-Check depend on note parsing.
- Never place real health data or source documents in Git.
