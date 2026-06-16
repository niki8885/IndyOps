"""Offline unit tests for the ESI integration (IO-24).

Network paths (token exchange, JWKS verify, ESI fetch) are not exercised here —
only the pure pieces: token encryption, the SSO state round-trip, claim parsing,
timestamp parsing and the ESI-json → row mappers.
"""
import datetime

from app.adapters import esi
from app.api import characters_router as cr
from app.core import crypto
from app.tasks import update_esi


def test_crypto_round_trip():
    token = "abc123.refresh-token_value-with-symbols/+="
    enc = crypto.encrypt(token)
    assert enc != token                 # actually encrypted
    assert crypto.decrypt(enc) == token


def test_crypto_decrypt_garbage_is_none():
    assert crypto.decrypt("not-a-valid-token") is None
    assert crypto.decrypt("") is None


def test_sso_state_round_trip():
    state = cr._make_state(42)
    assert cr._read_state(state) == 42


def test_sso_state_rejects_plain_jwt():
    # a token without purpose='sso_state' must not pass _read_state
    from jose import jwt
    from app.core import config
    bad = jwt.encode({"sso_uid": 1, "exp": datetime.datetime.now(datetime.timezone.utc)
                      + datetime.timedelta(minutes=5)},
                     config.SECRET_KEY, algorithm=config.ALGORITHM)
    try:
        cr._read_state(bad)
        assert False, "expected rejection"
    except Exception:
        pass


def test_parse_character_claims():
    claims = {"sub": "CHARACTER:EVE:90000001", "name": "Test Pilot",
              "owner": "ownerhash", "scp": ["esi-wallet.read_character_wallet.v1", "publicData"]}
    info = esi.parse_character_claims(claims)
    assert info["character_id"] == 90000001
    assert info["character_name"] == "Test Pilot"
    assert info["owner_hash"] == "ownerhash"
    assert info["scopes"] == "esi-wallet.read_character_wallet.v1 publicData"


def test_parse_character_claims_string_scope():
    info = esi.parse_character_claims({"sub": "CHARACTER:EVE:1", "name": "A", "scp": "publicData"})
    assert info["scopes"] == "publicData"


def test_parse_dt():
    dt = esi.parse_dt("2026-01-02T03:04:05Z")
    assert dt == datetime.datetime(2026, 1, 2, 3, 4, 5)
    assert esi.parse_dt(None) is None
    assert esi.parse_dt("garbage") is None


def test_map_transaction():
    row = update_esi._map_transaction(7, {
        "transaction_id": 123, "date": "2026-01-01T00:00:00Z", "type_id": 34,
        "quantity": 1000, "unit_price": 5.5, "is_buy": True, "client_id": 9,
        "location_id": 60003760, "journal_ref_id": 555,
    })
    assert row["character_id"] == 7
    assert row["transaction_id"] == 123
    assert row["date"] == datetime.datetime(2026, 1, 1, 0, 0, 0)
    assert row["unit_price"] == 5.5
    assert row["is_buy"] is True


def test_map_skill_and_job():
    skill = update_esi._map_skill(7, {"skill_id": 3380, "skillpoints_in_skill": 256000,
                                      "trained_skill_level": 5, "active_skill_level": 5})
    assert skill == {"character_id": 7, "skill_id": 3380, "skillpoints": 256000,
                     "trained_level": 5, "active_level": 5}

    job = update_esi._map_job(7, {"job_id": 99, "activity_id": 1, "blueprint_type_id": 1000,
                                  "product_type_id": 2000, "runs": 10, "status": "active",
                                  "start_date": "2026-01-01T00:00:00Z", "cost": 12345.6})
    assert job["job_id"] == 99
    assert job["activity_id"] == 1
    assert job["runs"] == 10
    assert job["start_date"] == datetime.datetime(2026, 1, 1, 0, 0, 0)
