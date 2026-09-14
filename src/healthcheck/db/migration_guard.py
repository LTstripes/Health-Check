"""Offline validation of the accepted Alembic migration ancestry."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from alembic.script import ScriptDirectory

MigrationIdentity = tuple[str, str | None]
MigrationParents = tuple[str, ...]

# This is the accepted lineage at the R04 integration boundary.  Adding a
# migration requires extending this list in the same change; an unlisted
# revision is never an implicitly accepted forward extension.
ACCEPTED_MIGRATION_CHAIN: tuple[MigrationIdentity, ...] = (
    ("0001_r01_core_schema", None),
    ("0002_canonical_selection_metric_identity", "0001_r01_core_schema"),
    ("0003_photo_candidate_provenance", "0002_canonical_selection_metric_identity"),
    ("0004_naive_minute_wall_clock", "0003_photo_candidate_provenance"),
    ("0005_garmin_persistence_contract", "0004_naive_minute_wall_clock"),
    ("0006_garmin_payload_observation_provenance", "0005_garmin_persistence_contract"),
    ("0007_garmin_collection_reconciliation", "0006_garmin_payload_observation_provenance"),
    ("0008_garmin_observation_reconciliation_version", "0007_garmin_collection_reconciliation"),
    ("0009_google_persistence_contract", "0008_garmin_observation_reconciliation_version"),
    ("0010_google_typed_normalization", "0009_google_persistence_contract"),
    ("0011_r05_agreement_run_persistence", "0010_google_typed_normalization"),
    ("0012_r05_agreement_successor_publication", "0011_r05_agreement_run_persistence"),
)
ACCEPTED_MIGRATION_HEAD = ACCEPTED_MIGRATION_CHAIN[-1][0]
MIGRATION_SCRIPT_LOCATION = Path(__file__).with_name("migrations")


class MigrationAncestryError(ValueError):
    """Raised when migration scripts do not preserve the accepted lineage."""


def _parents(down_revision: object) -> MigrationParents:
    if down_revision is None:
        return ()
    if isinstance(down_revision, str):
        return (down_revision,)
    return tuple(down_revision)  # type: ignore[arg-type]


def _format_parents(parents: Iterable[str]) -> str:
    values = tuple(parents)
    return repr(values[0]) if len(values) == 1 else repr(values)


def _unacknowledged_revision_errors(
    actual: dict[str, MigrationParents],
    accepted_ids: set[str],
    accepted_head: str,
) -> list[str]:
    """Return errors for revisions absent from the protected accepted chain."""

    extras = sorted(set(actual) - accepted_ids)
    if not extras:
        return []

    errors = [
        f"unacknowledged Alembic revision(s): {tuple(extras)!r}; "
        "extend the accepted migration chain in the same change"
    ]
    for revision in extras:
        parents = actual[revision]
        if len(parents) == 1 and parents[0] in accepted_ids and parents[0] != accepted_head:
            errors.append(
                f"unacknowledged revision {revision!r} is behind accepted head: "
                f"down_revision={parents[0]!r}; expected {accepted_head!r} only after "
                "explicit accepted-lineage update"
            )
    return errors


def validate_migration_ancestry(
    script_location: str | Path = MIGRATION_SCRIPT_LOCATION,
    accepted_chain: Sequence[MigrationIdentity] = ACCEPTED_MIGRATION_CHAIN,
) -> None:
    """Validate migration files against the accepted chain without opening a DB."""

    if not accepted_chain:
        raise MigrationAncestryError("accepted migration chain must not be empty")

    accepted = dict(accepted_chain)
    accepted_ids = set(accepted)
    accepted_head = accepted_chain[-1][0]
    try:
        directory = ScriptDirectory(str(script_location))
        heads = tuple(sorted(directory.get_heads()))
        revisions = tuple(directory.walk_revisions(base="base", head="heads"))
    except Exception as exc:
        raise MigrationAncestryError(f"unable to load migration ancestry: {exc}") from exc

    actual: dict[str, MigrationParents] = {}
    for script in revisions:
        if script.revision in actual:
            raise MigrationAncestryError(f"duplicate migration revision id: {script.revision!r}")
        actual[script.revision] = _parents(script.down_revision)

    errors: list[str] = []
    missing = sorted(accepted_ids - set(actual))
    if missing:
        errors.append(f"accepted migration revision(s) missing or renamed: {tuple(missing)!r}")

    changed = sorted(
        revision
        for revision in accepted_ids & set(actual)
        if actual[revision] != _parents(accepted[revision])
    )
    for revision in changed:
        errors.append(
            f"accepted revision {revision!r} changed down_revision: "
            f"expected {_format_parents(_parents(accepted[revision]))}, "
            f"found {_format_parents(actual[revision])}"
        )

    if len(heads) != 1:
        errors.append(f"expected exactly one Alembic head; found {heads!r}")
    elif heads[0] != accepted_head:
        errors.append(
            f"expected accepted Alembic head {accepted_head!r}; found {heads[0]!r}"
        )

    errors.extend(_unacknowledged_revision_errors(actual, accepted_ids, accepted_head))

    if errors:
        raise MigrationAncestryError("; ".join(errors))


def main() -> int:
    try:
        validate_migration_ancestry()
    except MigrationAncestryError as exc:
        print(f"Alembic migration ancestry check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Alembic migration ancestry check passed: head {ACCEPTED_MIGRATION_HEAD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
