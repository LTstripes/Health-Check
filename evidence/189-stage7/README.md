# #189 Stage 7 synthetic execution evidence

This package addresses the retrieval gap in [Integrator finding F1](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5984160600). It publishes existing execution artifacts, without rerunning or rewriting Stages 1–6. All content is synthetic; no Owner runtime, account-backed provider or private health data was used.

## Original run identity and provenance

The `original-1913073` JSON files are byte-preserving copies of the Stage-7 execution artifacts produced before this continuation. `original-sha256.json` records source/copy SHA-256 and byte lengths for all 43 originally published artifacts. The scoped Git attributes preserve original line endings.

The 36 original PNGs remain retrievable in the [immutable evidence-publication commit](https://github.com/LTstripes/Health-Check/tree/16a35fb9657e4a73b3045f5ab28e06f240106bdc/evidence/189-stage7/original-1913073). They are intentionally absent from the final working tree: the repository hygiene guard forbids image binaries, including synthetic screenshots. CI run `37234345441`, attempt 1, caught this publication error in `test_repository_hygiene_has_no_runtime_or_photo_binaries`. The correction removes only the newly published PNGs from the current tree; the guard is unchanged and the original files/hash manifest remain available at the immutable link. This failed CI is not a product/browser defect and is not relabeled as a pass.

- Candidate: `1913073fb35328f2f0c3ff8b4d5ba73b4cb11f3d`.
- Tree: `f8a47f986af06aa4ab3e50dbedd8b08aaea26ae1`.
- Pinned product base: `50b6638101e2327eb105e5d38921d6ce6ed2de42`; target `main`; branch `task/189-owner-acceptance-stage7`.
- [Original exact-candidate CI](https://github.com/LTstripes/Health-Check/actions/runs/37231809501), attempt 1: success; 2013 exact nodeids reconciled; Windows smoke evidence passed.

[owner-stage7-browser.json](original-1913073/owner-stage7-browser.json) is the original runner output, including its embedded clean candidate/tree, actual browser version, 174 check entries, expected HTTP resource failures and empty unexpected-error/write-request lists. The `populated-*` and `empty-*` PNGs at the immutable link are original viewport screenshots: section indices 0 Overview, 1 Weight, 2 Sleep, 3 Activity, 4 Data, 5 Agreement; widths 1100/800/390, height 900. Screenshots capture the closed initial surface; the execution JSON additionally records opened disclosures and local scrolling.

## Invocation and fixture context (reconstructed execution note)

This README is a later description of the recorded run, not original test stdout. The original JSON/PNG files remain unchanged. The former local `stage7-evidence.json` was also a later summary and is deliberately not presented here as execution output.

The locked project environment ran `python scripts/serve_owner_acceptance_fixture.py --port PORT`, with a distinct fresh external `HEALTHCHECK_DATA_DIR` named `hc189s7-*` for every server:

| Port | Arguments | Fixture |
| --- | --- | --- |
| 18970 | default | populated synthetic store |
| 18971 | `--empty` | initialized empty store |
| 18972 | `--unavailable` | uninitialized store |
| 18973 | `--read-errors` | synthetic SQLAlchemy read failures through production error handlers |

The browser command was `node scripts/check_owner_acceptance_browser.cjs`, with Playwright exposed by `NODE_PATH`, default Chromium, explicit external `HEALTHCHECK_BROWSER_EVIDENCE_DIR`, and these environment settings:

```text
HEALTHCHECK_BROWSER_BASE_URL=http://127.0.0.1:18970
HEALTHCHECK_BROWSER_EMPTY_URL=http://127.0.0.1:18971
HEALTHCHECK_BROWSER_UNAVAILABLE_URL=http://127.0.0.1:18972
HEALTHCHECK_BROWSER_FAILURE_URL=http://127.0.0.1:18973
```

The fixture reuses focused-test Activity/Sleep seeds and synthetic photo imports. The Agreement populated report is explicitly supplied by `agreement_fixture()`; its browser rendering is exercised, not independent Agreement calculation. Production page/API handlers, JavaScript and templates render the other states. Browser acceptance sends local GET/HEAD only; fixture preparation performs synthetic imports/confirmation before browser execution.

## F3: existing Activity asynchronous-state execution

- [activity-panels.json](original-1913073/activity-panels.json) embeds candidate `1913073…`: six successful cells (comparison and lag, each at 1100/800/390) exercise real result → delayed loading with cleared evidence → API HTTP 503 with cleared result → retry. No unexpected errors.
- [focused/activity-stage6-browser.json](original-1913073/focused/activity-stage6-browser.json) is the original eight-check output from `node scripts/check_owner_activity_browser.cjs`, invoked at candidate `1913073…` during the preceding Stage-7 execution. It proves delayed old/new series completion (latest submitted filter wins), loading cleanup, API 503 without stale result, unapplied-source guard and honest empty period. The filename identifies the existing Stage-6 checker; it does not identify a Stage-6 candidate. This original checker did not embed a SHA; the candidate association comes from the preceding execution record, not a newly inserted field or a claim that its JSON alone proves identity.
- The remaining `focused/*.json` files preserve the previously executed Weight, Sleep and Data checks. [import-review.json](original-1913073/import-review.json) preserves read-only review navigation/selection and narrow native-table scrolling.

## Continuation boundary and limitations

The continuation changes only the Stage-7 acceptance harness to select Firefox/WebKit and report engine identity/limitations, plus this evidence publication. It leaves product code, semantic contracts and the pinned baseline unchanged. All three engines executed against clean `16a35fb9657e4a73b3045f5ab28e06f240106bdc`, tree `162db05cf4f6b67aceaeba3fb82d8a55a17453fa`: [Chromium output](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5984370799), [Firefox output](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5984371850), [WebKit output](https://github.com/LTstripes/Health-Check/issues/189#issuecomment-5984372840). The subsequent hygiene correction changes only artifact/prose paths; browser evidence retains its actual execution SHA. The final candidate receives a fresh exact-candidate CI run. Neither original nor continuation browser evidence is relabeled as execution of another SHA.

Windows Playwright WebKit excludes native unstyled links from its default Tab order. The harness probes that behavior separately. If reproduced, it records first-Tab skip-link access as `UNVERIFIED`, tests skip-link activation after explicit focus, and reports `PASS_WITH_LIMITATIONS`; it does not turn that cell into a pass. See [WebKit's keyboard preference discussion](https://bugs.webkit.org/show_bug.cgi?id=199671). Enter/Space disclosure behavior, focus retention and the rest of the matrix remain asserted.

Actual Safari/macOS/iOS, physical mobile devices and Owner-controlled local/private/live UAT are `UNVERIFIED`. Playwright engine coverage is not evidence for those environments. Legacy import-review English body content was preserved by the accepted Stage-2 boundary; the Russian shell remains active. Integrator acceptance, Owner UAT, PR, merge and issue closure are separate; none is performed by this package.

CBM: skipped in this continuation — known acceptance-harness file and existing artifacts; no structural discovery required. Prior Stage-7 structural discovery was checked against the assigned source.
