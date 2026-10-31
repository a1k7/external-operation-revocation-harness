"""Demo seeder — runs all seven scenarios and prints a readable transcript.

Run from the project root:

    python seed.py

The script uses the on-disk SQLite database configured by `app.config`. It is
idempotent in spirit — subsequent runs accumulate operations and evidence
events, which is exactly what the dashboard is designed to show.
"""

from __future__ import annotations

import json

from app.database import init_db, session_scope
from app import scenario_runner


def main() -> None:
    print("Initialising database and running all 7 demonstration scenarios...\n")
    init_db()

    overall_pass = True
    for key, title in scenario_runner.SCENARIOS.items():
        print(f"── {key.upper()} · {title}")
        with session_scope() as db:
            result = scenario_runner.run_scenario(db, key)

        passed = bool(result.get("passed"))
        overall_pass = overall_pass and passed
        print(json.dumps(result, indent=2, default=str))
        print(f"   → {'PASS' if passed else 'FAIL'}\n")

    print("All scenarios passed." if overall_pass else "One or more scenarios failed.")
    print(
        "Open the dashboard to inspect the evidence timeline:\n"
        "    uvicorn app.main:app --host 127.0.0.1 --port 8000\n"
        "    open http://127.0.0.1:8000\n"
    )


if __name__ == "__main__":
    main()