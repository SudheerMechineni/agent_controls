from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .model import Clock, GuardError, canonical, digest


SCHEMA = """
CREATE TABLE IF NOT EXISTS principals(tenant TEXT, id TEXT, active INTEGER, epoch INTEGER,
  permissions TEXT, approve_account TEXT, control_admin INTEGER DEFAULT 0, PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS agents(tenant TEXT, id TEXT, active INTEGER, epoch INTEGER,
  artifact_digest TEXT, operations TEXT, PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS accounts(tenant TEXT, id TEXT, currency TEXT, balance INTEGER,
  screened INTEGER, screening_expiry INTEGER, version INTEGER, PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS mandates(tenant TEXT, id TEXT, principal TEXT, agent TEXT,
  task TEXT, active INTEGER, epoch INTEGER, expires INTEGER, purpose TEXT,
  debit TEXT, beneficiary TEXT, per_action INTEGER, total_limit INTEGER, used INTEGER,
  PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, tenant TEXT, principal TEXT,
  agent TEXT, task TEXT, action TEXT, action_hash TEXT, approval TEXT);
CREATE TABLE IF NOT EXISTS grants(jti TEXT PRIMARY KEY, proposal_id TEXT, consumed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(tenant TEXT, idem TEXT, action_hash TEXT, grant_jti TEXT,
  result TEXT, debit TEXT, principal TEXT, agent TEXT, PRIMARY KEY(tenant,idem));
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT,
  tenant TEXT, account TEXT, currency TEXT, delta INTEGER);
CREATE TABLE IF NOT EXISTS audit_outbox(seq INTEGER PRIMARY KEY AUTOINCREMENT,
  previous_hash TEXT, event TEXT, event_hash TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path: str | Path, clock: Clock):
        self.path, self.clock = str(path), clock
        self.audit_available = True
        with self.connection() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO settings VALUES('policy_version','cib-local-0.1')")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def audit(self, db, event: dict):
        if not self.audit_available:
            raise GuardError("DURABLE_AUDIT_UNAVAILABLE", 503)
        forbidden = {"access_token", "grant_token", "prompt", "raw_output", "secret"}
        if forbidden.intersection(event):
            raise ValueError("sensitive audit fields")
        event = {"specversion": "1.0", "id": str(uuid.uuid4()),
                 "source": "urn:cib:local-reference", "type": "cib.authority.control.v1",
                 "time": datetime.fromtimestamp(self.clock.now(), timezone.utc).isoformat(),
                 "datacontenttype": "application/json", "data": event}
        row = db.execute("SELECT seq,event_hash FROM audit_outbox ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row["event_hash"] if row else "0" * 64
        seq = row["seq"] + 1 if row else 1
        event_hash = digest({"seq": seq, "previous_hash": previous, "event": event})
        db.execute("INSERT INTO audit_outbox(previous_hash,event,event_hash) VALUES(?,?,?)",
                   (previous, canonical(event), event_hash))

    def verify_chain(self, expected_head: str | None = None, expected_count: int | None = None) -> bool:
        previous = "0" * 64
        count = 0
        with self.connection() as db:
            for row in db.execute("SELECT * FROM audit_outbox ORDER BY seq"):
                count += 1
                if row["seq"] != count or row["previous_hash"] != previous:
                    return False
                h = digest({"seq": row["seq"], "previous_hash": previous,
                            "event": json.loads(row["event"])})
                if h != row["event_hash"]:
                    return False
                previous = h
        return ((expected_head is None or previous == expected_head)
                and (expected_count is None or count == expected_count))

    def checkpoint(self) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT seq,event_hash FROM audit_outbox ORDER BY seq DESC LIMIT 1").fetchone()
            return {"count": row["seq"] if row else 0,
                    "head": row["event_hash"] if row else "0" * 64}
