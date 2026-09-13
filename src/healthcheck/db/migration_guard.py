"""Offline validation of the accepted Alembic migration ancestry."""

from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path

from alembic.script import ScriptDirectory

MigrationIdentity = tuple[str, str | None]
MigrationParents = tuple[str, ...]

# This is the accepted lineage at the R04 integration boundary.  Changing this
# list is intentionally a visible, reviewable acknowledgement of a lineage
# reconciliation or a new accepted release head.
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


def _forward_extension_errors(
    actual: dict[str, MigrationParents],
    accepted_ids: set[str],
    accepted_head: str,
) -> list[str]:
    """Return errors for revisions that are not a linear forward extension."""

    extras = sorted(set(actual) - accepted_ids)
    if not extras:
        return []

    errors: list[str] = []
    extra_ids = set(extras)
    children: dict[str, list[str]] = defaultdict(list)

    for revision in extras:
        parents = actual[revision]
        if len(parents) != 1:
            errors.append(
                f"new revision {revision!r} has {len(parents)} parent(s); "
                "only a linear forward extension is accepted"
            )
            continue
        parent = parents[0]
        if parent in accepted_ids and parent != accepted_head:
            errors.append(
                f"new revision {revision!r} is behind accepted head: "
                f"down_revision={parent!r}; expected {accepted_head!r} or a new revision"
            )
        children[parent].append(revision)

    if len(children[accepted_head]) != 1:
        errors.append(
            f"new revisions do not extend accepted head {accepted_head!r} "
            f"as one linear chain: first children={tuple(sorted(children[accepted_head]))!r}"
        )

    reached: set[str] = set()
    current = children[accepted_head][0] if len(children[accepted_head]) == 1 else None
    while current is not None:
        if current in reached:
            errors.append(f"new migration ancestry contains a cycle at {current!r}")
            break
        reached.add(current)
        next_revisions = sorted(children[current])
        if len(next_revisions) > 1:
            errors.append(
                f"new revision {current!r} branches into {tuple(next_revisions)!r}; "
                "only a linear forward extension is accepted"
            )
            break
        current = next_revisions[0] if next_revisions else None

    disconnected = sorted(extra_ids - reached)
    if disconnected:
        errors.append(f"new revisions are disconnected from accepted head: {tuple(disconnected)!r}")
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

    errors.extend(_forward_extension_errors(actual, accepted_ids, accepted_head))

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
