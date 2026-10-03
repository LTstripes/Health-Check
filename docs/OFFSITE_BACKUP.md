# Protected off-site backup and clean recovery v1

Authority: [#148](https://github.com/LTstripes/Health-Check/issues/148),
[Integrator freeze 5962166816](https://github.com/LTstripes/Health-Check/issues/148#issuecomment-5962166816).
This workflow wraps the existing [profile backup primitives](PROFILE_BACKUP.md).
It does not contact a cloud service, manage a Scheduler task, or authorize Owner-live work.

## Required Owner setup

- Choose an ordinary materialized local NTFS destination outside the profile and checkout.
  A sync client may copy it off-machine; Health-Check sees only filesystem IO.
- Choose explicit local NTFS staging outside profile, checkout and destination.
  It must be non-synced and private to the current Windows user. SYSTEM and local
  administrators are inside the host trust boundary. Broad allow ACLs, null/unsupported
  DACLs and uncertainty are refused. Plaintext residue is possible after a crash;
  an encrypted local staging volume is recommended. No secure erase claim is made.
- Supply an explicit absolute path to an Owner-trusted official `age.exe` v1.3.2.
  No PATH lookup, download/install, plugin or passphrase mode is supported.
  The executable must be a regular single-link non-reparse file outside all workflow roots.
  The version check is not binary provenance/signature verification.
- Supply exactly one native X25519 recipient and one dedicated native X25519 identity file.
  The identity is private, outside profile/checkout/destination/staging and is never archived.
  Store at least one independently tested recovery copy off the laptop, separate from the
  backup destination. Retain old identities while their archives are needed.
- The profile is the trusted local ledger root and must have private access. Do not make
  ACL changes on an existing Owner location without the Owner's explicit approval.

UNC/NAS, mapped/network drives, cloud placeholders/virtual filesystems, FAT/exFAT/ReFS,
reparse points/junctions/symlinks, hardlink/alias ambiguity and uncertain IO are unsupported.
Only one writer machine/profile may manage a destination; sync-replica locks are not distributed locks.
The `--staging-nonsynced` flag is the Owner's explicit attestation, not sync-client detection.

## Publish and inspect

Substitute explicit external paths; never put identity contents in arguments or logs:

```powershell
uv run --locked healthcheck offsite-backup --data-dir $Profile --destination $Destination `
  --staging $Staging --staging-nonsynced --age-executable $AgeExe `
  --recovery-identity $IdentityFile --recipient $Recipient --destination-alias offsite
uv run --locked healthcheck offsite-backup-list --data-dir $Profile `
  --destination $Destination --dry-run
```

The first command creates/verifies ZIP v1 through SQLite Online Backup, encrypts with age,
fully decrypts/authenticates into staging and verifies again. Ciphertext alone is copied to
an exclusive destination-volume `.partial`, flushed/closed, then renamed without overwrite.
The final destination file is reopened, compared with the expected ciphertext SHA-256,
fully decrypted/authenticated and verified through the same primitive. Only then is a
strict JSON receipt published beside it and `offsite-backup-ledger.json` updated atomically
in the source profile. Profile/destination operations are serialized with nonblocking locks.
The transient `.offsite-ledger.lock` is excluded from profile backups; the ledger is included.

The namespace is `hc148-v1-<UTC>-<UUID>.zip.age`; its receipt is that filename plus `.json`.
A final filename/receipt alone is not trusted completion. A crash before completion can
leave an unverified partial, ciphertext or orphan receipt. `publication_uncertain` requires
inspection; do not overwrite/retry the same name. Failure after destination verification
can still mean receipt/ledger completion is missing. No success is inferred from file existence.

## Retention

Keep is fixed at **3**. Trusted ledger append order defines newest points; timestamps, UUIDs
and destination mtimes cannot reorder rotation. Inspect with `offsite-backup-list` before opting into destructive
rotation via the same publication command plus `--rotate`. Rotation only follows a new
successfully verified point; the first missing-ledger run initializes trust without deleting.

Eligibility requires an exact namespace, a strict matching receipt, trusted local creation
record, current expected ciphertext size/hash and a safe single-link regular file identity.
Deletion is bound to the opened Windows handle. The ledger records no destination path or
key material. Missing/invalid/unreadable ledger or inconsistent inventory disables deletion.
Unknown files, partials, orphan/forged receipts, changed/corrupt archives and legacy points
are preserved. The bound is on managed verified points, not all destination contents.
Deletion/ledger failures are separate `retention=partial/failed` outcomes; the new verified
backup remains valid. Inspect `action_required` even when publication succeeded.

## Clean data recovery

Before total-laptop-loss recovery, obtain the archive UUID and expected ciphertext SHA-256
from an independently trusted record preserved outside both laptop and backup destination.
A destination receipt is not sufficient provenance. age authenticates ciphertext integrity,
not author identity, rollback resistance, remote availability or ransomware protection.

```powershell
uv run --locked healthcheck offsite-recover --backup $Ciphertext --target-dir $NewProfile `
  --staging $Staging --staging-nonsynced --age-executable $AgeExe `
  --recovery-identity $IdentityFile --expected-uuid $TrustedUuid `
  --expected-sha256 $TrustedSha256
```

The explicit new external target must not exist; replacement is refused. Its parent must
be private local NTFS. Fingerprint, full decryption/authentication, inner archive validation
and exact runtime migration revision are checked before restore mutation. Older/unknown
revisions require an accepted compatible runtime/recovery decision; no automatic migration
or repair is attempted. Restore reuses the existing primitive with no-overwrite publication.
Then SQLite integrity, migration identity and six capped domain/readiness counts are checked.
A failure after restore reports `target_created` and `restored_readiness_unverified`; it must
not be treated as pre-mutation rejection or automatically retried over the target.

Data recovery is separate from provider access. Machine/user-bound sessions may be unusable;
this command reports reauthorization required conservatively and never opens provider sessions,
decrypts/copies credentials, changes collection policy or performs provider calls.

For the complete Owner-controlled rehearsal:
1. Retrieve ciphertext, independent fingerprint and recovery material from another device/location.
2. Run clean data recovery into a disposable external profile and preserve the original ciphertext.
3. Review restored configuration/absolute paths and collection policy before enabling any operation.
4. Start the accepted loopback UI using explicit `--data-dir`; use the existing `smoke` command
   for supported read paths. The recovery command does not claim that smoke ran.
5. Re-establish Google Web client configuration when needed, then use existing `garmin-auth`
   and `google-auth` under the new Windows user. DPAPI portability is never assumed.
6. Only with explicit Owner approval use bounded accepted `owner-refresh`, preserving intended
   streams/collection policy. See [Owner refresh](OWNER_REFRESH.md); no implicit backfill.

Status separates created/protected/published/destination_verified, retention and rehearsal.
`offsite_presence` stays `UNVERIFIED` until off-machine retrieval/recovery is actually evidenced.
A local filesystem read-back cannot prove cloud upload or persistence through every power failure.
Lost local ledger records do not authorize adopting destination receipts for deletion.

Automated tests use only synthetic profiles and an explicitly labelled opaque age-process double.
They test orchestration, failure boundaries and native Windows IO, not the cryptographic implementation.
No binary is downloaded or discovered for tests. Official executable interoperability and Owner
protected/off-machine rehearsal remain explicit verification limitations until separately evidenced.
