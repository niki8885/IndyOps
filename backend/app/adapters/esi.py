import base64
import datetime
from app.core.timeutil import utcnow
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
    now = utcnow()
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
    char.token_expires_at = utcnow() + datetime.timedelta(seconds=expires_in)

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


def fetch_corporation(corporation_id: int) -> dict:
    """Public corporation info (name, ticker, alliance…) — no auth required."""
    return _esi_get(f"/corporations/{corporation_id}/")


def fetch_alliance(alliance_id: int) -> dict:
    """Public alliance info (name, ticker…) — no auth required."""
    return _esi_get(f"/alliances/{alliance_id}/")


def resolve_names(ids: list) -> dict:
    """Bulk-resolve ids → ``{id: {"name", "category"}}`` via /universe/names/ (public)."""
    ids = [i for i in {int(x) for x in ids if x}]
    if not ids:
        return {}
    resp = _session.post(
        f"{config.ESI_BASE_URL}/universe/names/",
        params={"datasource": "tranquility"},
        json=ids,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return {r["id"]: {"name": r.get("name"), "category": r.get("category")} for r in resp.json()}


def fetch_market_prices() -> list:
    """CCP's market-wide adjusted/average price per type_id — public, no auth."""
    return _esi_get("/markets/prices/")


def fetch_location(character_id: int, token: str) -> dict:
    """Current location: ``{solar_system_id, station_id?, structure_id?}``."""
    return _esi_get(f"/characters/{character_id}/location/", token)


def fetch_ship(character_id: int, token: str) -> dict:
    """Current ship: ``{ship_type_id, ship_name, ship_item_id}``."""
    return _esi_get(f"/characters/{character_id}/ship/", token)


def fetch_online(character_id: int, token: str) -> dict:
    """Online status: ``{online, last_login, last_logout, logins}``."""
    return _esi_get(f"/characters/{character_id}/online/", token)


def fetch_implants(character_id: int, token: str) -> list:
    """Active (currently-plugged) implant type_ids."""
    return _esi_get(f"/characters/{character_id}/implants/", token)


def fetch_mining(character_id: int, token: str) -> list:
    """Character mining ledger (ESI keeps ~30 days): ``[{date, quantity, type_id, solar_system_id}]``."""
    return _esi_get(f"/characters/{character_id}/mining/", token, paginate=True)


def fetch_structure(structure_id: int, token: str) -> dict:
    """
    Resolve an Upwell structure (citadel/complex) to its name + solar system.
    Requires the ``esi-universe.read_structures.v1`` scope and docking access for
    the character; raises (403/404) otherwise — callers cache the failure.
    """
    return _esi_get(f"/universe/structures/{structure_id}/", token)


def fetch_wallet_balance(character_id: int, token: str) -> float:
    return _esi_get(f"/characters/{character_id}/wallet/", token)


def fetch_transactions(character_id: int, token: str) -> list:
    """Character wallet transactions. ESI returns only the ~2500 most-recent rows and
    pages backwards via a ``from_id`` cursor (NOT X-Pages, so ``paginate=True`` can't be
    used here) — we follow the cursor to capture the full window ESI exposes (~30 days).
    Sync upserts these, so retained buy history accumulates and sells can FIFO-match."""
    path = f"/characters/{character_id}/wallet/transactions/"
    out: list = []
    seen: set = set()
    from_id: Optional[int] = None
    for _ in range(40):                       # safety cap (~100k transactions)
        params = {"from_id": from_id} if from_id is not None else None
        page = _esi_get(path, token, params=params)
        if not page:
            break
        fresh = [t for t in page if t.get("transaction_id") not in seen]
        if not fresh:                         # ESI returned only rows we already have
            break
        out.extend(fresh)
        seen.update(t.get("transaction_id") for t in page)
        from_id = min(t.get("transaction_id") for t in page)
    return out


def fetch_skills(character_id: int, token: str) -> dict:
    return _esi_get(f"/characters/{character_id}/skills/", token)


def fetch_assets(character_id: int, token: str) -> list:
    return _esi_get(f"/characters/{character_id}/assets/", token, paginate=True)


def fetch_contracts(character_id: int, token: str) -> list:
    return _esi_get(f"/characters/{character_id}/contracts/", token, paginate=True)


def fetch_contract_items(character_id: int, contract_id: int, token: str) -> list:
    """Items inside one of the character's contracts (immutable once the contract is
    finished — fetched once and cached)."""
    return _esi_get(f"/characters/{character_id}/contracts/{contract_id}/items/", token)


def fetch_industry_jobs(character_id: int, token: str) -> list:
    return _esi_get(
        f"/characters/{character_id}/industry/jobs/",
        token,
        params={"include_completed": "true"},
    )


def fetch_standings(character_id: int, token: str) -> list:
    """NPC standings (faction / npc_corp / agent) for the character."""
    return _esi_get(f"/characters/{character_id}/standings/", token)


def fetch_blueprints(character_id: int, token: str) -> list:
    """Owned blueprints (BPOs and BPCs): ``[{item_id, type_id, location_id, location_flag,
    quantity, runs, material_efficiency, time_efficiency}]``. ``runs == -1`` and
    ``quantity == -1`` mark a BPO (original); ``quantity == -2`` marks a BPC (copy)."""
    return _esi_get(f"/characters/{character_id}/blueprints/", token, paginate=True)


def fetch_market_orders(character_id: int, token: str) -> list:
    """Character's currently-open market orders (buy + sell). Active only — closed
    orders are not returned. Each carries: order_id, type_id, region_id, location_id,
    range, is_buy_order, price, volume_total, volume_remain, min_volume, duration,
    issued, escrow."""
    return _esi_get(f"/characters/{character_id}/orders/", token)


def fetch_planets(character_id: int, token: str) -> list:
    """Character's planetary-interaction colonies: ``[{planet_id, solar_system_id,
    planet_type, owner_id, upgrade_level, num_pins, last_update}]``. One row per
    colonized planet; ``planet_type`` is a string (temperate/barren/oceanic/…).
    Requires the ``esi-planets.manage_planets.v1`` scope."""
    return _esi_get(f"/characters/{character_id}/planets/", token)


def fetch_planet_detail(character_id: int, planet_id: int, token: str) -> dict:
    """Full layout of one colony: ``{links, pins, routes}``. Each pin carries its
    ``type_id`` and (when applicable) ``extractor_details`` (product_type_id,
    cycle_time, qty_per_cycle, expiry_time on the pin), ``factory_details``,
    ``schematic_id`` and ``contents`` ([{type_id, amount}]) for storage pins."""
    return _esi_get(f"/characters/{character_id}/planets/{planet_id}/", token)


def fetch_wallet_journal(character_id: int, token: str) -> list:
    """Wallet journal (income/expense events incl. ``player_donation``). Paginated.
    Each entry carries: id, ref_type, amount, balance, date, first_party_id,
    second_party_id, reason/description."""
    return _esi_get(f"/characters/{character_id}/wallet/journal/", token, paginate=True)


def resolve_ids(names: list) -> dict:
    """Bulk-resolve names → ids by category via /universe/ids/ (public, no auth).
    Returns the raw payload keyed by category, e.g.
    ``{"corporations": [{"id": ..., "name": ...}], ...}``."""
    names = [n for n in names if n]
    if not names:
        return {}
    resp = _session.post(
        f"{config.ESI_BASE_URL}/universe/ids/",
        params={"datasource": "tranquility"},
        json=names,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()
