"""Local reference for proposed versus approved purpose-scoped memory.

Memory is NOT an entitlement, mandate, screening result, balance or approval.
The policy engine never imports this store. Retrieval rechecks source access.
"""
from __future__ import annotations

import json
import uuid

from .model import GuardError, Identity
from .policy import row_or_deny
from .store import Store


class MemoryService:
    def __init__(self, store: Store):
        self.store = store
        with store.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS memory_sources(tenant TEXT, id TEXT, readers TEXT,
              active INTEGER, version INTEGER, PRIMARY KEY(tenant,id));
            CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY, tenant TEXT, principal TEXT,
              purpose TEXT, fact TEXT, source TEXT, source_version INTEGER, status TEXT,
              expires INTEGER, legal_hold INTEGER DEFAULT 0);
            """)

    def _scope(self, identity, scope):
        if identity.expires_at is not None and identity.expires_at <= self.store.clock.now():
            raise GuardError("IDENTITY_CONTEXT_EXPIRED", 401)
        if scope not in identity.scopes:
            raise GuardError("MEMORY_SCOPE_DENIED")

    def _source(self, db, identity, source_id, operation="memory.read"):
        row = db.execute("SELECT * FROM memory_sources WHERE tenant=? AND id=?",
                         (identity.tenant, source_id)).fetchone()
        user = row_or_deny(db, "principals", identity.tenant, identity.principal)
        if identity.agent is not None:
            agent = row_or_deny(db, "agents", identity.tenant, identity.agent)
            if not agent["active"] or operation not in json.loads(agent["operations"]):
                raise GuardError("MEMORY_SOURCE_ACCESS_DENIED")
        if not user["active"] or not row or not row["active"] or identity.principal not in json.loads(row["readers"]):
            raise GuardError("MEMORY_SOURCE_ACCESS_DENIED")
        return row

    def propose(self, identity: Identity, purpose: str, fact: str, source_id: str, ttl: int = 300) -> str:
        self._scope(identity, "memory:write")
        if purpose != "service-preference":
            raise GuardError("MEMORY_SCOPE_OR_PURPOSE_DENIED")
        if not isinstance(fact, str) or not 1 <= len(fact) <= 512 or not 0 < ttl <= 600:
            raise GuardError("INVALID_MEMORY", 400)
        with self.store.transaction() as db:
            source = self._source(db, identity, source_id, "memory.write")
            memory_id = str(uuid.uuid4())
            db.execute("INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,0)",
                       (memory_id, identity.tenant, identity.principal, purpose, fact,
                        source_id, source["version"], "PROPOSED", self.store.clock.now() + ttl))
            self.store.audit(db, {"event": "memory.proposed", "tenant": identity.tenant,
                                  "principal": identity.principal, "memory_id": memory_id})
        return memory_id

    def approve(self, steward: Identity, memory_id: str):
        self._scope(steward, "memory:steward")
        if steward.agent is not None or "memory:steward" not in steward.scopes:
            raise GuardError("HUMAN_MEMORY_STEWARD_REQUIRED")
        with self.store.transaction() as db:
            user = row_or_deny(db, "principals", steward.tenant, steward.principal)
            # Demonstration directory role, not an agent-supplied role claim.
            if not user["active"] or not user["control_admin"]:
                raise GuardError("MEMORY_STEWARD_ENTITLEMENT")
            row = db.execute("SELECT * FROM memories WHERE id=? AND tenant=?", (memory_id, steward.tenant)).fetchone()
            if not row or row["status"] != "PROPOSED" or row["expires"] <= self.store.clock.now():
                raise GuardError("MEMORY_NOT_APPROVABLE", 409)
            db.execute("UPDATE memories SET status='APPROVED' WHERE id=?", (memory_id,))
            self.store.audit(db, {"event": "memory.approved", "tenant": steward.tenant,
                                  "principal": steward.principal, "memory_id": memory_id})

    def retrieve(self, identity: Identity, purpose: str) -> list[dict]:
        self._scope(identity, "memory:read")
        if "memory:read" not in identity.scopes:
            raise GuardError("MEMORY_READ_SCOPE")
        result = []
        with self.store.transaction() as db:
            rows = db.execute("SELECT * FROM memories WHERE tenant=? AND principal=? AND purpose=? "
                              "AND status='APPROVED' AND expires>?",
                              (identity.tenant, identity.principal, purpose, self.store.clock.now())).fetchall()
            for row in rows:
                try:
                    source = self._source(db, identity, row["source"])
                except GuardError:
                    continue
                if source["version"] != row["source_version"]:
                    continue
                result.append({"memory_id": row["id"], "fact": row["fact"], "source": row["source"],
                               "source_version": row["source_version"], "trust": "untrusted-context-data"})
            self.store.audit(db, {"event": "memory.retrieved", "tenant": identity.tenant,
                                  "principal": identity.principal, "count": len(result)})
        return result

    def restrict_or_delete(self, steward: Identity, memory_id: str):
        self._scope(steward, "memory:steward")
        if steward.agent is not None or "memory:steward" not in steward.scopes:
            raise GuardError("HUMAN_MEMORY_STEWARD_REQUIRED")
        with self.store.transaction() as db:
            user = row_or_deny(db, "principals", steward.tenant, steward.principal)
            if not user["active"] or not user["control_admin"]:
                raise GuardError("MEMORY_STEWARD_ENTITLEMENT")
            row = db.execute("SELECT * FROM memories WHERE id=? AND tenant=?", (memory_id, steward.tenant)).fetchone()
            if not row:
                raise GuardError("RESOURCE_OR_AUTHORITY_NOT_AVAILABLE", 404)
            if row["legal_hold"]:
                # Preserve held evidence under restricted access; do not claim erasure.
                db.execute("UPDATE memories SET status='RESTRICTED_HELD' WHERE id=?", (memory_id,))
            else:
                db.execute("UPDATE memories SET status='TOMBSTONED',fact='' WHERE id=?", (memory_id,))
            self.store.audit(db, {"event": "memory.restricted_or_tombstoned", "tenant": steward.tenant,
                                  "principal": steward.principal, "memory_id": memory_id,
                                  "held": bool(row["legal_hold"])})
