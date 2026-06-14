"""Worker job wrapper: advisory lock + duration logging + never-raises."""
import datetime

from app import jobs
from app.core.database import MarketIndexSnapshot
from app.core.indices_data import INDEX_META, INDEX_ORDER
from app.repositories import cache_repo


def test_advisory_lock_is_noop_off_postgres():
    # tests run on sqlite → lock is a no-op that always "acquires"
    with jobs._advisory_lock("sde") as acquired:
        assert acquired is True


def test_run_executes_the_job():
    calls = []
    jobs._run("index", lambda: (calls.append(1), "ok")[1])
    assert calls == [1]


def test_run_swallows_exceptions():
    def boom():
        raise ValueError("nope")

    jobs._run("tracking", boom)   # must not propagate


def test_warm_index_cache_populates(app_session):
    key = INDEX_ORDER[0]
    base = datetime.datetime(2025, 1, 1)
    for i in range(12):
        app_session.add(MarketIndexSnapshot(
            index_key=key, timestamp=base + datetime.timedelta(hours=i),
            price_index=100.0 + i, volume_index=10.0 + i,
            top3_share=0.5, h_index=0.3, entropy=1.0, liquidity_index=2.0))
    app_session.commit()

    warmed = jobs.warm_index_cache(app_session, window=10)
    assert warmed == 1                      # only the seeded index has data
    cached = cache_repo.get_cached(app_session, "index", key, 10)
    assert cached is not None
    assert cached["key"] == key and cached["label"] == INDEX_META[key]["label"]
