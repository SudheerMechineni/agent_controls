"""HTTP/ASGI adapter. No demo issuer or key endpoint is exposed.

No production server bootstrap is supplied: put a bank-approved FAPI/IAM
resource-server implementation and authenticated transport in front of this
port. The local in-memory test transport does not implement mTLS or DPoP.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from .model import Action, GuardError
from .runtime import Runtime


class ProposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: dict


class ExecuteBody(ProposeBody):
    grant: str = Field(max_length=16000)


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(title="CIB Agent Authority Local Reference", version="0.1.0")
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(GuardError)
    async def handle_guard(_request, e: GuardError):
        headers = {"Cache-Control": "no-store"}
        if e.status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse({"code": e.code}, status_code=e.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_request, _e):
        # Framework default errors can echo sensitive request input.
        return JSONResponse({"code": "INVALID_REQUEST"}, status_code=422,
                            headers={"Cache-Control": "no-store"})

    def authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise GuardError("BEARER_REQUIRED", 401)
        identity = runtime.identity(credentials.credentials)
        request.state.identity = identity
        return identity

    identity_dep = Depends(authenticate)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/live")
    def live():
        return {"status": "up", "deployment_profile": "local-reference-only"}

    @app.get("/ready")
    def ready():
        if not runtime.store.audit_available:
            raise GuardError("DURABLE_AUDIT_UNAVAILABLE", 503)
        return {"status": "ready-for-local-tests"}

    @app.post("/v1/proposals")
    def propose(body: ProposeBody, identity=identity_dep):
        return runtime.propose(identity, Action.parse(body.action))

    @app.post("/v1/proposals/{proposal_id}/approve")
    def approve(proposal_id: str, identity=identity_dep):
        return runtime.approve(identity, proposal_id)

    @app.post("/v1/proposals/{proposal_id}/authorize")
    def authorize(proposal_id: str, identity=identity_dep):
        return runtime.authorize(identity, proposal_id)

    @app.post("/v1/actions/execute")
    def execute(body: ExecuteBody, identity=identity_dep):
        return runtime.execute(identity, body.grant, Action.parse(body.action))

    @app.get("/v1/payments/by-idempotency-key/{key}")
    def status(key: str, identity=identity_dep):
        return runtime.payment_status(identity, key)

    @app.post("/v1/controls/agents/{agent_id}/suspend")
    def suspend(agent_id: str, identity=identity_dep):
        runtime.suspend_agent(identity, agent_id)
        return {"status": "SUSPENDED"}

    @app.post("/v1/controls/mandates/{mandate_id}/revoke")
    def revoke(mandate_id: str, identity=identity_dep):
        runtime.revoke_mandate(identity, mandate_id)
        return {"status": "REVOKED"}

    return app
