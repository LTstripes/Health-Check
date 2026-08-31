# Decisions and Open Questions

## Confirmed product decisions

### Purpose

- Build a personal health observatory, not a workout generator.
- Single user only.
- Primary use on a laptop.
- Dashboard and AI/LLM are equally important interfaces.
- Support automatic periodic reports and arbitrary ad-hoc analysis.

### Report cadence

- Weekly: Sunday.
- Monthly: last calendar day of the month.
- Annual: year end.
- No dedicated daily briefing in MVP.

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

- Garmin wearable: worn concurrently with Fitbit; exact Garmin model still to record.
- **Google Fitbit Air**: worn concurrently with Garmin.
- **Xiaomi Body Composition Scale S400**.
- Garmin expected to provide most wearable/training data.
- Fitbit is a candidate primary sleep source, pending a real Garmin-vs-Fitbit comparison.
- Both sources should remain visible regardless of canonical-source choice.
- Periodic statistical comparison between devices is desired.
- Garmin proprietary scores (Body Battery, Training Readiness, Stress, etc.) should be retained as informative signals.

### Xiaomi workflow

- Prefer automatic BLE ingestion through openScale/openScale-sync if stable with S400.
- Keep photo/screenshot import as fallback and historical import path.
- AI/vision-extracted measurements require confirmation before writing.

### Context/journal

- No mandatory structured daily energy/mood/stress diary.
- Do support spontaneous free-text life events and observations.
- Analytics should be able to relate these events to health changes and recurring patterns.

### History

- Backfill the maximum reliable history from each source.
- Garmin history may span several years.
- Fitbit history is currently much shorter.
- Xiaomi historical focus starts with roughly the last six months.

### Automation

- Sync should happen automatically.
- Analytics/baselines should recalculate automatically.
- Periodic reports should generate automatically.

### Future direction

- Later expand beyond wearables into laboratory tests and other personal health documents.
- Possible inputs include bloodwork, vitamin/mineral results and other lab/medical reports.
- Preserve source documents outside Git, normalize extracted values, retain lab ranges/units and require confirmation for uncertain extraction.

## Open questions before implementation

These do not block the documentation/bootstrap phase but should be resolved before or during R00/R01.

1. **Exact Garmin watch model(s).** This affects available metrics and should be part of provider/device metadata.
2. **Report delivery channel.** Where should Sunday/month-end/year-end reports proactively appear: local dashboard only, Telegram, email, ChatGPT workflow, or a combination?
3. **Life-context capture UX.** Preferred first path: quick field in the dashboard, Telegram/chat message into the local service, or both?
4. **External LLM privacy boundary.** Is it acceptable for selected health metrics/derived analytics to be sent to OpenAI when the user asks Lera/ChatGPT to analyze them, while the complete raw database remains local? Or should a local-model-only mode be a hard requirement from v1?
5. **Nutrition scope.** For the first releases, should food/alcohol remain free-text context only ("late dinner", "three days drinking"), with no calorie/macronutrient tracking?
6. **Future lab-data boundary.** Should full source documents remain local by default with only normalized/selected values sent to an external LLM, or is sending an explicitly selected full document to the LLM acceptable?
7. **Travel/timezone semantics.** For long-term reports, should calendar-day boundaries follow the user's local timezone at the measurement/event, or a fixed home timezone? Sleep crossing timezones needs an explicit rule eventually.
8. **Repository/project name.** Current GitHub repository is named `Healh-Check` (missing the second `t` in `Health`). Decide whether to rename before implementation or keep it intentionally.

## Default proposals if not otherwise decided

- Keep all practical raw/source payloads locally for reproducibility and future re-parsing.
- Store source-specific measurements indefinitely unless storage becomes a real problem.
- Use versioned canonical-source rules instead of destructive normalization.
- Present AI findings as: observation -> evidence -> likely interpretation -> suggestion -> confidence/caveat.
- Keep nutrition as free-text context initially.
- Use external LLMs only on explicit user action/reports and send the minimum data needed for the question.
- Never place real health data or source documents in Git.
