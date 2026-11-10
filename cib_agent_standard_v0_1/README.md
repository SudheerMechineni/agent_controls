# CIB agent controls — local reference pack

Version 0.1, prepared 9 November 2026. Synthetic data only. This pack accompanies [the recommended architecture standard](CIB_Agent_Architecture_Standards_v0.1.md).

## What you can run

The local implementation demonstrates three references:

1. **Authority and cash domain:** verify a delegated test identity, propose an internal transfer, require an independently entitled human checker, issue a signed exact-action grant, recheck current authority/limits, and book an idempotent balanced journal.
2. **HTTP adapter:** separate proposal, approval, authorization, execution, status and emergency-control routes; identity comes from signed test tokens, not request fields or arbitrary identity headers.
3. **Governed memory:** proposed/approved separation, purpose and tenant isolation, current source ACL/version checks, expiry, tombstoning and legal-hold restriction.

The reference rejects changed payment details and revoked authority, serializes cumulative-limit races, prevents duplicate ledger effects and fails closed if durable local audit cannot commit. It also demonstrates the lost-acknowledgement problem: the payment can be booked even when the caller receives an uncertain outcome.

## Run

Use an isolated Python 3.12 environment and the bank's approved package mirror. The versions in `requirements-tested.txt` are the exact installed direct dependencies used for validation; they are not an enterprise-approved or transitive hash lock.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-tested.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m cib_reference.demo
```

No real client, payment rail, blockchain, model, external API or identity provider is contacted by the demo/tests. The synthetic fixtures generate independent ephemeral Ed25519 keys in memory. Keys and tokens are not bundled or printed by the demo.

Expected demonstration:

```text
altered_amount: ACTION_DIGEST_MISMATCH
lost_ack: OUTCOME_UNKNOWN_QUERY_ORIGINAL_KEY
status: BOOKED
retry_returns_original_receipt: true
post_suspend: PRINCIPAL_AGENT_OR_MANDATE_SUSPENDED
local_audit_chain_valid: true
```

The real command prints JSON and an audit checkpoint; the checkpoint changes each run.

## Where to start

| Need | File |
|---|---|
| Standards across all ten areas, CIB profiles and source links | `CIB_Agent_Architecture_Standards_v0.1.md` |
| Implementation decisions, trust boundaries and code map | `docs/IMPLEMENTATION_GUIDE.md` |
| Scope and replacement work before any bank deployment | `ops/PRODUCTION_READINESS.md` |
| Financial containment, uncertain outcome and recovery | `ops/INCIDENT_RUNBOOK.md` |
| Temporal integration and financial-state semantics | `blueprints/TEMPORAL_EXECUTION.md` |
| MCP/A2A, FAPI, entitlements, DA and vendor integration | `blueprints/PLATFORM_INTEGRATION.md` |
| Machine-readable profile, mandate and release manifest | `examples/` |
| Action, control-event, OpenAPI and event-channel contracts | `contracts/` |
| Validated test count and environment | `docs/VALIDATION.md` |

## Important implementation boundaries

- This is an executable design aid, **not production banking software**.
- The test issuer is not an OAuth authorization server. The HTTP adapter is not a FAPI, mTLS or DPoP implementation. There is no production server bootstrap or public token-issuance endpoint.
- The local policy is Python. Production should use the bank's approved authorization/PDP and domain-control implementations, with equivalent tested semantics.
- All demo accounts use SGD and synthetic corporate tenants. The example is an internal same-currency book transfer, not a cross-border payment or final settlement rail.
- The screening field is a synthetic trusted-domain fact used to demonstrate freshness/rechecking. It is not a sanctions, fraud, KYT or AML engine.
- SQLite supplies one serializable writer boundary. That does not establish atomicity across an actual core ledger, limits service and external rail. Production requires domain reservations/idempotency and reconciliation.
- The hash chain detects local mutation and truncation against a trusted checkpoint. It is not WORM, non-repudiation or a defense against an administrator who can rewrite the chain and its only checkpoint.
- The demo's local memory tombstone is not proof of erasure from backups, indexes, snapshots or exported copies.
- Temporal, service mesh, HSM, OPA, production IAM, multi-region failover and live CIB integrations are blueprints, **not executed integrations** in this pack.
- Runtime restarts create new ephemeral signing keys; persisted test grants cannot be reused through a fresh Runtime. Production key custody, overlap/rotation, KID/JWKS lifecycle and durable service configuration are replacement interfaces.

Treat all identifiers and limits in examples as synthetic. Do not insert real client records, production credentials or bank secrets into the test fixtures.
