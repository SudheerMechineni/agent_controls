from __future__ import annotations

import json
import uuid
from pathlib import Path

from .identity import TokenCodec, verified_identity
from .model import Action, Clock, GuardError, Identity, OutcomeUnknown, canonical
from .policy import evaluate, row_or_deny
from .store import Store


class Runtime:
    """Local, single consistency-domain executable control reference.

    SQLite serializes checks, limits, debit/credit, grant consumption and the
    audit outbox. This is intentionally NOT evidence that these operations
    are atomic across a real gateway, core ledger and external payment rail.
    No external bank, network, LLM or real payment is contacted.
    """

    def __init__(self, path: str | Path, clock: Clock | None = None):
        self.clock = clock or Clock()
        self.store = Store(path, self.clock)
        self.iam = TokenCodec("urn:demo:iam", "urn:cib:authority", "at+jwt", self.clock, 300)
        self.capabilities = TokenCodec("urn:demo:authority", "urn:cib:cash-domain", "cib-action+jwt", self.clock, 30)
        self.approvals = TokenCodec("urn:demo:approval", "urn:cib:authority", "cib-approval+jwt", self.clock, 120)

    def identity(self, bearer: str) -> Identity:
        return verified_identity(self.iam, bearer)

    def require_scope(self, identity: Identity, scope: str):
        if identity.expires_at is not None and identity.expires_at <= self.clock.now():
            raise GuardError("IDENTITY_CONTEXT_EXPIRED", 401)
        if scope not in identity.scopes:
            raise GuardError("INSUFFICIENT_SCOPE")

    @staticmethod
    def _proposal(db, identity: Identity, proposal_id: str):
        row = db.execute("SELECT * FROM proposals WHERE id=? AND tenant=?", (proposal_id, identity.tenant)).fetchone()
        if row is None:
            raise GuardError("RESOURCE_OR_AUTHORITY_NOT_AVAILABLE", 404)
        if (row["principal"], row["agent"], row["task"]) != (identity.principal, identity.agent, identity.task):
            raise GuardError("PROPOSAL_IDENTITY_BINDING")
        return row

    def propose(self, identity: Identity, action: Action) -> dict:
        action = Action.parse(action.data())
        self.require_scope(identity, "action:propose")
        with self.store.transaction() as db:
            decision = evaluate(db, identity, action, self.clock)
            pid = str(uuid.uuid4())
            db.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?,?,NULL)",
                       (pid, identity.tenant, identity.principal, identity.agent,
                        identity.task, canonical(action.data()), action.hash))
            self.store.audit(db, {"event": "action.proposed", "proposal_id": pid,
                                  "tenant": identity.tenant, "principal": identity.principal,
                                  "agent": identity.agent, "task": identity.task,
                                  "action_hash": action.hash, "snapshot": decision.snapshot})
        return {"proposal_id": pid, "action_hash": action.hash,
                "decision": "REQUIRE_APPROVAL" if decision.requires_approval else "ALLOW"}

    def approve(self, checker: Identity, proposal_id: str) -> dict:
        self.require_scope(checker, "approval:decide")
        if checker.agent is not None:
            raise GuardError("DIRECT_HUMAN_APPROVAL_REQUIRED")
        with self.store.transaction() as db:
            p = db.execute("SELECT * FROM proposals WHERE id=? AND tenant=?", (proposal_id, checker.tenant)).fetchone()
            if p is None:
                raise GuardError("RESOURCE_OR_AUTHORITY_NOT_AVAILABLE", 404)
            action = Action.parse(json.loads(p["action"]))
            user = row_or_deny(db, "principals", checker.tenant, checker.principal)
            if (not user["active"] or user["approve_account"] != action.debit_account
                    or checker.principal == p["principal"]):
                raise GuardError("MAKER_CHECKER_OR_APPROVER_ENTITLEMENT")
            original = Identity(p["tenant"], p["principal"], p["agent"], p["task"], frozenset())
            decision = evaluate(db, original, action, self.clock)
            receipt = self.approvals.issue({"sub": checker.principal, "tenant": checker.tenant,
                                            "proposal_id": proposal_id, "action_hash": action.hash,
                                            "maker": p["principal"], "approver_epoch": user["epoch"],
                                            "reviewed_snapshot": decision.snapshot})
            db.execute("UPDATE proposals SET approval=? WHERE id=?", (receipt, proposal_id))
            self.store.audit(db, {"event": "action.approved", "proposal_id": proposal_id,
                                  "tenant": checker.tenant, "principal": checker.principal,
                                  "action_hash": action.hash})
        # Receipt is kept server-side; model never needs human credentials.
        return {"proposal_id": proposal_id, "status": "APPROVED", "action_hash": action.hash}

    def _approval_check(self, db, p, action: Action, snapshot: dict):
        if not p["approval"]:
            raise GuardError("APPROVAL_REQUIRED", 409)
        receipt = self.approvals.verify(p["approval"])
        checker = row_or_deny(db, "principals", p["tenant"], receipt["sub"])
        if (receipt.get("tenant") != p["tenant"] or receipt.get("proposal_id") != p["id"]
                or receipt.get("action_hash") != action.hash or receipt.get("maker") != p["principal"]
                or receipt.get("reviewed_snapshot") != snapshot
                or receipt["sub"] == p["principal"] or not checker["active"]
                or checker["epoch"] != receipt.get("approver_epoch")
                or checker["approve_account"] != action.debit_account):
            raise GuardError("APPROVAL_STALE_OR_BINDING_FAILED")

    def authorize(self, identity: Identity, proposal_id: str) -> dict:
        self.require_scope(identity, "action:propose")
        with self.store.transaction() as db:
            p = self._proposal(db, identity, proposal_id)
            action = Action.parse(json.loads(p["action"]))
            decision = evaluate(db, identity, action, self.clock)
            if decision.requires_approval:
                self._approval_check(db, p, action, decision.snapshot)
            mandate = row_or_deny(db, "mandates", identity.tenant, action.mandate_id)
            life = min(30, mandate["expires"] - self.clock.now(),
                       (identity.expires_at or self.clock.now() + 30) - self.clock.now())
            if life <= 0:
                raise GuardError("AUTHORITY_EXPIRED_BEFORE_GRANT", 401)
            grant = self.capabilities.issue({"sub": identity.principal, "tenant": identity.tenant,
                                              "act": {"sub": identity.agent}, "task": identity.task,
                                              "proposal_id": proposal_id, "action_hash": action.hash,
                                              "snapshot": decision.snapshot}, ttl=life)
            claims = self.capabilities.verify(grant)
            db.execute("INSERT INTO grants VALUES(?,?,0)", (claims["jti"], proposal_id))
            self.store.audit(db, {"event": "action.authorized", "proposal_id": proposal_id,
                                  "tenant": identity.tenant, "principal": identity.principal,
                                  "agent": identity.agent, "task": identity.task,
                                  "action_hash": action.hash, "grant_jti": claims["jti"],
                                  "snapshot": decision.snapshot})
        return {"grant": grant, "expires_in_seconds": life, "action_hash": action.hash}

    def execute(self, identity: Identity, grant: str, action: Action,
                *, simulate_lost_ack: bool = False) -> dict:
        action = Action.parse(action.data())
        self.require_scope(identity, "action:execute")
        claims = self.capabilities.verify(grant)
        if (claims.get("tenant"), claims.get("sub"), claims.get("act"), claims.get("task")) != (
                identity.tenant, identity.principal, {"sub": identity.agent}, identity.task):
            raise GuardError("GRANT_IDENTITY_BINDING")
        if claims.get("action_hash") != action.hash:
            raise GuardError("ACTION_DIGEST_MISMATCH")
        try:
            result = self._execute_transaction(identity, claims, action)
        except GuardError as e:
            # An auditable denial is independent of the rolled-back business tx.
            # If the audit service itself is unavailable, no money is posted.
            try:
                with self.store.transaction() as db:
                    self.store.audit(db, {"event": "action.denied", "tenant": identity.tenant,
                                          "principal": identity.principal, "agent": identity.agent,
                                          "task": identity.task, "action_hash": action.hash,
                                          "reason": e.code})
            except GuardError:
                pass
            raise
        if simulate_lost_ack:
            # The ledger committed; the caller did not receive confirmation.
            raise OutcomeUnknown()
        return result

    def _execute_transaction(self, identity, claims, action):
        with self.store.transaction() as db:
            self.require_scope(identity, "action:execute")
            if claims["exp"] <= self.clock.now():
                raise GuardError("GRANT_EXPIRED_BEFORE_ACCEPTANCE", 401)
            p = self._proposal(db, identity, claims["proposal_id"])
            if p["action_hash"] != action.hash:
                raise GuardError("ACTION_DIGEST_MISMATCH")
            # Liveness/revocation and identity remain checked even on a retry.
            for table, object_id in [("principals", identity.principal), ("agents", identity.agent),
                                     ("mandates", action.mandate_id)]:
                entry = row_or_deny(db, table, identity.tenant, object_id)
                if not entry["active"]:
                    raise GuardError("PRINCIPAL_AGENT_OR_MANDATE_SUSPENDED")
            existing = db.execute("SELECT * FROM payments WHERE tenant=? AND idem=?",
                                  (identity.tenant, action.idempotency_key)).fetchone()
            if existing:
                if (existing["action_hash"] != action.hash
                        or existing["principal"] != identity.principal or existing["agent"] != identity.agent):
                    raise GuardError("IDEMPOTENCY_CONFLICT", 409)
                # Identity-scoped response retrieval; no new financial side effect.
                self._status_entitlement(db, identity, existing)
                return json.loads(existing["result"])
            grant_row = db.execute("SELECT * FROM grants WHERE jti=?", (claims["jti"],)).fetchone()
            if not grant_row or grant_row["proposal_id"] != p["id"] or grant_row["consumed"]:
                raise GuardError("GRANT_NOT_FOUND_OR_ALREADY_USED", 409)
            decision = evaluate(db, identity, action, self.clock)
            if decision.snapshot != claims.get("snapshot"):
                raise GuardError("AUTHORIZATION_CHANGED_REAUTHORIZE", 409)
            if decision.requires_approval:
                self._approval_check(db, p, action, decision.snapshot)
            if action.operation == "accounts.balance":
                balance = row_or_deny(db, "accounts", identity.tenant, action.debit_account)["balance"]
                result = {"status": "READ", "account_ref": action.debit_account,
                          "balance_minor": balance, "currency": action.currency}
            else:
                payment_id = str(uuid.uuid4())
                # All checks, counters, double entry, idempotency and audit commit
                # under the same writer transaction in this local reference.
                db.execute("UPDATE accounts SET balance=balance-? WHERE tenant=? AND id=?",
                           (action.amount_minor, identity.tenant, action.debit_account))
                db.execute("UPDATE accounts SET balance=balance+? WHERE tenant=? AND id=?",
                           (action.amount_minor, identity.tenant, action.credit_account))
                db.execute("UPDATE mandates SET used=used+? WHERE tenant=? AND id=?",
                           (action.amount_minor, identity.tenant, action.mandate_id))
                for account, delta in [(action.debit_account, -action.amount_minor),
                                       (action.credit_account, action.amount_minor)]:
                    db.execute("INSERT INTO ledger(payment_id,tenant,account,currency,delta) VALUES(?,?,?,?,?)",
                               (payment_id, identity.tenant, account, action.currency, delta))
                result = {"status": "BOOKED", "payment_id": payment_id,
                          "idempotency_key": action.idempotency_key, "action_hash": action.hash}
                db.execute("INSERT INTO payments VALUES(?,?,?,?,?,?,?,?)",
                           (identity.tenant, action.idempotency_key, action.hash, claims["jti"],
                            canonical(result), action.debit_account, identity.principal, identity.agent))
            db.execute("UPDATE grants SET consumed=1 WHERE jti=?", (claims["jti"],))
            self.store.audit(db, {"event": "action.executed", "tenant": identity.tenant,
                                  "principal": identity.principal, "agent": identity.agent,
                                  "task": identity.task, "action_hash": action.hash,
                                  "grant_jti": claims["jti"], "result_ref": result.get("payment_id"),
                                  "status": result["status"], "snapshot": decision.snapshot})
        return result

    @staticmethod
    def _status_entitlement(db, identity, payment):
        user = row_or_deny(db, "principals", identity.tenant, identity.principal)
        if (not user["active"] or "accounts.balance" not in
                json.loads(user["permissions"]).get(payment["debit"], [])):
            raise GuardError("STATUS_ENTITLEMENT_DENIED")
        if identity.agent is not None and (payment["principal"] != identity.principal
                                          or payment["agent"] != identity.agent):
            raise GuardError("STATUS_IDENTITY_BINDING")

    def payment_status(self, identity: Identity, key: str) -> dict:
        self.require_scope(identity, "payment:status")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM payments WHERE tenant=? AND idem=?", (identity.tenant, key)).fetchone()
            if not row:
                return {"status": "NOT_FOUND_NOT_PROOF_OF_NO_EFFECT"}
            self._status_entitlement(db, identity, row)
            self.store.audit(db, {"event": "payment.status.read", "tenant": identity.tenant,
                                  "principal": identity.principal, "agent": identity.agent,
                                  "action_hash": row["action_hash"]})
            return json.loads(row["result"])

    def suspend_agent(self, admin: Identity, agent_id: str):
        self.require_scope(admin, "control:admin")
        if admin.agent is not None:
            raise GuardError("DIRECT_HUMAN_CONTROL_REQUIRED")
        with self.store.transaction() as db:
            user = row_or_deny(db, "principals", admin.tenant, admin.principal)
            if not user["active"] or not user["control_admin"]:
                raise GuardError("CONTROL_ADMIN_REQUIRED")
            row_or_deny(db, "agents", admin.tenant, agent_id)
            db.execute("UPDATE agents SET active=0,epoch=epoch+1 WHERE tenant=? AND id=?", (admin.tenant, agent_id))
            self.store.audit(db, {"event": "agent.suspended", "tenant": admin.tenant,
                                  "principal": admin.principal, "agent": agent_id})

    def revoke_mandate(self, admin: Identity, mandate_id: str):
        self.require_scope(admin, "control:admin")
        if admin.agent is not None:
            raise GuardError("DIRECT_HUMAN_CONTROL_REQUIRED")
        with self.store.transaction() as db:
            user = row_or_deny(db, "principals", admin.tenant, admin.principal)
            if not user["active"] or not user["control_admin"]:
                raise GuardError("CONTROL_ADMIN_REQUIRED")
            row_or_deny(db, "mandates", admin.tenant, mandate_id)
            db.execute("UPDATE mandates SET active=0,epoch=epoch+1 WHERE tenant=? AND id=?", (admin.tenant, mandate_id))
            self.store.audit(db, {"event": "mandate.revoked", "tenant": admin.tenant,
                                  "principal": admin.principal, "mandate_id": mandate_id})
