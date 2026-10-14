"""Focused #243/#403 full-artifact regressions invoked by the Windows process suite.

The filename deliberately stays outside pytest lane discovery: #246 owns that
manifest and workflow. Reuse the existing synthetic artifact builder read-only.
"""

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from test_ci_workflow import (
    ContractError,
    ExpectedWorkflowIdentity,
    _absent_observations,
    _windows_smoke_fixture,
    validate_windows_smoke_artifact,
)

MATRIX = json.loads(
    (Path(__file__).parent / "fixtures" / "ci_windows_exit255_transcripts.json").read_text()
)
EXIT128 = json.loads(
    (Path(__file__).parent / "fixtures" / "ci_windows_exit128_transcripts.json").read_text(
        encoding="utf-8"
    )
)


def exit128_case(case):
    output = copy.deepcopy(case.get("output", EXIT128["output"]))
    for change in reversed(case.get("output_changes", [])):
        output[change["start"] : change["end"]] = change["items"]
    owned = copy.deepcopy(case.get("owned", EXIT128["owned"]))
    for change in case.get("identity_updates", []):
        owned[change["index"]][change["field"]] = change["value"]
    return output, owned


class TranscriptEvidenceTests(unittest.TestCase):
    checks = 0

    def validate_case(self, transcript, accepted, mutation=None, *, native_code=255, owned=None):
        with tempfile.TemporaryDirectory(prefix="healthcheck-exit255-") as temporary:
            root, head, tree = _windows_smoke_fixture(Path(temporary))
            artifact = root / "ci-windows-smoke-123-1"
            evidence = json.loads((artifact / "smoke-evidence.json").read_text())
            cleanup = evidence["scenarios"][1]["cleanup"]
            cleanup["owned_process_identities"].extend(
                {
                    "Id": pid,
                    "Name": "python.exe",
                    "CommandLine": f"synthetic child {pid}",
                    "CreationTime": "637134336010000000",
                }
                for pid in range(203, 211)
            )
            # Map sanitized matrix PIDs 100..108 to the fixture's 202..210.
            output = [
                re.sub(r"(?<=PID )10[0-8]\b", lambda m: str(int(m[0]) + 102), line)
                if isinstance(line, str)
                else line
                for line in transcript
            ]
            if owned is not None:
                captured = copy.deepcopy(owned)
                aliases = {identity["Id"]: 202 + index for index, identity in enumerate(captured)}
                output = [
                    re.sub(
                        r"(?<=PID )\d+",
                        lambda m: (
                            str(aliases.get(int(m[0]), int(m[0])))
                            if m[0] == str(int(m[0]))
                            else m[0]
                        ),
                        line,
                    )
                    if isinstance(line, str)
                    else line
                    for line in transcript
                ]
                for identity in captured:
                    identity["Id"] = aliases[identity["Id"]]
                cleanup["owned_process_identities"] = captured
                cleanup["root_name"] = captured[0]["Name"]
                cleanup["root_command_line"] = captured[0]["CommandLine"]
                cleanup["root_creation_time"] = captured[0]["CreationTime"]
            cleanup.update(
                termination_outcome="exited-during-termination",
                taskkill_exit_code=native_code,
                lifecycle_diagnostic_verified=True,
                taskkill_output=output,
            )
            for field in ("post_termination_observations", "final_process_observations"):
                cleanup[field] = _absent_observations(cleanup["owned_process_identities"])
            if mutation:
                mutation(evidence, cleanup)
            evidence["cleanup"]["scenarios"][1] = cleanup
            (artifact / "smoke-evidence.json").write_text(json.dumps(evidence))
            (artifact / "cleanup.json").write_text(json.dumps(evidence["cleanup"]))
            kwargs = dict(
                job_result="success",
                head_sha=head,
                tree_sha=tree,
                workflow_identity=ExpectedWorkflowIdentity(
                    "push", "refs/heads/task/125-ci-windows-smoke", "", "", "", ""
                ),
            )
            raw_before = copy.deepcopy(cleanup["taskkill_output"])
            if accepted:
                validated = validate_windows_smoke_artifact(root, **kwargs)
                self.assertEqual(
                    raw_before, validated["scenarios"][1]["cleanup"]["taskkill_output"]
                )
            else:
                with self.assertRaises(ContractError):
                    validate_windows_smoke_artifact(root, **kwargs)
            self.assertEqual(raw_before, cleanup["taskkill_output"])
            self.assertEqual(
                raw_before,
                json.loads((artifact / "smoke-evidence.json").read_text())["scenarios"][1][
                    "cleanup"
                ]["taskkill_output"],
            )
            type(self).checks += 1

    def test_shared_transcript_matrix(self):
        for case in MATRIX["cases"]:
            with self.subTest(case=case["name"]):
                separator = case.get("separator_index", 9)
                if case["accepted"] and "separator_index" in case:
                    self.assertIsInstance(case["output"][separator], str)
                    self.assertEqual(len(case["output"][separator]), 0)
                if "separator_codepoint" in case:
                    self.assertIsInstance(case["output"][separator], str)
                    self.assertEqual(len(case["output"][separator]), 1)
                    self.assertEqual(ord(case["output"][separator]), case["separator_codepoint"])
                    self.assertFalse(case["accepted"])
                self.validate_case(case["output"], case["accepted"])
                if "separator_codepoint" in case:
                    print(f"Python Unicode U+{case['separator_codepoint']:04X}: length=1 rejected")

    def test_ownership_snapshot_diagnostic_cannot_waive_failed_capture(self):
        for reason in ("child_creation_missing", "child_predates_parent"):
            with self.subTest(reason=reason):

                def failed_capture(evidence, cleanup):
                    def identity(pid, ticks, parent=None):
                        record = dict(
                            Id=pid,
                            IdPresent=True,
                            IdValid=True,
                            CreationTime=ticks,
                            CreationTimePresent=ticks is not None,
                            CreationTimeValid=ticks is not None,
                            CreationTimeState="valid" if ticks is not None else "missing",
                        )
                        if parent is not None:
                            record.update(
                                ParentProcessId=parent,
                                ParentProcessIdPresent=True,
                                ParentProcessIdValid=True,
                            )
                        return record

                    cleanup.update(
                        termination_issued=False,
                        termination_outcome="failed",
                        taskkill_exit_code=None,
                        taskkill_output=[],
                        lifecycle_diagnostic_verified=False,
                        owned_process_identities=[],
                        post_termination_observations=[],
                        final_process_observations=[],
                        errors=["ambiguous descendant ownership (reused parent PID)"],
                        ownership_snapshot_diagnostic=dict(
                            Reason=reason,
                            CapturedRoot=identity(202, "637134336000000000"),
                            Parent=identity(203, "637134336010000000", 202),
                            Child=identity(
                                204,
                                None
                                if reason == "child_creation_missing"
                                else "637134336009999999",
                                203,
                            ),
                        ),
                    )

                # Keep all other fixture evidence successful: even optimistic
                # enclosing status cannot make this failed capture acceptable.
                self.validate_case(MATRIX["cases"][0]["output"], False, failed_capture)

    def test_separator_preserves_lifecycle_and_final_evidence(self):
        for name in ("retained_shape", "observed_one_sibling_suffix"):
            with self.subTest(transcript=name):
                transcript = next(
                    case["output"] for case in MATRIX["cases"] if case["name"] == name
                )
                self.check_lifecycle_and_final_evidence(transcript)

    def test_exit128_shared_matrix(self):
        for case in EXIT128["cases"]:
            with self.subTest(exit128=case["name"]):
                transcript, owned = exit128_case(case)
                self.validate_case(transcript, case["accepted"], native_code=128, owned=owned)

    def test_exit128_preserves_lifecycle_and_final_evidence(self):
        self.check_lifecycle_and_final_evidence(
            EXIT128["output"], native_code=128, owned=EXIT128["owned"]
        )

    def check_lifecycle_and_final_evidence(self, transcript, *, native_code=255, owned=None):
        def validate(transcript, accepted, mutation=None):
            self.validate_case(transcript, accepted, mutation, native_code=native_code, owned=owned)

        for field in ("post_termination_observations", "final_process_observations"):
            for target in (0, 2, 3, 8):
                for mode in (
                    "alive",
                    "query_error",
                    "invalid_time",
                    "missing_time",
                    "same_time_changed",
                    "missing_command",
                    "reuse",
                    "foreign_pid",
                ):
                    with self.subTest(field=field, target=target, mode=mode):

                        def mutate(evidence, cleanup):
                            record = cleanup[field][target]
                            identity = cleanup["owned_process_identities"][target]
                            record["ObservedIdentity"].update(identity, Exists=True)
                            record["Classification"] = "same-identity-alive"
                            if mode == "query_error":
                                record["ObservedIdentity"]["QueryError"] = "synthetic query failure"
                                record["Classification"] = "unknown"
                            elif mode == "invalid_time":
                                record["ObservedIdentity"]["CreationTime"] = "invalid"
                                record["Classification"] = "reused"
                            elif mode == "missing_time":
                                record["ObservedIdentity"].pop("CreationTime")
                            elif mode == "missing_command":
                                record["ObservedIdentity"]["CommandLine"] = ""
                            elif mode == "foreign_pid":
                                record["ObservedIdentity"]["Id"] = 999
                            elif mode == "same_time_changed":
                                record["ObservedIdentity"]["Name"] = "changed.exe"
                                record["Classification"] = "reused"
                            elif mode == "reuse":
                                record["ObservedIdentity"]["CreationTime"] = str(
                                    int(identity["CreationTime"]) + 1
                                )
                                record["Classification"] = "reused"

                        validate(transcript, mode == "reuse", mutate)

            validate(transcript, False, lambda e, c: c[field].pop())
            validate(
                transcript, False, lambda e, c: c[field].__setitem__(8, copy.deepcopy(c[field][0]))
            )

        def root_reuse_child_survives(evidence, cleanup):
            for field in ("post_termination_observations", "final_process_observations"):
                root = cleanup[field][0]
                identity = cleanup["owned_process_identities"][0]
                root["ObservedIdentity"].update(identity, Exists=True)
                root["ObservedIdentity"]["CreationTime"] = str(int(identity["CreationTime"]) + 1)
                root["Classification"] = "reused"
                child = cleanup[field][8]
                child["ObservedIdentity"].update(
                    cleanup["owned_process_identities"][8], Exists=True
                )
                child["Classification"] = "same-identity-alive"

        validate(transcript, False, root_reuse_child_survives)

        for code in (1, 5, 127, 129, 254, 256, -1, 255 if native_code == 128 else 128):
            with self.subTest(exit_code=code):
                validate(transcript, False, lambda e, c: c.update(taskkill_exit_code=code))
        for field, value in (
            ("termination_issued", False),
            ("root_already_exited", True),
            ("lifecycle_diagnostic_verified", False),
            ("identity_changed_process_ids", [210]),
            ("remaining_owned_process_ids", [210]),
        ):
            with self.subTest(field=field):
                validate(transcript, False, lambda e, c: c.update({field: value}))
        validate(
            transcript,
            False,
            lambda e, c: c["ports_closed"].update(ui=False),
        )
        validate(transcript, False, lambda e, c: e["scenarios"][1]["runtime"].update(removed=False))
        validate(transcript, False, lambda e, c: e.update(dpapi=None))
        validate(transcript, False, lambda e, c: c["ports_closed"].update(ingest=False))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TranscriptEvidenceTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"Python full-artifact transcript regressions: {TranscriptEvidenceTests.checks} checks")
    raise SystemExit(0 if result.wasSuccessful() else 1)
