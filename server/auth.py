"""Tokens de sessão do professor e limitação de tentativas de login."""
import base64
import hashlib
import hmac
import time
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Query, Request

from config import CONFIG

def _signing_key() -> bytes:
    # A senha do painel entra na chave: ao trocá-la, todas as sessões antigas deixam de valer.
    pwd_digest = hashlib.sha256(str(CONFIG["admin_password"]).encode()).hexdigest()
    return f"{CONFIG['secret_key']}:{pwd_digest}".encode()


def check_admin_password(password: str) -> bool:
    return hmac.compare_digest(password.encode(), str(CONFIG["admin_password"]).encode())


def create_access_token(remember: bool = True) -> str:
    # Lembrar: 365 dias. Senão: 24 horas.
    duration = 365 * 24 * 3600 if remember else 24 * 3600
    payload = f"{int(time.time() + duration)}:teacher"
    sig = hmac.new(_signing_key(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def verify_token(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        expires_at, role, sig = raw.split(":")
        if time.time() > int(expires_at):
            return False
        expected = hmac.new(_signing_key(), f"{expires_at}:{role}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def require_auth(request: Request, token: Optional[str] = Query(None)) -> None:
    """Dependência FastAPI: aceita 'Authorization: Bearer <token>' ou ?token=."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Não autorizado")


def check_agent_key(provided: Optional[str]) -> bool:
    """Sem agent_key configurada, qualquer agente é aceito (modo zero-config)."""
    expected = str(CONFIG.get("agent_key") or "")
    if not expected:
        return True
    return hmac.compare_digest((provided or "").encode(), expected.encode())


class RateLimiter:
    """Bloqueia um IP por `window` segundos após `max_fails` falhas seguidas."""

    def __init__(self, max_fails: int = 5, window: int = 60):
        self.max_fails = max_fails
        self.window = window
        self._fails = defaultdict(list)

    def _recent(self, key: str) -> list:
        now = time.time()
        recent = [t for t in self._fails[key] if now - t < self.window]
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        return recent

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_fails

    def fail(self, key: str) -> None:
        self._fails[key].append(time.time())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)
