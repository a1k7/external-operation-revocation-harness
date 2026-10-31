# External Operation Revocation & Outcome Verification Harness

A locally runnable technical demonstration that models the following business
problem:

> An AI agent receives authorization to perform an external operation (e.g. a
> refund). The agent dispatches the operation to a receiving system. Before the
> operation finishes, the authorization is revoked. **Can the system establish
> what actually happened — completion, cancellation, or an unknown outcome?**

The harness deliberately separates "what we asked for" from "what the external
system actually did", and it refuses to promote any acknowledgment or
cancellation request to a proven terminal outcome without independent
verification.

> **This is a simulation.** It does not integrate with any real payment
> processor and cannot cancel real-world transactions. See
> [Limitations](#architectural-limitations) at the bottom.

---

## What this demonstrates

| Concern | Demonstrated by |
|---|---|
| Authorization lifecycle (grant / revoke / version) | `app/authorization_service.py` |
| Dispatch guards and idempotent dispatch | `app/operation_dispatcher.py` |
| A separate, deterministic simulated receiver | `app/external_receiver.py` |
| Five-way outcome classification | `app/outcome_verification.py` |
| Tamper-evident evidence ledger (SHA-256 chain) | `app/evidence_ledger.py` |
| Seven reproducible scenarios + dashboard | `app/scenario_runner.py`, `static/` |
| Automated tests including concurrency & tamper detection | `tests/` |

### Verified outcome categories

Every operation is classified into exactly one of:

- `CANCELLATION_REQUESTED` — receiver asked to cancel, no acknowledgment yet
- `CANCELLATION_ACKNOWLEDGED` — receiver acknowledged; still not terminal
- `CANCELLATION_CONFIRMED` — receiver independently reports terminal CANCELLED
- `COMPLETION_CONFIRMED` — receiver independently reports terminal COMPLETED
- `OUTCOME_UNKNOWN` — receiver is inconclusive or state is unrecognised

Nothing is ever upgraded from `*_REQUESTED` or `*_ACKNOWLEDGED` to `*_CONFIRMED`.

---

## Project layout
revocation-harness/
├── app/
│ ├── init.py
│ ├── config.py
│ ├── database.py
│ ├── models.py
│ ├── schemas.py
│ ├── authorization_service.py
│ ├── operation_dispatcher.py
│ ├── external_receiver.py
│ ├── outcome_verification.py
│ ├── evidence_ledger.py
│ ├── scenario_runner.py
│ ├── routes.py
│ └── main.py
├── static/
│ ├── index.html
│ ├── app.js
│ └── styles.css
├── tests/
│ ├── init.py
│ ├── conftest.py
│ ├── test_authorization.py
│ ├── test_dispatcher.py
│ ├── test_receiver.py
│ ├── test_outcome_verification.py
│ ├── test_evidence_ledger.py
│ └── test_scenarios.py
├── seed.py
├── run.sh
├── requirements.txt
├── pytest.ini
├── pyproject.toml
├── .gitignore
└── README.md


---

## Prerequisites

- macOS (also works on Linux/WSL)
- Python **3.11+**
- VS Code (optional, but that's the target environment)
- No API keys, cloud accounts, or paid services.

Check your Python version:


python3 --version       # must be ≥ 3.11
Setup (copy-paste into macOS Terminal)

bash
# 1. Create and enter the project directory
mkdir -p ~/revocation-harness
cd ~/revocation-harness

# 2. Create every file listed in the folder structure above.
#    In VS Code, use New File for each path shown; then paste the code from
#    this delivery into the matching file.

# 3. Create the virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
Optional: one-shot launcher

bash
chmod +x run.sh
./run.sh            # installs deps, seeds data, starts the server
Running the demo

Seed all scenarios and print a transcript

bash
python seed.py
This runs each of the seven scenarios in order, prints the JSON result, and
writes evidence events into the local SQLite database.

Start the API + dashboard

bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
Then open:

Dashboard: http://127.0.0.1:8000/
OpenAPI docs: http://127.0.0.1:8000/docs
Reset demo state

bash
rm -f data/revocation_harness.db
python seed.py
Running the automated tests

bash
pytest -v
Expected output (illustrative — not executed in this response)

===================== test session starts ======================
platform darwin -- Python 3.11.x, pytest-8.2.0
collected 29 items

tests/test_authorization.py ....                          [ 13%]
tests/test_dispatcher.py ....                             [ 27%]
tests/test_receiver.py .....                              [ 44%]
tests/test_outcome_verification.py .....                  [ 62%]
tests/test_evidence_ledger.py ...                         [ 72%]
tests/test_scenarios.py ........                          [100%]

====================== 29 passed in ~1.4s ======================
The numbers above reflect the intended result of the provided tests. They
were not executed while authoring this document; please run them locally.
You can also run a single file:

bash
pytest tests/test_scenarios.py -v
pytest tests/test_scenarios.py::test_concurrent_dispatch_same_idempotency_key -v
The concurrency test uses a per-test file-backed SQLite database and a
threading.Barrier, so results are deterministic.

# REST API surface

Method	Path	Purpose
GET	/api/health	Liveness probe
POST	/api/authorizations	Grant an authorization
POST	/api/authorizations/{id}/revoke	Revoke with reason
GET	/api/authorizations	List authorizations
GET	/api/authorizations/{id}	Fetch one authorization
POST	/api/operations/dispatch	Dispatch a new operation
POST	/api/operations/{uid}/cancel	Request receiver cancellation
POST	/api/operations/{uid}/advance?seconds=N	Advance simulated time
POST	/api/operations/{uid}/verify	Classify current outcome
GET	/api/operations	List operations (with live classification)
GET	/api/operations/{uid}	One operation
GET	/api/operations/{uid}/evidence	Evidence timeline for an operation
GET	/api/evidence	Full ledger
GET	/api/evidence/verify	Recompute chain; report tamper point
GET	/api/scenarios	List the seven scenarios
POST	/api/scenarios/run	Execute one scenario by key
The seven mandatory scenarios

Each scenario is runnable via the dashboard, the /api/scenarios/run endpoint,
or python seed.py.

Revocation before dispatch → BLOCKED_REVOKED. No receiver is created.
Revocation after dispatch, before completion → cancel + advance →
CANCELLATION_CONFIRMED.
Completion before cancellation takes effect → cancel is rejected →
COMPLETION_CONFIRMED.
Inconclusive receiver → OUTCOME_UNKNOWN. Never assumed cancelled.
Duplicate idempotency key → exactly one operation and one receiver
record; second call returns DUPLICATE.
Cancellation acknowledged, not terminal → CANCELLATION_ACKNOWLEDGED,
explicitly not CANCELLATION_CONFIRMED.
Multiple operations pending during revocation → each classified
independently (CANCELLATION_CONFIRMED, COMPLETION_CONFIRMED,
OUTCOME_UNKNOWN).
How the "never assume" rule is enforced

The classifier in app/outcome_verification.py maps the receiver's raw state
plus its cancellation flags onto one of the five outcomes. There is no code
path that converts an ACK_PENDING receiver into CANCELLATION_CONFIRMED.
Confirmed outcomes require the receiver to be in a terminal state and, for
cancellation, to have a prior acknowledgment on record.

The evidence ledger appends both the request and the verification as
separate events, so any future auditor can see what was assumed vs. observed.

# Architectural limitations

This harness is a technical demonstration, not a production system. In
particular:

The receiver is a local simulation. Its state machine is defined in
external_receiver.py. It does not call any real payment processor and does
not cancel anything outside the process.
"Simulated time" is a mechanical convenience. advance_simulated_time
deterministically moves the receiver past its settle boundary. Real external
systems respond over real time and over unpredictable latencies; the harness
does not model network jitter, partial failures, or duplicate delivery from
the receiver.
SQLite + check_same_thread=False is a demo convenience. The concurrency
test exercises the idempotency guarantee at the database layer, but SQLite's
write serialization is not the same as a distributed idempotency guarantee.
A production implementation would rely on the receiving system's own
idempotency contract and a persistent, transactional idempotency store.
The evidence ledger is one SQLite table with a per-row hash chain.
Tampering with the database file itself or truncating it will not be
detected from within the same database — the chain is only verifiable
relative to what is stored. A production audit log typically requires
append-only storage, off-device anchoring (e.g. a Merkle root published to a
separate trust domain), and access controls that this harness does not have.
The hash pepper is a fixed demo constant. It lives in
app/config.py (HASH_CHAIN_PEPPER) and is not a secret. It exists only
to make hashes reproducible across restarts.
No authentication or authorization is applied to the HTTP API. Anyone
with local access can grant, revoke, dispatch, cancel, or verify.
No real PKI, no real transport security, no mTLS, no signature scheme
with the external system. All of that is exactly what a real integration
would need in order to establish (rather than merely observe) an external
outcome.
The word "verified" in this harness means "verified against the local
simulation", not "verified against an external party". No third-party
certification, attestation, or guarantee is claimed or implied.
Non-claims

This project is not production-ready.
It is not certified, accredited, or endorsed by any standards body.
It does not cancel, refund, or otherwise affect real financial
transactions.
It does not prove that any specific vendor's revocation semantics will
behave the way this simulation does.
The purpose is to make the shape of the question concrete and testable, so
that a real integration can be designed against a target instead of against an
assumption.

