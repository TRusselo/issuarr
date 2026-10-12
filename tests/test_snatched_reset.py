"""Snatched issues whose download is gone go back to Wanted (Deadpool Team-Up, Jungle Action, 2026-10-12).

Removing or stopping a direct download before it finished left its issues Snatched for good, and
so did grabs lost to a restart or to JD2. Removing now puts them back; the Wanted page can reset
the ones already stuck.
"""
import datetime
import json
import os
import queue
import types

import cherrypy
import pytest

import mylar
from mylar import archives, db, downloadqueue
from mylar.queues import ddl, jd2
from mylar.webserve import WebInterface

NOW = datetime.datetime(2026, 10, 12, 10, 0)
OLD = '2026-10-11 22:41:45'      # well over STUCK_HOURS before NOW
RECENT = '2026-10-12 08:30:00'


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        POST_PROCESSING=True, JD2_ENABLE=False, DDL_AUTORESUME=False, DDL_LOCATION=str(tmp_path / 'dl'), JD2_DEST_DIR=str(tmp_path / 'jd'),
        ARCHIVE_REVIEW_DIR=str(tmp_path / 'review')), raising=False)
    for name in ('PP_QUEUE', 'DDL_QUEUE', 'JD2_QUEUE'):
        monkeypatch.setattr(mylar, name, queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUED', set(), raising=False)
    monkeypatch.setattr(mylar, 'PACK_ISSUEIDS_DONT_QUEUE', {}, raising=False)
    monkeypatch.setattr(archives, 'DDL_FILING', {})
    monkeypatch.setattr(archives, 'JOBS', [])
    monkeypatch.setattr(jd2, 'HOLDING', [None])
    monkeypatch.setattr(ddl, 'ACTIVE', set())
    monkeypatch.setattr(ddl, 'PENDING', [])
    os.makedirs(str(tmp_path / 'dl'))
    d = db.DBConnection()
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, ComicName TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, ReleaseComicName TEXT, Issue_Number TEXT, Status TEXT, Deleted INTEGER DEFAULT 0)')
    d.action('CREATE TABLE storyarcs (IssueArcID TEXT, IssueID TEXT, Status TEXT)')
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT)')
    d.action('CREATE TABLE oneoffhistory (IssueID TEXT, ComicID TEXT, ComicName TEXT, IssueNumber TEXT, Status TEXT)')
    d.action('CREATE TABLE snatched (IssueID TEXT, ComicName TEXT, Issue_Number TEXT, DateAdded TEXT, Status TEXT, '
             'ComicID TEXT, Provider TEXT)')
    d.action('CREATE TABLE nzblog (IssueID TEXT, NZBName TEXT, SARC TEXT, PROVIDER TEXT, ID TEXT, AltNZBName TEXT, OneOff TEXT)')
    d.action('CREATE TABLE ddl_info (ID TEXT UNIQUE, series TEXT, year TEXT, filename TEXT, size TEXT, issueid TEXT, '
             'comicid TEXT, link TEXT, status TEXT, remote_filesize TEXT, updated_date TEXT, mainlink TEXT, issues TEXT, '
             'site TEXT, pack INTEGER, link_type TEXT, tmp_filename TEXT, jd2_job_id TEXT)')
    d.action('CREATE TABLE client_jobs (IssueID TEXT, IssueArcID TEXT, ComicID TEXT, Client TEXT, JobID TEXT, Name TEXT, DateAdded TEXT)')
    d.action('CREATE TABLE attention (path TEXT PRIMARY KEY, reason TEXT, detail TEXT, comicid TEXT, status TEXT, added TEXT, size INTEGER)')
    d.action("INSERT INTO comics VALUES ('29329', 'Deadpool Team-Up')")
    return d


@pytest.fixture
def method(monkeypatch):
    def set_method(m):
        monkeypatch.setattr(cherrypy.request, 'method', m, raising=False)
    set_method('POST')
    return set_method


def issue(d, iid, status='Snatched', number='1', snatched=OLD, provider='DDL(GetComics)', ddl_id=None, name='Deadpool Team-Up',
          comicid='29329'):
    d.action('INSERT INTO issues VALUES (?, ?, ?, ?, ?)', [iid, comicid, name, number, status])
    if snatched:
        d.action("INSERT INTO snatched VALUES (?, ?, ?, ?, 'Snatched', ?, ?)", [iid, name, number, snatched, comicid, provider])
    if ddl_id:
        d.action("INSERT INTO nzblog (IssueID, NZBName, PROVIDER, ID) VALUES (?, ?, ?, ?)", [iid, name, provider, ddl_id])


def download(d, rid, iid, status='Queued', pack=0, filename=None, jd2_job=None):
    d.action('INSERT INTO ddl_info (ID, series, issueid, comicid, status, pack, filename, jd2_job_id, site, link_type) '
             "VALUES (?, ?, ?, '29329', ?, ?, ?, ?, 'DDL(GetComics)', 'GC-Main')",
             [rid, 'Deadpool Team-Up #%s' % rid, iid, status, pack, filename, jd2_job])


def statuses(d):
    return {r['IssueID']: r['Status'] for r in d.select('SELECT IssueID, Status FROM issues')}


def requeue(mode, id=None):
    return json.loads(WebInterface().ddl_requeue(mode, id=id))


def stuck(d):
    return [i['issueid'] for i in downloadqueue.stuck_snatched(d, now=NOW)]


# ---- removing a download -------------------------------------------------

@pytest.mark.unit
def test_removing_an_unfinished_download_puts_its_issue_back_to_wanted(myDB):
    issue(myDB, '589801', ddl_id='49915')
    download(myDB, '49915', '589801')
    r = requeue('remove', id='49915')
    assert statuses(myDB) == {'589801': 'Wanted'}
    assert r['message'].endswith('. Its issue is back to Wanted')
    assert myDB.select('SELECT * FROM ddl_info') == []


@pytest.mark.unit
def test_removing_a_pack_puts_every_issue_it_snatched_back_but_not_ones_already_downloaded(myDB):
    # nzblog ties each pack issue to the ddl_info id, so this works after a restart too
    for n, iid in enumerate(('267133', '263881', '261346'), start=883):
        issue(myDB, iid, number=str(n), ddl_id='4746')
    issue(myDB, '252998', status='Downloaded', number='886', ddl_id='4746')
    issue(myDB, '999', number='900')    # another grab of the same series
    download(myDB, '4746', '267133', pack=1, jd2_job='1791799656622')
    mylar.PACK_ISSUEIDS_DONT_QUEUE.update({'263881': '4746', '261346': '4746', '999': '5000'})
    r = requeue('remove', id='4746')
    assert statuses(myDB) == {'267133': 'Wanted', '263881': 'Wanted', '261346': 'Wanted', '252998': 'Downloaded', '999': 'Snatched'}
    assert r['message'].endswith('. 3 issues are back to Wanted')
    # left in the map, the download thread would mark them Skipped when it drops the pack
    assert mylar.PACK_ISSUEIDS_DONT_QUEUE == {'999': '5000'}


@pytest.mark.unit
def test_removing_a_finished_download_leaves_its_issue_alone(myDB):
    issue(myDB, '1044777', ddl_id='330191')
    download(myDB, '330191', '1044777', status='Completed', filename='Daredevil 004 [__1044777__].cbz')
    r = requeue('remove', id='330191')
    assert statuses(myDB) == {'1044777': 'Snatched'}
    assert 'Wanted' not in r['message']


@pytest.mark.unit
def test_stopping_a_download_marks_it_failed_and_puts_its_issue_back(myDB):
    issue(myDB, '912138', ddl_id='270262')
    download(myDB, '270262', '912138', status='Downloading')
    requeue('abort', id='270262')
    assert statuses(myDB) == {'912138': 'Wanted'}
    assert myDB.selectone("SELECT status FROM ddl_info WHERE ID='270262'").fetchone()['status'] == 'Failed'
    assert '270262' in mylar.DDL_CANCEL


@pytest.mark.unit
def test_clear_the_queue_puts_queued_issues_back(myDB):
    issue(myDB, '1', ddl_id='10')
    issue(myDB, '2', ddl_id='20')
    issue(myDB, '3', ddl_id='30')
    download(myDB, '10', '1')
    download(myDB, '20', '2')
    download(myDB, '30', '3', status='Downloading')
    r = requeue('clear_queue')
    assert statuses(myDB) == {'1': 'Wanted', '2': 'Wanted', '3': 'Snatched'}
    assert r['message'] == 'Successfully cleared 2 items from the Queue. 2 issues are back to Wanted'


@pytest.mark.unit
def test_clear_failed_puts_still_snatched_issues_back_and_clear_finished_does_not(myDB, method):
    issue(myDB, '1', ddl_id='10')                       # stopped before this fix, so still Snatched
    issue(myDB, '2', status='Failed', ddl_id='20')      # every source failed: already Failed
    issue(myDB, '3', ddl_id='30')                       # finished, waiting to be filed
    download(myDB, '10', '1', status='Failed')
    download(myDB, '20', '2', status='Failed')
    download(myDB, '30', '3', status='Completed', filename='x [__3__].cbz')
    mylar.PP_QUEUE.put({'download_info': {'provider': 'DDL', 'id': '30'}})
    r = json.loads(WebInterface().ddl_clear(status='Failed'))
    assert r['message'] == 'Cleared 2 failed downloads from the list. 1 issue is back to Wanted'
    json.loads(WebInterface().ddl_clear(status='Completed'))
    assert statuses(myDB) == {'1': 'Wanted', '2': 'Failed', '3': 'Snatched'}


@pytest.mark.unit
def test_unsnatch_never_touches_issues_that_moved_on(myDB):
    for iid, status in (('1', 'Downloaded'), ('2', 'Archived'), ('3', 'Failed'), ('4', 'Skipped'), ('5', 'Snatched')):
        issue(myDB, iid, status=status)
    myDB.action("INSERT INTO annuals (IssueID, Status) VALUES ('6', 'Snatched')")
    assert downloadqueue.unsnatch(myDB, ['1', '2', '3', '4', '5', '6', None]) == ['5', '6']
    assert statuses(myDB) == {'1': 'Downloaded', '2': 'Archived', '3': 'Failed', '4': 'Skipped', '5': 'Wanted'}


# ---- issues already stuck ------------------------------------------------

@pytest.mark.unit
def test_stuck_lists_old_snatches_nothing_is_getting(myDB):
    issue(myDB, '12579', number='1', ddl_id='22597', name='Jungle Action')   # JD2 junk grab, row long gone
    issue(myDB, '589801', ddl_id='49915', name='Batgirl Annual')             # removed before this fix
    issue(myDB, '136635', snatched=OLD)                                      # no nzblog row at all
    assert sorted(stuck(myDB)) == ['12579', '136635', '589801']


@pytest.mark.unit
def test_stuck_leaves_out_downloads_still_on_their_way(myDB):
    # the Deadpool Team-Up pack at JD2: one ddl_info row, its issues tied to it by nzblog
    issue(myDB, '267133', number='883', ddl_id='4746')
    issue(myDB, '213653', number='893', ddl_id='4746')
    download(myDB, '4746', '267133', pack=1, jd2_job='1791799656622')
    issue(myDB, '2', ddl_id='20')
    download(myDB, '20', '2', status='Incomplete')
    issue(myDB, '3', snatched=RECENT)
    issue(myDB, '4', ddl_id='40')
    mylar.JD2_QUEUE.put({'id': '40'})                  # row already gone, JD2 still has it
    issue(myDB, '5')
    mylar.PACK_ISSUEIDS_DONT_QUEUE['5'] = '50'
    mylar.DDL_QUEUED.add('50')
    assert stuck(myDB) == []


@pytest.mark.unit
def test_stuck_leaves_out_downloads_waiting_to_be_filed(myDB, tmp_path):
    # downloaded before a restart lost post-processing's queue: the file is still there to file
    issue(myDB, '1044777', ddl_id='330191')
    download(myDB, '330191', '1044777', status='Completed', filename='Daredevil - Black Armor 004 (2024)[__1044777__].cbz')
    (tmp_path / 'dl' / 'Daredevil - Black Armor 004 (2024)[__1044777__].cbz').write_bytes(b'x')
    # a pack extracted to a folder, its other issue tied by nzblog
    issue(myDB, '158600', number='4', ddl_id='294227')
    issue(myDB, '246146', number='3', ddl_id='294227')
    download(myDB, '294227', '158600', status='Completed', pack=1, filename='JP-Raptors Hijack 01-04 (994)[__158600__].zip')
    os.makedirs(str(tmp_path / 'dl' / 'JP-Raptors Hijack 01-04 (994)[__158600__]'))
    # a JD2 download, in its ' - <id>' folder
    issue(myDB, '120334', ddl_id='14364')
    download(myDB, '14364', '120334', status='Completed')
    os.makedirs(str(tmp_path / 'jd' / 'Aliens Omnibus Vol. 2 (2007) - 14364'))
    # in post-processing's queue, or being filed
    issue(myDB, '7', ddl_id='70')
    download(myDB, '70', '7', status='Completed')
    archives.ddl_filing({'provider': 'DDL', 'id': '70'}, 'waiting')
    assert stuck(myDB) == []


@pytest.mark.unit
def test_stuck_leaves_out_a_series_post_processing_is_filing(myDB):
    issue(myDB, '1', comicid='100')
    issue(myDB, '2', comicid='200')
    mylar.PP_QUEUE.put({'comicid': '100', 'issueid': None, 'ddl': False})
    assert stuck(myDB) == ['2']


@pytest.mark.unit
def test_stuck_lists_a_finished_download_whose_file_is_gone(myDB):
    issue(myDB, '1', ddl_id='10')
    download(myDB, '10', '1', status='Completed', filename='Alpha 001 [__1__].cbz')
    assert stuck(myDB) == ['1']


@pytest.mark.unit
def test_stuck_leaves_out_files_in_needs_attention(myDB, tmp_path):
    issue(myDB, '504912', ddl_id='20337')
    download(myDB, '20337', '504912', status='Completed', filename='Birds of Prey v01 (2012) [__504912__]')
    path = str(tmp_path / 'review' / 'Birds of Prey v01 (2012) [__504912__]' / 'Birds of Prey v01.cbr')
    os.makedirs(os.path.dirname(path))
    with open(path, 'wb') as f:
        f.write(b'x')
    myDB.action("INSERT INTO attention (path, status, size) VALUES (?, 'open', 1)", [path])
    assert stuck(myDB) == []


@pytest.mark.unit
def test_stuck_leaves_client_grabs_alone(myDB):
    issue(myDB, '1', provider='experimental')            # an nzb grab: SABnzbd may still have it
    issue(myDB, '2', ddl_id='20')                        # a GetComics torrent handed to a client
    myDB.action("INSERT INTO client_jobs (IssueID, Client, JobID) VALUES ('2', 'qbittorrent', 'abc')")
    issue(myDB, '3', snatched=None)                      # no record of the grab
    assert stuck(myDB) == []


@pytest.mark.unit
def test_reset_puts_stuck_issues_back_to_wanted(myDB, method, monkeypatch):
    issue(myDB, '1', ddl_id='10')
    issue(myDB, '2', snatched=RECENT)
    issue(myDB, '3', status='Downloaded')
    real = downloadqueue.stuck_snatched
    monkeypatch.setattr(downloadqueue, 'stuck_snatched', lambda d: real(d, now=NOW))
    listed = json.loads(WebInterface().stuck_snatched())
    assert (listed['count'], listed['hours']) == (1, downloadqueue.STUCK_HOURS)
    assert [i['issueid'] for i in listed['issues']] == ['1']
    r = json.loads(WebInterface().reset_stuck_snatched())
    assert r == {'status': True, 'count': 1, 'message': 'Put 1 issue back to Wanted'}
    assert statuses(myDB) == {'1': 'Wanted', '2': 'Snatched', '3': 'Downloaded'}


@pytest.mark.unit
def test_reset_refuses_get(myDB, method):
    issue(myDB, '1', ddl_id='10')
    method('GET')
    with pytest.raises(cherrypy.HTTPError) as e:
        WebInterface().reset_stuck_snatched()
    assert e.value.status == 405
    assert statuses(myDB) == {'1': 'Snatched'}
