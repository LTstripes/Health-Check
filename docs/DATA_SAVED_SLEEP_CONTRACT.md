# Data: latest saved sleep (#305 / #376)

This default-only card shows `sleep_duration_asleep_seconds` separately for one
exact Garmin source and one exact Google source. It reuses the accepted
`read_source_sleep_night` / `resolve_source_sleep_point` rules: current typed
sessions, source eligibility, Google main/nap preference and uncertain singleton,
metric eligibility, explicit zero, partial records and same-night ambiguity.
It does not change those readers, canonical selection or explicit-date views.

Observation date is the typed persisted local **wake date**, never parent-record,
UTC, receipt, refresh or snapshot date. Age is evaluation local date minus wake
date in civil days. Search excludes dates after evaluation; there is no age
threshold. Refresh and unknown snapshot age cannot invalidate saved history.

An explicit exact source remains authoritative. For Google, the shared
[metric source selector](METRIC_SOURCE_SELECTION.md) evaluates each source through
this same bounded latest reader; one eligible source is selected only after
complete discovery. Multiple eligible/ambiguous candidates or an incomplete
search remain blocked. Garmin source selection is unchanged. Search walks observed wake-date
groups newest first, skipping ineligible groups while disclosing newer exclusions.
An older eligible night is explicitly historical; no empty search proves that
sleep was never collected. Missing/invalid/conflicting nights never become zero.

Use one read-only physical snapshot for both providers. Bound source inventory to
32, examined date groups to 32 and candidate records to 256, preserving complete
same-date groups and the existing 200-record night cap. SQLite work/time guards
also bound the wake-date sort (there is no wake-date index in the accepted schema).
Overflow/read failure yields no selected value from an incomplete group/search.
No schema/index migration, provider request, raw-body read or persisted change.

UI shows duration, source, wake date, civil-day age, partial/uncertain-role cues and
concise newer-conflict/missing notices. It uses OwnerDate and existing Data layout;
no technical JSON is added to an information badge. RHR/provider status remain
their existing independent blocks. This is synthetic engineering validation,
not Owner UAT or full completion of either issue.
