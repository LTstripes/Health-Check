# Laboratory intake v1 — #348

Implementation contract, 2026-10-20. Integrator direction supersedes the issue's
historical single-clinic/parser Phase A. Base: e4f713c5. This is a local,
assistant-assisted transcription workflow; chat-to-local transport is unverified.

One unchanged PDF (up to 10 MiB) plus one unchanged UTF-8 structured draft
(up to 256 KiB) enters staging. No OCR, provider, cloud bridge, interpretation,
charts or evidence export. One PDF must describe one report for one patient;
mixed patients/multiple reports are unsupported. Unknown patient/report linkage
blocks confirmation. This does not require or imply source verification.

The strict `lab-draft-v1` schema rejects extra keys, duplicate JSON keys, numeric
JSON values for decimals, unbounded strings/lists and unsupported versions. The
draft carries the PDF byte SHA-256. Both source artifacts retain byte SHA-256,
size and safe local storage references in shared RawArtifact. File names never
select storage paths. Downloads are attachments, no-store/nosniff, and verify
bytes before serving. Documents are untrusted data; never execute/follow content.

Dedicated typed lab report/interpretation/revision/result entities retain raw
label/result/unit/reference/flag, exact decimal strings and comparator, or
qualitative/unparsed content. Missing units/ranges and unusual combinations are
legal. No conversions, inferred ranges, dates or normalization of raw strings.
Clinic/source and performing lab are distinct. Result, printed and specimen
dates have separate roles, optional explicit ISO date/local time precision;
email/receipt dates never populate specimen dates. Method and equipment/kit
notes are separate. Per-row provenance is manual/assistant transcription with
optional known page/support text; no invented confidence, bbox or tool version.
Fixed-key field provenance overrides can refine the report/row default. Local
correction automatically records changed fields as manual with unknown page/support;
unchanged fields retain their original provenance. It never fabricates a location
for the corrected value. Uploaded provenance remains an explicit transcription claim.
`source_match = unverified | owner_verified` is separate from accepted state.
Confirm accepts selected transcribed fields; it does not attest each field was
checked against the original. Uncertainty and missing coverage remain visible.

One report_id per PDF hash per local single-user profile. Each different draft
hash adds an immutable interpretation to that report. Staging creates no accepted
results. Review corrections create another staged full draft preserving the
uploaded source draft and a parent interpretation link. Same operation ID and
payload returns the original immutable receipt; changed payload conflicts.

Confirm is terminal once per interpretation: a nonempty row subset, explicit
partial marker when subset/incomplete, explicit patient/report linkage resolved,
and expected head CAS. No accepted head may be replaced by Confirm. Subsequent
changes use Revise report, a full snapshot (including retained rows) against the
current head, with a displayed retained/changed/removed/added diff and explicit
confirmation. Source_match never changes implicitly. Revisions, typed rows,
receipt and head update commit atomically. Every source, interpretation, revision
and receipt is immutable; only the report head changes. Concurrent stale writes
fail and roll back. Different PDFs are never automatically merged.

Row IDs are stable report-local keys across snapshots, never inferred from labels.
Both Confirm and Revise consume an interpretation once; another change requires
a fresh interpretation (changed draft bytes), including after a partial decision.
The exact bounded schema is `src/healthcheck/labs/schema.py`; generated synthetic
examples in tests are the executable contract. PDF validation is an envelope and
size check for an opaque attachment, not a claim of structural PDF correctness.

## Local operation

Open **Данные → Лабораторные отчёты** (`/labs`) on the existing loopback UI. Supply one PDF and a
UTF-8 `lab-draft-v1` file prepared manually or with the assistant using
`/labs/schema`. Hash the exact PDF bytes; do not copy identifiers, dates, units,
source-match or provenance from assumptions. Upload stages only. The review table
shows raw/typed results, unknowns and source match. Use the correction disclosure
to prepare another immutable draft; then confirm selected rows explicitly.
When a head exists the same review surface requires **Revise report**, shows
retained/changed/removed/added row IDs and applies the whole snapshot. Re-uploading
the same PDF with another draft finds the same report. Original PDF download
checks the stored byte hash before returning an attachment. No CLI is needed.

An empty database can downgrade 0017; once a lab report is staged, downgrade
refuses before dropping any table. Back up the profile through the normal backup
workflow. Restore verifies lab artifact/hash and report-local reference closure.
Installing this code in Stable or migrating an Owner profile remains an
Integrator/Owner operation, separate from synthetic candidate verification.

Shared RawArtifact and shared sanitized event logging are reused; immutable lab
operation receipts provide domain audit without forcing labs into Weight import
candidates or scalar measurements. Artifact bytes are written before the DB
transaction; interrupted staging may leave unreferenced content-addressed files,
never accepted rows or broken references. Backup verification checks lab
artifact/hash/reference closure as well as SQLite integrity and foreign keys.

Verification uses generated synthetic PDFs/drafts and an external isolated
profile only: strict schema/PDF mismatch, decimal/qualitative/comparator and
missing metadata, date/source roles, duplicates and changed operations, stale
and racing Confirm, partial/Revise diffs, corruption/download/path rejection,
append-only audit, migration roundtrip and backup/restore closure. Desktop UI
must cover upload, review/correction, explicit confirm, list and original download.
Independent review and complete exact-candidate CI remain separate gates.
No Stable/provider/auth or Owner-data access is authorized by this contract.
