from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

ACCESS_TOKEN_ENV = "KALSHI_TEMPS_ACCESS_TOKEN"


@dataclass(frozen=True)
class AccessStatus:
    required: bool
    mode: str
    warning: str | None

    def as_dict(self) -> dict[str, object]:
        return {"required": self.required, "mode": self.mode, "warning": self.warning}


def configured_access_token() -> str | None:
    token = os.getenv(ACCESS_TOKEN_ENV)
    return token if token else None


def access_status() -> AccessStatus:
    if configured_access_token():
        return AccessStatus(required=True, mode="env-token", warning=None)
    return AccessStatus(
        required=False,
        mode="open-local-dev",
        warning="No KALSHI_TEMPS_ACCESS_TOKEN is set; local dashboard/API are open for development only.",
    )


def _request_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization") or ""
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value:
        return value.strip()
    return request.headers.get("x-access-token")


def is_protected_path(path: str) -> bool:
    return path == "/dashboard" or path.startswith("/api/")


async def access_gate(request: Request, call_next):
    expected = configured_access_token()
    if expected and is_protected_path(request.url.path):
        supplied = _request_token(request)
        if not supplied or not hmac.compare_digest(supplied, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "Access token required", "auth": access_status().as_dict()},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)
