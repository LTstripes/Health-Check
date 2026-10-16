"""Explicit standalone CLI: python -m healthcheck.export_combined_evidence."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from healthcheck.chat_evidence import PROFILE_KINDS, EvidenceError
from healthcheck.combined_evidence import (
    CombinedEvidenceRequest,
    encode_combined_evidence,
    read_combined_evidence,
    render_combined_evidence,
)
from healthcheck.export_chat_evidence import _check_output_location


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded saved Sleep + Activity + Context export")
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--profile-kind", required=True, choices=sorted(PROFILE_KINDS))
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument("--days", required=True, type=int, choices=(7, 30))
    parser.add_argument("--activity-garmin-source-id", required=True)
    parser.add_argument("--sleep-garmin-source-id")
    parser.add_argument("--sleep-google-source-id")
    parser.add_argument("--sleep-google-auto-select", action="store_true",
                        help="Select the unique eligible Google Sleep source in this window")
    parser.add_argument("--include-context", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--context-limit", type=int, default=50)
    parser.add_argument("--evaluation-local-date", required=True, type=date.fromisoformat,
                        help="Explicit evaluation date; never inferred from host timezone")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="New external directory; never overwrites existing files")
    parser.add_argument("--agent-workspace-root", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    try:
        output = args.output_dir.expanduser().resolve()
        _check_output_location(output, args.agent_workspace_root)
        profile = args.profile.expanduser().resolve()
        if output == profile or profile in output.parents:
            raise EvidenceError("output_must_be_outside_profile")
        if output.exists():
            raise EvidenceError("output_destination_already_exists")
        packet = read_combined_evidence(
            profile=profile, profile_kind=args.profile_kind,
            request=CombinedEvidenceRequest(
                args.end_date, args.days, args.activity_garmin_source_id,
                args.sleep_garmin_source_id, args.sleep_google_source_id,
                args.include_context, args.context_limit, args.sleep_google_auto_select),
            evaluated_at_utc=datetime.now(UTC), evaluation_local_date=args.evaluation_local_date,
        )
        machine = encode_combined_evidence(packet)
        readable = render_combined_evidence(packet)
        output.mkdir(parents=True, exist_ok=False)
        (output / "evidence.json").write_text(machine, encoding="utf-8")
        (output / "evidence.txt").write_text(readable, encoding="utf-8")
    except EvidenceError as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print("Export failed: output_or_profile_unavailable", file=sys.stderr)
        return 2
    print("Combined evidence JSON and text saved locally; no upload performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
