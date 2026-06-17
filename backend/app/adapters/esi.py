import base64
import datetime
import logging
import time
from typing import Optional
from urllib.parse import urlencode
import requests
from jose import jwt
from jose.exceptions import JWTError

from app.core import config, crypto

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_session = requests.Session()
_session.headers.update({"User-Agent": config.ESI_USER_AGENT})


# OAuth2 token endpoint

def _basic_auth_header() -> dict:
    raw = f"{config.ESI_CLIENT_ID}:{config.ESI_CLIENT_SECRET}".encode()
    return {
        "Authorization": "Basic " + base64.b64encode(raw).decode(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": "login.eveonline.com",
    }


def authorize_url(state: str) -> str:
    """Build the EVE SSO login URL the browser is redirected to."""
    params = {
        "response_type": "code",
        "redirect_uri": config.ESI_CALLBACK_URL,
        "client_id": config.ESI_CLIENT_ID,
        "scope": " ".join(config.ESI_SCOPES),
        "state": state,
    }
    return f"{config.ESI_AUTHORIZE_URL}?{urlencode(params)}"


def _token_request(payload: dict) -> dict:
    resp = _session.post(
        config.ESI_TOKEN_URL,
        data=urlencode(payload),
        headers=_basic_auth_header(),
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"SSO token request failed ({resp.status_code}): {resp.text}")
    return resp.json()


def exchange_code(code: str) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    return _token_request({"grant_type": "authorization_code", "code": code})


def refresh(refresh_token: str) -> dict:
    """Exchange a refresh token for a fresh access token (and a rotated refresh token)."""
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


# Access-token (JWT) verification against the EVE SSO JWKS

_jwks_cache: dict = {"keys": None, "ts": 0.0}
_JWKS_TTL = 3600


def _jwks() -> list:
    now = time.time()
    if _jwks_cache["keys"] is not None and now - _jwks_cache["ts"] < _JWKS_TTL:
        return _jwks_cache["keys"]
    resp = _session.get(config.ESI_JWKS_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    _jwks_cache["keys"] = keys
    _jwks_cache["ts"] = now
    return keys


def verify_access_token(token: str) -> dict:
    """
    Verify an ESI access-token JWT (signature, expiry, audience) and return its
    claims. Issuer is checked manually since CCP uses both the bare host and the
    https form.
    """
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        key = next((k for k in _jwks() if k.get("kid") == kid), None)
        if key is None:
            raise RuntimeError("no matching JWKS key for token")
        claims = jwt.decode(
            token,
            key,
            algorithms=[key.get("alg", "RS256")],
            audience=config.ESI_CLIENT_ID,
            options={"verify_iss": False},
        )
    except JWTError as exc:
        raise RuntimeError(f"invalid ESI access token: {exc}")

    iss = claims.get("iss")
    if iss not in config.ESI_TOKEN_ISSUERS:
        raise RuntimeError(f"unexpected token issuer: {iss}")
    return claims


def parse_character_claims(claims: dict) -> dict:
    """Pull the bits we store from verified token claims."""
    sub = claims.get("sub", "")          # 'CHARACTER:EVE:<id>'
    character_id = int(sub.rsplit(":", 1)[-1]) if sub else None
    scp = claims.get("scp")
    scopes = " ".join(scp) if isinstance(scp, list) else (scp or "")
    return {
        "character_id": character_id,
        "character_name": claims.get("name"),
        "owner_hash": claims.get("owner"),
        "scopes": scopes,
    }


# ---------------------------------------------------------------------------
# Token lifecycle for a stored LinkedCharacter
# ---------------------------------------------------------------------------

def valid_access_token(db, char) -> str:
    """
    Return a usable access token for ``char``, refreshing (and persisting the
    rotated tokens) if the current one is missing or about to expire. Marks the
    character ``token_expired`` and raises on refresh failure.
    """
    now = datetime.datetime.utcnow()
    fresh_enough = (
        char.token_expires_at is not None
        and char.token_expires_at - now > datetime.timedelta(seconds=60)
    )
    if fresh_enough:
        tok = crypto.decrypt(char.access_token_enc)
        if tok:
            return tok

    refresh_tok = crypto.decrypt(char.refresh_token_enc)
    if not refresh_tok:
        char.status = "invalid"
        db.commit()
        raise RuntimeError("no refresh token stored for character")

    try:
        data = refresh(refresh_tok)
    except Exception as exc:
        char.status = "token_expired"
        char.updated_at = now
        db.commit()
        raise RuntimeError(f"token refresh failed: {exc}")

    store_tokens(char, data)
    char.status = "active"
    char.updated_at = now
    db.commit()
    return data["access_token"]


def store_tokens(char, data: dict) -> None:
    """Encrypt + write an OAuth token response onto a LinkedCharacter (no commit)."""
    char.access_token_enc = crypto.encrypt(data["access_token"])
    if data.get("refresh_token"):
        char.refresh_token_enc = crypto.encrypt(data["refresh_token"])
    expires_in = int(data.get("expires_in", 1200))
    char.token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)

# ESI data endpoints

def _esi_get(path: str, access_token: Optional[str] = None, params: Optional[dict] = None,
             paginate: bool = False):
    """GET an ESI resource. With paginate=True, follows X-Pages and concatenates lists."""
    url = f"{config.ESI_BASE_URL}{path}"
    headers = {"Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    base_params = {"datasource": "tranquility", **(params or {})}

    resp = _session.get(url, headers=headers, params=base_params, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    if not paginate:
        return data

    pages = int(resp.headers.get("X-Pages", 1))
    for page in range(2, pages + 1):
        r = _session.get(url, headers=headers, params={**base_params, "page": page}, timeout=_TIMEOUT)
        r.raise_for_status()
        data.extend(r.json())
    return data


def parse_dt(value: Optional[str]) -> Optional[datetime.datetime]:
    """Parse an ESI ISO-8601 timestamp ('...Z') into a naive UTC datetime."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def fetch_affiliation(character_id: int) -> dict:
    """Public corp/alliance affiliation for a character (no auth)."""
    resp = _session.post(
        f"{config.ESI_BASE_URL}/characters/affiliation/",
        params={"datasource": "tranquility"},
        json=[character_id],
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else {}


def fetch_wallet_balance(character_id: int, token: str) -> float:
    return _esi_get(f"/characters/{character_id}/wallet/", token)


def fetch_transactions(character_id: int, token: str) -> list:
    return _esi_get(f"/characters/{character_id}/wallet/transactions/", token)


def fetch_skills(character_id: int, token: str) -> dict:
    return _esi_get(f"/characters/{character_id}/skills/", token)


def fetch_assets(character_id: int, token: str) -> list:
    return _esi_get(f"/characters/{character_id}/assets/", token, paginate=True)


def fetch_contracts(character_id: int, token: str) -> list:
    return _esi_get(f"/characters/{character_id}/contracts/", token, paginate=True)


def fetch_industry_jobs(character_id: int, token: str) -> list:
    return _esi_get(
        f"/characters/{character_id}/industry/jobs/",
        token,
        params={"include_completed": "true"},
    )


def fetch_standings(character_id: int, token: str) -> list:
    """NPC standings (faction / npc_corp / agent) for the character."""
    return _esi_get(f"/characters/{character_id}/standings/", token)
