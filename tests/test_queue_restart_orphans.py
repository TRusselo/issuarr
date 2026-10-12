"""Restart queue picks up rows left with a JD2 job id that JD2 no longer holds, the ones the stall notice counts."""
import collections
import queue
import threading
import types

import pytest

import mylar
from mylar import db, webserve
from mylar.queues import ddl, jd2


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_AUTORESUME=False, JD2_ENABLE=True), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'JD2_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(ddl, 'GC_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'FAILOVER_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'PENDING', collections.deque())
    monkeypatch.setattr(ddl, 'ACTIVE', set())
    monkeypatch.setattr(jd2, 'HOLDING', [None])
    loaded = threading.Event()
    loaded.set()
    monkeypatch.setattr(jd2, 'LOADED', loaded)
    d = db.DBConnection()
    d.action('CREATE TABLE ddl_info (ID TEXT UNIQUE, series TEXT, year TEXT, filename TEXT, size TEXT, issueid TEXT, comicid TEXT, '
             'link TEXT, status TEXT, remote_filesize TEXT, updated_date TEXT, mainlink TEXT, issues TEXT, site TEXT, '
             'submit_date TEXT, pack INTEGER, link_type TEXT, tmp_filename TEXT, jd2_job_id TEXT)')
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT)')
    d.action('CREATE TABLE storyarcs (IssueID TEXT)')
    return d


def ddl_row(d, rid, jd2_job=None):
    d.action("INSERT INTO ddl_info (ID, series, issueid, comicid, link, status, updated_date, site, link_type, jd2_job_id) "
             "VALUES (?, 'Iron Man', '1', '100', 'https://example.com/f', 'Queued', '2026-10-11 12:00', 'DDL(GetComics)', "
             "'Pixeldrain', ?)", [rid, jd2_job])


def job_id(d, rid):
    return d.selectone('SELECT jd2_job_id FROM ddl_info WHERE ID=?', [rid]).fetchone()['jd2_job_id']


def queued_ids():
    return [i['id'] for i in list(mylar.DDL_QUEUE.queue)]


def restart_queue():
    return webserve.WebInterface().ddl_requeue(mode='restart_queue')


@pytest.mark.unit
def test_restart_queue_hands_a_row_jd2_dropped_to_the_built_in_downloaders(myDB):
    ddl_row(myDB, 'b')
    ddl_row(myDB, 'c', jd2_job='17917')                     # JD2 no longer watching it
    restart_queue()
    assert sorted(queued_ids()) == ['b', 'c']
    assert job_id(myDB, 'c') is None


@pytest.mark.unit
def test_restart_queue_leaves_rows_jd2_holds(myDB):
    ddl_row(myDB, 'c', jd2_job='17917')
    ddl_row(myDB, 'd', jd2_job='17918')
    mylar.JD2_QUEUE.put({'id': 'c'})
    jd2.HOLDING[0] = 'd'
    restart_queue()
    assert queued_ids() == []
    assert (job_id(myDB, 'c'), job_id(myDB, 'd')) == ('17917', '17918')


@pytest.mark.unit
def test_restart_queue_waits_for_jd2_to_reload_its_rows(myDB):
    # at startup the DDL queue restarts before the JD2 monitor has put its saved rows back
    jd2.LOADED.clear()
    ddl_row(myDB, 'c', jd2_job='17917')
    restart_queue()
    assert queued_ids() == []
    assert job_id(myDB, 'c') == '17917'


@pytest.mark.unit
def test_with_jd2_off_every_jd2_row_is_dropped(myDB):
    jd2.LOADED.clear()
    mylar.CONFIG.JD2_ENABLE = False
    ddl_row(myDB, 'c', jd2_job='17917')
    restart_queue()
    assert queued_ids() == ['c']
