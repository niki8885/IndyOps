"""Offline unit tests for the HTTP-issuing pieces of ``app.adapters.esi``.

The pure helpers (claim parsing, dt parsing, crypto) are already covered by
``tests/test_esi.py``; this file fills the network-facing gaps. The shared
module-level ``esi._session`` is monkeypatched with a tiny fake so no request
leaves the process. ``_jwks`` cache is reset where relevant.
"""
import types

import pytest

from app.adapters import esi


class FakeResponse:
    def __init__(self, json_data=None, *, status_code=200, text="", headers=None, raise_exc=None):
        self._json = json_data
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._raise_exc = raise_exc

    def json(self):
        return self._json

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc


class FakeSession:
    """Records get/post calls and returns queued responses (or a callable)."""

    def __init__(self):
        self.headers = {}
        self.get_calls = []
        self.post_calls = []
        self._get_resp = None
        self._post_resp = None

    def get(self, url, **kw):
        self.get_calls.append((url, kw))
        r = self._get_resp
        return r(url, **kw) if callable(r) else r

    def post(self, url, **kw):
        self.post_calls.append((url, kw))
        r = self._post_resp
        return r(url, **kw) if callable(r) else r


@pytest.fixture
def fake_session(monkeypatch):
    fs = FakeSession()
    monkeypatch.setattr(esi, "_session", fs)
    return fs


@pytest.fixture(autouse=True)
def _reset_jwks():
    esi._jwks_cache.update({"keys": None, "ts": 0.0})
    yield


# ── authorize_url (pure, but uncovered) ──────────────────────────────────────

def test_authorize_url_contains_params():
    url = esi.authorize_url("mystate")
    assert url.startswith(esi.config.ESI_AUTHORIZE_URL)
    assert "response_type=code" in url
    assert "state=mystate" in url
    assert "client_id=" in url


# ── _token_request / exchange_code / refresh ─────────────────────────────────

def test_exchange_code_happy_path(fake_session):
    fake_session._post_resp = FakeResponse(
        {"access_token": "AT", "refresh_token": "RT", "expires_in": 1200})
    out = esi.exchange_code("authcode")
    assert out["access_token"] == "AT"
    url, kw = fake_session.post_calls[0]
    assert url == esi.config.ESI_TOKEN_URL
    assert "authorization_code" in kw["data"]


def test_refresh_happy_path(fake_session):
    fake_session._post_resp = FakeResponse({"access_token": "AT2"})
    out = esi.refresh("RT")
    assert out["access_token"] == "AT2"
    _, kw = fake_session.post_calls[0]
    assert "refresh_token" in kw["data"]


def test_token_request_raises_on_non_200(fake_session):
    fake_session._post_resp = FakeResponse(status_code=400, text="bad_grant")
    with pytest.raises(RuntimeError) as ei:
        esi.exchange_code("x")
    assert "400" in str(ei.value)
    assert "bad_grant" in str(ei.value)


# ── _jwks (cached fetch) ─────────────────────────────────────────────────────

def test_jwks_fetches_and_caches(fake_session):
    fake_session._get_resp = FakeResponse({"keys": [{"kid": "k1"}]})
    assert esi._jwks() == [{"kid": "k1"}]
    # second call served from cache
    assert esi._jwks() == [{"kid": "k1"}]
    assert len(fake_session.get_calls) == 1


# ── verify_access_token (error branches; no real RSA needed) ─────────────────

def test_verify_access_token_no_matching_key(fake_session, monkeypatch):
    fake_session._get_resp = FakeResponse({"keys": [{"kid": "other"}]})
    monkeypatch.setattr(esi.jwt, "get_unverified_header", lambda t: {"kid": "missing"})
    with pytest.raises(RuntimeError) as ei:
        esi.verify_access_token("token")
    assert "no matching JWKS key" in str(ei.value)


def test_verify_access_token_jwt_error_wrapped(fake_session, monkeypatch):
    fake_session._get_resp = FakeResponse({"keys": [{"kid": "k1"}]})
    monkeypatch.setattr(esi.jwt, "get_unverified_header", lambda t: {"kid": "k1"})

    def boom(*a, **k):
        raise esi.JWTError("bad sig")

    monkeypatch.setattr(esi.jwt, "decode", boom)
    with pytest.raises(RuntimeError) as ei:
        esi.verify_access_token("token")
    assert "invalid ESI access token" in str(ei.value)


def test_verify_access_token_unexpected_issuer(fake_session, monkeypatch):
    fake_session._get_resp = FakeResponse({"keys": [{"kid": "k1"}]})
    monkeypatch.setattr(esi.jwt, "get_unverified_header", lambda t: {"kid": "k1"})
    monkeypatch.setattr(esi.jwt, "decode", lambda *a, **k: {"iss": "https://evil.example"})
    with pytest.raises(RuntimeError) as ei:
        esi.verify_access_token("token")
    assert "unexpected token issuer" in str(ei.value)


def test_verify_access_token_accepts_valid_issuer(fake_session, monkeypatch):
    good_iss = esi.config.ESI_TOKEN_ISSUERS[0]
    fake_session._get_resp = FakeResponse({"keys": [{"kid": "k1"}]})
    monkeypatch.setattr(esi.jwt, "get_unverified_header", lambda t: {"kid": "k1"})
    monkeypatch.setattr(esi.jwt, "decode",
                        lambda *a, **k: {"iss": good_iss, "sub": "CHARACTER:EVE:1"})
    claims = esi.verify_access_token("token")
    assert claims["iss"] == good_iss


# ── _esi_get (single + paginated) via the public fetchers ────────────────────

def test_fetch_corporation_unauthed_get(fake_session):
    fake_session._get_resp = FakeResponse({"name": "Test Corp", "ticker": "TST"})
    out = esi.fetch_corporation(98000001)
    assert out["name"] == "Test Corp"
    url, kw = fake_session.get_calls[0]
    assert url.endswith("/corporations/98000001/")
    assert "Authorization" not in kw["headers"]
    assert kw["params"]["datasource"] == "tranquility"


def test_fetch_alliance_get(fake_session):
    fake_session._get_resp = FakeResponse({"name": "Test Alliance"})
    assert esi.fetch_alliance(99000001)["name"] == "Test Alliance"


def test_esi_get_with_token_sets_auth_header(fake_session):
    fake_session._get_resp = FakeResponse({"solar_system_id": 30000142})
    esi.fetch_location(123, "ABC-TOKEN")
    _, kw = fake_session.get_calls[0]
    assert kw["headers"]["Authorization"] == "Bearer ABC-TOKEN"


def test_fetch_assets_paginated(fake_session):
    def resp(url, **kw):
        page = kw["params"].get("page")
        if page is None:
            return FakeResponse([{"item_id": 1}], headers={"X-Pages": "2"})
        return FakeResponse([{"item_id": 2}])

    fake_session._get_resp = resp
    out = esi.fetch_assets(123, "tok")
    assert [a["item_id"] for a in out] == [1, 2]
    assert len(fake_session.get_calls) == 2


def test_fetch_mining_single_page(fake_session):
    # X-Pages defaults to 1 → no extra request
    fake_session._get_resp = FakeResponse([{"type_id": 1230, "quantity": 100}])
    out = esi.fetch_mining(123, "tok")
    assert out[0]["quantity"] == 100
    assert len(fake_session.get_calls) == 1


def test_esi_get_raises_on_http_error(fake_session):
    fake_session._get_resp = FakeResponse(raise_exc=RuntimeError("403"))
    with pytest.raises(RuntimeError):
        esi.fetch_skills(123, "tok")


def test_fetch_industry_jobs_includes_completed(fake_session):
    fake_session._get_resp = FakeResponse([{"job_id": 1}])
    esi.fetch_industry_jobs(123, "tok")
    _, kw = fake_session.get_calls[0]
    assert kw["params"]["include_completed"] == "true"


# ── POST endpoints: affiliation + name resolution ────────────────────────────

def test_fetch_affiliation_returns_first_row(fake_session):
    fake_session._post_resp = FakeResponse([{"character_id": 7, "corporation_id": 98}])
    out = esi.fetch_affiliation(7)
    assert out["corporation_id"] == 98


def test_fetch_affiliation_empty_rows(fake_session):
    fake_session._post_resp = FakeResponse([])
    assert esi.fetch_affiliation(7) == {}


def test_resolve_names_happy_path(fake_session):
    fake_session._post_resp = FakeResponse([
        {"id": 34, "name": "Tritanium", "category": "inventory_type"},
    ])
    out = esi.resolve_names([34, 34, None, 0])  # dedup + drop falsy
    assert out == {34: {"name": "Tritanium", "category": "inventory_type"}}
    _, kw = fake_session.post_calls[0]
    assert kw["json"] == [34]


def test_resolve_names_empty_short_circuits(fake_session):
    fake_session._post_resp = FakeResponse(
        raise_exc=AssertionError("should not POST for empty ids"))
    assert esi.resolve_names([None, 0]) == {}
    assert fake_session.post_calls == []


def test_fetch_market_prices(fake_session):
    fake_session._get_resp = FakeResponse([{"type_id": 34, "adjusted_price": 5.0}])
    out = esi.fetch_market_prices()
    assert out[0]["type_id"] == 34


# ── store_tokens (no HTTP, but on the token lifecycle path) ──────────────────

def test_store_tokens_encrypts_and_sets_expiry(monkeypatch):
    char = types.SimpleNamespace(access_token_enc=None, refresh_token_enc="OLD",
                                 token_expires_at=None)
    monkeypatch.setattr(esi.crypto, "encrypt", lambda v: f"enc({v})")
    esi.store_tokens(char, {"access_token": "AT", "refresh_token": "RT", "expires_in": 600})
    assert char.access_token_enc == "enc(AT)"
    assert char.refresh_token_enc == "enc(RT)"
    assert char.token_expires_at is not None


def test_store_tokens_keeps_refresh_when_absent(monkeypatch):
    char = types.SimpleNamespace(access_token_enc=None, refresh_token_enc="OLD",
                                 token_expires_at=None)
    monkeypatch.setattr(esi.crypto, "encrypt", lambda v: f"enc({v})")
    esi.store_tokens(char, {"access_token": "AT"})  # no refresh_token, no expires_in
    assert char.access_token_enc == "enc(AT)"
    assert char.refresh_token_enc == "OLD"  # unchanged
