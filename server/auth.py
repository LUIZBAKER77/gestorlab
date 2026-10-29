"""Sessões da equipe (tokens assinados) e limitação de tentativas de login."""
import base64
import hashlib
import hmac
import time
from collections import defaultdict
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Query, Request

import database
from config import CONFIG

_SECRET = CONFIG["secret_key"].encode()


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"],
            "must_change": bool(user["must_change"])}


def _fingerprint(user: Dict[str, Any]) -> str:
    # Parte do hash da senha entra no token: trocar a senha invalida as sessões antigas.
    return user["password_hash"][:16]


def create_access_token(user: Dict[str, Any], remember: bool = True) -> str:
    # Lembrar: 30 dias. Senão: 12 horas.
    duration = 30 * 24 * 3600 if remember else 12 * 3600
    payload = f"{int(time.time() + duration)}:{user['id']}:{_fingerprint(user)}"
    sig = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def verify_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Devolve o usuário (público) se o token for válido, a conta estiver ativa e a senha não mudou."""
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        expires_at, user_id, fingerprint, sig = raw.split(":")
        if time.time() > int(expires_at):
            return None
        expected = hmac.new(_SECRET, f"{expires_at}:{user_id}:{fingerprint}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        user = database.get_user_auth(int(user_id))
    except Exception:
        return None
    if not user or not user["active"] or not hmac.compare_digest(fingerprint, _fingerprint(user)):
        return None
    return public_user(user)


def _token_from(request: Request, token: Optional[str]) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return token


def require_auth_any(request: Request, token: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Usuário logado (mesmo que ainda precise trocar a senha provisória)."""
    user = verify_token(_token_from(request, token))
    if not user:
        raise HTTPException(status_code=401, detail="Não autorizado")
    return user


def require_auth(user: Dict[str, Any] = Depends(require_auth_any)) -> Dict[str, Any]:
    """Usuário logado que já trocou a senha provisória."""
    if user["must_change"]:
        raise HTTPException(status_code=403, detail="Troque a senha provisória para continuar.")
    return user


def require_admin(user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Só administradores podem fazer isto.")
    return user


def check_agent_key(provided: Optional[str]) -> bool:
    """Sem agent_key configurada, qualquer agente é aceito (modo zero-config)."""
    expected = str(CONFIG.get("agent_key") or "")
    if not expected:
        return True
    return hmac.compare_digest((provided or "").encode(), expected.encode())


class RateLimiter:
    """Bloqueia uma chave (IP) por `window` segundos após `max_fails` falhas seguidas."""

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
