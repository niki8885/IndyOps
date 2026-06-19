"""
Short shareable job codes (store calc/chain request params, hand back a tiny code).

Keeping the code short — so the QR and Code128 barcode stay scannable — means the
params live in the DB, not in the code. Retention is ~1 week; the store is capacity-
bounded and evicts expired rows first, then the oldest, when full ("overwrite when out
of space"). Codes are random 8-digit numbers (unguessable enough for a share link;
re-checked for uniqueness on insert).
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Optional

from app.core.database import ShareCode
from app.core.timeutil import utcnow

_TTL_DAYS = 7
_MAX_CODES = 100_000
_CODE_DIGITS = 8

# First-digit reservation by category, so a code's leading digit tells you what it opens:
#   1–4  → production calculator + make-vs-buy chain (our share codes)
#   9    → projects (Indy + PAK)
# 0 and 5–8 are left free for future categories.
_PREFIX = {"production": "1234", "chain": "1234", "project": "9", "indy": "9", "pak": "9"}
_DEFAULT_PREFIX = "1234"


def prefix_for(source: str) -> str:
    return _PREFIX.get(source, _DEFAULT_PREFIX)


def _gen_code(prefix_digits: str) -> str:
    first = prefix_digits[secrets.randbelow(len(prefix_digits))]
    rest = "".join(str(secrets.randbelow(10)) for _ in range(_CODE_DIGITS - 1))
    return first + rest


def _evict(db) -> None:
    """Purge expired rows and, if at capacity, evict the oldest ("overwrite on no space")."""
    db.query(ShareCode).filter(ShareCode.expires_at < utcnow()).delete(synchronize_session=False)
    if db.query(ShareCode).count() >= _MAX_CODES:
        for old in db.query(ShareCode).order_by(ShareCode.created_at.asc()).limit(200).all():
            db.delete(old)


def store_share(db, source: str, body: dict) -> str:
    """Persist a re-run body and return its short reserved-prefix code."""
    _evict(db)
    prefix = prefix_for(source)
    code = _gen_code(prefix)
    for _ in range(10):  # vanishingly unlikely to collide; re-roll if it does
        if not db.query(ShareCode).filter(ShareCode.code == code).first():
            break
        code = _gen_code(prefix)
    db.add(ShareCode(code=code, source=source, body=body,
                     expires_at=now_plus_ttl()))
    db.commit()
    return code


def now_plus_ttl():
    return utcnow() + timedelta(days=_TTL_DAYS)


def upsert_share(db, code: str, source: str, body: dict) -> str:
    """Reuse an existing code (refresh its body + expiry) so reopening a shared build keeps
    the SAME code instead of minting a new one; insert it if it's gone (e.g. expired)."""
    code = str(code)
    row = db.query(ShareCode).filter(ShareCode.code == code).first()
    if row is None:
        _evict(db)
        row = ShareCode(code=code, source=source, body=body, expires_at=now_plus_ttl())
        db.add(row)
    else:
        row.body = body
        row.source = source
        row.expires_at = now_plus_ttl()
    db.commit()
    return code


def get_share(db, code: str) -> Optional[dict]:
    """Return ``{"source", "body"}`` for a live (non-expired) code, else None."""
    row = (db.query(ShareCode)
           .filter(ShareCode.code == str(code), ShareCode.expires_at > utcnow())
           .first())
    return {"source": row.source, "body": row.body} if row else None
