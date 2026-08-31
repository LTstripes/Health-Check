# Health-Check

Single-user, local-first personal health observatory for long-term analysis across wearables, body composition, life context and (later) laboratory data.

> Status: **pre-implementation / architecture & source audit**. No production health data should be committed to this repository.

## Product direction

Health-Check should automatically collect data, compute reproducible analytics, show long-term dashboards, produce weekly/monthly/yearly reviews, and support arbitrary natural-language questions through a read-only AI/LLM layer.

Current priority:

1. weight and body composition;
2. sleep;
3. physical activity / fitness;
4. general wellbeing / recovery.

Current sources:

- Garmin Vivoactive 5 / Garmin Connect (primary source for most wearable/training signals);
- Google Fitbit Air / Google Health;
- Xiaomi Body Composition Scale S400;
- free-text life context/events captured primarily through Telegram and dashboard;
- future: lab tests and other health documents.

Automatic reports should be available in the local dashboard and proactively delivered through **email and Telegram**.

## Canonical documentation

- [Product Vision](docs/PRODUCT_VISION.md)
- [Target Architecture](docs/ARCHITECTURE.md)
- [Reference Projects and Reuse Strategy](docs/REFERENCE_PROJECTS.md)
- [Provisional Roadmap](docs/ROADMAP.md)
- [Decisions and Open Questions](docs/DECISIONS_AND_OPEN_QUESTIONS.md)

## Core engineering principles

- Single user; avoid SaaS/multi-tenant complexity.
- Local-first storage, initially favoring SQLite.
- Local-first is mainly about simplicity/control/reproducibility, not a strict no-cloud privacy rule.
- Preserve source-specific/raw data and provenance.
- Canonical metrics must not erase original Garmin/Fitbit/Xiaomi values.
- Deterministic Python/SQL/statistical code does the math; the LLM interprets and advises.
- Dashboard and AI are equal product interfaces.
- Automatic sync and periodic reports should work without manual exports.
- Telegram + dashboard are the preferred MVP paths for free-text life context.
- Obsidian is optional/non-canonical; detailed nutrition tracking remains outside the first releases.
- Real personal health data, screenshots, lab reports, provider tokens and databases **must never be committed to Git**.

## Next step

Run **R00 — source-level technical audit** before implementing the product. The audit should inspect the actual code and exact SHAs/tags of the candidate donor/reference projects, verify licenses, compare schemas/sync/test quality, and decide what to reuse versus write locally.
