import tempfile
import unittest
from pathlib import Path

import httpx

from cib_reference.api import create_app
from cib_reference.fixtures import agent_token, human_token, seed, transfer
from cib_reference.model import ManualClock
from cib_reference.runtime import Runtime


class HttpTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = Runtime(Path(self.tmp.name) / "test.db", ManualClock())
        seed(self.rt)
        self.app = create_app(self.rt)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://local-test")
        self.agent_headers = {"Authorization": "Bearer " + agent_token(self.rt)}
        self.checker_headers = {"Authorization": "Bearer " + human_token(self.rt)}
        self.action = transfer(self.rt).data()

    async def asyncTearDown(self):
        await self.client.aclose()
        self.tmp.cleanup()

    async def test_missing_bearer_is_401(self):
        r = await self.client.post("/v1/proposals", json={"action": self.action})
        self.assertEqual(401, r.status_code)
        self.assertEqual("Bearer", r.headers["www-authenticate"])

    async def test_identity_headers_cannot_substitute_for_credentials(self):
        r = await self.client.post("/v1/proposals", json={"action": self.action},
                                   headers={"X-Principal": "maker", "X-Agent": "treasury-agent"})
        self.assertEqual(401, r.status_code)

    async def test_extra_wrapper_fields_are_rejected(self):
        r = await self.client.post("/v1/proposals", headers=self.agent_headers,
                                   json={"action": self.action, "approved": True})
        self.assertEqual(422, r.status_code)

    async def test_action_cannot_supply_tenant(self):
        r = await self.client.post("/v1/proposals", headers=self.agent_headers,
                                   json={"action": {**self.action, "tenant": "CORP_B"}})
        self.assertEqual(400, r.status_code)

    async def test_full_http_approval_and_execution(self):
        r = await self.client.post("/v1/proposals", headers=self.agent_headers, json={"action": self.action})
        self.assertEqual(200, r.status_code)
        pid = r.json()["proposal_id"]
        r = await self.client.post(f"/v1/proposals/{pid}/authorize", headers=self.agent_headers)
        self.assertEqual(409, r.status_code)
        r = await self.client.post(f"/v1/proposals/{pid}/approve", headers=self.checker_headers)
        self.assertEqual(200, r.status_code)
        r = await self.client.post(f"/v1/proposals/{pid}/authorize", headers=self.agent_headers)
        grant = r.json()["grant"]
        r = await self.client.post("/v1/actions/execute", headers=self.agent_headers,
                                   json={"grant": grant, "action": self.action})
        self.assertEqual(200, r.status_code)
        self.assertEqual("BOOKED", r.json()["status"])
        self.assertEqual("no-store", r.headers["cache-control"])

    async def test_stale_identity_token_is_401(self):
        self.rt.clock.advance(301)
        r = await self.client.post("/v1/proposals", headers=self.agent_headers, json={"action": self.action})
        self.assertEqual(401, r.status_code)

    async def test_audit_failure_makes_readiness_unavailable(self):
        self.rt.store.audit_available = False
        self.assertEqual(503, (await self.client.get("/ready")).status_code)
        self.assertEqual(200, (await self.client.get("/live")).status_code)

    async def test_wrong_customer_cannot_query_payment(self):
        headers = {"Authorization": "Bearer " + agent_token(self.rt, tenant="CORP_B")}
        r = await self.client.get("/v1/payments/by-idempotency-key/payment-1", headers=headers)
        self.assertEqual("NOT_FOUND_NOT_PROOF_OF_NO_EFFECT", r.json()["status"])

    async def test_openapi_declares_bearer_not_fapi_certification(self):
        spec = self.app.openapi()
        self.assertEqual("http", spec["components"]["securitySchemes"]["HTTPBearer"]["type"])
        self.assertEqual("bearer", spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"])


if __name__ == "__main__":
    unittest.main()
