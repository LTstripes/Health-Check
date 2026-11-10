"""Run with the selected release's interpreter; never bootstrap a profile."""

import json
import sqlite3
import sys
from pathlib import Path


def main():
    action, code, profile = sys.argv[1:4]
    code, profile = Path(code), Path(profile)
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    import healthcheck

    if not Path(healthcheck.__file__).resolve().is_relative_to(code / "src"):
        raise ValueError("wrong installed package")
    if Path(sys.prefix).resolve() != code / ".venv":
        raise ValueError("wrong interpreter")
    if action == "head":
        heads = ScriptDirectory(str(code / "src/healthcheck/db/migrations")).get_heads()
    elif action == "current":
        # Alembic's current-revision operation, without env.py (which sets WAL).
        # mode=ro also prevents a typo from creating a new SQLite database.
        from sqlalchemy import create_engine

        uri = (profile / "healthcheck.db").as_uri() + "?mode=ro"
        engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
        try:
            with engine.connect() as connection:
                heads = list(MigrationContext.configure(connection).get_current_heads())
        finally:
            engine.dispose()
    elif action == "binding":
        from healthcheck.assistant_period_read import (
            code_identity,
            database_identity,
            load_operator_binding,
            runtime_identity,
            schema_identity,
        )

        binding = load_operator_binding(Path(sys.argv[4]))
        binding.validate()
        if (binding.profile != profile or binding.code_id != code_identity()
                or binding.runtime_id != runtime_identity()
                or binding.schema_heads != schema_identity()
                or binding.database_id != database_identity(profile)):
            raise ValueError("binding identity mismatch")
        print(json.dumps({"status": "PASS"}))
        return
    else:
        raise ValueError("unknown probe")
    if len(heads) != 1:
        raise ValueError("exactly one revision required")
    print(json.dumps(heads[0]))


if __name__ == "__main__":
    main()
