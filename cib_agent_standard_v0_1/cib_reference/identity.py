from __future__ import annotations

import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .model import Clock, GuardError, Identity


class TokenCodec:
    """Local test issuer/validator using an established JOSE library.

    Do not substitute this for the bank authorization server, JWKS lifecycle,
    FAPI implementation, HSM service or sender-constraint enforcement.
    Separate codec instances represent separate signing trust domains.
    """

    def __init__(self, issuer: str, audience: str, token_type: str, clock: Clock, max_ttl: int):
        self.issuer, self.audience, self.token_type = issuer, audience, token_type
        self.clock, self.max_ttl = clock, max_ttl
        self._private = Ed25519PrivateKey.generate()
        self.public = self._private.public_key()
        self.kid = str(uuid.uuid4())

    def issue(self, claims: dict[str, Any], ttl: int | None = None) -> str:
        life = self.max_ttl if ttl is None else ttl
        if not 0 < life <= self.max_ttl:
            raise ValueError("invalid lifetime")
        now = self.clock.now()
        payload = dict(claims)
        payload.update(iss=self.issuer, aud=self.audience, iat=now, nbf=now,
                       exp=now + life, jti=str(uuid.uuid4()))
        return jwt.encode(payload, self._private, algorithm="EdDSA",
                          headers={"typ": self.token_type, "kid": self.kid})

    def verify(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or len(token) > 16000:
            raise GuardError("INVALID_TOKEN", 401)
        try:
            header = jwt.get_unverified_header(token)
            if header.get("typ") != self.token_type or header.get("kid") != self.kid:
                raise ValueError("wrong token class or key")
            # Untrusted header URLs are never followed; algorithm is allowlisted.
            if any(k in header for k in ["jku", "x5u", "jwk", "crit"]):
                raise ValueError("unsupported header")
            result = jwt.decode(token, self.public, algorithms=["EdDSA"],
                                issuer=self.issuer, audience=self.audience,
                                options={"require": ["iss", "aud", "sub", "iat", "nbf", "exp", "jti"],
                                         "verify_exp": False, "verify_iat": False,
                                         "verify_nbf": False})
            for name in ["iat", "nbf", "exp"]:
                if type(result[name]) is not int:
                    raise ValueError("invalid timestamp")
            now = self.clock.now()
            if (result["iat"] > now or result["nbf"] > now or result["exp"] <= now
                    or result["exp"] - result["iat"] > self.max_ttl
                    or result["exp"] <= result["iat"]):
                raise ValueError("invalid lifetime")
            if not isinstance(result["sub"], str) or not isinstance(result["jti"], str):
                raise ValueError("invalid subject")
            return result
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as e:
            raise GuardError("INVALID_OR_EXPIRED_TOKEN", 401) from e


def verified_identity(codec: TokenCodec, token: str) -> Identity:
    p = codec.verify(token)
    try:
        actor = p.get("act")
        if actor is not None and (not isinstance(actor, dict) or set(actor) != {"sub"}):
            raise ValueError("demo supports one actor hop only")
        values = [p["tenant"], p["sub"], p["task"]]
        if actor is not None:
            values.append(actor["sub"])
        if not all(isinstance(v, str) and 0 < len(v) <= 96 for v in values):
            raise ValueError("invalid identity fields")
        if not isinstance(p["scope"], str):
            raise ValueError("invalid scope")
        return Identity(p["tenant"], p["sub"], actor["sub"] if actor else None,
                        p["task"], frozenset(p["scope"].split()), p["exp"])
    except (KeyError, ValueError, TypeError) as e:
        raise GuardError("INVALID_IDENTITY_CONTEXT", 401) from e
