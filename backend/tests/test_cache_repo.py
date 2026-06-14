"""analytics_cache read-through repository."""
import datetime

from app.core.database import AnalyticsCache
from app.repositories import cache_repo


def test_set_then_get(app_session):
    cache_repo.set_cached(app_session, "index", "mineral", 10, {"a": 1})
    assert cache_repo.get_cached(app_session, "index", "mineral", 10) == {"a": 1}


def test_miss_returns_none(app_session):
    assert cache_repo.get_cached(app_session, "index", "nope", 10) is None


def test_upsert_keeps_single_row(app_session):
    cache_repo.set_cached(app_session, "index", "mineral", 10, {"v": 1})
    cache_repo.set_cached(app_session, "index", "mineral", 10, {"v": 2})
    assert cache_repo.get_cached(app_session, "index", "mineral", 10) == {"v": 2}
    assert app_session.query(AnalyticsCache).count() == 1


def test_window_is_part_of_the_key(app_session):
    cache_repo.set_cached(app_session, "index", "mineral", 10, {"w": 10})
    cache_repo.set_cached(app_session, "index", "mineral", 20, {"w": 20})
    assert cache_repo.get_cached(app_session, "index", "mineral", 10) == {"w": 10}
    assert cache_repo.get_cached(app_session, "index", "mineral", 20) == {"w": 20}


def test_ttl_treats_stale_as_miss(app_session):
    cache_repo.set_cached(app_session, "index", "mineral", 10, {"v": 1})
    row = app_session.query(AnalyticsCache).first()
    row.computed_at = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
    app_session.commit()
    assert cache_repo.get_cached(app_session, "index", "mineral", 10, max_age_seconds=3600) is None
    assert cache_repo.get_cached(app_session, "index", "mineral", 10) == {"v": 1}   # no TTL → still served
