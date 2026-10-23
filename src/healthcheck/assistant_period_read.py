"""Local operator-bound saved-period reader (#507), without runtime startup.

The assistant supplies only {"end_date": "YYYY-MM-DD", "days": 7 or 30}.
The executor supplies an independently provisioned OperatorBinding, or launches
``python -m healthcheck.assistant_period_read --binding <operator-json>`` with
that request on stdin. Binding paths/identities are never request arguments.

The Python result retains complete immutable packet JSON for inspection. stdout
contains a bounded digest, not a replacement evidence packet. Consumers MUST use
validate_complete_output on the entire captured stdout before accepting it.
Neither this module nor a skill grants access, transport or provider permission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, fields
from datetime import UTC, date, datetime
from importlib.metadata import distributions
from pathlib import Path
from zoneinfo import ZoneInfo

from alembic.script import ScriptDirectory

from healthcheck import combined_evidence as combined
from healthcheck.chat_evidence import MAX_OUTPUT_BYTES, PROFILE_KINDS, EvidenceError, _json

VERSION = "health-assistant-period-read-v1"
OUTPUT_VERSION = "health-assistant-period-output-v1"
MAX_DIGEST_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 256
MAX_BINDING_BYTES = 16 * 1024
OBSERVATION_LIMIT = 3
CONTEXT_LIMIT = 50
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def code_identity() -> str:
    """Bind the loaded source tree, migrations and locked dependency declaration.

    This is a local operator compatibility proof, not authentication or a claim
    that a running process is protected from its own OS user.
    """
    package = Path(__file__).resolve().parent
    root = package.parent.parent
    files = sorted(package.rglob("*.py")) + [root / "pyproject.toml", root / "uv.lock"]
    return _hash(
        _json(
            [
                (
                    str(path.relative_to(root)).replace("\\", "/"),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
                for path in files
            ]
        )
    )


def runtime_identity() -> str:
    """Exact local interpreter path/binary/version and installed distribution set."""
    executable = Path(sys.executable).resolve()
    return _hash(
        _json(
            {
                "executable": str(executable),
                "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "python": sys.version,
                "distributions": sorted(
                    (item.metadata["Name"], item.version) for item in distributions()
                ),
            }
        )
    )


def schema_identity() -> tuple[str, ...]:
    return tuple(
        sorted(
            ScriptDirectory(
                str(Path(combined.__file__).resolve().parent / "db" / "migrations")
            ).get_heads()
        )
    )


def database_identity(profile: Path) -> str:
    """Operator enrollment helper: exact physical DB identity, never an auto choice."""
    stat = (profile / "healthcheck.db").stat()
    return f"{stat.st_dev}:{stat.st_ino}"


@dataclass(frozen=True)
class SourceBindings:
    activity_garmin_source_id: str
    sleep_garmin_source_id: str | None = None
    sleep_google_source_id: str | None = None
    stress_garmin_source_id: str | None = None
    body_battery_garmin_source_id: str | None = None
    hrv_garmin_source_id: str | None = None
    hrv_google_source_id: str | None = None
    rhr_garmin_source_id: str | None = None
    rhr_google_source_id: str | None = None
    steps_garmin_source_id: str | None = None
    steps_google_source_id: str | None = None

    def request(self, end_date: date, days: int) -> combined.CombinedEvidenceRequest:
        # Fixed projection, caps, saved observed Steps and no automatic selection.
        return combined.CombinedEvidenceRequest(
            end_date=end_date,
            days=days,
            **asdict(self),
            projection="compact",
            include_context=True,
            context_limit=CONTEXT_LIMIT,
            include_weight=True,
            steps_view="observed",
        )


@dataclass(frozen=True)
class OperatorBinding:
    profile: Path
    profile_kind: str
    database_id: str
    code_id: str
    runtime_id: str
    schema_heads: tuple[str, ...]
    evaluation_zone: str
    sources: SourceBindings

    def validate(self) -> None:
        if (
            not isinstance(self.profile, Path)
            or not self.profile.is_absolute()
            or self.profile_kind not in PROFILE_KINDS
            or type(self.database_id) is not str
            or re.fullmatch(r"[0-9]+:[0-9]+", self.database_id) is None
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (self.code_id, self.runtime_id)
            )
            or type(self.schema_heads) is not tuple
            or not self.schema_heads
            or any(type(head) is not str for head in self.schema_heads)
            or type(self.evaluation_zone) is not str
            or type(self.sources) is not SourceBindings
        ):
            raise EvidenceError("invalid_operator_binding")
        # Validate source identities/options before any profile access.
        self.sources.request(date(2000, 1, 31), 7).validate()
        ZoneInfo(self.evaluation_zone)

    def preflight(self) -> None:
        self.validate()
        if self.code_id != code_identity():
            raise EvidenceError("bound_code_mismatch")
        if self.runtime_id != runtime_identity():
            raise EvidenceError("bound_runtime_mismatch")
        if self.schema_heads != schema_identity():
            raise EvidenceError("bound_schema_mismatch")
        if not self.profile.is_dir() or not (self.profile / "healthcheck.db").is_file():
            raise EvidenceError("profile_database_unavailable")
        if self.profile != self.profile.resolve() or self.database_id != database_identity(
            self.profile
        ):
            raise EvidenceError("bound_profile_mismatch")
        # The existing reader validates actual schema heads IN its one snapshot.


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("duplicate_argument")
        result[key] = value
    return result


def _load_json(text: str):
    return json.loads(
        text,
        object_pairs_hook=_object,
        parse_constant=lambda _value: (_ for _ in ()).throw(EvidenceError("invalid_json")),
    )


def parse_request(value: object) -> tuple[date, int]:
    if (
        type(value) is not dict
        or set(value) != {"end_date", "days"}
        or type(value["end_date"]) is not str
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value["end_date"]) is None
        or type(value["days"]) is not int
        or value["days"] not in (7, 30)
    ):
        raise EvidenceError("unsupported_period_request")
    try:
        end = date.fromisoformat(value["end_date"])
        # Reuse the accepted period bounds, including underflow/date.max.
        from healthcheck.sleep_evidence import SleepEvidenceRequest

        SleepEvidenceRequest(end, value["days"], garmin_source_id="validation-only").validate()
    except (ValueError, OverflowError) as exc:
        raise EvidenceError("unsupported_period_request") from exc
    return end, value["days"]


def _binding_from_json(text: str) -> OperatorBinding:
    value = _load_json(text)
    if (
        type(value) is not dict
        or set(value) != {field.name for field in fields(OperatorBinding)}
        or type(value["profile"]) is not str
        or type(value["schema_heads"]) is not list
        or type(value["sources"]) is not dict
    ):
        raise EvidenceError("invalid_operator_binding")
    return OperatorBinding(
        **{
            **value,
            "profile": Path(value["profile"]),
            "schema_heads": tuple(value["schema_heads"]),
            "sources": SourceBindings(**value["sources"]),
        }
    )


def _validate_packet(packet: dict, request, binding, clock, local_date) -> str:
    """Check this adapter's fixed contract and existing compact references/hash.

    Source readers remain the semantic/disclosure authority. This does not
    reconstruct detailed evidence or introduce an alternative schema framework.
    """
    encoded = combined.encode_combined_evidence(packet)
    frozen = _load_json(encoded)
    expected = {
        "sleep": {
            provider: identity
            for provider, identity in (
                ("garmin", request.sleep_garmin_source_id),
                ("google", request.sleep_google_source_id),
            )
            if identity is not None
        },
        "activity": {"garmin": request.activity_garmin_source_id},
        "weight": {"selection_policy": "accepted_weight_overlay_and_canonical"},
    }
    for domain in ("stress", "body_battery", "hrv", "rhr", "steps", "google_steps"):
        if domain == "google_steps":
            selections = {"google_source_id": request.steps_google_source_id}
        elif domain in ("hrv", "rhr"):
            selections = {
                f"{provider}_source_id": getattr(request, f"{domain}_{provider}_source_id")
                for provider in ("garmin", "google")
            }
        else:
            selections = {"garmin_source_id": getattr(request, f"{domain}_garmin_source_id")}
        if any(value is not None for value in selections.values()):
            expected[domain] = selections
    window = {
        "start_date": request.domain_requests()[0].start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "precision": "inclusive_local_date",
    }
    expected_version = (
        "health-chat-combined-compact-evidence-v7"
        if (request.steps_google_source_id is not None)
        else "health-chat-combined-compact-evidence-v4"
    )
    if (
        frozen["version"] != expected_version
        or frozen["provenance_version"] != combined.PROVENANCE_VERSION
        or frozen["projection"]
        != {
            "mode": "compact",
            "detailed_version": expected_version.replace("-compact", ""),
            "sleep_evidence_schema": combined.COMPACT_SLEEP_SCHEMA_VERSION,
            "sleep_segments": "counts_and_sha256_not_replayable_segments",
            "sleep_session_endpoints": "retained_with_original_temporal_precision",
            "session_evidence": "evidence_common_overlaid_with_metric_evidence",
            "field_paths": "session_field_path_sets_indexed_by_field_paths_index",
            "session_intervals": "session_interval_sets_indexed_by_session_intervals_index",
            "quality_inputs": "session_quality_input_sets_indexed_by_quality_inputs_index",
            "night_summary": "summary_record_id_references_saved_session_or_null",
            "values_and_flags": "unchanged_accepted_reader_results",
        }
        or frozen["request"]
        != {
            "days": request.days,
            "include_context": True,
            "requested_range": window,
            "effective_range": window,
            "range_truncated": False,
            "sources": expected,
        }
        or frozen["profile"]["kind"] != binding.profile_kind
        or frozen["evaluation_clock"]
        != {"utc": clock.astimezone(UTC).isoformat(), "local_date": local_date.isoformat()}
        or frozen["snapshot"] != "one_sqlite_read_transaction"
        or frozen["limits"]["max_output_bytes"] != MAX_OUTPUT_BYTES
        or frozen["interpretation"]["source_pooling"] != "not_performed"
        or frozen["interpretation"]["causality"] != "not_established"
        or frozen["envelope_hash"]
        != _hash(_json({key: item for key, item in frozen.items() if key != "envelope_hash"}))
    ):
        raise EvidenceError("incompatible_combined_packet")
    if set(frozen["sections"]) != set(expected) | {"context"}:
        # sleep/activity/domain keys coincide with their request selection keys.
        raise EvidenceError("incompatible_combined_packet")
    for provider in frozen["sections"]["sleep"]["providers"].values():
        window = provider["source_range"]
        if window is None:
            continue
        for night in window["days"]:
            for source in night["sources"]:
                for session in source["sessions"]:
                    for cell in session["metrics"].values():
                        restored = combined._restore_compact_sleep_evidence(session, cell)
                        index = restored.get("field_paths_index")
                        if type(index) is not int or not 0 <= index < len(
                            session["field_path_sets"]
                        ):
                            raise EvidenceError("invalid_compact_sleep_index")
    return encoded


def _take(value: dict, names: str) -> dict:
    return {key: value[key] for key in names.split() if key in value}


def _observations(sections: dict) -> list[dict]:
    """Copy existing facts; never compute a mean, sum, eligibility or causal join."""
    result = []
    for domain, section in sections.items():
        providers = (
            section["providers"]
            if domain in {"sleep", "activity", "hrv", "rhr"}
            else {
                "google"
                if domain == "google_steps"
                else "owner"
                if domain in {"context", "weight"}
                else "garmin": section
            }
        )
        for provider, body in providers.items():
            pointer = f"/sections/{domain}" + (
                f"/providers/{provider}" if "providers" in section else ""
            )
            item = {
                "domain": domain,
                "provider": provider,
                "packet_pointer": pointer,
                "summary": _take(
                    body,
                    "selected_source_id source_id source_identity "
                    "source_selection selection state reason meaning unit acquisition_coverage "
                    "acquisition_coverage_state search search_complete warnings "
                    "eligible_day_count excluded_day_count missing_day_count "
                    "mean_exact mean_value mean_display window_state limits "
                    "coverage pagination timezone finality",
                ),
            }
            if domain == "sleep":
                window = body["source_range"]
                item["summary"]["source_range"] = (
                    None
                    if window is None
                    else _take(
                        window,
                        "state reason availability coverage missing_dates "
                        "wake_date_missing_by_source",
                    )
                )
                rows = [] if window is None else window["series"]
                # A series is already the resolved source/role selection, retain
                # its metadata and bounded points without deriving new values.
                item["facts"] = [
                    {
                        **_take(row, "source_id metric_code unit role state reason"),
                        "points": row["points"][-OBSERVATION_LIMIT:],
                        "omitted_points": max(0, len(row["points"]) - OBSERVATION_LIMIT),
                    }
                    for row in rows[-OBSERVATION_LIMIT:]
                ]
            elif domain == "activity":
                item["facts"] = {
                    code: _take(
                        cell,
                        "state reason metric_code unit aggregation search observed_day_count "
                        "missing_day_count coverage eligibility exclusions",
                    )
                    for code, cell in body["metrics"].items()
                }
                item["summary"]["temporal_evidence"] = _take(
                    section["temporal_evidence"], "state reason limits"
                )
                rows = []
            elif domain == "context":
                item["summary"].update(
                    _take(
                        body,
                        "trust absence_semantics relationship "
                        "returned_count total_count has_more truncated limit",
                    )
                )
                rows = body["rows"]
                # Context text is deliberately absent from the digest; complete
                # escaped untrusted revisions remain in frozen packet JSON.
                item["facts"] = [
                    _take(row, "event_id revision_id revision_number temporal")
                    for row in rows[-OBSERVATION_LIMIT:]
                ]
            elif domain == "weight":
                item["summary"]["source_status"] = body["source_status"]
                item["summary"]["pages"] = {
                    key: _take(body[key], "returned_count total_count has_more truncated limit")
                    for key in ("measured_facts", "daily_series", "trend_series")
                }
                rows = body["daily_series"]["rows"]
                item["facts"] = rows[-OBSERVATION_LIMIT:]
            else:
                rows = body.get(
                    "cells",
                    body.get("points", body.get("observations", body.get("daily_maxima", []))),
                )
                item["facts"] = rows[-OBSERVATION_LIMIT:]
            item["omitted_rows"] = max(0, len(rows) - OBSERVATION_LIMIT)
            result.append(item)
    return result


@dataclass(frozen=True)
class FrozenPeriodRead:
    packet_json: str
    digest_json: str
    output: str


def read_assistant_period(
    *, binding: OperatorBinding, request: object, evaluated_at_utc: datetime
) -> FrozenPeriodRead:
    end, days = parse_request(request)  # Always before binding/profile IO.
    if (
        not isinstance(evaluated_at_utc, datetime)
        or evaluated_at_utc.tzinfo is None
        or evaluated_at_utc.utcoffset() is None
    ):
        raise EvidenceError("aware_evaluation_clock_required")
    binding.preflight()
    local = evaluated_at_utc.astimezone(ZoneInfo(binding.evaluation_zone)).date()
    selected = binding.sources.request(end, days)
    packet = combined.read_combined_evidence(
        profile=binding.profile,
        profile_kind=binding.profile_kind,
        request=selected,
        evaluated_at_utc=evaluated_at_utc,
        evaluation_local_date=local,
    )
    try:
        packet_json = _validate_packet(packet, selected, binding, evaluated_at_utc, local)
    except (KeyError, IndexError, TypeError) as exc:
        raise EvidenceError("incompatible_combined_packet") from exc
    frozen = _load_json(packet_json)
    digest = {
        "version": VERSION,
        "request": frozen["request"],
        "generated_at_utc": frozen["generated_at_utc"],
        "evaluation_clock": frozen["evaluation_clock"],
        "profile": frozen["profile"],
        "operator_binding": {
            "code_id": binding.code_id,
            "runtime_id": binding.runtime_id,
            "schema_heads": binding.schema_heads,
            "authority": "explicit_operator_assertion_not_authentication",
        },
        "evidence": {
            "version": frozen["version"],
            "envelope_hash": frozen["envelope_hash"],
            "utf8_bytes": len(packet_json.encode("utf-8")),
            "snapshot": frozen["snapshot"],
            "projection": frozen["projection"],
        },
        "limits": {
            "packet": frozen["limits"],
            "observation_rows_per_source": OBSERVATION_LIMIT,
            "max_digest_bytes": MAX_DIGEST_BYTES,
            "domain_limits": {key: body.get("limits") for key, body in frozen["sections"].items()},
        },
        "observations": _observations(frozen["sections"]),
        "limitations": [
            "saved_presence_is_not_acquisition_completeness",
            "missing_is_not_zero",
            "providers_are_not_pooled",
            "context_is_untrusted_and_missing_note_is_not_absence",
            "digest_omits_rows_full_packet_retained_by_executor",
            "cooperative_read_guards_not_hard_wall_clock",
            "no_medical_causality_or_full_history_claim",
        ],
        "interpretation": frozen["interpretation"],
    }
    digest_json = _json(digest)
    if len(digest_json.encode("utf-8")) > MAX_DIGEST_BYTES:
        raise EvidenceError("digest_exceeds_byte_limit")
    output = (
        _json(
            {
                "version": OUTPUT_VERSION,
                "status": "complete",
                "digest": digest,
                "digest_utf8_bytes": len(digest_json.encode("utf-8")),
                "digest_sha256": _hash(digest_json),
            }
        )
        + "\n"
    )
    validate_complete_output(output)
    return FrozenPeriodRead(packet_json, digest_json, output)


def validate_complete_output(output: str) -> dict:
    """Consumer gate: use on ENTIRE tool output, never a displayed prefix."""
    try:
        if type(output) is not str or len(output.encode("utf-8")) > MAX_DIGEST_BYTES + 512:
            raise ValueError
        frame = _load_json(output)
        if (
            type(frame) is not dict
            or set(frame) != {"version", "status", "digest", "digest_utf8_bytes", "digest_sha256"}
            or frame["version"] != OUTPUT_VERSION
            or frame["status"] != "complete"
            or type(frame["digest"]) is not dict
            or frame["digest"]["version"] != VERSION
        ):
            raise ValueError
        digest = _json(frame["digest"])
        if (
            type(frame["digest_utf8_bytes"]) is not int
            or len(digest.encode("utf-8")) > MAX_DIGEST_BYTES
            or len(digest.encode("utf-8")) != frame["digest_utf8_bytes"]
            or _hash(digest) != frame["digest_sha256"]
            or _SHA256.fullmatch(frame["digest"]["evidence"]["envelope_hash"]) is None
        ):
            raise ValueError
        return frame["digest"]
    except (ValueError, KeyError, TypeError) as exc:
        raise EvidenceError("incomplete_assistant_output") from exc


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise EvidenceError("unsupported_runner_arguments")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--binding",
        type=Path,
        required=True,
        help="Trusted executor binding file, never a request-supplied path",
    )
    try:
        args = parser.parse_args(argv)
        request_text = sys.stdin.read(MAX_REQUEST_BYTES + 1)
        if len(request_text.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise EvidenceError("unsupported_period_request")
        request = _load_json(request_text)
        parse_request(request)
        with args.binding.open("r", encoding="utf-8") as stream:
            text = stream.read(MAX_BINDING_BYTES + 1)
        if len(text.encode("utf-8")) > MAX_BINDING_BYTES:
            raise EvidenceError("invalid_operator_binding")
        result = read_assistant_period(
            binding=_binding_from_json(text), request=request, evaluated_at_utc=datetime.now(UTC)
        )
        # One complete prevalidated UTF-8 output; no prefix on execution failure.
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is None:
            sys.stdout.write(result.output)
        else:
            buffer.write(result.output.encode("utf-8"))
            buffer.flush()
        return 0
    except Exception as exc:
        explanations = {
            "unsupported_period_request": "Use an ISO end_date and integer days 7 or 30 only.",
            "unsupported_runner_arguments": "The executor must supply only its --binding option.",
            "selected_source_unavailable": "An operator-bound saved source is unavailable.",
            "selected_source_wrong_provider": "An operator-bound source has the wrong provider.",
            "profile_database_unavailable": "The bound saved profile is offline or missing.",
            "profile_schema_not_current": "The saved profile schema is incompatible.",
            "bound_code_mismatch": "The runner code differs from the operator binding.",
            "bound_runtime_mismatch": "The executor runtime differs from the operator binding.",
            "bound_schema_mismatch": "The expected schema differs from the operator binding.",
            "bound_profile_mismatch": "The saved profile differs from the operator binding.",
            "output_exceeds_byte_limit": "The complete evidence exceeds the output limit.",
            "digest_exceeds_byte_limit": "The complete digest exceeds its output limit.",
        }
        reason = (
            explanations.get(
                str(exc),
                "Request, operator binding or complete evidence is unavailable or incompatible.",
            )
            if isinstance(exc, EvidenceError)
            else "Execution could not complete."
        )
        print(
            "Cannot read this saved period: " + reason + " No successful result was produced.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
