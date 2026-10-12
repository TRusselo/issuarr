"""JD2 jobs that can never finish, or that the queue no longer wants, are let go.

2026-10-11: MEGA said "The hosting period for this file has now expired. Only paid users can
download it." for four JD2 items. That wasn't on the dead list, so they were polled forever and
sat Queued. Three of them were removed in the UI but stayed in the JD2 monitor. Another removed
item (Airboy Archives Vol. 5) was given up on afterwards, and the give-up recreated its deleted
ddl_info row as a bare Queued row that crashed Restart queue.
"""
import queue
import sqlite3
import types

import pytest

import mylar
from mylar import db
from mylar.downloaders.jdownloader2 import JDownloader2
from mylar.queues import ddl, jd2

EXPIRED = 'The hosting period for this file has now expired. Only paid users can download it.'
JOB = '1791780694262'


def item(**kwargs):
    base = {'id': '193251', 'series': 'Batman: Earth One Vol. 3', 'year': '2021', 'link_type': 'GC-Mega',
            'mainlink': 'https://getcomics.org/dc/batman-earth-one-vol-3/', 'comicid': '58436',
            'issueid': '390442', 'oneoff': False, 'jd2_job_id': JOB}
    base.update(kwargs)
    return base


def make_db(*rows):
    conn = db.DBConnection.__new__(db.DBConnection)
    conn.connection = sqlite3.connect(':memory:')
    conn.connection.row_factory = sqlite3.Row
    conn.connection.execute('CREATE TABLE ddl_info (id TEXT, series TEXT, status TEXT, jd2_job_id TEXT, '
                            'updated_date TEXT, issueid TEXT, comicid TEXT, pack TEXT)')
    for row in rows:
        conn.connection.execute('INSERT INTO ddl_info (id, series, status, jd2_job_id, updated_date) VALUES (?, ?, ?, ?, ?)',
                                [row.get('id', '193251'), 'Batman: Earth One Vol. 3', row.get('status', 'Queued'),
                                 row.get('jd2_job_id', JOB), '2026-10-11 22:51'])
    return conn


def ddl_rows(conn):
    return [dict(r) for r in conn.connection.execute('SELECT id, status, jd2_job_id FROM ddl_info')]


class FakeJD2:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.polled = []
        self.removed = []

    def status(self, job_id, record_id=None):
        self.polled.append(job_id)
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    def remove(self, job_id, record_id=None):
        self.removed.append((job_id, record_id))


@pytest.fixture
def setup(monkeypatch, tmp_path):
    clock = [0.0]
    sent = []
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_DDL=True, POST_PROCESSING=False, CACHE_DIR=str(tmp_path)), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUED', set(), raising=False)
    monkeypatch.setattr(mylar, 'PACK_ISSUEIDS_DONT_QUEUE', {}, raising=False)
    monkeypatch.setattr(jd2, 'HOLDING', [None])
    monkeypatch.setattr(jd2, 'PROGRESS', {})
    monkeypatch.setattr(jd2, 'time', types.SimpleNamespace(sleep=lambda s: None, monotonic=lambda: clock[0]))
    monkeypatch.setattr(ddl, 'send_to_failover', lambda it, result, jd2_gave_up=False: sent.append((it['id'], result['reason'])))
    monkeypatch.setattr(ddl.helpers, 'reverse_the_pack_snatch', lambda *a: None)
    return types.SimpleNamespace(clock=clock, sent=sent)


def run_monitor(monkeypatch, client, conn, *items):
    """One pass over the items. Whatever the monitor puts back comes out after 'exit'."""
    monkeypatch.setattr(jd2, 'JDownloader2', lambda: client)
    monkeypatch.setattr(jd2.db, 'DBConnection', lambda: conn)
    q = queue.Queue()
    for it in items:
        q.put(it)
    q.put('exit')
    jd2.jd2_queue_monitor(q)
    return list(q.queue)


@pytest.mark.unit
def test_a_removed_or_aborted_item_is_dropped_and_its_cancel_cleared(setup, monkeypatch):
    mylar.DDL_CANCEL.add('193251')
    client = FakeJD2({'found': True, 'status': 'Downloading'})
    conn = make_db({'status': 'Failed'})
    left = run_monitor(monkeypatch, client, conn, item())
    assert left == []                      # not put back
    assert client.polled == []             # JD2 isn't even asked
    assert client.removed == [(JOB, None)]  # this job only
    assert mylar.DDL_CANCEL == set()       # a later grab of the same post isn't dropped
    assert jd2.HOLDING[0] is None
    assert setup.sent == []


@pytest.mark.unit
@pytest.mark.parametrize('rows', [(), ({'status': 'Failed'},), ({'jd2_job_id': '1791780699999'},), ({'jd2_job_id': None},)],
                         ids=['row-removed', 'row-failed', 'sent-again', 'given-up'])
def test_a_job_the_queue_no_longer_wants_is_dropped(setup, monkeypatch, rows):
    client = FakeJD2({'found': True, 'status': 'Blocked by Cloudflare Site-Protection'})
    conn = make_db(*rows)
    before = ddl_rows(conn)
    left = run_monitor(monkeypatch, client, conn, item())
    assert left == [] and client.polled == []
    assert client.removed == [(JOB, None)]   # a newer job for the same record isn't touched
    assert ddl_rows(conn) == before          # no ghost row, nothing changed
    assert setup.sent == []


@pytest.mark.unit
def test_an_expired_hosting_period_gives_up_on_the_first_poll(setup, monkeypatch):
    client = FakeJD2({'found': True, 'status': EXPIRED, 'data': {'name': 'Batman - Earth One v03 (2021).cbr'}})
    conn = make_db({})
    left = run_monitor(monkeypatch, client, conn, item())
    assert left == []
    assert client.removed == [(JOB, '193251')]
    assert setup.sent == [('193251', 'JD2 status %s' % EXPIRED)]
    assert ddl_rows(conn) == [{'id': '193251', 'status': 'Queued', 'jd2_job_id': None}]


@pytest.mark.unit
def test_a_healthy_job_is_still_followed(setup, monkeypatch):
    client = FakeJD2({'found': True, 'status': 'Downloading', 'loaded': 1024})
    left = run_monitor(monkeypatch, client, make_db({}), item())
    assert [i['id'] for i in left] == ['193251']
    assert client.removed == [] and setup.sent == []


@pytest.mark.unit
@pytest.mark.parametrize('status', [EXPIRED, 'Only paid users can download this file', 'Hosting period expired'])
def test_expired_hosting_counts_as_dead(status):
    assert jd2.jd2_status_is_dead(status)


@pytest.mark.unit
@pytest.mark.parametrize('status', ['Transfer quota exceeded - waiting', 'Skipped - captcha input', 'Premium download', 'Downloading'])
def test_waits_the_user_can_fix_are_not_dead(status):
    assert not jd2.jd2_status_is_dead(status)


@pytest.mark.unit
def test_the_client_fails_a_package_whose_links_all_expired():
    client = JDownloader2.__new__(JDownloader2)
    client._job_links = lambda job_id, record_id=None: {
        'downloadsV2': ([{'status': EXPIRED, 'bytesLoaded': 0}, {'status': 'File not found', 'bytesLoaded': 0}], ['p1']),
        'linkgrabberv2': ([], [])}
    result = client.status(JOB, '193251')
    assert result['status'] == 'Failed' and EXPIRED in result['reason']


@pytest.mark.unit
def test_the_client_reports_bytes_downloaded_across_the_package():
    client = JDownloader2.__new__(JDownloader2)
    client._job_links = lambda job_id, record_id=None: {
        'downloadsV2': ([{'status': EXPIRED, 'bytesLoaded': 0}, {'status': 'Downloading', 'bytesLoaded': 5000}], ['p1']),
        'linkgrabberv2': ([], [])}
    result = client.status(JOB, '193251')
    assert result['status'] == EXPIRED and result['loaded'] == 5000


@pytest.mark.unit
def test_give_up_on_a_removed_row_creates_no_row(setup, monkeypatch):
    mylar.DDL_CANCEL.add('120120')
    jd2.HOLDING[0] = '120120'
    conn = make_db()
    jd2.jd2_give_up(conn, item(id='120120', series='Airboy Archives Vol. 5'), '120120', 'JD2 status Blocked by Cloudflare')
    assert ddl_rows(conn) == []
    assert setup.sent == []
    assert jd2.HOLDING[0] is None and mylar.DDL_CANCEL == set()


@pytest.mark.unit
def test_give_up_with_direct_downloads_off_on_a_removed_row_creates_no_row(setup, monkeypatch):
    mylar.CONFIG.ENABLE_DDL = False
    marked = []
    monkeypatch.setattr(mylar, 'search', types.SimpleNamespace(FailedMark=lambda *a, **k: marked.append(a)), raising=False)
    conn = make_db()
    jd2.jd2_give_up(conn, item(), '193251', 'JD2 status offline')
    jd2.jd2_mark_failed(conn, item(), '193251', 'JD2 status offline')
    assert ddl_rows(conn) == [] and marked == []


@pytest.mark.unit
def test_mark_failed_updates_the_row(setup, monkeypatch):
    marked = []
    monkeypatch.setattr(mylar, 'search', types.SimpleNamespace(FailedMark=lambda *a, **k: marked.append(a[0])), raising=False)
    conn = make_db({})
    jd2.jd2_mark_failed(conn, item(), '193251', 'JD2 status offline')
    assert ddl_rows(conn) == [{'id': '193251', 'status': 'Failed', 'jd2_job_id': JOB}]
    assert marked == ['390442']


@pytest.mark.unit
def test_a_job_with_no_progress_for_hours_is_given_up_on(setup, monkeypatch):
    client = FakeJD2({'found': True, 'status': 'Waiting for the file host', 'loaded': 2048})
    conn = make_db({})
    assert run_monitor(monkeypatch, client, conn, item())
    setup.clock[0] = jd2.NO_PROGRESS_LIMIT - 60
    assert run_monitor(monkeypatch, client, conn, item())
    setup.clock[0] = jd2.NO_PROGRESS_LIMIT
    assert run_monitor(monkeypatch, client, conn, item()) == []
    assert client.removed == [(JOB, '193251')]
    assert setup.sent == [('193251', 'no progress in JD2 for 6 hours')]
    assert jd2.PROGRESS == {}


@pytest.mark.unit
def test_a_slow_download_that_keeps_moving_is_never_cut_short(setup, monkeypatch):
    client = FakeJD2()
    conn = make_db({})
    for hour in range(0, 25):
        setup.clock[0] = hour * 3600
        client.statuses = [{'found': True, 'status': 'Downloading', 'loaded': hour * 1000}]
        assert run_monitor(monkeypatch, client, conn, item())
    assert client.removed == [] and setup.sent == []


@pytest.mark.unit
def test_without_byte_counts_a_changing_status_counts_as_progress(setup):
    assert not jd2.jd2_no_progress(JOB, 'Waiting 00:10:00', now=0)
    assert not jd2.jd2_no_progress(JOB, 'Waiting 00:09:50', now=jd2.NO_PROGRESS_LIMIT)
    assert not jd2.jd2_no_progress(JOB, 'Waiting 00:09:50', now=jd2.NO_PROGRESS_LIMIT + 60)
    assert jd2.jd2_no_progress(JOB, 'Waiting 00:09:50', now=2 * jd2.NO_PROGRESS_LIMIT)
