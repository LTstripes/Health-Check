"""Fresh external synthetic profile for Overview readability; loopback only."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc344-") or runtime.exists():
        raise ValueError("Use a fresh external hc344-* synthetic directory")
    sys.path.insert(0, str(ROOT / "tests"))
    import uvicorn
    from fastapi.testclient import TestClient

    from test_dashboard_ui import _ui
    from test_period_brief_ui import seed_334_weight, seed_a_plus_weight, seed_overview_a_plus

    port = int(os.environ.get("HEALTHCHECK_UI_PORT", "8144"))
    app, _, paths = _ui(runtime, ui_port=port)
    seed_overview_a_plus(paths)
    with TestClient(app, base_url=f"http://127.0.0.1:{port}",
                    headers={"Origin": f"http://127.0.0.1:{port}"}) as client:
        seed_a_plus_weight(client)
        for month, days in ((3, (12,)), (4, (1, 2, 3)), (5, (1, 12, 31)),
                            (7, tuple(range(1, 32)))):
            seed_334_weight(client, month, days)
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
