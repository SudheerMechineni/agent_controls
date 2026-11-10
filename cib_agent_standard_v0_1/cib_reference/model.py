from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Any


class GuardError(Exception):
    def __init__(self, code: str, status: int = 403):
        super().__init__(code)
        self.code, self.status = code, status


class OutcomeUnknown(GuardError):
    def __init__(self):
        super().__init__("OUTCOME_UNKNOWN_QUERY_ORIGINAL_KEY", 503)


def canonical(value: Any) -> str:
    """Local CIB demo c14n-v1: fixed ASCII keys/IDs, integers, no floats.

    Not an implementation of RFC 8785. Production cross-language contracts
    need an approved canonicalization profile and shared conformance vectors.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Clock:
    def now(self) -> int:
        return int(time.time())

    def business_date(self) -> str:
        # Demonstration has one UTC value-date convention. Production must
        # use the product/legal-entity calendar and market cut-off service.
        return datetime.fromtimestamp(self.now(), timezone.utc).date().isoformat()


class ManualClock(Clock):
    def __init__(self, now: int | None = None):
        # Stable synthetic time makes expiry/date tests reproducible across
        # midnight and future runs. Runtime defaults to real Clock, not this.
        self.value = int(datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp()) if now is None else now

    def now(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += seconds


@dataclass(frozen=True)
class Identity:
    tenant: str
    principal: str
    agent: str | None
    task: str
    scopes: frozenset[str]
    expires_at: int | None = None


@dataclass(frozen=True)
class Action:
    operation: str
    debit_account: str
    credit_account: str
    amount_minor: int
    currency: str
    value_date: str
    purpose: str
    mandate_id: str
    idempotency_key: str
    schema_version: str = "cib.action.v1"

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "Action":
        if not isinstance(data, dict):
            raise GuardError("INVALID_ACTION", 400)
        allowed = {f.name for f in fields(cls)}
        required = allowed - {"schema_version"}
        if set(data) - allowed or required - set(data):
            raise GuardError("UNKNOWN_OR_MISSING_ACTION_FIELDS", 400)
        for key, value in data.items():
            if key == "amount_minor":
                if type(value) is not int or not 0 <= value <= 10**12:
                    raise GuardError("INVALID_AMOUNT_MINOR", 400)
            elif not isinstance(value, str) or len(value) > 128:
                raise GuardError("INVALID_ACTION_FIELD", 400)
        obj = cls(**data)
        identifiers = [obj.debit_account, obj.purpose, obj.mandate_id, obj.idempotency_key]
        if obj.credit_account:
            identifiers.append(obj.credit_account)
        if any(not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", x) for x in identifiers):
            raise GuardError("INVALID_IDENTIFIER", 400)
        if obj.schema_version != "cib.action.v1" or obj.currency != "SGD":
            raise GuardError("UNSUPPORTED_SCHEMA_OR_CURRENCY", 400)
        try:
            datetime.strptime(obj.value_date, "%Y-%m-%d")
        except ValueError as e:
            raise GuardError("INVALID_VALUE_DATE", 400) from e
        if obj.operation == "payments.internal-transfer":
            if obj.amount_minor <= 0 or not obj.credit_account or obj.credit_account == obj.debit_account:
                raise GuardError("INVALID_TRANSFER", 400)
        elif obj.operation == "accounts.balance":
            if obj.amount_minor != 0 or obj.credit_account:
                raise GuardError("INVALID_BALANCE_REQUEST", 400)
        else:
            raise GuardError("UNREGISTERED_OPERATION", 400)
        return obj

    def data(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def hash(self) -> str:
        return digest({"profile": "cib-action-c14n-v1", "action": self.data()})
