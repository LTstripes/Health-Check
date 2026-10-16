"""External synthetic Overview only; no Owner profile or provider operations."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    root = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if root.is_relative_to(ROOT) or not root.name.startswith("hc-completed-") or root.exists():
        raise ValueError("Use a fresh external hc-completed-* synthetic directory")
    root.mkdir()
    sys.path.insert(0, str(ROOT / "tests"))
    import uvicorn

    from healthcheck.web import pages, period_brief_query
    from healthcheck.web.ui_app import create_ui_app
    from test_overview_completed import NOW, seed_completed
    from test_stress_baseline import database

    fixture = database.__wrapped__(root)
    stored = next(fixture)
    _source_id, settings = seed_completed(stored)
    port = int(os.environ.get("HEALTHCHECK_UI_PORT", "8197"))
    settings = settings.model_copy(update={"ui_port": port})

    class SyntheticDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    pages.datetime = period_brief_query.datetime = SyntheticDatetime
    original_period = pages._brief_period

    def period(*, preset, start_date, end_date):
        if start_date is None and end_date is None and preset in {None, "7", "30", "90"}:
            key = preset or "30"
            end = date(2099, 1, 8)
            start = end - timedelta(days=int(key) - 1)
            lower, upper, _ = original_period(preset=None, start_date=start.isoformat(),
                                              end_date=end.isoformat())
            return lower, upper, key
        return original_period(preset=preset, start_date=start_date, end_date=end_date)

    pages._brief_period = period
    app, _ = create_ui_app(settings)
    paths = ["src/healthcheck/web/pages.py", "src/healthcheck/web/static/overview.css",
             "src/healthcheck/web/overview_completed.py", "tests/test_overview_completed.py",
             "src/healthcheck/web/overview_charts.py", "src/healthcheck/web/sleep_view.py",
             "src/healthcheck/web/overview_body_battery.py",
             "src/healthcheck/web/garmin_query.py",
             "src/healthcheck/garmin/body_battery_read.py",
             "src/healthcheck/analytics/garmin_baselines.py",
             "tests/test_stress_baseline.py", "tests/test_body_battery_read.py",
             "scripts/serve_completed_overview_fixture.py"]
    paths += [str(path.relative_to(ROOT)).replace("\\", "/")
              for path in (ROOT / "src/healthcheck/web/templates").glob("overview*.html")]
    identity = {
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "pid": os.getpid(), "executable": sys.executable, "profile": str(settings.data_dir),
        "synthetic": True, "endpoint": f"http://127.0.0.1:{port}",
        "evaluation_clock": NOW.isoformat(), "created_at_utc": datetime.now(UTC).isoformat(),
        "source_hashes": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in paths},
    }

    @app.get("/__synthetic_identity", include_in_schema=False)
    def synthetic_identity():
        return identity

    (root / "fixture-identity.json").write_text(json.dumps(identity, indent=2) + "\n",
                                               encoding="utf-8")
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
    finally:
        fixture.close()


if __name__ == "__main__":
    main()
