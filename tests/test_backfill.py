"""Archive crawls are one-off; daily runs must not repeat them."""
import pytest
import yaml

from observatoire import fetch as F
from observatoire.schema import Document, Tier
from observatoire.store import Store

CONFIG = {
    "people": [{
        "slug": "p1", "name": "P One", "party": "X", "match": ["One"],
        "sources": [
            {"type": "rss",  "url": "https://a.test/feed", "tier": "2"},
            {"type": "site", "url": "https://a.test",      "tier": "2"},
        ],
    }]
}


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "sources.yaml"
    p.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    return p


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture
def spy(monkeypatch):
    called = []

    def make(kind):
        def f(src, person, sid):
            called.append(kind)
            return [Document(person=person["slug"], source_id=sid, kind=kind,
                             tier=Tier.PARTY_OR_STAFF, url=f"https://a.test/{kind}",
                             text="x" * 500)], []
        return f

    monkeypatch.setattr(F, "FETCHERS", {k: make(k) for k in ("rss", "site")})
    return called


def test_daily_run_skips_archive_crawls(cfg, store, spy):
    F.run(cfg, store, do_archive=False, backfill=False)
    assert spy == ["rss"]


def test_backfill_runs_only_the_archive_crawls(cfg, store, spy):
    F.run(cfg, store, do_archive=False, backfill=True)
    assert spy == ["site"]


def test_backfill_and_daily_together_cover_every_source(cfg, store, spy):
    F.run(cfg, store, do_archive=False, backfill=True)
    F.run(cfg, store, do_archive=False, backfill=False)
    assert sorted(spy) == ["rss", "site"]


def test_a_skipped_source_records_no_run(cfg, store, spy):
    """A source that was never attempted must not look like a source that
    returned nothing, or the liveness check would call it dead."""
    F.run(cfg, store, do_archive=False, backfill=False)
    store.commit()
    ids = [r[0] for r in store.db.execute("SELECT DISTINCT source_id FROM source_runs")]
    assert not any(":site:" in i for i in ids)


def test_site_is_the_only_backfill_type():
    assert F.BACKFILL_ONLY == {"site"}
