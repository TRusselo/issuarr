"""Finished direct downloads a restart left unfiled go back to post-processing (2026-10-12 04:31).

Fourteen downloads were waiting for another post-processing run when the container restarted;
the wait was in memory, so their issues stayed Snatched with the files sitting in mylar-dl.
"""
import os
import queue
import types

import pytest

import mylar
from mylar import archives, db, downloadqueue
from mylar.queues import ddl


@pytest.fixture
def env(monkeypatch, tmp_path):
    dl, jd = tmp_path / 'mylar-dl', tmp_path / 'jdownloader'
    dl.mkdir()
    jd.mkdir()
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        POST_PROCESSING=True, DDL_LOCATION=str(dl) + os.sep, JD2_DEST_DIR=str(jd), ENABLE_CHECK_FOLDER=False,
        CHECK_FOLDER=None, ARCHIVE_REVIEW_DIR=str(tmp_path / 'review')), raising=False)
    monkeypatch.setattr(mylar, 'PP_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(archives, 'DDL_FILING', {})
    monkeypatch.setattr(ddl, 'REFILED', ddl.threading.Event())
    for name in ('fdebug', 'info', 'warn'):
        monkeypatch.setattr(ddl.logger, name, lambda *a, **k: None)
    d = db.DBConnection()
    d.action('CREATE TABLE ddl_info (ID TEXT UNIQUE, series TEXT, year TEXT, filename TEXT, size TEXT, issueid TEXT, '
             'comicid TEXT, link TEXT, status TEXT, remote_filesize TEXT, updated_date TEXT, mainlink TEXT, issues TEXT, '
             'site TEXT, submit_date TEXT, pack INTEGER, link_type TEXT, tmp_filename TEXT, jd2_job_id TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE storyarcs (IssueArcID TEXT, IssueID TEXT, Status TEXT)')
    d.action('CREATE TABLE oneoffhistory (IssueID TEXT, ComicID TEXT, ComicName TEXT, IssueNumber TEXT, Status TEXT)')
    d.action('CREATE TABLE attention (path TEXT PRIMARY KEY, reason TEXT, detail TEXT, comicid TEXT, status TEXT, added TEXT, size INTEGER)')
    return types.SimpleNamespace(db=d, dl=dl, jd=jd)


def finished(env, rid, issueid, name, status='Snatched', pack=0, tmp=True, jd2=None, series='Punisher', table='issues'):
    path = os.path.join(str(env.dl), name) if name else None
    env.db.action('INSERT INTO ddl_info (ID, series, year, filename, issueid, comicid, status, pack, link_type, site, '
                  "tmp_filename, jd2_job_id) VALUES (?, ?, '2024', ?, ?, '9', 'Completed', ?, 'GC-Main', 'DDL(GetComics)', ?, ?)",
                  [rid, series, None if jd2 else name, issueid, pack, path if tmp and not jd2 else None, jd2])
    if status:
        env.db.action('INSERT INTO %s (IssueID, Status) VALUES (?, ?)' % table, [issueid, status])
    return path


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'x')


def queued():
    out = []
    while not mylar.PP_QUEUE.empty():
        out.append(mylar.PP_QUEUE.get_nowait())
    return out


@pytest.mark.unit
def test_a_finished_download_the_restart_left_snatched_goes_back_to_post_processing(env):
    path = finished(env, '331566', '1046271', 'Punisher 004 (2024) (Digital) (Walkabout-Empire)[__1046271__].cbz')
    touch(path)
    assert ddl.refile_unfiled(env.db) == 1
    assert queued() == [{'nzb_name': os.path.basename(path), 'nzb_folder': path, 'failed': False, 'issueid': '1046271',
                         'comicid': '9', 'apicall': True, 'ddl': True, 'pack': False,
                         'download_info': {'provider': 'DDL', 'id': '331566'}}]


@pytest.mark.unit
def test_reload_saved_refiles_once_per_start(env):
    touch(finished(env, '331566', '1046271', 'Punisher 004[__1046271__].cbz'))
    ddl.reload_saved(env.db)
    ddl.reload_saved(env.db)  # the DDL queue restarted, or the JD2 worker asked too
    assert len(queued()) == 1


@pytest.mark.unit
@pytest.mark.parametrize('status', ['Downloaded', 'Archived'])
def test_an_issue_already_filed_is_left_alone(env, status):
    touch(finished(env, '1', '11', 'Alpha 001[__11__].cbz', status=status))
    touch(finished(env, '2', '12', 'Alpha 002[__12__].cbz', status=status, table='annuals'))
    assert ddl.refile_unfiled(env.db) == 0
    assert queued() == []


@pytest.mark.unit
def test_filed_anywhere_counts_even_if_another_table_still_says_snatched(env):
    touch(finished(env, '1', '11', 'Alpha 001[__11__].cbz'))
    env.db.action("INSERT INTO storyarcs VALUES ('a1', '11', 'Downloaded')")
    assert ddl.refile_unfiled(env.db) == 0


@pytest.mark.unit
def test_a_download_whose_file_is_gone_is_left_as_not_filed(env):
    finished(env, '14364', '113935', 'Aliens Omnibus v01 (2007)[__113935__].cbr', tmp=False)
    assert ddl.refile_unfiled(env.db) == 0
    assert queued() == []


@pytest.mark.unit
def test_a_zip_that_was_unpacked_is_filed_from_its_folder_as_ddl_process_would(env):
    # tmp_filename still names the .zip, which getcomics deleted after unpacking it
    path = finished(env, '294227', '158600', 'JP-Raptors Hijack 01-04 (994)[__158600__].zip', pack=1)
    folder = os.path.join(str(env.dl), 'JP-Raptors Hijack 01-04 (994)[__158600__]')
    touch(os.path.join(folder, 'JP-Raptors Hijack 01-04 (994)', 'JP-Raptors Hijack #01 (1994).cbr'))
    assert not os.path.exists(path)
    assert ddl.refile_unfiled(env.db) == 1
    assert queued() == [{'nzb_name': os.path.basename(folder), 'nzb_folder': folder, 'failed': False, 'issueid': None,
                         'comicid': '9', 'apicall': True, 'ddl': True, 'pack': True,
                         'download_info': {'provider': 'DDL', 'id': '294227'}}]


@pytest.mark.unit
def test_a_bare_file_name_is_found_in_the_download_folder_and_megas(env):
    finished(env, '1', '11', 'Alpha 001[__11__].cbz', tmp=False)
    touch(os.path.join(str(env.dl), 'mega', 'Alpha 001[__11__].cbz'))
    ddl.refile_unfiled(env.db)
    assert queued()[0]['nzb_folder'] == os.path.join(str(env.dl), 'mega', 'Alpha 001[__11__].cbz')


@pytest.mark.unit
def test_a_finished_jd2_download_is_handed_off_like_the_jd2_monitor_does(env):
    finished(env, '110211', '692531', None, jd2='1791787097617', series='Legends of The Dark Knight Vol. 2')
    folder = os.path.join(str(env.jd), 'Legends of The Dark Knight Vol. 2 (2024) - 110211')
    touch(os.path.join(folder, 'Legends of The Dark Knight v02 (2018).cbr'))
    assert ddl.refile_unfiled(env.db) == 1
    assert queued() == [{'nzb_name': os.path.basename(folder), 'nzb_folder': folder, 'failed': False, 'issueid': '692531',
                         'comicid': '9', 'apicall': True, 'ddl': True, 'pack': False,
                         'download_info': {'provider': 'JD2', 'id': '110211', 'job_id': '1791787097617'}}]


@pytest.mark.unit
def test_a_jd2_folder_left_by_another_post_with_the_same_id_is_not_taken(env):
    # GetComics post ids repeat across volumes: only the JD2 job's own folder counts, and only for JD2 rows
    finished(env, '14364', '113935', 'Aliens Omnibus v01 (2007)[__113935__].cbr', tmp=False)
    touch(os.path.join(str(env.jd), 'Aliens Omnibus Vol. 2 (2007) - 14364', 'Aliens Omnibus v02.cbr'))
    assert ddl.refile_unfiled(env.db) == 0


@pytest.mark.unit
def test_nothing_is_queued_twice(env):
    touch(finished(env, '1', '11', 'Alpha 001[__11__].cbz'))
    touch(finished(env, '2', '12', 'Alpha 002[__12__].cbz'))
    mylar.PP_QUEUE.put({'nzb_name': 'x', 'download_info': {'provider': 'DDL', 'id': '1'}})
    archives.DDL_FILING['2'] = 'filing'
    assert ddl.refile_unfiled(env.db) == 0


@pytest.mark.unit
def test_files_waiting_under_needs_attention_are_left_there(env):
    path = finished(env, '1', '11', 'Alpha 001[__11__].cbz')
    touch(path)
    env.db.action("INSERT INTO attention (path, status, size) VALUES (?, 'open', 1)", [path])
    assert ddl.refile_unfiled(env.db) == 0


@pytest.mark.unit
def test_a_download_inside_the_monitored_folder_is_left_to_the_monitor(env):
    touch(finished(env, '1', '11', 'Alpha 001[__11__].cbz'))
    mylar.CONFIG.ENABLE_CHECK_FOLDER, mylar.CONFIG.CHECK_FOLDER = True, os.path.dirname(str(env.dl))
    assert ddl.refile_unfiled(env.db) == 0


@pytest.mark.unit
def test_nothing_happens_with_post_processing_off(env):
    touch(finished(env, '1', '11', 'Alpha 001[__11__].cbz'))
    mylar.CONFIG.POST_PROCESSING = False
    assert ddl.refile_unfiled(env.db) == 0
    mylar.CONFIG.POST_PROCESSING = True  # turned on later the same run, it still gets its one look
    assert ddl.refile_unfiled(env.db) == 1
