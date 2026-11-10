"""Regenerate local demo contracts/examples; no external calls or keys saved."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cib_reference.api import create_app
from cib_reference.fixtures import agent_token, human_token, seed, transfer
from cib_reference.model import ManualClock
from cib_reference.runtime import Runtime


def write(relative, value):
    (ROOT / relative).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


ident = {"type": "string", "pattern": "^[A-Za-z0-9_.:-]{1,96}$", "maxLength": 96}
action_schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:cib:local-reference:action:v1",
    "title": "CIB local reference action — SGD only",
    "type": "object", "additionalProperties": False,
    "required": ["operation", "debit_account", "credit_account", "amount_minor", "currency",
                 "value_date", "purpose", "mandate_id", "idempotency_key"],
    "properties": {
        "operation": {"enum": ["accounts.balance", "payments.internal-transfer"]},
        "debit_account": ident,
        "credit_account": {"type": "string", "pattern": "^$|^[A-Za-z0-9_.:-]{1,96}$", "maxLength": 96},
        "amount_minor": {"type": "integer", "minimum": 0, "maximum": 10**12},
        "currency": {"const": "SGD"},
        "value_date": {"type": "string", "format": "date"},
        "purpose": ident, "mandate_id": ident, "idempotency_key": ident,
        "schema_version": {"const": "cib.action.v1", "default": "cib.action.v1"},
    },
    "allOf": [
        {"if": {"properties": {"operation": {"const": "accounts.balance"}}},
         "then": {"properties": {"amount_minor": {"const": 0}, "credit_account": {"const": ""}}}},
        {"if": {"properties": {"operation": {"const": "payments.internal-transfer"}}},
         "then": {"properties": {"amount_minor": {"minimum": 1}, "credit_account": {"minLength": 1}}}},
    ],
    "description": "Domain additionally requires different debit/credit accounts, current business date, "
                   "registered resources, live mandate/entitlements, screening, approval, funds and limits. "
                   "Schema validity alone never establishes authority."
}

event_schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:cib:local-reference:authority-event:v1",
    "title": "CIB local control evidence envelope",
    "type": "object", "additionalProperties": False,
    "required": ["specversion", "id", "source", "type", "time", "datacontenttype", "data"],
    "properties": {
        "specversion": {"const": "1.0"}, "id": {"type": "string", "format": "uuid"},
        "source": {"type": "string", "format": "uri"},
        "type": {"const": "cib.authority.control.v1"},
        "time": {"type": "string", "format": "date-time"},
        "datacontenttype": {"const": "application/json"},
        "data": {"type": "object", "required": ["event", "tenant"],
                 "properties": {"event": {"type": "string"}, "tenant": {"type": "string"}},
                 "not": {"anyOf": [{"required": [x]} for x in
                                   ["access_token", "grant_token", "prompt", "raw_output", "secret"]]}}
    },
    "description": "Local evidence fields are intentionally references/hashes. Production defines a fuller "
                   "governed bank evidence schema and independent protected record custody."
}

write("contracts/action.schema.json", action_schema)
write("contracts/authority-event.schema.json", event_schema)

with tempfile.TemporaryDirectory() as temp:
    runtime = Runtime(Path(temp) / "contract.db", ManualClock())
    seed(runtime)
    action = transfer(runtime)
    actor = runtime.identity(agent_token(runtime))
    checker = runtime.identity(human_token(runtime))
    pid = runtime.propose(actor, action)["proposal_id"]
    runtime.approve(checker, pid)
    runtime.execute(actor, runtime.authorize(actor, pid)["grant"], action)
    with runtime.store.connection() as db:
        event = json.loads(db.execute("SELECT event FROM audit_outbox ORDER BY seq DESC LIMIT 1").fetchone()[0])
    write("examples/action.json", action.data())
    write("examples/authority-event.json", event)
    spec = create_app(runtime).openapi()
    # Reflect the lower-layer strict parser in the published adapter contract.
    # HTTP wrapper/auth contracts are generated directly by FastAPI.
    embedded = {k: v for k, v in action_schema.items() if k not in {"$schema", "$id"}}
    spec["components"]["schemas"]["Action"] = embedded
    for name in ["ProposeBody", "ExecuteBody"]:
        spec["components"]["schemas"][name]["properties"]["action"] = {"$ref": "#/components/schemas/Action"}
    spec["info"]["description"] = (
        "Executable local synthetic-data reference only. Bearer test tokens are not FAPI/mTLS/DPoP. "
        "No production issuer or server bootstrap is exposed. Action schema includes parser constraints; "
        "domain checks remain mandatory."
    )
    write("contracts/authority.openapi.json", spec)

print("Generated action schema, event schema, OpenAPI and synthetic examples.")
