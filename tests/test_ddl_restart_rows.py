"""Rows a container restart must pick up again (What If? Vol. 2, 2026-10-11)."""
import sys
import types

import pytest

import mylar
from mylar import db
from mylar.queues import ddl


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE ddl_info (ID TEXT UNIQUE, series TEXT, status TEXT, jd2_job_id TEXT, updated_date TEXT)')
    return d


@pytest.fixture
def requeued(monkeypatch):
    calls = []

    class WebInterface:
        def ddl_requeue(self, mode):
            calls.append(mode)
    fake = types.SimpleNamespace(WebInterface=WebInterface)
    monkeypatch.setattr(mylar, 'webserve', fake, raising=False)
    monkeypatch.setitem(sys.modules, 'mylar.webserve', fake)
    return calls


def row(d, rid):
    return d.selectone('SELECT status, jd2_job_id FROM ddl_info WHERE ID=?', [rid]).fetchone()


@pytest.mark.unit
def test_restart_picks_up_a_download_that_once_went_through_jd2(myDB, requeued):
    # JD2 gave up, the built-in downloader took it, the container restarted mid-download
    myDB.action("INSERT INTO ddl_info VALUES ('400586', 'What If? Vol. 2', 'Downloading', '1791742045856', '2026-10-11 14:47')")
    ddl.reload_saved(myDB)
    assert tuple(row(myDB, '400586')) == ('Queued', None)
    assert requeued == ['restart_queue']


@pytest.mark.unit
def test_restart_leaves_jobs_jd2_is_still_doing_to_jd2(myDB, requeued):
    myDB.action("INSERT INTO ddl_info VALUES ('344', 'Kick-Ass 3', 'Queued', '1791742287277', '2026-10-11 12:11')")
    ddl.reload_saved(myDB)
    assert tuple(row(myDB, '344')) == ('Queued', '1791742287277')
    assert requeued == []


@pytest.mark.unit
def test_built_in_download_clears_an_old_jd2_job_id(monkeypatch):
    upserts = []
    fake_db = types.SimpleNamespace(upsert=lambda table, vals, ctrl: upserts.append(vals))
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(POST_PROCESSING=True), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUED', set(), raising=False)
    item = {'id': '400586', 'series': 'What If? Vol. 2', 'site': 'DDL(GetComics)', 'link_type': 'GC-Nowhere'}
    ddl.ddl_process(fake_db, item)
    assert upserts[0]['status'] == 'Downloading'
    assert 'jd2_job_id' in upserts[0] and upserts[0]['jd2_job_id'] is None
