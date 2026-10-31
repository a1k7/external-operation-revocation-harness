"""Central runtime configuration.

All values are local-only. No external services or secrets are used.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# SQLite database file used by the running server.
DATABASE_URL = os.environ.get(
    "REVOCATION_HARNESS_DB_URL",
    f"sqlite:///{DATA_DIR / 'revocation_harness.db'}",
)

# Deterministic pepper used when computing hash-chain event hashes.
# This is a demo constant — NOT a security secret.
HASH_CHAIN_PEPPER = "revocation-harness-demo-pepper-v1"

# Deterministic timing windows for the simulated receiver.
# Used so tests never depend on wall-clock sleeps.
RECEIVER_DEFAULT_SETTLE_SECONDS = 60  # simulated seconds until terminal
RECEIVER_CANCEL_GRACE_SECONDS = 5     # simulated seconds cancellation is accepted

APP_TITLE = "External Operation Revocation & Outcome Verification Harness"
APP_VERSION = "0.1.0"