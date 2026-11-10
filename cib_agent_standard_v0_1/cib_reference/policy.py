from __future__ import annotations

import json
from dataclasses import dataclass

from .model import Action, Clock, GuardError, Identity


@dataclass(frozen=True)
class Decision:
    snapshot: dict
    requires_approval: bool


def row_or_deny(db, table: str, tenant: str, object_id: str):
    # table is a code-owned literal, never supplied by an API or model.
    if table not in {"principals", "agents", "accounts", "mandates"}:
        raise ValueError("invalid table")
    row = db.execute(f"SELECT * FROM {table} WHERE tenant=? AND id=?", (tenant, object_id)).fetchone()
    if row is None:
        raise GuardError("RESOURCE_OR_AUTHORITY_NOT_AVAILABLE", 404)
    return row


def evaluate(db, identity: Identity, action: Action, clock: Clock) -> Decision:
    """Executable demonstration PDP; replace with the approved bank PDP.

    Inputs are server-side records and verified identity, never LLM assertions
    that screening passed or that someone approved the action.
    Mutable exposure counters are enforced again in the ledger transaction.
    """
    if identity.agent is None:
        raise GuardError("AGENT_IDENTITY_REQUIRED")
    user = row_or_deny(db, "principals", identity.tenant, identity.principal)
    agent = row_or_deny(db, "agents", identity.tenant, identity.agent)
    mandate = row_or_deny(db, "mandates", identity.tenant, action.mandate_id)
    debit = row_or_deny(db, "accounts", identity.tenant, action.debit_account)
    if not user["active"] or not agent["active"]:
        raise GuardError("PRINCIPAL_OR_AGENT_SUSPENDED")
    if action.operation not in json.loads(agent["operations"]):
        raise GuardError("AGENT_OPERATION_NOT_APPROVED")
    permissions = json.loads(user["permissions"])
    if action.operation not in permissions.get(action.debit_account, []):
        raise GuardError("ENTITLEMENT_DENIED")
    if (not mandate["active"] or mandate["expires"] <= clock.now()
            or mandate["principal"] != identity.principal
            or mandate["agent"] != identity.agent or mandate["task"] != identity.task):
        raise GuardError("MANDATE_INVALID_REVOKED_OR_EXPIRED")
    if (mandate["debit"] != action.debit_account or mandate["purpose"] != action.purpose
            or debit["currency"] != action.currency):
        raise GuardError("MANDATE_SCOPE_MISMATCH")
    if action.value_date != clock.business_date():
        raise GuardError("VALUE_DATE_REQUIRES_REVIEW")
    credit_version = None
    if action.operation == "payments.internal-transfer":
        credit = row_or_deny(db, "accounts", identity.tenant, action.credit_account)
        if action.credit_account != mandate["beneficiary"] or credit["currency"] != action.currency:
            raise GuardError("BENEFICIARY_OR_CURRENCY_NOT_APPROVED")
        if (not credit["screened"] or credit["screening_expiry"] <= clock.now()):
            raise GuardError("SCREENING_MISSING_FAILED_OR_STALE")
        if action.amount_minor > mandate["per_action"]:
            raise GuardError("PER_ACTION_LIMIT")
        if mandate["used"] + action.amount_minor > mandate["total_limit"]:
            raise GuardError("CUMULATIVE_MANDATE_LIMIT")
        if debit["balance"] < action.amount_minor:
            raise GuardError("INSUFFICIENT_AVAILABLE_FUNDS")
        credit_version = credit["version"]
    policy = db.execute("SELECT value FROM settings WHERE key='policy_version'").fetchone()[0]
    return Decision({"principal_epoch": user["epoch"], "agent_epoch": agent["epoch"],
                     "mandate_epoch": mandate["epoch"], "policy_version": policy,
                     "agent_artifact_digest": agent["artifact_digest"],
                     "debit_version": debit["version"], "credit_version": credit_version},
                    action.operation == "payments.internal-transfer")
