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


class _ParserRejected(Exception):
    """A stdout request failed argument parsing; supplied values stay unprinted."""


class _ArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises instead of exiting when sanitizing errors.

    File-mode behavior and ``--help`` are unchanged. Only an already-identified
    stdout request suppresses argparse's usage/error text, because that text can
    echo arbitrary (possibly private) supplied values.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._sanitize_errors = False

    def error(self, message: str) -> None:
        if self._sanitize_errors:
            raise _ParserRejected
        super().error(message)


def _requests_stdout(argv: list[str], parser: argparse.ArgumentParser) -> bool:
    """True when argv selects stdout, including argparse long-option abbreviations.

    Mirrors argparse's own resolution so any unique abbreviation of ``--stdout``
    that it accepts (``--st``, ``--std``, ``--stdo``, ``--stdou``), with a
    separated or ``=``-attached value, is recognized as a stdout request.
    Unrelated or ambiguous tokens are not, leaving file-mode parsing unchanged.
    """
    for token in argv:
        if not token.startswith("--"):
            continue
        matches = parser._get_option_tuples(token)
        if len(matches) == 1 and matches[0][0].dest == "stdout_format":
            return True
    return False


def _write_stdout_safely(text: str) -> None:
    """Write one complete serializer result to stdout as exact UTF-8 bytes.

    Redirected or piped stdout receives the exact UTF-8 bytes of the serializer
    result even when the active console encoding cannot represent some
    characters; the packet is never re-escaped into invalid JSON, substituted or
    truncated. A text-only stream without a byte buffer receives the text as-is.
    """

    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = _ArgumentParser(description="Bounded saved Sleep + Activity + Context export")
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
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output-dir", type=Path,
                             help="New external directory; never overwrites existing files")
    destination.add_argument("--stdout", dest="stdout_format", choices=("json", "text"),
                             help="Emit only the selected serializer result on stdout")
    parser.add_argument("--agent-workspace-root", type=Path, action="append", default=[])
    # Abbreviation-aware: set only after every option string is registered.
    parser._sanitize_errors = _requests_stdout(argv, parser)
    try:
        args = parser.parse_args(argv)
    except _ParserRejected:
        # A malformed stdout request: empty stdout, one bounded sanitized code.
        print("Export failed: invalid_arguments", file=sys.stderr)
        return 2
    try:
        if args.output_dir is not None:
            output = args.output_dir.expanduser().resolve()
            _check_output_location(output, args.agent_workspace_root)
            profile = args.profile.expanduser().resolve()
            if output == profile or profile in output.parents:
                raise EvidenceError("output_must_be_outside_profile")
            if output.exists():
                raise EvidenceError("output_destination_already_exists")
        else:
            profile = args.profile.expanduser().resolve()
        packet = read_combined_evidence(
            profile=profile, profile_kind=args.profile_kind,
            request=CombinedEvidenceRequest(
                args.end_date, args.days, args.activity_garmin_source_id,
                args.sleep_garmin_source_id, args.sleep_google_source_id,
                args.include_context, args.context_limit, args.sleep_google_auto_select),
            evaluated_at_utc=datetime.now(UTC), evaluation_local_date=args.evaluation_local_date,
        )
        if args.output_dir is not None:
            machine = encode_combined_evidence(packet)
            readable = render_combined_evidence(packet)
            output.mkdir(parents=True, exist_ok=False)
            (output / "evidence.json").write_text(machine, encoding="utf-8")
            (output / "evidence.txt").write_text(readable, encoding="utf-8")
        else:
            # Validate and build the full serializer result before any byte
            # reaches stdout, so no payload leaks on a later failure.
            payload = (encode_combined_evidence(packet) if args.stdout_format == "json"
                       else render_combined_evidence(packet))
            _write_stdout_safely(payload)
    except EvidenceError as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print("Export failed: output_or_profile_unavailable", file=sys.stderr)
        return 2
    if args.output_dir is not None:
        print("Combined evidence JSON and text saved locally; no upload performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
