from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

from .fixtures import agent_token, human_token, seed, transfer
from .model import GuardError, ManualClock, OutcomeUnknown
from .runtime import Runtime


def main():
    with tempfile.TemporaryDirectory(prefix="cib-demo-") as folder:
        runtime = Runtime(Path(folder) / "demo.db", ManualClock())
        seed(runtime)
        agent = runtime.identity(agent_token(runtime))
        checker = runtime.identity(human_token(runtime))
        admin = runtime.identity(human_token(runtime, "operator"))
        action = transfer(runtime)
        proposal = runtime.propose(agent, action)
        runtime.approve(checker, proposal["proposal_id"])
        grant = runtime.authorize(agent, proposal["proposal_id"])["grant"]
        try:
            runtime.execute(agent, grant, replace(action, amount_minor=action.amount_minor + 1))
        except GuardError as e:
            print(json.dumps({"altered_amount": e.code}))
        try:
            runtime.execute(agent, grant, action, simulate_lost_ack=True)
        except OutcomeUnknown as e:
            print(json.dumps({"lost_ack": e.code}))
        receipt = runtime.payment_status(agent, action.idempotency_key)
        retry = runtime.execute(agent, grant, action)
        print(json.dumps({"status": receipt["status"], "retry_returns_original_receipt": receipt == retry}))
        next_action = transfer(runtime, "payment-2")
        next_proposal = runtime.propose(agent, next_action)["proposal_id"]
        runtime.approve(checker, next_proposal)
        next_grant = runtime.authorize(agent, next_proposal)["grant"]
        runtime.suspend_agent(admin, "treasury-agent")
        try:
            runtime.execute(agent, next_grant, next_action)
        except GuardError as e:
            print(json.dumps({"post_suspend": e.code}))
        print(json.dumps({"local_audit_chain_valid": runtime.store.verify_chain(),
                          "audit_checkpoint": runtime.store.checkpoint()}))


if __name__ == "__main__":
    main()
