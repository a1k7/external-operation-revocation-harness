# External Operation Revocation & Outcome Verification Harness

A locally runnable technical demonstration that models the following business problem:

> An AI agent receives authorization to perform an external operation (e.g. a refund). The agent dispatches the operation to a receiving system. Before the operation finishes, the authorization is revoked. **Can the system establish what actually happened — completion, cancellation, or an unknown outcome?**

The harness deliberately separates "what we asked for" from "what the external system actually did", and it refuses to promote any acknowledgment or cancellation request to a proven terminal outcome without independent verification.

> **This is a simulation.** It does not integrate with any real payment processor and cannot cancel real-world transactions. See [Architectural Limitations](#architectural-limitations) at the bottom.

---

## Project Purpose

This project provides a reference architecture for handling authorization revocation mid-flight, implementing safe recovery policies, and verifying external operation outcomes even when the receiving system returns ambiguous or inconclusive responses.

---

## Architecture Overview

- **FastAPI Backend:** Exposes the API and serves the dashboard.
- **SQLite Persistence:** Stores authorizations, operations, idempotency keys, and the hash-chained evidence ledger.
- **External Receiver Simulator:** A deterministic state machine that simulates an external payment processor. It has hidden internal states (`actual_state`) and outward responses (`outward_response`).
- **Verification Engine:** Evaluates the receiver's outward response and any independent evidence to classify the outcome. It never reads the hidden internal state.
- **Evidence Ledger:** An append-only, SHA-256 hash-chained log of all state changes.

---

## Complete Folder Structure

```text
revocation-harness/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── authorization_service.py
│   ├── operation_dispatcher.py
│   ├── external_receiver.py
│   ├── outcome_verification.py
│   ├── evidence_ledger.py
│   ├── scenario_runner.py
│   ├── routes.py
│   └── main.py
├── static/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_authorization.py
│   ├── test_dispatcher.py
│   ├── test_receiver.py
│   ├── test_outcome_verification.py
│   ├── test_evidence_ledger.py
│   ├── test_scenarios.py
│   ├── test_scenario_8.py
│   ├── test_scenario_9.py
│   └── test_scenario_10.py
├── docs/
│   ├── scenario-coverage-matrix.md
│   └── verifier-methodology.md
├── seed.py
├── run.sh
├── requirements.txt
├── pytest.ini
├── pyproject.toml
├── .gitignore
└── README.md
```

## Prerequisites

macOS (also works on Linux/WSL)
Python 3.11+ (Python 3.12 is highly recommended for wheel compatibility)
No API keys, cloud accounts, or paid services.
Check your Python version:

bash
python3 --version  # must be >= 3.11
Installation Instructions (macOS)

bash
# 1. Clone the repository
git clone https://github.com/YOUR_GITHUB_USERNAME/external-operation-revocation-harness.git
cd external-operation-revocation-harness

# 2. Create and activate a virtual environment (using Python 3.12)
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
Running the Application

Seed the 10 Scenarios

bash
rm -rf data/  # Wipe old DB to start fresh (optional)
python seed.py
This initializes the database, runs all ten demonstration scenarios, and prints a transcript of the results to your terminal.

Start the Server

bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
View the Dashboard

Open your browser to: http://127.0.0.1:8000/

View the API Documentation

Open your browser to: http://127.0.0.1:8000/docs

Scenario Execution

## Baseline Scenarios (1–7)

You can run these via the dashboard by clicking the "Run Scenario" buttons, or via the API using curl. These cover:

Revocation before dispatch.
Revocation after dispatch.
Completion before cancellation.
Inconclusive receiver response.
Duplicate idempotency key.
Cancellation acknowledgment without terminal confirmation.
Multiple pending operations.
Extended Scenarios (8–10)

The harness also includes three advanced evaluation scenarios:

Scenario 8 (Trust Boundaries): Tests that actual internal state (e.g., actual completion) is hidden by an inconclusive outward response, preventing the verifier from guessing.
Scenario 9 (Policy Evaluation): Tests revocation policies (BLOCK_NEW_DISPATCHES vs. REQUEST_CANCELLATION_OF_IN_FLIGHT).
Scenario 10 (Business-Level Idempotency): Tests retrying with a new idempotency key but the same business_refund_id.
Run them via the dashboard or the API:

bash
curl -X POST http://127.0.0.1:8000/api/scenarios/run \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"scenario_8"}'
Running Automated Tests

bash
python -m pytest -v
This runs all baseline and extended tests. The suite includes deterministic tests for concurrency, trust-boundary isolation, and business-level idempotency.

## Expected Output:

text
36 passed in ~0.8s
Sample Evidence Export

The evidence ledger is accessible via the API:

bash
curl http://127.0.0.1:8000/api/evidence
Each event is SHA-256 hash-chained. You can verify the chain integrity at any time:

bash
curl http://127.0.0.1:8000/api/evidence/verify
(Expected response: {"total_events": N, "intact": true, "broken_at_event_uid": null})

## What SHA-256 Hash Chaining Proves (and Does Not Prove)

Proves: The ledger has not been modified after the fact. If an attacker changes a payload or deletes an event, the hashes will no longer match. It provides append-only tamper-evidence.
Does Not Prove: It does not establish the authenticity of the events themselves. Because the hash chain is stored in the same local SQLite database, an attacker with root access to the machine could rewrite the entire database and recompute the hashes. It does not prove that an external system actually performed the operation.
Verifier Methodology & Coverage Matrix

For deep dives into the architecture and how this compares to other payment simulations:

See docs/verifier-methodology.md for a detailed explanation of the trust boundaries and verification logic.
See docs/scenario-coverage-matrix.md for a comparison against German Giraldo's public payment simulation.
Security & Architectural Limitations

Local Simulation Only: The external receiver is a deterministic state machine. It does not call real payment APIs. No real financial transactions can occur.
Hash Chain Constraints: The SHA-256 hash chain proves tamper-evidence after the fact. It does not prove authenticity. Because the chain resides in the same local SQLite database, it does not establish independent evidence authority.
Business-Level Exactly-Once: The business_refund_id check is enforced via a local database constraint. This does not establish distributed exactly-once semantics across a network. It relies on the local database remaining the single source of truth.
No Authentication: The API has no authentication or authorization. Anyone with local access can grant, revoke, dispatch, or verify operations.
No Real PKI: There is no cryptographic signing of messages between the harness and the receiver.
Non-Claims

## This project is not production-ready.
It does not cancel, refund, or otherwise affect real financial transactions.
It is not certified, accredited, or endorsed by any standards body.
It does not prove that any specific vendor's revocation semantics will behave exactly as simulated here.
