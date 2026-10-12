"""Downloads > Queue: a direct download says Finished only once post-processing has filed it."""
import json
import os
import queue
import types

import cherrypy
import pytest

import mylar
from mylar import archives, db, downloadqueue
from mylar.queues import postprocess


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(POST_PROCESSING=True, EXTRA_TORZNABS=[],
                        ARCHIVE_REVIEW_DIR=str(tmp_path / 'review'), JD2_DEST_DIR=str(tmp_path / 'jd')), raising=False)
    monkeypatch.setattr(mylar, 'PP_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(archives, 'DDL_FILING', {})
    for name in ('fdebug', 'info', 'warn', 'error'):
        monkeypatch.setattr(downloadqueue.logger, name, lambda *a, **k: None)
    downloadqueue._CACHE.update(at=0, key=None, data={}, busy=False)
    d = db.DBConnection()
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE storyarcs (IssueArcID TEXT, Status TEXT)')
    d.action('CREATE TABLE oneoffhistory (IssueID TEXT, ComicID TEXT, ComicName TEXT, IssueNumber TEXT, Status TEXT)')
    d.action('CREATE TABLE snatched (IssueID TEXT, ComicName TEXT, Issue_Number TEXT, Size INTEGER, DateAdded TEXT, '
             'Status TEXT, FolderName TEXT, ComicID TEXT, Provider TEXT, Hash TEXT, crc TEXT)')
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicVersion TEXT, ComicYear TEXT)')
    d.action('CREATE TABLE ddl_info (ID TEXT UNIQUE, series TEXT, year TEXT, filename TEXT, size TEXT, issueid TEXT, site TEXT, '
             'jd2_job_id TEXT, comicid TEXT, link TEXT, status TEXT, updated_date TEXT, issues TEXT, pack INTEGER, link_type TEXT)')
    d.action('CREATE TABLE attention (path TEXT PRIMARY KEY, reason TEXT, detail TEXT, comicid TEXT, status TEXT, added TEXT, size INTEGER)')
    d.action("INSERT INTO comics VALUES ('100', 'Alpha', NULL, '2020')")
    return d


def done(d, id, issueid, issue_status, pack=0, filename=None):
    """A direct download that has finished downloading (ddl_info says Completed); filename '' leaves it NULL, as JD2 does."""
    d.action("INSERT INTO ddl_info (ID, series, year, filename, issueid, comicid, status, updated_date, pack, link_type, site) "
             "VALUES (?, 'Alpha', '2020', ?, ?, '100', 'Completed', '2026-10-12 04:00', ?, 'GC-Main', 'DDL(GetComics)')",
             [id, ('Alpha 001 (2020)[__%s__].cbz' % issueid if filename is None else filename) or None, issueid, pack])
    if issue_status:
        d.action("INSERT INTO issues VALUES (?, '100', '1', ?)", [issueid, issue_status])


def flag(d, path, state='open'):
    """A file Needs attention lists; it has to exist, as the page drops rows whose file has gone."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'x')
    d.action("INSERT INTO attention (path, status, size) VALUES (?, ?, 1)", [path, state])


def status(d, id):
    row = {r['key']: r for r in downloadqueue.build(d)}['ddl-%s' % id]
    return row['status'], row['message']


@pytest.mark.unit
def test_downloaded_but_still_in_the_post_processing_queue_is_waiting_to_file(myDB):
    done(myDB, '7', '1043823', 'Snatched')
    mylar.PP_QUEUE.put({'nzb_name': 'Alpha 001.cbz', 'comicid': '100', 'download_info': {'provider': 'DDL', 'id': '7'}})
    assert status(myDB, '7') == ('Waiting to file', None)


@pytest.mark.unit
def test_jd2_download_in_the_post_processing_queue_is_waiting_to_file(myDB):
    done(myDB, '8', '5', 'Snatched')
    mylar.PP_QUEUE.put({'nzb_name': 'x', 'download_info': {'provider': 'JD2', 'id': 8, 'job_id': 'j'}})
    assert status(myDB, '8')[0] == 'Waiting to file'


@pytest.mark.unit
def test_taken_off_the_queue_but_waiting_for_its_turn_is_waiting_to_file(myDB):
    done(myDB, '7', '1', 'Snatched')
    archives.ddl_filing({'provider': 'DDL', 'id': '7'}, 'waiting')
    assert status(myDB, '7')[0] == 'Waiting to file'


@pytest.mark.unit
def test_being_post_processed_is_filing(myDB):
    done(myDB, '7', '1', 'Snatched')
    archives.ddl_filing({'provider': 'DDL', 'id': '7'}, 'filing')
    assert status(myDB, '7')[0] == 'Filing'


@pytest.mark.unit
def test_filed_issue_is_finished(myDB):
    done(myDB, '7', '1', 'Downloaded')
    done(myDB, '9', '2', 'Archived')
    assert status(myDB, '7') == ('Completed', None)
    assert status(myDB, '9') == ('Completed', None)


@pytest.mark.unit
def test_run_ended_without_filing_the_issue_is_not_filed(myDB):
    done(myDB, '7', '1', 'Snatched')
    st, note = status(myDB, '7')
    assert st == 'Not filed' and 'still Snatched' in note


@pytest.mark.unit
def test_file_left_in_needs_attention_is_not_filed(myDB, tmp_path):
    done(myDB, '7', '504912', 'Snatched')
    flag(myDB, str(tmp_path / 'mylar-dl' / 'Birds of Prey v01 (2012) [__504912__]' / 'Birds of Prey v01.cbr'))
    st, note = status(myDB, '7')
    assert st == 'Not filed' and 'Needs attention' in note


@pytest.mark.unit
def test_needs_attention_match_follows_what_that_page_lists(myDB, tmp_path):
    # a row whose file has gone isn't on the page; nor is an ignored file, until it changes
    done(myDB, '7', '11', 'Snatched')
    done(myDB, '8', '12', 'Snatched')
    done(myDB, '9', '13', 'Snatched')
    myDB.action("INSERT INTO attention (path, status) VALUES (?, 'open')", [str(tmp_path / 'gone [__11__].cbz')])
    flag(myDB, str(tmp_path / 'dl' / 'Alpha 002 [__12__].cbz'), state='ignored')
    flag(myDB, str(tmp_path / 'dl' / 'Alpha 003 [__13__].cbz'), state='ignored')
    myDB.action("UPDATE attention SET size = 5 WHERE path LIKE '%[__13__]%'")
    assert 'still Snatched' in status(myDB, '7')[1]
    assert 'still Snatched' in status(myDB, '8')[1]
    assert 'Needs attention' in status(myDB, '9')[1]
    assert myDB.select("SELECT COUNT(*) AS n FROM attention")[0]['n'] == 3   # reading the queue doesn't tidy the list


@pytest.mark.unit
def test_jd2_files_under_needs_attention_are_found_by_their_folder(myDB, tmp_path):
    # JD2 rows have no file name, so no [__id__] mark; their folder in JD2_DEST_DIR ends ' - <ddl id>'
    done(myDB, '4746', '267133', 'Snatched', pack=1, filename='')
    done(myDB, '110211', '692531', 'Snatched', filename='')
    done(myDB, '47', '700', 'Snatched', pack=1, filename='')
    flag(myDB, str(tmp_path / 'jd' / 'Beta (1994) - 4746' / 'Beta 02 (1994).cbr'))
    flag(myDB, str(tmp_path / 'jd' / 'Gamma (2001) - 110211' / 'Gamma 001.cbz'))
    flag(myDB, str(tmp_path / 'jd' / 'Delta (2001) - 474' / 'Delta 001.cbz'))
    assert status(myDB, '4746') == ('Not filed', "Filing couldn't place it. It's waiting under Needs attention.")
    assert 'Needs attention' in status(myDB, '110211')[1]
    assert status(myDB, '47')[0] == 'Completed'


@pytest.mark.unit
def test_file_filed_as_another_issue_says_so(myDB):
    done(myDB, '14364', '120334', 'Snatched', filename='Aliens Omnibus v01 (2007) (digital)[__113935__].cbr')
    myDB.action("INSERT INTO issues VALUES ('113935', '100', '1', 'Downloaded')")
    assert status(myDB, '14364') == ('Not filed', 'Filed as a different issue (#1); this issue is still Snatched.')


@pytest.mark.unit
def test_pack_is_finished_when_its_run_ends_unless_files_wait_in_needs_attention(myDB, tmp_path):
    done(myDB, 'p1', '206854', 'Snatched', pack=1, filename='Iron Man Noir (01-04) (2010) [__206854__].zip')
    done(myDB, 'p2', '158600', 'Snatched', pack=1, filename='JP-Raptors Hijack 01-04 (994)[__158600__].zip')
    flag(myDB, str(tmp_path / 'mylar-dl' / 'JP-Raptors Hijack 01-04 (994)[__158600__]' / 'JP #04 (1994).cbr'))
    archives.ddl_filing({'provider': 'DDL', 'id': 'p1'}, 'filing')
    assert status(myDB, 'p1')[0] == 'Filing'
    archives.ddl_filing({'provider': 'DDL', 'id': 'p1'}, None)
    assert status(myDB, 'p1')[0] == 'Completed'
    assert status(myDB, 'p2')[0] == 'Not filed'


@pytest.mark.unit
def test_post_processing_off_means_downloaded_is_finished(myDB):
    mylar.CONFIG.POST_PROCESSING = False
    done(myDB, '7', '1', 'Snatched')
    assert status(myDB, '7')[0] == 'Completed'


@pytest.mark.unit
def test_post_processing_worker_marks_a_direct_download_waiting_then_the_run_clears_it(monkeypatch):
    monkeypatch.setattr(archives, 'DDL_FILING', {})
    monkeypatch.setattr(mylar, 'APILOCK', False, raising=False)
    seen = []

    class FakeProcess:
        def __init__(self, *a, **kw):
            self.info = a[-1]

        def post_process(self):
            seen.append(dict(archives.DDL_FILING))
            archives.ddl_filing(self.info, None)

    monkeypatch.setattr(postprocess.process, 'Process', FakeProcess)
    monkeypatch.setattr(postprocess.time, 'sleep', lambda s: None)
    q = queue.Queue()
    q.put({'nzb_name': 'a', 'nzb_folder': '/x', 'failed': False, 'issueid': '1', 'comicid': '100', 'apicall': True,
           'ddl': True, 'download_info': {'provider': 'DDL', 'id': '7'}})
    q.put('exit')
    postprocess.postprocess_main(q)
    assert seen == [{'7': 'waiting'}] and archives.DDL_FILING == {}


@pytest.mark.unit
def test_clear_finished_keeps_downloads_not_filed_yet(myDB, monkeypatch):
    from mylar.webserve import WebInterface
    monkeypatch.setattr(cherrypy.request, 'method', 'POST', raising=False)
    done(myDB, '1', '11', 'Downloaded')
    done(myDB, '2', '12', 'Snatched')
    done(myDB, '3', '13', 'Snatched')
    archives.ddl_filing({'provider': 'DDL', 'id': '3'}, 'filing')
    r = json.loads(WebInterface().ddl_clear(status='Completed'))
    assert r['message'] == 'Cleared 1 finished download from the list. 2 downloads are not filed yet, so they stayed'
    assert sorted(x['ID'] for x in myDB.select('SELECT ID FROM ddl_info')) == ['2', '3']


@pytest.mark.unit
def test_post_processor_run_marks_its_download_filing_and_clears_it_after(monkeypatch):
    from mylar import PostProcessor
    monkeypatch.setattr(archives, 'DDL_FILING', {'7': 'waiting'})
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp.nzb_name, pp.comicid, pp.apicall = 'Alpha 001.cbz', '100', False
    pp.issueid, pp.ddl, pp.pack = '1', True, False
    pp.download_info = {'provider': 'DDL', 'id': '7'}
    seen = []
    monkeypatch.setattr(pp, '_locked_process', lambda: seen.append(dict(archives.DDL_FILING)), raising=False)
    pp.Process()
    assert seen == [{'7': 'filing'}] and archives.DDL_FILING == {}
