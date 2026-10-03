# Dependency advisory audit

The reproducible entrypoint is:

```shell
uv run --locked python scripts/dependency_audit.py --output-dir <fresh-external-evidence-directory>
```

Use a new directory for every attempt. The entrypoint reads every registry
name and version from `uv.lock`, including development groups and
platform-specific packages. It invokes `pip-audit==2.10.1` in an isolated uv
tool environment with `--no-deps --disable-pip --strict` and
`--vulnerability-service osv`. It does not resolve or install project code,
change the lock, or apply fixes.

Exit `0` means a complete clean registry audit. Exit `1` means complete
advisory findings. Exit `2` means a scanner, network, tool, or coverage
failure. Missing packages, malformed output, and status disagreement fail
closed. Neither nonzero outcome is a pass. Ordinary CI does not run this
audit. `.github/workflows/dependency-audit.yml` runs it for pull requests and
pushes to `main` that touch dependency or audit policy paths, and for manual
dispatch. It uploads evidence even when the audit fails. Docs-only and
unrelated code changes do not trigger that network work. A dependency change
needs both ordinary CI and this workflow.

Weekly Dependabot groups cover uv registry version updates (limit two open
PRs) and GitHub Actions version updates (limit one). Those limits do not cap
GitHub security updates. Garmin is ignored: its VCS pin needs a separately
assigned update. No automatic merge is enabled.

## Issue #242 reproduction

Baseline: `754f19068cede943ddfb5c5f4ce0cfe72fa9689e`.
Audit date: 2026-10-03 UTC. Tools: uv 0.12.17, Python 3.12.14,
pip-audit 2.10.1, service OSV. Both audits covered 45 registry packages.
Baseline lock SHA-256:
`782c554fd00f0f311f61e1b93228e317552435d0242bc14a8b96b49181590fcd`.
Patched lock SHA-256:
`6ea5dbd974972d855042b41e25fd6b616873884616838fdc64d6e9187f7e3f4f`.

| Package | Baseline | Patched | Exposure | Advisory |
| --- | --- | --- | --- | --- |
| urllib3 | 2.7.0 | 2.8.0 | runtime | PYSEC-2026-4175 / GHSA-8988-9cw3-xx77, PYSEC-2026-4176 / GHSA-gh4c-6fx4-qh6g, PYSEC-2026-4177 / GHSA-vxq7-64xx-v4gw |
| pytest | 8.4.2 | 9.0.3 | development | PYSEC-2026-1845 / GHSA-6w46-j5rx-g56g / CVE-2025-71176 |

The baseline OSV result was `findings` (exit 1) for those four IDs only.
Fix versions were urllib3 2.8.0 and pytest 9.0.3. The patched OSV result was
`clean` (exit 0). No other registry package had an OSV finding. The only
version changes are those two packages. The lock also records the pytest
specifier `>=9.0.3,<10` and the uv constraint `urllib3>=2.8.0,<3`.
A clean-workspace re-run at 2026-10-03T21:19Z repeated that result: the same
entrypoint against an isolated checkout of baseline `754f190` and against the
patched lock. Python for that re-run was 3.13.15. The git blob of `uv.lock`
was unchanged.

urllib3 is reachable through the Garmin client's requests dependency. The
audit establishes affected versions, not exploitation in any Owner runtime.
pytest is development tooling. Its temporary-directory advisory concerns Unix
multi-user conditions.

On 2026-10-03 one pip-audit PyPI JSON query of the two vulnerable pins
returned no advisories. A later query the same day returned the same four IDs
and duplicated the pytest row. The gate stays on OSV so a false-clean PyPI
response cannot pass. OSV has no global snapshot version; reproduction fixes
the inventory and scanner, not future advisory content.

Coverage excludes the first-party editable project and the unaudited Garmin
VCS source at `54079fbca3cafaa371b5d0cd1aa9cfb0ae62c7a5`. Registry dependencies
of that source are included. The scanner checks known package advisories, not
VCS integrity, build dependencies, exploitability, or live providers.
No Owner or provider access was used.

Ordinary CI pins action SHAs and defaults the token to `contents: read`.
Only classify keeps `pull-requests: read` and `actions: read` for Stage B
discovery. The audit workflow uses `contents: read` and the same pinned
action SHAs. No write scopes were added.
