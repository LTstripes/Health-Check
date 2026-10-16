# Google metric source selection

Google is one logical provider in the normal view. The backend selects an exact
saved source only when metric-specific eligibility proves one usable candidate
inside the requested scope and every candidate search completes. Selection does
not pool records, rewrite identities or establish lineage. Equal durations or
RHR values, UUID order, latest dates and history length never choose a source.

`metric_source_selection.select_metric_source` reuses the accepted Statistics
Sleep discovery decision. Readers retain eligibility, units, dates, work limits,
correction/retirement and provenance. An ambiguous-only candidate competes even
without a scalar. Two usable candidates conflict even on disjoint dates. Any
incomplete candidate blocks automatic selection; a prefix cannot supply a mean.
Exact overrides bypass unrelated identities and do not fall back if empty.

Consumers:

- Overview RHR evaluates all Google identities with the existing bounded period
  reader (at most 32 sources, 400 days, 4096 records/source and 256 records/day).
  The selected packet is reused without changing values, dates, n/N, exclusions,
  rational mean or last-observation provenance. Other metrics and out-of-window
  observations do not establish RHR eligibility. Latest RHR is unchanged.
- Data Sleep evaluates each Google source with the existing latest reader:
  32 sources, 32 observed date groups, 256 records and 200 records/night. This is
  a bounded latest search ending on the evaluation date, not a period aggregate.
  A complete no-value single-source result retains its original exclusions.
- Statistics Sleep keeps its existing five windows, loader, caps and deadline.
  The extracted source-cell function is also used by Sleep evidence for its
  explicit 7/30-day window. Existing family/record/role gates exclude broad
  family list copies before source choice; identical values are not the proof.
- Sleep evidence opts into Google provider discovery with `google_auto_select`.
  Combined forwards `sleep_google_auto_select`, also exposed in its CLI. These
  flags default to false, preserving explicit and omitted-provider contracts.
  Once selected, the accepted exact range reader produces unchanged points and
  provenance. Its own 400-record range cap still applies: unique selection is
  not a promise that every richer detail read fits its limits.

Sleep evidence returns the same `sleep-window-selection-v1` decision as
Statistics, projected through an explicit recursive allowlist. Conflict,
incomplete and no-eligible outcomes have no selected source and `source_range`
is null. These are complete labelled outcomes, not missing Google sections.
A successful automatic request records `request.sources.google=null` (no exact
ID requested), with the resolved ID only in the provider section and selection.
The shared loader borrows the evidence caller's SQL guard; it never replaces or
removes that guard, changes pragmas, weakens write denial or opens another snapshot.

Acquisition coverage, refresh and snapshot age stay separate and may be unknown.
No provider calls, raw-file reads/deletion, new scopes, schemas, permissions,
canonical selection, live connector setup or Stable operations are involved.
Tests use real persistence/readers and synthetic profiles. Owner UAT is separate.
