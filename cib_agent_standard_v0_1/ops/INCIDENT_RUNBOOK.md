# Agent containment and uncertain financial outcome runbook

**Purpose:** recommended operational procedure for adaptation to the bank's incident process. Emergency containment authority and independent re-enable authority must be established before launch.

## 1. Trigger

Trigger assessment on unauthorized or out-of-purpose tools/actions, changed instructions after approval, data exfiltration, suspicious delegation, runaway execution/cost, policy freshness failure, untrusted model/provider routing, incorrect-but-available operation or a material unexplained financial outcome.

Record: service/release, corporate/principal/agent/task IDs, action/operation IDs, discovery time, last known trustworthy state and affected product/legal entity. Protect these records; do not copy credentials, raw client data or hidden reasoning into general incident channels.

## 2. Contain new authority

1. Suspend the narrowest safe scope: task, mandate, agent release, provider, tool, client or product.
2. Revoke/invalidate relevant credentials/grants and increment authoritative policy/mandate epochs.
3. Enforce stop at gateway/tool and final domain acceptance; verify propagation rather than assuming it.
4. Restrict egress and quarantine compromised runtime/memory/artifacts.
5. Preserve the evidence and supervision needed to reconcile already accepted work.

Do not grant the agent authority to disable its own guardrails or reset its breaker. A rapid protective stop should not wait for a design committee if delegated incident authority already exists.

## 3. Establish the financial state

For every affected operation classify:

| State | Action |
|---|---|
| Proposed, not accepted | Stop/expire proposal and any unused reservations under domain rules |
| Pending approval | Revoke approval task; do not treat chat cancellation as complete |
| Authorized, not accepted | Revoke grant/mandate and verify acceptance fence |
| Accepted/booked | Obtain authoritative domain receipt; track external/settlement status |
| Unknown | Query original operation key, correlate provider receipt, reconcile ledger/network and preserve reservations |
| Settled/final | Use separately authorized recall/reversal/compensating business process where legally/operationally possible |

Never create a new idempotency key because a timeout occurred. A missing status response does not prove that no effect occurred. Do not replay historical approvals or reverse ledger entries outside the product's accounting controls.

## 4. Continue safely

Move to a prepared manual or narrower approved workflow, preserving current entitlements and SoD. Apply explicit operating windows/transaction caps if full 24x7 controls are unavailable. Prioritize material customer and liquidity exposures with the product owner and Treasury/FCC as applicable.

## 5. Reconstruct and remediate

Correlate trusted principal/actor, mandate version, exact instruction digest, reviewed object/approver, policy/facts, domain acceptance, retries, provider/network receipts and final ledger outcome. Treat model summaries as investigative aids, not authoritative evidence.

Identify the complete affected population, assess client harm, reconcile balances/limits/reservations, correct records, notify through approved processes and verify completion independently. Apply regulatory/customer notification rules determined by Legal/Compliance; do not invent universal timelines.

## 6. Return to service

Require root cause and containment review; rotated/revoked credentials; corrected policy/model/tool/memory artifacts; negative regression and recovery evidence; accountable owner and independent control sign-off; bounded canary and monitored expansion. Re-enablement must be a deliberate action, not automatic breaker expiry.

## 7. Measures

- Time from detection to verified new-acceptance stop.
- Number/value of accepted and uncertain operations after the stop request.
- Time to authoritative reconciliation and client harm containment.
- Completeness of evidence and absence of unexplained ledger/limit differences.
- Manual fallback capacity and reviewer load.
- Coverage of common provider/cloud/identity/SDK dependencies.
