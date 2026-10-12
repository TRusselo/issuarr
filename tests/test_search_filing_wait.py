"""Searching waits for filing only when filing could be handling the same series.

2026-10-11: every search waited for all post-processing to finish, and with downloads finishing
one after another the search queue moved one issue every 35-60 seconds.
2026-10-11 later: with every remaining item Supergirl, filing each issue held the next one for
2-2.5 minutes. A single-issue download now holds only its own issue.
"""
import queue

import pytest

import mylar
from mylar import archives, autoadd
from mylar.queues import search as worker


@pytest.fixture
def filing(monkeypatch):
    monkeypatch.setattr(mylar, 'PP_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(archives, 'JOBS', [])
    monkeypatch.setattr(autoadd, 'running', lambda: False)
    monkeypatch.setattr(worker, 'HELD', {})
    for name in ('info', 'fdebug'):
        monkeypatch.setattr(worker.logger, name, lambda *a, **k: None)


def item(comicid='100', issueid='1'):
    return {'comicid': comicid, 'issueid': issueid, 'comicname': 'Iron Man', 'issuenumber': '4'}


@pytest.mark.unit
def test_filing_another_series_doesnt_hold_a_search(filing):
    archives.JOBS.append(('200', None))
    mylar.PP_QUEUE.put({'comicid': '300'})
    assert not worker.held(item())


@pytest.mark.unit
def test_filing_the_same_series_holds_it(filing):
    archives.JOBS.append(('100', None))
    assert worker.held(item())
    archives.JOBS.clear()
    mylar.PP_QUEUE.put({'comicid': '100'})
    assert worker.held(item())


@pytest.mark.unit
@pytest.mark.parametrize('how', ['monitored folder', 'auto-add'])
def test_filing_that_could_be_anything_holds_every_search(filing, monkeypatch, how):
    if how == 'auto-add':
        monkeypatch.setattr(autoadd, 'running', lambda: True)
    else:
        archives.JOBS.append((None, None))
    assert worker.held(item())


@pytest.mark.unit
def test_a_held_search_goes_ahead_after_the_limit(filing, monkeypatch):
    archives.JOBS.append(('100', None))
    worker.HELD['1'] = 0     # held since the epoch
    assert not worker.held(item())
    assert '1' not in worker.HELD


@pytest.mark.unit
def test_post_processing_registers_its_series_while_it_runs(filing, monkeypatch):
    from mylar import PostProcessor
    seen = []
    monkeypatch.setattr(PostProcessor.PostProcessor, '_locked_process', lambda self: seen.append(list(archives.JOBS)))
    for name, comicid, issueid, ddl, pack, expected in (
            ('Iron Man #4', '100', '4', True, False, [('100', '4')]),
            ('Iron Man v01-v03', '100', '4', True, True, [('100', None)]),
            ('Iron Man #4', '100', '4', False, None, [('100', None)]),
            ('Manual Run', None, None, False, None, [(None, None)])):
        pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
        pp.nzb_name, pp.comicid, pp.issueid, pp.apicall, pp.ddl, pp.pack = name, comicid, issueid, False, ddl, pack
        pp.Process()
        assert seen.pop() == expected and archives.JOBS == []


class _Stop(Exception):
    pass


@pytest.mark.unit
def test_a_single_issue_download_that_unpacks_as_a_pack_holds_every_search(filing, monkeypatch):
    from mylar import PostProcessor
    seen = []

    def stop():
        seen.append((archives.holds('93160', '585072'), archives.holds('1', '2')))
        raise _Stop()
    monkeypatch.setattr(PostProcessor.PostProcessor, '_locked_process', lambda self: self._process_main())
    monkeypatch.setattr(PostProcessor.archives, 'prepare', lambda folder: (('pack', '/dl/Supergirl 007'), []))
    monkeypatch.setattr(PostProcessor.db, 'DBConnection', stop)
    for name in ('fdebug', 'info'):
        monkeypatch.setattr(PostProcessor.logger, name, lambda *a, **k: None)
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp.nzb_name, pp.nzb_folder, pp.module, pp.log = 'Supergirl 007 (2017).zip', '/dl', '[PP]', ''
    pp.comicid, pp.issueid, pp.apicall, pp.ddl, pp.pack = '93160', '585070', False, True, False
    with pytest.raises(_Stop):
        pp.Process()
    assert seen == [(True, True)] and archives.JOBS == []


@pytest.mark.unit
def test_a_story_arc_download_holds_its_series():
    assert archives.own_issue('585070', True, False) == '585070'
    assert archives.own_issue('123_456', True, False) is None


def supergirl(issueid, **payload):
    return dict({'nzb_name': 'Supergirl 007 (2017) [__%s__].cbz' % issueid, 'comicid': '93160',
                 'issueid': issueid, 'ddl': True}, **payload)


def wanted(issueid, number):
    return {'comicid': '93160', 'issueid': issueid, 'comicname': 'Supergirl', 'issuenumber': number}


@pytest.mark.unit
def test_filing_a_single_issue_holds_only_that_issue(filing):
    mylar.PP_QUEUE.put(supergirl('585070', pack=False))
    assert not worker.held(wanted('585072', '9'))
    assert worker.held(wanted('585070', '7'))


@pytest.mark.unit
def test_a_running_single_issue_job_holds_only_that_issue(filing):
    archives.JOBS.append(('93160', '585070'))
    assert not worker.held(wanted('585072', '9'))
    assert worker.held(wanted('585070', '7'))


@pytest.mark.unit
@pytest.mark.parametrize('payload', [
    # JD2 packs carry the searched issue's id, not the issues inside
    {'pack': True, 'download_info': {'provider': 'JD2', 'id': 'x'}},
    # a non-zip DDL pack carries the item's issueid too
    {'pack': True, 'download_info': {'provider': 'DDL', 'id': 'x'}},
    # pack status unknown, or a payload from before the flag
    {'pack': None},
    {},
    # usenet/torrent/api downloads aren't DDL
    {'pack': False, 'ddl': False},
])
def test_anything_but_a_known_single_issue_holds_the_series(filing, payload):
    mylar.PP_QUEUE.put(supergirl('585070', **payload))
    assert worker.held(wanted('585072', '9'))


class FakeDB:
    def __init__(self, pack):
        self.pack = pack

    def selectone(self, query, args):
        rows = [] if self.pack is None else [{'pack': self.pack}]
        return type('Cursor', (), {'fetchone': lambda _: rows[0] if rows else None})()


@pytest.mark.unit
@pytest.mark.parametrize('item, db_pack, expected', [
    ({'id': 'x'}, 1, True),
    ({'id': 'x'}, 0, False),
    ({'id': 'x'}, None, None),                                                  # nothing known
    ({'id': 'x', 'comicinfo': [{'pack': True}]}, None, True),
    ({'id': 'x', 'packinfo': {'pack': False}, 'comicinfo': [{'pack': False}]}, None, False),
    ({'id': 'x', 'comicinfo': [{'pack': False}]}, 1, True),                     # any pack sign wins
])
def test_pack_status_for_the_filing_payload(item, db_pack, expected):
    from mylar.queues import ddl
    assert ddl.is_pack(item, FakeDB(db_pack)) is expected


GHOSTBUSTERS = {'id': '170010', 'site': 'DDL(GetComics)', 'link_type': 'GC-Mega', 'link': 'https://mega.nz/file/x',
                'series': 'Ghostbusters', 'year': '2012', 'issueid': '461757', 'comicid': '52010', 'resume': None,
                'remote_filesize': 0}


def ddl_filing(monkeypatch, pack):
    """One finished non-zip DDL download through ddl_process; returns its filing payload."""
    from mylar.queues import ddl
    import types
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(POST_PROCESSING=True), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUED', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(mylar, 'PACK_ISSUEIDS_DONT_QUEUE', {}, raising=False)
    monkeypatch.setattr(ddl.helpers, 'check_file_condition', lambda path: {'status': True})
    monkeypatch.setattr(ddl, 'ddl_cleanup', lambda record_id: None)
    for name in ('info', 'fdebug'):
        monkeypatch.setattr(ddl.logger, name, lambda *a, **k: None)

    class Mega(object):
        def ddl_download(self, link, filename, id, issueid, site):
            return {'success': True, 'filename': 'Ghostbusters (v01-v09) (2012-2014).cbz', 'path': '/downloads/ddl'}
    monkeypatch.setattr(ddl.mega, 'MegaNZ', Mega)
    db = types.SimpleNamespace(upsert=lambda *a, **k: None, selectone=FakeDB(None).selectone)
    ddl.ddl_process(db, dict(GHOSTBUSTERS, comicinfo=[{'pack': pack}]))
    return mylar.PP_QUEUE.get_nowait()


@pytest.mark.unit
@pytest.mark.parametrize('pack', [True, False])
def test_a_ddl_download_says_whether_it_is_a_pack(filing, monkeypatch, pack):
    job = ddl_filing(monkeypatch, pack)
    assert job['pack'] is pack and job['issueid'] == '461757'
    mylar.PP_QUEUE.put(job)
    # a pack holds every other issue of the series; a single issue only holds itself
    assert worker.held({'comicid': '52010', 'issueid': '461760', 'comicname': 'Ghostbusters', 'issuenumber': '4'}) is pack


@pytest.mark.unit
@pytest.mark.parametrize('extra, db_pack, expected', [
    ({'comicinfo': [{'pack': True}], 'packinfo': {'pack': True}}, None, True),
    ({}, 1, True),                                  # restarted job: only ddl_info knows
    ({}, None, None),                               # nothing knows
    ({'comicinfo': [{'pack': False}]}, 0, False),
])
def test_a_jd2_download_says_whether_it_is_a_pack(filing, monkeypatch, extra, db_pack, expected):
    import types
    from mylar.queues import jd2
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(POST_PROCESSING=True, JD2_DEST_DIR='/downloads/jd'), raising=False)

    class Client(object):
        def status(self, job_id, record_id):
            return {'found': True, 'status': 'Finished', 'data': {'name': 'Ghostbusters (v01-v09) (2012-2014) GetComics.INFO.zip'}}

        def remove(self, job_id, record_id):
            pass
    monkeypatch.setattr(jd2, 'JDownloader2', Client)
    monkeypatch.setattr(jd2.db, 'DBConnection', lambda: types.SimpleNamespace(upsert=lambda *a, **k: None,
                                                                             selectone=FakeDB(db_pack).selectone))
    for name in ('info', 'warn', 'debug'):
        monkeypatch.setattr(jd2.logger, name, lambda *a, **k: None)
    q = queue.Queue()
    q.put(dict(GHOSTBUSTERS, jd2_job_id='1791766601125', filename='Ghostbusters (2012)', **extra))
    q.put('exit')
    jd2.jd2_queue_monitor(q)
    job = mylar.PP_QUEUE.get_nowait()
    assert job['pack'] is expected and job['issueid'] == '461757'
    mylar.PP_QUEUE.put(job)
    assert worker.held({'comicid': '52010', 'issueid': '461760', 'comicname': 'Ghostbusters', 'issuenumber': '4'}) is not (expected is False)
