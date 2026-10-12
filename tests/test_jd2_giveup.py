import queue
import types

import pytest

import mylar
from mylar import getcomics
from mylar.queues import ddl, jd2


class FakeDB:
    def __init__(self):
        self.upserts = []
        self.actions = []

    def upsert(self, table, vals, ctrl):
        self.upserts.append((table, vals, ctrl))

    def selectone(self, query, args=None):
        return types.SimpleNamespace(fetchone=lambda: {'jd2_job_id': '1791741854472'})

    def action(self, query, args=None):
        self.actions.append((query, args))
        return types.SimpleNamespace(rowcount=1)


@pytest.fixture
def sent(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_DDL=True), raising=False)
    out = []
    monkeypatch.setattr(ddl, 'send_to_failover', lambda item, result, jd2_gave_up=False: out.append((item, result, jd2_gave_up)))
    return out


def jd2_item(**kwargs):
    base = {'id': '54429', 'series': 'Age of Ultron #1 – 10AI (2013)', 'link_type': 'GC-Mega',
            'mainlink': 'https://getcomics.org/marvel/age-of-ultron-1-10ai-2013/', 'link': 'https://getcomics.org/dls/mega',
            'main_link': 'https://getcomics.org/dls/main', 'jd2_job_id': '1791741854472',
            'jd2_priority_links': {'https://getcomics.org/dls/mega': 'HIGHEST'}, 'comicid': '58436', 'issueid': '390442'}
    base.update(kwargs)
    return base


@pytest.mark.unit
def test_jd2_give_up_hands_the_item_to_failover(sent):
    fake_db = FakeDB()
    jd2.jd2_give_up(fake_db, jd2_item(), '54429', 'JD2 status Blocked by Cloudflare')
    item, result, jd2_gave_up = sent[0]
    assert jd2_gave_up is True
    assert 'jd2_job_id' not in item and 'jd2_priority_links' not in item and 'main_link' not in item
    assert item['id'] == '54429' and item['link_type'] == 'GC-Mega'
    query, args = fake_db.actions[0]
    assert query == 'UPDATE ddl_info SET status=?, jd2_job_id=?, updated_date=? WHERE id=?'
    assert args[:2] == ['Queued', None] and args[-1] == '54429'


@pytest.mark.unit
def test_jd2_give_up_with_direct_downloads_off_marks_failed(sent, monkeypatch):
    mylar.CONFIG.ENABLE_DDL = False
    failed = []
    monkeypatch.setattr(jd2, 'jd2_mark_failed', lambda myDB, item, record_id, reason: failed.append(record_id))
    jd2.jd2_give_up(FakeDB(), jd2_item(), '54429', 'offline')
    assert failed == ['54429']
    assert sent == []


@pytest.mark.unit
def test_jd2_fallback_to_getcomics_direct_is_gone():
    assert not hasattr(jd2, 'jd2_fallback')


@pytest.mark.unit
def test_without_jd2_links_go_straight_to_the_built_in_downloaders(monkeypatch):
    # what the failover worker relies on after setting ggc.jd2 = None
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'JD2_QUEUE', queue.Queue(), raising=False)
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.jd2 = None
    gc.issueid, gc.comicid, gc.oneoff = '390442', '58436', False
    link = {'series': 'Age of Ultron #1 – 10AI', 'site': 'mega', 'year': '2013', 'size': '617 MB',
            'issues': None, 'links': 'https://getcomics.org/dls/mega', 'pack': True}
    fake_db = FakeDB()
    gc._queue_links([link], [link], [], '54429', 'https://getcomics.org/marvel/age-of-ultron-1-10ai-2013/', None, None, [], fake_db)
    queued = mylar.DDL_QUEUE.get_nowait()
    assert queued['link_type'] == 'GC-Mega'
    assert mylar.JD2_QUEUE.empty()
    vals = fake_db.upserts[0][1]
    assert vals['link'] == 'https://getcomics.org/dls/mega' and vals['link_type'] == 'GC-Mega'
