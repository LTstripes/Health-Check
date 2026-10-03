"""Focused #243 full-artifact regressions invoked by the Windows process suite.

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


class TranscriptEvidenceTests(unittest.TestCase):
    checks = 0

    def validate_case(self, transcript, accepted, mutation=None):
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
                for line in transcript
            ]
            cleanup.update(
                termination_outcome="exited-during-termination",
                taskkill_exit_code=255,
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
                if "separator_codepoint" in case:
                    self.assertIsInstance(case["output"][9], str)
                    self.assertEqual(len(case["output"][9]), 1)
                    self.assertEqual(ord(case["output"][9]), case["separator_codepoint"])
                    self.assertFalse(case["accepted"])
                self.validate_case(case["output"], case["accepted"])
                if "separator_codepoint" in case:
                    print(f"Python Unicode U+{case['separator_codepoint']:04X}: length=1 rejected")

    def test_separator_preserves_lifecycle_and_final_evidence(self):
        transcript = MATRIX["cases"][0]["output"]
        for field in ("post_termination_observations", "final_process_observations"):
            for target in (0, 8):
                for mode in ("alive", "query_error", "invalid_time", "same_time_changed", "reuse"):
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
                            elif mode == "same_time_changed":
                                record["ObservedIdentity"]["Name"] = "changed.exe"
                                record["Classification"] = "reused"
                            elif mode == "reuse":
                                record["ObservedIdentity"]["CreationTime"] = str(
                                    int(identity["CreationTime"]) + 1
                                )
                                record["Classification"] = "reused"

                        self.validate_case(transcript, mode == "reuse", mutate)

        for code in (1, 5, 254, 256, -1):
            with self.subTest(exit_code=code):
                self.validate_case(
                    transcript, False, lambda e, c: c.update(taskkill_exit_code=code)
                )
        for field, value in (
            ("termination_issued", False),
            ("root_already_exited", True),
            ("lifecycle_diagnostic_verified", False),
            ("identity_changed_process_ids", [210]),
            ("remaining_owned_process_ids", [210]),
        ):
            with self.subTest(field=field):
                self.validate_case(transcript, False, lambda e, c: c.update({field: value}))
        self.validate_case(
            transcript,
            False,
            lambda e, c: c["ports_closed"].update(ui=False),
        )
        self.validate_case(
            transcript, False, lambda e, c: e["scenarios"][1]["runtime"].update(removed=False)
        )
        self.validate_case(transcript, False, lambda e, c: e.update(dpapi=None))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TranscriptEvidenceTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"Python full-artifact transcript regressions: {TranscriptEvidenceTests.checks} checks")
    raise SystemExit(0 if result.wasSuccessful() else 1)
