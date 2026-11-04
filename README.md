External Operation Revocation & Outcome Verification Harness  
A duplicate idempotency key yields exactly one operation and one receiver record; the second call returns DUPLICATE. Cancellation is acknowledged but not terminal, marked CANCELLATIONACKNOWLEDGED rather than CANCELLATIONCONFIRMED. When multiple operations are pending during revocation, each is classified independently as CANCELLATIONCONFIRMED, COMPLETIONCONFIRMED, or OUTCOME_UNKNOWN.  

How the “never assume” rule is enforced  
The classifier in app/outcomeverification.py maps the receiver’s raw state and cancellation flags to one of five outcomes. No code path converts an ACKPENDING receiver into CANCELLATION_CONFIRMED. Confirmed outcomes require the receiver to be in a terminal state and, for cancellation, to have a prior acknowledgment on record.  

The evidence ledger records both the request and verification as separate events, allowing any future auditor to compare assumptions with observations.  

Architectural limitations  
This harness is a technical demonstration rather than a production system. In particular:  

The receiver is a local simulation defined in external_receiver.py. It does not contact any real payment processor or cancel anything outside the process.  
“Simulated time” is a mechanical convenience. advancesimulatedtime moves the receiver past its settle boundary deterministically. Real external systems respond over real time and unpredictable latencies; the harnessThe model omits network jitter, partial failures, and duplicate delivery from the receiver. SQLite with checksamethread=False serves as a demonstration convenience; the concurrency test checks idempotency at the database level, yet SQLite’s write serialization differs from a distributed guarantee. A production setup would depend on the receiving system’s idempotency contract and a persistent, transactional store.  

The evidence ledger uses one SQLite table with a per-row hash chain. Tampering with or truncating the file remains undetected within the same database, since the chain is verifiable only against stored data. A production audit log generally needs append-only storage, off-device anchoring such as a Merkle root published to a separate trust domain, and access controls absent here.  

The hash pepper is a fixed demonstration constant in app/config.py (HASHCHAINPEPPER) and is not secret; it exists solely to make hashes reproducible across restarts. No authentication or authorization applies to the HTTP API, so anyone with local access may grant, revoke, dispatch, cancel, or verify. There is no real PKI, transport security, mTLS, or signature scheme with the external system—all of which a real integration would require to establish rather than merely observe an external outcome.  

The term “verified” here means verified against the local simulation, not against an external party; no third-party certification, attestation, or guarantee is claimed or implied.  

Non-claims  
This project is not production-ready.  
It is not certified, accredited, or endorsed by any standards body.  
It does not cancel, refund, or otherwise affect real financial transactions.  
It does not prove that any specific vendor’s revocation semantics will behave like this simulation.  

The purpose is to make the shape of the question concrete and testable so that a real integration can be designed against a target rather than an assumption.
