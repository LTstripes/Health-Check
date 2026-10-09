"""Explicit standalone command: python -m healthcheck.export_chat_evidence."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from healthcheck.chat_evidence import (
    DOMAINS,
    PROFILE_KINDS,
    EvidenceError,
    EvidenceRequest,
    encode_evidence,
    read_period_evidence,
    render_evidence,
)


def _check_output_location(output: Path, agent_workspace_roots: list[Path]) -> None:
    # Inspect markers only: linked worktrees use a .git file, not a directory.
    # lstat also rejects broken marker links; unreadable ancestry fails closed.
    for ancestor in (output, *output.parents):
        try:
            (ancestor / ".git").lstat()
        except FileNotFoundError:
            continue
        raise EvidenceError("output_must_be_outside_git_or_agent_workspace")
    for root in agent_workspace_roots:
        workspace = root.expanduser().resolve()
        if output == workspace or workspace in output.parents:
            raise EvidenceError("output_must_be_outside_git_or_agent_workspace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local bounded health + Context export")
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--profile-kind", required=True, choices=sorted(PROFILE_KINDS))
    parser.add_argument("--from", required=True, dest="start", type=date.fromisoformat)
    parser.add_argument("--to", required=True, dest="end", type=date.fromisoformat)
    parser.add_argument("--domain", required=True, action="append", choices=sorted(DOMAINS))
    parser.add_argument("--metric", action="append", default=[])
    parser.add_argument("--garmin-source-id")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--weight-cadence-days", type=int, default=7,
                        help="Explicit export policy, not inferred from runtime config (default 7)")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="New directory outside the profile; never overwrites existing files")
    parser.add_argument("--agent-workspace-root", type=Path, action="append", default=[],
                        help="Explicit development root to exclude even without .git; repeatable")
    args = parser.parse_args(argv)
    try:
        output = args.output_dir.expanduser().resolve()
        _check_output_location(output, args.agent_workspace_root)
        profile = args.profile.expanduser().resolve()
        if output == profile or profile in output.parents:
            raise EvidenceError("output_must_be_outside_profile")
        if output.exists():
            raise EvidenceError("output_destination_already_exists")
        clock = datetime.now(UTC)
        envelope = read_period_evidence(
            profile=profile, profile_kind=args.profile_kind,
            request=EvidenceRequest(args.start, args.end, tuple(args.domain), tuple(args.metric),
                                    args.garmin_source_id, args.limit, args.weight_cadence_days),
            evaluated_at_utc=clock, evaluation_local_date=clock.astimezone().date(),
        )
        machine = encode_evidence(envelope)
        readable = render_evidence(envelope)
        output.mkdir(parents=True, exist_ok=False)
        (output / "evidence.json").write_text(machine, encoding="utf-8")
        (output / "evidence.txt").write_text(readable, encoding="utf-8")
    except EvidenceError as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Storage/query failures never echo paths, original text or provider bodies.
        print("Export failed: output_or_profile_unavailable", file=sys.stderr)
        return 2
    print("Evidence JSON and readable text saved locally; no upload performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
