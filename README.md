# Health-Check

The UI defaults to loopback. An optional single-owner home-server mode uses the
same dashboard with mandatory HTTPS and browser login; see
[protected home dashboard setup](docs/OWNER_OPERATIONS.md#home-server-setup).
Network exposure, certificate trust and real credential setup require separate
Owner approval; no private data is migrated automatically.

Personal health evidence from Garmin, Google and Xiaomi: preserved originals,
source-specific observations and deterministic analytics with explicit provenance,
coverage and uncertainty. Desktop A+ views and bounded evidence exports keep
missing, unknown and genuine zero distinct. This is decision support, not diagnosis.

## Local bootstrap

Use Python 3.12+ and uv. Run from an assigned code checkout with an explicit external
**synthetic** data directory for development; never use Stable as a test profile.

```powershell
uv sync --locked
$env:HEALTHCHECK_DATA_DIR = 'C:\Temp\healthcheck-synthetic'
```

The complete start/demo/Windows route is in [Owner Operations](docs/OWNER_OPERATIONS.md#bootstrap)
and [Development](docs/DEVELOPMENT_PROCESS.md#synthetic-demo). Startup may migrate;
read-only Owner analysis must use the separate read boundary. No provider login,
real-data import, refresh or deployment is authorized by bootstrap examples.

## Documentation

- [Product Vision](docs/PRODUCT_VISION.md): purpose, journeys, desktop UX and health meaning.
- [Architecture](docs/ARCHITECTURE.md): complete data/source/versioned evidence contracts.
- [Development Process](docs/DEVELOPMENT_PROCESS.md): task, review, exact CI and documentation upkeep.
- [Owner Operations](docs/OWNER_OPERATIONS.md): setup, commands, backup, recovery and action boundaries.
- [Project Wiki](docs/PROJECT_WIKI.md): one dated accepted/installed/UAT state, remaining work and history.

Agents start with [AGENTS.md](AGENTS.md). Public Git/CI uses synthetic examples and
contains no Owner datasets, screenshots or credentials. MIT licensed; reviewed
donor reuse and external GPL/AGPL boundaries remain in Development/Architecture.
