import queue
import types

import pytest

import mylar
import mylar.search  # noqa: F401 - makes mylar.search available to patch
from mylar.queues import ddl


class FakeGC:
    instances = []
    reply = {'success': True, 'site': 'GC-Media'}

    def __init__(self, query=None, issueid=None, comicid=None, oneoff=False, **kwargs):
        self.jd2 = 'jd2-helper'
        self.calls = []
        FakeGC.instances.append(self)

    def parse_downloadresults(self, id, mainlink, comicinfo=None, packinfo=None, link_type_failure=None):
        self.calls.append({'id': id, 'mainlink': mainlink, 'failed': list(link_type_failure or [])})
        return FakeGC.reply


@pytest.fixture
def failover(monkeypatch):
    FakeGC.instances = []
    FakeGC.reply = {'success': True, 'site': 'GC-Media'}
    monkeypatch.setattr(ddl, 'FAILOVER', {})
    monkeypatch.setattr(ddl.getcomics, 'GC', FakeGC)
    gave_up = []
    monkeypatch.setattr(ddl, 'ddl_give_up', lambda myDB, item: gave_up.append(item['id']))
    return gave_up


def item(**kwargs):
    base = {'id': '54429', 'series': 'Age of Ultron', 'site': 'DDL(GetComics)', 'link_type': 'GC-Mega',
            'mainlink': 'https://getcomics.org/marvel/age-of-ultron-1-10ai-2013/', 'comicid': '58436',
            'issueid': '390442', 'oneoff': False, 'comicinfo': None, 'packinfo': None}
    base.update(kwargs)
    return base


@pytest.mark.unit
def test_failed_link_is_skipped_on_the_next_try(failover):
    ddl.handle_failure(None, item(), {'success': False})
    gc = FakeGC.instances[0]
    assert gc.calls == [{'id': '54429', 'mainlink': item()['mainlink'], 'failed': ['GC-Mega']}]
    assert gc.jd2 == 'jd2-helper'
    assert failover == []


@pytest.mark.unit
def test_jd2_give_up_tries_own_downloaders_without_jd2(failover):
    ddl.handle_failure(None, item(), {}, jd2_gave_up=True)
    gc = FakeGC.instances[0]
    assert gc.jd2 is None
    assert gc.calls[0]['failed'] == []


@pytest.mark.unit
def test_item_jd2_gave_up_on_never_goes_back_to_jd2(failover):
    ddl.handle_failure(None, item(), {}, jd2_gave_up=True)
    ddl.handle_failure(None, item(), {'success': False})
    second = FakeGC.instances[1]
    assert second.jd2 is None
    assert second.calls[0]['failed'] == ['GC-Mega']


@pytest.mark.unit
def test_no_links_left_marks_failed(failover):
    FakeGC.reply = {'success': False, 'links_exhausted': ['GC-Mega']}
    ddl.handle_failure(None, item(), {'success': False})
    assert failover == ['54429']


@pytest.mark.unit
def test_exhausted_result_gives_up_without_rereading_the_page(failover):
    ddl.handle_failure(None, item(), {'success': False, 'links_exhausted': ['GC-Main']})
    assert failover == ['54429']
    assert FakeGC.instances == []


@pytest.mark.unit
def test_item_without_mainlink_is_marked_failed(failover):
    ddl.handle_failure(None, item(mainlink=None), {'success': False})
    assert failover == ['54429']
    assert FakeGC.instances == []


@pytest.mark.unit
def test_external_server_failure_marks_issue_failed(failover, monkeypatch):
    marked, deleted = [], []
    monkeypatch.setattr(mylar.search, 'FailedMark', lambda *a, **k: marked.append(a))
    fake_db = types.SimpleNamespace(action=lambda sql, args: deleted.append(args))
    ddl.handle_failure(fake_db, item(site='DDL(External)', link_type='DDL-Ext'), {'success': False, 'filename': 'x.cbz'})
    assert deleted == [['54429']]
    assert marked[0][:3] == ('390442', '58436', '54429')
    assert '54429' not in ddl.FAILOVER


@pytest.mark.unit
def test_items_waiting_for_failover_count_as_queued(monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(ddl, 'FAILOVER_QUEUE', queue.Queue())
    ddl.send_to_failover({'id': 'x'}, {'success': False})
    assert 'x' in ddl.waiting_ids()
    assert ddl.waiting_count() == 1
