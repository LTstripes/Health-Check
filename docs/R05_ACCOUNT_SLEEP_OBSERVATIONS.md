# Exploratory account sleep observations — issue #122

`account_wearables_sleep_observations_v1` is a separately selected exploratory
cohort under issue #122 and Integrator note `5701378562`. It is not
Garmin-vs-Fitbit/device agreement, device accuracy or interchangeability evidence.
It can never qualify for canonical selection, #105 or the 42-night gate.

Select it explicitly with
`SleepPairingQuery(cohort=ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS)` and pass the
result through the existing metric projection, agreement persistence and report
services. The legacy pairing query `all` still selects `device_pair` and
`family_pair`; their rules, serialized pairs and version identity are unchanged.
The report's `all` filter includes published runs for the new cohort as well.

## Pairing rule

`r05-account-wearables-sleep-pairing-v1` reads current persisted projections,
using the same stored local wake-date join and metric eligibility machinery.

- Garmin evidence must belong to a valid Garmin provider/account source. Device
  attribution is preserved exactly; the reader never assigns Vivoactive 5.
- Google must have an explicitly identified source or eligible
  `google-wearables` family. Unattributed identities, excluded/broad families,
  conflicting source eligibility, invalid records and missing wake dates remain
  excluded. Explicit source filters bound the query before pairing.
- Exclude every explicit `nap=true`. Do not rewrite missing, null, invalid or
  false main/nap/manual-edit values.
- Competing Google sources on the same wake date are excluded before role
  selection. Multiple Garmin records are also ambiguous.
- Within one Google source, use its explicit `main=true, nap=false` rule.
  Multiple explicit mains are excluded; other candidates retain an explicit
  `google_explicit_main_preferred` exclusion.
- Otherwise exactly one remaining Google session may supply an observation.
  More than one is excluded without longest/latest selection. This fallback
  does not assert that a session is an overnight main: even explicit
  `main=false` remains false and the observation's session role is flagged
  uncertain.

The pair freezes the role states/values, manual-edit state, source eligibility,
candidate IDs, chosen rule/selection and uncertainty flags. The query, pairing
result and agreement run all carry the new pairing version. An explicit attempt
to persist this cohort under another pairing version is rejected. Existing
frozen runs remain intact and replay uses their original snapshots. No migration
or provider normalization change is required.

## Report and gates

The existing per-metric statistics become available at 14 valid nights, without
an additional span gate. Metric missing/null/zero and partial-evidence rules are
unchanged. The strong-gate eligible count is always zero and canonical proposal
eligibility is always false, including at 42+ nights. The report and frozen
night drill-down show the cohort label, uncertainty notice and inclusion or
exclusion basis. Independent Reviewer and Integrator acceptance, followed by
the bounded Owner-only live re-check, remain separate delivery gates.
