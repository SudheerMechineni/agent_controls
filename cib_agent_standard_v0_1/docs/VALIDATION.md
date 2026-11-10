# Validation record

**Validated:** 9 November 2026  
**Pack:** CIB agent architecture/control reference v0.1  
**Scope:** local synthetic-data implementation, contracts and artifact structure.

## Executed results

| Check | Result |
|---|---|
| Local control, HTTP, memory and schema test suite | **72 tests passed**, no failures/errors |
| Core authority/financial controls | 46 tests passed |
| HTTP/ASGI adapter | 9 tests passed |
| Governed memory | 13 tests passed |
| Contract examples and schema guards | 4 tests passed |
| Demonstration | Ran successfully: changed action denied; lost acknowledgement reconciled; duplicate returned original receipt; post-suspension action denied; local audit chain valid |
| Standards catalogue | 69 unique controls across all ten areas; machine-readable CSV generated |
| JSON syntax | 5 JSON files parsed |
| YAML syntax | 6 YAML files parsed, including multi-document hardening fragment |
| Generated OpenAPI | Internal references resolved |
| Markdown structure | Balanced fenced blocks checked |

Executed commands included:

```bash
python3 -m cib_reference.demo
python3 scripts/build_contracts.py
python3 -m unittest discover -s tests -v
```

Tests include actual concurrent submissions against the local transactional store. Two independently authorized instructions cannot both overspend a shared cumulative mandate cap, and eight concurrent retries of one instruction produce a single financial effect.

Negative scenarios include altered amount/beneficiary/purpose/key, missing or stale approvals, maker self-approval, agent impersonation of a checker, wrong tenant/task/audience/issuer, unapproved algorithms/key headers, revoked agent/mandate/principal, changed policy/release/entitlement version, stale screening, identity/grant expiry, audit failure, lost acknowledgement and poisoned memory attempting to supply banking approval.

## Runtime and direct dependency versions used

- Python 3.12.14
- cryptography 50.0.0
- PyJWT 2.13.0
- FastAPI 0.141.1
- Pydantic 2.13.4
- HTTPX 0.28.1
- jsonschema 4.26.0
- PyYAML 6.0.3

These are the installed versions actually used, not a statement that the bank has approved these packages or that a full transitive/hash lock has been created.

## Not established by this validation

- No real bank, model, payment rail, blockchain, HSM, OAuth server or provider was contacted by the demo/tests.
- HTTP tests use an in-process ASGI transport, not a deployed TLS/mTLS/DPoP service.
- No FAPI, MCP, A2A, Kubernetes, Envoy, OPA or Temporal conformance/integration certification was performed.
- YAML parsing does not validate a deployment against a cluster, release-specific API schema or security accreditation.
- The AsyncAPI file is a design contract; no broker/exporter/consumer was executed and no independent AsyncAPI conformance claim is made.
- No production performance, failover, penetration test, real FCC control, regulatory approval or complete retention/erasure process was tested.
- A local hash chain does not establish independent immutability or legal non-repudiation.

The production-readiness gate specifies the integrations and evidence required beyond these local results.
