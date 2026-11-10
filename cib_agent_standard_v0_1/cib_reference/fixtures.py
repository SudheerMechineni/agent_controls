"""Synthetic fixtures only. Never expose these issuance helpers as endpoints."""
from __future__ import annotations

from dataclasses import replace

from .model import Action, canonical
from .runtime import Runtime


def seed(runtime: Runtime):
    with runtime.store.transaction() as db:
        for tenant in ["CORP_A", "CORP_B"]:
            permissions = canonical({"OPS_SGD": ["accounts.balance", "payments.internal-transfer"]})
            users = [(tenant, "maker", 1, 1, permissions, None, 0),
                     (tenant, "checker", 1, 1, permissions, "OPS_SGD", 0),
                     (tenant, "operator", 1, 1, permissions, None, 1),
                     (tenant, "outsider", 1, 1, "{}", None, 0)]
            db.executemany("INSERT INTO principals VALUES(?,?,?,?,?,?,?)", users)
            db.execute("INSERT INTO agents VALUES(?,?,?,?,?,?)",
                       (tenant, "treasury-agent", 1, 1, "sha256:demo-release-approved",
                        canonical(["accounts.balance", "payments.internal-transfer", "memory.read", "memory.write"])))
            for account, balance in [("OPS_SGD", 10_000_000), ("PAYROLL_SGD", 100_000), ("OTHER_SGD", 0)]:
                db.execute("INSERT INTO accounts VALUES(?,?,?,?,?,?,?)",
                           (tenant, account, "SGD", balance, 1, runtime.clock.now() + 3600, 1))
            db.execute("INSERT INTO mandates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (tenant, "mandate-1", "maker", "treasury-agent", "task-1", 1, 1,
                        runtime.clock.now() + 600, "payroll", "OPS_SGD", "PAYROLL_SGD",
                        1_000_000, 1_500_000, 0))


def agent_token(runtime: Runtime, tenant="CORP_A", principal="maker", task="task-1", scopes=None):
    return runtime.iam.issue({"sub": principal, "tenant": tenant, "act": {"sub": "treasury-agent"},
                              "task": task, "scope": scopes if scopes is not None else
                              "action:propose action:execute payment:status"})


def human_token(runtime: Runtime, principal="checker", tenant="CORP_A", scopes=None):
    return runtime.iam.issue({"sub": principal, "tenant": tenant, "task": "human-review",
                              "scope": scopes if scopes is not None else
                              "approval:decide control:admin payment:status"})


def transfer(runtime: Runtime, key="payment-1", amount=250_000) -> Action:
    return Action.parse({"operation": "payments.internal-transfer", "debit_account": "OPS_SGD",
                         "credit_account": "PAYROLL_SGD", "amount_minor": amount,
                         "currency": "SGD", "value_date": runtime.clock.business_date(),
                         "purpose": "payroll", "mandate_id": "mandate-1", "idempotency_key": key})


def balance_action(runtime: Runtime) -> Action:
    return replace(transfer(runtime, "balance-1"), operation="accounts.balance",
                   credit_account="", amount_minor=0)
