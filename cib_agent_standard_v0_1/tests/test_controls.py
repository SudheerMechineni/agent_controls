from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import jwt

from cib_reference.fixtures import agent_token, balance_action, human_token, seed, transfer
from cib_reference.model import Action, GuardError, ManualClock, OutcomeUnknown
from cib_reference.runtime import Runtime


class ControlsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = Runtime(Path(self.tmp.name) / "bank.db", ManualClock())
        seed(self.rt)
        self.agent = self.rt.identity(agent_token(self.rt))
        self.checker = self.rt.identity(human_token(self.rt))
        self.admin = self.rt.identity(human_token(self.rt, "operator"))
        self.action = transfer(self.rt)

    def tearDown(self):
        self.tmp.cleanup()

    def change(self, sql, args=()):
        with self.rt.store.transaction() as db:
            db.execute(sql, args)

    def scalar(self, sql, args=()):
        with self.rt.store.connection() as db:
            return db.execute(sql, args).fetchone()[0]

    def approved(self, action=None, identity=None):
        a, i = action or self.action, identity or self.agent
        pid = self.rt.propose(i, a)["proposal_id"]
        self.rt.approve(self.checker, pid)
        return self.rt.authorize(i, pid)["grant"]

    def assert_denied(self, call, code=None):
        with self.assertRaises(GuardError) as cm:
            call()
        if code:
            self.assertEqual(code, cm.exception.code)

    def test_balance_read_has_no_monetary_side_effect(self):
        action = balance_action(self.rt)
        p = self.rt.propose(self.agent, action)
        self.assertEqual("ALLOW", p["decision"])
        grant = self.rt.authorize(self.agent, p["proposal_id"])["grant"]
        self.assertEqual(10_000_000, self.rt.execute(self.agent, grant, action)["balance_minor"])
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM ledger"))

    def test_transfer_is_balanced_double_entry(self):
        result = self.rt.execute(self.agent, self.approved(), self.action)
        self.assertEqual("BOOKED", result["status"])
        self.assertEqual(2, self.scalar("SELECT COUNT(*) FROM ledger"))
        self.assertEqual(0, self.scalar("SELECT SUM(delta) FROM ledger"))

    def test_approval_is_required(self):
        pid = self.rt.propose(self.agent, self.action)["proposal_id"]
        self.assert_denied(lambda: self.rt.authorize(self.agent, pid), "APPROVAL_REQUIRED")

    def test_maker_cannot_approve_even_with_approver_permission(self):
        pid = self.rt.propose(self.agent, self.action)["proposal_id"]
        self.change("UPDATE principals SET approve_account='OPS_SGD' WHERE tenant='CORP_A' AND id='maker'")
        maker = self.rt.identity(human_token(self.rt, "maker"))
        self.assert_denied(lambda: self.rt.approve(maker, pid), "MAKER_CHECKER_OR_APPROVER_ENTITLEMENT")

    def test_agent_cannot_impersonate_human_approval(self):
        pid = self.rt.propose(self.agent, self.action)["proposal_id"]
        agent = self.rt.identity(agent_token(self.rt, principal="checker", scopes="approval:decide"))
        self.assert_denied(lambda: self.rt.approve(agent, pid), "DIRECT_HUMAN_APPROVAL_REQUIRED")

    def test_scope_is_not_approver_entitlement(self):
        pid = self.rt.propose(self.agent, self.action)["proposal_id"]
        outsider = self.rt.identity(human_token(self.rt, "outsider"))
        self.assert_denied(lambda: self.rt.approve(outsider, pid))

    def test_amount_mutation_breaks_grant(self):
        grant = self.approved()
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, replace(self.action, amount_minor=1)),
                           "ACTION_DIGEST_MISMATCH")

    def test_beneficiary_mutation_breaks_grant(self):
        grant = self.approved()
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, replace(self.action, credit_account="OTHER_SGD")),
                           "ACTION_DIGEST_MISMATCH")

    def test_purpose_mutation_breaks_grant(self):
        grant = self.approved()
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, replace(self.action, purpose="investment")),
                           "ACTION_DIGEST_MISMATCH")

    def test_idempotency_key_mutation_breaks_grant(self):
        grant = self.approved()
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, replace(self.action, idempotency_key="new-key")),
                           "ACTION_DIGEST_MISMATCH")

    def test_task_is_bound_to_mandate_and_grant(self):
        other = self.rt.identity(agent_token(self.rt, task="task-2"))
        self.assert_denied(lambda: self.rt.propose(other, self.action), "MANDATE_INVALID_REVOKED_OR_EXPIRED")
        grant = self.approved()
        self.assert_denied(lambda: self.rt.execute(other, grant, self.action), "GRANT_IDENTITY_BINDING")

    def test_cross_tenant_grant_rejected(self):
        grant = self.approved()
        other = self.rt.identity(agent_token(self.rt, tenant="CORP_B"))
        self.assert_denied(lambda: self.rt.execute(other, grant, self.action), "GRANT_IDENTITY_BINDING")

    def test_cross_tenant_proposal_not_found(self):
        pid = self.rt.propose(self.agent, self.action)["proposal_id"]
        other = self.rt.identity(agent_token(self.rt, tenant="CORP_B"))
        self.assert_denied(lambda: self.rt.authorize(other, pid), "RESOURCE_OR_AUTHORITY_NOT_AVAILABLE")

    def test_missing_scope_rejected(self):
        other = self.rt.identity(agent_token(self.rt, scopes="payment:status"))
        self.assert_denied(lambda: self.rt.propose(other, self.action), "INSUFFICIENT_SCOPE")

    def test_user_entitlement_is_still_required(self):
        other = self.rt.identity(agent_token(self.rt, principal="outsider"))
        self.assert_denied(lambda: self.rt.propose(other, self.action), "ENTITLEMENT_DENIED")

    def test_wrong_beneficiary_and_per_action_limit(self):
        self.assert_denied(lambda: self.rt.propose(self.agent, replace(self.action, credit_account="OTHER_SGD")),
                           "BENEFICIARY_OR_CURRENCY_NOT_APPROVED")
        self.assert_denied(lambda: self.rt.propose(self.agent, replace(self.action, amount_minor=1_000_001)),
                           "PER_ACTION_LIMIT")

    def test_post_authorization_agent_suspend(self):
        grant = self.approved()
        self.rt.suspend_agent(self.admin, "treasury-agent")
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action),
                           "PRINCIPAL_AGENT_OR_MANDATE_SUSPENDED")
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM ledger"))

    def test_post_authorization_mandate_revoke(self):
        grant = self.approved()
        self.rt.revoke_mandate(self.admin, "mandate-1")
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action))

    def test_agent_cannot_suspend_another_agent(self):
        delegated = self.rt.identity(agent_token(self.rt, principal="operator", scopes="control:admin"))
        self.assert_denied(lambda: self.rt.suspend_agent(delegated, "treasury-agent"),
                           "DIRECT_HUMAN_CONTROL_REQUIRED")

    def test_control_scope_without_directory_role_denied(self):
        self.assert_denied(lambda: self.rt.suspend_agent(self.checker, "treasury-agent"), "CONTROL_ADMIN_REQUIRED")

    def test_post_authorization_principal_suspend(self):
        grant = self.approved()
        self.change("UPDATE principals SET active=0,epoch=epoch+1 WHERE tenant='CORP_A' AND id='maker'")
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action))

    def test_policy_change_requires_new_authorization(self):
        grant = self.approved()
        self.change("UPDATE settings SET value='cib-local-0.2' WHERE key='policy_version'")
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action), "AUTHORIZATION_CHANGED_REAUTHORIZE")

    def test_agent_release_change_requires_new_authorization(self):
        grant = self.approved()
        self.change("UPDATE agents SET artifact_digest='sha256:new-release' WHERE tenant='CORP_A'")
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action), "AUTHORIZATION_CHANGED_REAUTHORIZE")

    def test_entitlement_epoch_change_invalidates_grant(self):
        grant = self.approved()
        self.change("UPDATE principals SET epoch=epoch+1 WHERE tenant='CORP_A' AND id='maker'")
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action), "AUTHORIZATION_CHANGED_REAUTHORIZE")

    def test_approver_revocation_is_checked_at_execution(self):
        grant = self.approved()
        self.change("UPDATE principals SET active=0 WHERE tenant='CORP_A' AND id='checker'")
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action), "APPROVAL_STALE_OR_BINDING_FAILED")

    def test_screening_is_rechecked_not_trusted_from_agent(self):
        grant = self.approved()
        self.change("UPDATE accounts SET screened=0,version=version+1 WHERE tenant='CORP_A' AND id='PAYROLL_SGD'")
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action), "SCREENING_MISSING_FAILED_OR_STALE")

    def test_screening_expiry_is_checked(self):
        self.change("UPDATE accounts SET screening_expiry=? WHERE tenant='CORP_A' AND id='PAYROLL_SGD'",
                    (self.rt.clock.now(),))
        self.assert_denied(lambda: self.rt.propose(self.agent, self.action), "SCREENING_MISSING_FAILED_OR_STALE")

    def test_expired_grant_denied(self):
        grant = self.approved()
        self.rt.clock.advance(31)
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action), "INVALID_OR_EXPIRED_TOKEN")

    def test_grant_cannot_outlive_authenticated_principal_context(self):
        self.rt.clock.advance(290)
        # Re-establish trusted screening and mandate validity for this test.
        pid = self.rt.propose(self.agent, self.action)["proposal_id"]
        self.checker = self.rt.identity(human_token(self.rt))
        self.rt.approve(self.checker, pid)
        response = self.rt.authorize(self.agent, pid)
        self.assertEqual(10, response["expires_in_seconds"])

    def test_expiry_is_rechecked_after_acceptance_queue_wait(self):
        claims = self.rt.capabilities.verify(self.approved())
        self.rt.clock.advance(31)
        self.assert_denied(lambda: self.rt._execute_transaction(self.agent, claims, self.action),
                           "GRANT_EXPIRED_BEFORE_ACCEPTANCE")

    def test_expired_approval_cannot_be_extended_by_new_grant(self):
        pid = self.rt.propose(self.agent, self.action)["proposal_id"]
        self.rt.approve(self.checker, pid)
        self.rt.clock.advance(121)
        self.assert_denied(lambda: self.rt.authorize(self.agent, pid), "INVALID_OR_EXPIRED_TOKEN")

    def test_approval_expiry_during_valid_grant_is_rechecked(self):
        pid = self.rt.propose(self.agent, self.action)["proposal_id"]
        self.rt.approve(self.checker, pid)
        self.rt.clock.advance(110)
        grant = self.rt.authorize(self.agent, pid)["grant"]
        self.rt.clock.advance(11)
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action), "INVALID_OR_EXPIRED_TOKEN")

    def test_iam_token_cannot_be_used_as_action_grant(self):
        self.assert_denied(lambda: self.rt.execute(self.agent, agent_token(self.rt), self.action))

    def test_tampered_jwt_and_unapproved_algorithm_denied(self):
        token = agent_token(self.rt)
        parts = token.split(".")
        parts[1] = jwt.utils.base64url_encode(b'{"sub":"operator"}').decode()
        self.assert_denied(lambda: self.rt.identity(".".join(parts)))
        claims = jwt.decode(token, options={"verify_signature": False})
        none = jwt.encode(claims, key="", algorithm="none", headers={"typ": "at+jwt", "kid": self.rt.iam.kid})
        self.assert_denied(lambda: self.rt.identity(none))

    def test_wrong_audience_and_issuer_denied_even_with_fixture_signature(self):
        claims = self.rt.iam.verify(agent_token(self.rt))
        for field in ["aud", "iss"]:
            changed = {**claims, field: "urn:wrong"}
            token = jwt.encode(changed, self.rt.iam._private, algorithm="EdDSA",
                               headers={"typ": "at+jwt", "kid": self.rt.iam.kid})
            self.assert_denied(lambda: self.rt.identity(token))

    def test_remote_key_header_never_used(self):
        claims = self.rt.iam.verify(agent_token(self.rt))
        token = jwt.encode(claims, self.rt.iam._private, algorithm="EdDSA",
                           headers={"typ": "at+jwt", "kid": self.rt.iam.kid,
                                    "jku": "https://attacker.invalid/keys"})
        self.assert_denied(lambda: self.rt.identity(token))

    def test_unknown_identity_fields_and_bad_amounts_rejected(self):
        data = self.action.data()
        for value in [True, 1.5, -1, "100"]:
            self.assert_denied(lambda v=value: Action.parse({**data, "amount_minor": v}))
        for field in ["tenant", "principal", "screening_passed", "approved", "agent_id"]:
            self.assert_denied(lambda f=field: Action.parse({**data, f: "spoofed"}))

    def test_unsupported_currency_and_operation_denied(self):
        for field, value in [("currency", "USD"), ("operation", "keys.export")]:
            self.assert_denied(lambda f=field, v=value: Action.parse({**self.action.data(), f: v}))

    def test_parallel_duplicate_execution_books_once(self):
        grant = self.approved()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.rt.execute(self.agent, grant, self.action), range(8)))
        self.assertEqual(1, len({x["payment_id"] for x in results}))
        self.assertEqual(2, self.scalar("SELECT COUNT(*) FROM ledger"))
        self.assertEqual(self.action.amount_minor, self.scalar("SELECT used FROM mandates WHERE tenant='CORP_A'"))

    def test_parallel_distinct_grants_cannot_overspend_shared_limit(self):
        self.change("UPDATE mandates SET total_limit=800000 WHERE tenant='CORP_A'")
        a, b = transfer(self.rt, "race-1", 500_000), transfer(self.rt, "race-2", 500_000)
        ga, gb = self.approved(a), self.approved(b)
        def run(pair):
            try:
                return self.rt.execute(self.agent, pair[0], pair[1])["status"]
            except GuardError as e:
                return e.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(run, [(ga, a), (gb, b)]))
        self.assertCountEqual(["BOOKED", "CUMULATIVE_MANDATE_LIMIT"], result)
        self.assertEqual(500_000, self.scalar("SELECT used FROM mandates WHERE tenant='CORP_A'"))

    def test_same_idempotency_key_different_payload_is_conflict(self):
        self.rt.execute(self.agent, self.approved(), self.action)
        new = replace(self.action, amount_minor=self.action.amount_minor + 1)
        grant = self.approved(new)
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, new), "IDEMPOTENCY_CONFLICT")

    def test_lost_ack_is_reconciled_by_original_key(self):
        grant = self.approved()
        with self.assertRaises(OutcomeUnknown):
            self.rt.execute(self.agent, grant, self.action, simulate_lost_ack=True)
        receipt = self.rt.payment_status(self.agent, self.action.idempotency_key)
        self.assertEqual(receipt, self.rt.execute(self.agent, grant, self.action))
        self.assertEqual(2, self.scalar("SELECT COUNT(*) FROM ledger"))

    def test_absence_of_status_is_not_treated_as_no_effect(self):
        self.assertEqual("NOT_FOUND_NOT_PROOF_OF_NO_EFFECT",
                         self.rt.payment_status(self.agent, "missing")["status"])

    def test_audit_failure_rolls_back_money_limits_and_grant(self):
        grant = self.approved()
        before = self.scalar("SELECT balance FROM accounts WHERE tenant='CORP_A' AND id='OPS_SGD'")
        self.rt.store.audit_available = False
        self.assert_denied(lambda: self.rt.execute(self.agent, grant, self.action), "DURABLE_AUDIT_UNAVAILABLE")
        self.assertEqual(before, self.scalar("SELECT balance FROM accounts WHERE tenant='CORP_A' AND id='OPS_SGD'"))
        self.assertEqual(0, self.scalar("SELECT used FROM mandates WHERE tenant='CORP_A'"))
        self.assertEqual(0, self.scalar("SELECT consumed FROM grants"))
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM ledger"))
        self.rt.store.audit_available = True
        self.assertEqual("BOOKED", self.rt.execute(self.agent, grant, self.action)["status"])

    def test_local_chain_detects_mutation_and_anchored_truncation(self):
        self.approved()
        anchor = self.rt.store.checkpoint()
        self.assertTrue(self.rt.store.verify_chain(anchor["head"], anchor["count"]))
        self.change("DELETE FROM audit_outbox WHERE seq=(SELECT MAX(seq) FROM audit_outbox)")
        self.assertFalse(self.rt.store.verify_chain(anchor["head"], anchor["count"]))
        self.change("UPDATE audit_outbox SET event='{}' WHERE seq=1")
        self.assertFalse(self.rt.store.verify_chain())

    def test_outbox_contains_no_tokens_or_raw_model_content(self):
        grant = self.approved()
        self.rt.execute(self.agent, grant, self.action)
        with self.rt.store.connection() as db:
            records = "\n".join(x[0] for x in db.execute("SELECT event FROM audit_outbox"))
        self.assertNotIn(grant, records)
        self.assertNotIn("access_token", records)
        self.assertNotIn("raw_output", records)
        self.assertNotIn("prompt", records)


if __name__ == "__main__":
    unittest.main()
