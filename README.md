# Health-Check

Health-Check is a single-user, local-first personal health observatory. It keeps source evidence from several devices, computes reproducible analytics on a Windows laptop, and exposes the same evidence through a local dashboard and an AI/LLM interface.

It is not a SaaS product, workout planner, medical diagnostic system, or replacement for Garmin/Fitbit/Xiaomi daily apps.

## Product priorities

1. Weight and body composition.
2. Sleep.
3. Physical activity and fitness, especially cycling.
4. Recovery and general wellbeing.

Planned sources are Garmin Vivoactive 5, Google Fitbit Air through the applicable Google health-data interface, Xiaomi Body Composition Scale S400, and free-text life-context events. Laboratory results and other personal health documents are later work.

## Architecture in one minute

```text
provider payloads / photos / context
                |
                v
raw evidence -> typed source records -> versioned canonical selection
                                      |
                                      v
                         deterministic analytics
                                      |
                                      v
                  evidence packets and saved reports
                         /                    \
                  dashboard              read-only AI
```

- Runtime: Python 3.12+, FastAPI, SQLite in WAL mode, and a small Windows-first local service.
- Android: openScale and openScale-sync remain external GPL applications for the S400 path.
- Source-specific values are retained even when another source becomes canonical.
- Physical device, provider/input method, and measurement algorithm are separate identities.
- Xiaomi-app and openScale body-composition values are not silently joined into one curve.
- Analytics, coverage, and source agreement are calculated deterministically; every confidence value states whether it is rule-derived, model-reported, or human-confirmed and is never invented. The LLM explains compact structured evidence.
- Weekly, month-end, and annual reports share one report model and are rendered for dashboard, Telegram, and email.

## Current status

R00 architecture is consolidated. No application code exists yet. The approved next vertical slice is **R01 — Weight & Body Composition**, which builds the small reusable core, imports historical Xiaomi screenshots with confirmation, accepts the openScale-sync webhook contract, computes conservative weight/body-composition analytics, and provides a minimal dashboard.

R01 deliberately excludes Garmin ingestion, Fitbit ingestion, a custom Recovery Score, and full Telegram/email delivery.

## Canonical documentation

- [Product Vision](docs/PRODUCT_VISION.md)
- [Final Architecture](docs/ARCHITECTURE.md)
- [R00 Final Architecture Audit](docs/audits/R00_FINAL_ARCHITECTURE.md)
- [R01 Implementation Spec](docs/R01_IMPLEMENTATION_SPEC.md)
- [Reference Projects and Reuse Strategy](docs/REFERENCE_PROJECTS.md)
- [Roadmap](docs/ROADMAP.md)
- [Decisions and Open Questions](docs/DECISIONS_AND_OPEN_QUESTIONS.md)
- [Backlog Ideas](docs/BACKLOG_IDEAS.md)

## Safety and repository hygiene

Real health data, screenshots, databases, provider responses, tokens, credentials, reports, and laboratory documents must never be committed. Consumer wearables and BIA scales are observational tools, not clinical instruments; Health-Check must expose uncertainty and must not present associations as diagnoses or causation.

## License

Health-Check is licensed under the [MIT License](LICENSE). Reused donor code must still retain any attribution/notices required by its own license and be reviewed at the exact reused source commit.
