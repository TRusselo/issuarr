"""Follow-ups from the parallel-downloads review (issue #10)."""
import collections
import json
import queue
import types

import pytest

import mylar
from mylar import getcomics
from mylar.downloaders import mediafire
from mylar.queues import ddl


class FakeDB:
    def __init__(self):
        self.upserts = []

    def upsert(self, table, vals, ctrl):
        self.upserts.append((table, vals, ctrl))


class Recorder:
    def __init__(self):
        self.entered = 0

    def __enter__(self):
        self.entered += 1

    def __exit__(self, *exc):
        return False


def item(**kwargs):
    base = {'id': '54429', 'series': 'Age of Ultron', 'site': 'DDL(GetComics)', 'link_type': 'GC-Main',
            'mainlink': 'https://getcomics.org/marvel/age-of-ultron-1-10ai-2013/', 'comicid': '58436',
            'issueid': '390442', 'oneoff': False, 'comicinfo': None, 'packinfo': None}
    base.update(kwargs)
    return base


@pytest.mark.unit
def test_cookie_is_read_under_the_cookie_lock(monkeypatch, tmp_path):
    lock = Recorder()
    monkeypatch.setattr(getcomics, '_COOKIE_LOCK', lock)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_FLARESOLVERR=False), raising=False)
    cookie = tmp_path / '.gc_cookies.dat'
    cookie.write_text(json.dumps([{'name': 'cf_clearance', 'value': 'x'}]))
    g = getcomics.GC.__new__(getcomics.GC)
    g.session_path = str(cookie)
    g.session = types.SimpleNamespace(cookies=types.SimpleNamespace(set=lambda **kw: None))
    g._load_ua = lambda: None
    g.cookie_receipt()
    assert lock.entered == 1


@pytest.mark.unit
def test_failed_download_goes_back_to_queued_while_it_waits_for_failover(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(ddl.db, 'DBConnection', lambda *a, **k: fake_db)
    monkeypatch.setattr(ddl, 'ACTIVE', set())
    monkeypatch.setattr(ddl, 'ddl_process', lambda myDB, it: {'success': False, 'link_type_failure': 'GC-Pixel'})
    sent = []
    monkeypatch.setattr(ddl, 'send_to_failover', lambda it, result, jd2_gave_up=False: sent.append(it['id']))
    ddl.run_download(item(link_type='GC-Pixel'))
    assert ('ddl_info', {'status': 'Queued'}, {'id': '54429'}) in fake_db.upserts
    assert sent == ['54429']


@pytest.mark.unit
def test_next_source_clears_the_previous_file_path(monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.jd2 = None
    gc.issueid, gc.comicid, gc.oneoff = '390442', '58436', False
    link = {'series': 'Age of Ultron #1 – 10AI', 'site': 'mega', 'year': '2013', 'size': '617 MB',
            'issues': None, 'links': 'https://getcomics.org/dls/mega', 'pack': True}
    fake_db = FakeDB()
    gc._queue_links([link], [link], [], '54429', item()['mainlink'], None, None, [], fake_db)
    assert fake_db.upserts[0][1]['tmp_filename'] is None


@pytest.mark.unit
def test_cancelled_item_forgets_its_failover_history(monkeypatch):
    monkeypatch.setattr(ddl, 'FAILOVER', {'54429': {'failed': ['GC-Mega'], 'no_jd2': True}})
    monkeypatch.setattr(mylar, 'DDL_CANCEL', {'54429'}, raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUED', set(), raising=False)
    monkeypatch.setattr(ddl.helpers, 'reverse_the_pack_snatch', lambda *a: None)
    monkeypatch.setattr(ddl, 'ddl_cleanup', lambda record_id: None)
    assert ddl.ddl_cancelled(item()) is True
    assert '54429' not in ddl.FAILOVER


@pytest.mark.unit
def test_a_thread_that_fails_to_start_keeps_its_item(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_MAX_PARALLEL=3), raising=False)
    monkeypatch.setattr(ddl, 'PENDING', collections.deque([item(link_type='GC-Pixel')]))
    monkeypatch.setattr(ddl, 'RUNNING', [0])
    monkeypatch.setattr(ddl, 'STOP', ddl.threading.Event())

    def boom(*a, **k):
        raise RuntimeError("can't start new thread")
    monkeypatch.setattr(ddl, '_start', boom)
    ddl.start_waiting()
    assert ddl.RUNNING[0] == 0
    assert [i['id'] for i in ddl.PENDING] == ['54429']


@pytest.mark.unit
def test_restart_picks_the_source_again_with_a_clean_slate(monkeypatch):
    monkeypatch.setattr(ddl, 'FAILOVER_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'FAILOVER', {'54429': {'failed': ['GC-Media', 'GC-Mega'], 'no_jd2': True}})
    ddl.repick(item())
    entry = ddl.FAILOVER_QUEUE.get_nowait()
    assert entry['item']['id'] == '54429' and entry['repick'] is True
    assert '54429' not in ddl.FAILOVER


@pytest.mark.unit
def test_repick_reads_the_page_with_no_failed_sources(monkeypatch):
    calls = []

    class FakeGC:
        def __init__(self, **kwargs):
            self.jd2 = 'jd2-helper'

        def parse_downloadresults(self, id, mainlink, comicinfo=None, packinfo=None, link_type_failure=None):
            calls.append(list(link_type_failure))
            return {'success': True}
    monkeypatch.setattr(ddl, 'FAILOVER', {})
    monkeypatch.setattr(ddl, 'ACTIVE', set())
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(ddl.getcomics, 'GC', FakeGC)
    ddl.handle_failure(None, item(link_type='GC-Main'), {}, repick=True)
    assert calls == [[]]


@pytest.mark.unit
def test_mediafire_logs_why_it_failed(monkeypatch):
    warned = []
    monkeypatch.setattr(mediafire.logger, 'warn', lambda msg, *a: warned.append(msg % a if a else msg))
    m = mediafire.MediaFire.__new__(mediafire.MediaFire)
    m.headers = {}
    m.session = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(headers={}, text='<html></html>', status_code=200))
    m.extractDownloadLink = lambda text: None
    result = m.ddl_download('https://www.mediafire.com/file/abc', '54429', '390442')
    assert result['success'] is False
    assert any('https://www.mediafire.com/file/abc' in w for w in warned)
