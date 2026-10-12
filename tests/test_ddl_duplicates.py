"""One download per item: a second Restart, or an older attempt that ends late, mustn't queue it again.

2026-10-11: Restart was clicked twice on Age of Ultron (617 MB). Each click sent a job to JD2; both
gave up, and each give-up queued a GetComics download, so the pack downloaded twice and held the
one GetComics slot for 20 more minutes.
"""
import collections
import queue
import types

import pytest

import mylar
from mylar.queues import ddl, jd2


def item(**kwargs):
    base = {'id': '54429', 'series': 'Age of Ultron', 'site': 'DDL(GetComics)', 'link_type': 'GC-Main',
            'mainlink': 'https://getcomics.org/marvel/age-of-ultron-1-10ai-2013/', 'comicid': '58436',
            'issueid': '390442', 'oneoff': False, 'comicinfo': None, 'packinfo': None}
    base.update(kwargs)
    return base


class FakeDB:
    def __init__(self, jd2_job_id=None):
        self.jd2_job_id = jd2_job_id
        self.upserts = []

    def upsert(self, table, vals, ctrl):
        self.upserts.append((table, vals, ctrl))

    def selectone(self, query, args=None):
        row = {'jd2_job_id': self.jd2_job_id}
        return types.SimpleNamespace(fetchone=lambda: row)


@pytest.fixture
def queues(monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'JD2_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(ddl, 'GC_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'FAILOVER_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'PENDING', collections.deque())
    monkeypatch.setattr(ddl, 'ACTIVE', set())
    monkeypatch.setattr(ddl, 'FAILOVER', {})
    monkeypatch.setattr(jd2, 'HOLDING', [None])
    reads = []

    class FakeGC:
        def __init__(self, **kwargs):
            self.jd2 = 'jd2-helper'

        def parse_downloadresults(self, *a, **k):
            reads.append(a[0])
            return {'success': True}
    monkeypatch.setattr(ddl.getcomics, 'GC', FakeGC)
    return reads


@pytest.mark.unit
@pytest.mark.parametrize('where', ['downloading', 'gc_queue', 'pending', 'ddl_queue', 'jd2_queue', 'jd2_holding'])
def test_an_older_attempt_ending_is_ignored_while_the_item_is_in_flight(queues, where):
    if where == 'downloading':
        ddl.ACTIVE.add('54429')
    elif where == 'gc_queue':
        ddl.GC_QUEUE.put(item())
    elif where == 'pending':
        ddl.PENDING.append(item(link_type='GC-Pixel'))
    elif where == 'ddl_queue':
        mylar.DDL_QUEUE.put(item())
    elif where == 'jd2_queue':
        mylar.JD2_QUEUE.put(item(jd2_job_id='1791757930309'))
    else:
        jd2.HOLDING[0] = '54429'
    ddl.handle_failure(None, item(), {}, jd2_gave_up=True)
    assert queues == []                      # the page wasn't read again, nothing new queued
    assert '54429' not in ddl.FAILOVER


@pytest.mark.unit
def test_a_failure_with_nothing_else_in_flight_still_looks_for_another_source(queues):
    ddl.handle_failure(None, item(), {}, jd2_gave_up=True)
    assert queues == ['54429']


@pytest.mark.unit
def test_a_failed_download_reaches_failover_after_it_stops_counting_as_active(queues, monkeypatch):
    seen = []
    monkeypatch.setattr(ddl.db, 'DBConnection', lambda *a, **k: FakeDB())
    monkeypatch.setattr(ddl, 'ddl_process', lambda myDB, it: {'success': False, 'link_type_failure': 'GC-Main'})
    monkeypatch.setattr(ddl, 'send_to_failover', lambda it, result, jd2_gave_up=False: seen.append(set(ddl.ACTIVE)))
    ddl.run_download(item())
    assert seen == [set()]


@pytest.mark.unit
def test_jd2_give_up_from_a_replaced_job_is_ignored(queues, monkeypatch):
    sent = []
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_DDL=True), raising=False)
    monkeypatch.setattr(ddl, 'send_to_failover', lambda *a, **k: sent.append(a[0]['id']))
    db = FakeDB(jd2_job_id='1791757930309')   # the row moved on to the second job
    jd2.jd2_give_up(db, item(jd2_job_id='1791757909234'), '54429', 'JD2 status Blocked by Cloudflare')
    assert sent == [] and db.upserts == []


@pytest.mark.unit
def test_jd2_give_up_from_the_current_job_goes_to_failover_and_lets_go_of_the_item(queues, monkeypatch):
    sent = []
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_DDL=True), raising=False)
    monkeypatch.setattr(ddl, 'send_to_failover', lambda *a, **k: sent.append(a[0]['id']))
    jd2.HOLDING[0] = '54429'
    jd2.jd2_give_up(FakeDB(jd2_job_id='1791757930309'), item(jd2_job_id='1791757930309'), '54429', 'JD2 status offline')
    assert sent == ['54429']
    assert jd2.HOLDING[0] is None


@pytest.mark.unit
def test_items_at_jd2_count_as_queued(queues):
    mylar.JD2_QUEUE.put(item(id='1', jd2_job_id=0))
    mylar.JD2_QUEUE.put('startup')
    jd2.HOLDING[0] = '2'
    assert jd2.at_jd2() == {'1', '2'}
