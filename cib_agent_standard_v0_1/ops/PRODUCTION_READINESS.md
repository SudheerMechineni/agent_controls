# Production readiness — required replacement and assurance work

The local pack intentionally does not bootstrap a production service. The following gates must be resolved before a controlled bank pilot or deployment. “Pass” means measured, independently reviewed evidence under the bank's process; it does not mean that this document grants approval.

| Area | Current pack | Required replacement/integration | Accountable owner |
|---|---|---|---|
| Identity | Ephemeral local test issuer and JOSE verification | Approved IAM/AS, keys/JWKS lifecycle, token revocation, FAPI/conformance, workload identity, mTLS/DPoP and TLS termination model | IAM/Security |
| Corporate authority | Synthetic user, mandate and checker records | Client master, authorized signatories, corporate mandates, standing authority, current entitlements and SoD | Channels/Product |
| Policy | Small local Python evaluator | Approved PDP/authorization with signed policy lifecycle, freshness and obligation enforcement | Authorization/control owners |
| Banking checks | Synthetic screening flag and account balances | Real FCC/fraud/beneficiary, product limits, liquidity, cut-off/holiday, currency and client eligibility services | Product/FCC/Treasury |
| Ledger | Single-file SGD book-transfer simulation | Authoritative core/ledger or payment domain, double-entry/legal accounting, durable idempotency, reconciliation, audit and accounting controls | Product/Finance |
| Distributed effects | One local writer transaction | Reservations, external acceptance/receipt/status contracts, inbox/outbox export, provider deduplication, unknown-outcome recovery | Product/SRE |
| Orchestration | Blueprint | Temporal workers, authentication/authorization, encrypted minimal history, bounded Activities, version/replay/cancellation tests | Workflow platform/Product |
| Data/memory | Local purpose/source/version isolation | Approved catalogue, source ACL propagation, classification, retention/legal hold, deletion from indexes/caches/backups/exports and restore workflow | Data/Privacy/Records |
| Evidence | Local hash-linked outbox/checkpoint | Independent collector, retention/WORM where required, access separation, protected checkpoints, clock integrity, capacity and retention policy | Records/Security/Operations |
| Observability | Test results and local events | Redacted OTel traces, stable bank evidence schema, alerts, dashboards, cost/exposure budgets and SLOs | SRE/Security |
| Deployment | Hardening fragments | Supported pinned images, verified builds, admission policies, networking/egress, secret delivery, autoscaling, sandboxing and penetration tests | Platform/Security |
| Availability/DR | Not tested | Product RTO/RPO, regional placement, writer fencing, durable limit/idempotency recovery and game days | SRE/Business continuity |
| Agent/model | No model/framework call | Approved models, guarded routing, prompt/retrieval/tool release management, adversarial/domain evals and change gates | AI platform/Product |
| Interoperability | HTTP/JSON contracts only | Approved MCP/A2A profiles, STS, tool registry, callback controls and conformance tests | Integration/IAM |
| Digital Assets | Architecture mapping only | HSM, wallet/custody, supply cap, chain ID/nonce, finality, provider/network adapter, legal asset and ledger reconciliation | DA/Product/Security |
| Vendor | Architectural seams | Contracts, regional processing, incident/change assurance, fourth-party map, exit/recovery test | TPRM/Product |
| Operating model | Synthetic roles | Named owners, 24x7 or restricted-window operation, runbooks, meaningful review, remediation and re-enable governance | Business/Technology owner |
| Regulatory | Source-informed draft | Entity/jurisdiction applicability, independent challenge, legal terms, records and product approvals | Legal/Compliance/AI Risk |

## Suggested release gates

1. **Design:** signed purpose/tier/authority/data-flow/dependency records and product invariants.
2. **Build:** reviewed code, locked and scanned dependencies, SBOM, protected builder/signing/deployment identities, attested artifact.
3. **Control:** deny/expiry/revocation/SoD/race/poisoning and business-negative tests pass.
4. **Resilience:** unknown outcome, suspension, cancellation, failover, provider loss and recovery rehearsed.
5. **Operations:** owners/on-call, dashboards, capacity, evidence custody, reviewer load and client support ready.
6. **Independent approval:** applicable CISO, Product Risk, FCC, AI/Model Risk, Compliance, Architecture and operations sign-off.
7. **Limited launch:** shadow/prepare-only first, then bounded C3 exposure with stop thresholds; no shadow financial writes.

## Essential limits of local evidence

- Local passing tests do not establish production performance, security accreditation or legal compliance.
- Process-local signing keys are lost on restart. The durable SQLite store is not a production key/authority lifecycle implementation.
- Local concurrency tests exercise one host/database consistency boundary, not multi-region shared limits.
- A local audit hash chain is not independently immutable evidence.
- The example memory tombstone does not purge historical backups or external indexes.
- A negative model answer or a chat-level refusal is not an enforcement control; no model is needed for these control tests.
