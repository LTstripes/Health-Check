"""Loopback-only synthetic Overview Weight cases; fresh external runtime only."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc334-") or runtime.exists():
        raise ValueError("Use a fresh external hc334-* synthetic directory")
    sys.path.insert(0, str(ROOT / "tests"))
    import uvicorn
    from fastapi.testclient import TestClient

    from test_dashboard_ui import _ui
    from test_period_brief_ui import seed_334_weight

    port = int(os.environ.get("HEALTHCHECK_UI_PORT", "8134"))
    app, _, _ = _ui(runtime, ui_port=port)
    with TestClient(app, base_url=f"http://127.0.0.1:{port}",
                    headers={"Origin": f"http://127.0.0.1:{port}"}) as client:
        for month, days in ((3, (12,)), (4, (1, 2, 3)), (5, (1, 12, 31)),
                            (7, tuple(range(1, 32)))):
            seed_334_weight(client, month, days)
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
