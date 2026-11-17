"""Bot ishga tushganda RSS yig'ish: faqat oxirgi yig'ishdan 2 soatdan ko'p o'tgan bo'lsa."""

import os
import time

from app.collector import jobs
from app.config import get_settings
from app.scheduler import scheduler as sch


def test_rss_due_by_stamp_age(tmp_path):
    stamp = tmp_path / "rss_last_run"
    assert jobs.rss_due(2, stamp)  # hech yig'ilmagan
    jobs.mark_rss_done(stamp)
    assert not jobs.rss_due(2, stamp)
    old = time.time() - 3 * 3600
    os.utime(stamp, (old, old))
    assert jobs.rss_due(2, stamp)


def test_startup_job_only_when_due(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(sch, "rss_due", lambda hours: True)
    assert sch.build_scheduler(None, settings, None, bot=object()).get_job("rss_startup") is not None
    monkeypatch.setattr(sch, "rss_due", lambda hours: False)
    assert sch.build_scheduler(None, settings, None, bot=object()).get_job("rss_startup") is None
    monkeypatch.setattr(sch, "rss_due", lambda hours: True)
    assert sch.build_scheduler(None, settings, None).get_job("rss_startup") is None  # CLI rejimida yo'q
