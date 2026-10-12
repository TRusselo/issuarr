"""Clear finished / Clear failed on Downloads > Queue: ddl_clear deletes only those ddl_info rows."""
import json

import cherrypy
import pytest

import mylar
from mylar import db
from mylar.webserve import WebInterface

ROWS = [('1', 'Completed'), ('2', 'Completed'), ('3', 'Failed'), ('4', 'Queued'),
        ('5', 'Downloading'), ('6', 'Incomplete'), ('7', 'Checking')]


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set())
    d = db.DBConnection()
    d.action('CREATE TABLE ddl_info (ID TEXT UNIQUE, series TEXT, status TEXT, issueid TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, Status TEXT)')
    d.action('CREATE TABLE snatched (IssueID TEXT, Status TEXT)')
    for rid, status in ROWS:
        d.action('INSERT INTO ddl_info VALUES (?, ?, ?, ?)', [rid, 'Series %s' % rid, status, 'iss%s' % rid])
        d.action('INSERT INTO issues VALUES (?, ?)', ['iss%s' % rid, 'Downloaded'])
        d.action('INSERT INTO snatched VALUES (?, ?)', ['iss%s' % rid, 'Snatched'])
    return d


@pytest.fixture
def method(monkeypatch):
    def set_method(m):
        monkeypatch.setattr(cherrypy.request, 'method', m, raising=False)
    set_method('POST')
    return set_method


def statuses(d):
    return sorted((r['ID'], r['status']) for r in d.select('SELECT ID, status FROM ddl_info'))


def clear(status):
    return json.loads(WebInterface().ddl_clear(status=status))


@pytest.mark.unit
def test_clear_finished_deletes_only_completed_rows(myDB, method):
    r = clear('Completed')
    assert r['status'] is True
    assert r['message'] == 'Cleared 2 finished downloads from the list'
    assert statuses(myDB) == [(rid, s) for rid, s in ROWS if s != 'Completed']


@pytest.mark.unit
def test_clear_failed_deletes_only_failed_rows(myDB, method):
    r = clear('Failed')
    assert r['message'] == 'Cleared 1 failed download from the list'
    assert statuses(myDB) == [(rid, s) for rid, s in ROWS if s != 'Failed']


@pytest.mark.unit
def test_clear_leaves_issue_status_and_snatched_alone(myDB, method, monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set())
    clear('Completed')
    clear('Failed')
    assert [r['Status'] for r in myDB.select('SELECT Status FROM issues')] == ['Downloaded'] * len(ROWS)
    assert [r['Status'] for r in myDB.select('SELECT Status FROM snatched')] == ['Snatched'] * len(ROWS)
    assert mylar.DDL_CANCEL == set()


@pytest.mark.unit
@pytest.mark.parametrize('status', ['Queued', 'Downloading', 'Incomplete', 'Checking', 'completed', '',
                                    None, "Completed' OR 1=1 --", ['Completed', 'Failed']])
def test_clear_rejects_other_statuses(myDB, method, status):
    r = clear(status)
    assert r['status'] is False
    assert statuses(myDB) == sorted(ROWS)


@pytest.mark.unit
def test_clear_refuses_get(myDB, method):
    method('GET')
    with pytest.raises(cherrypy.HTTPError) as e:
        clear('Completed')
    assert e.value.status == 405
    assert statuses(myDB) == sorted(ROWS)


@pytest.mark.unit
def test_clear_with_nothing_to_clear(myDB, method):
    clear('Failed')
    r = clear('Failed')
    assert r == {'status': True, 'message': 'There were no failed downloads to clear'}


@pytest.mark.unit
def test_clear_failed_keeps_a_download_still_stopping(myDB, method):
    # Stop marks the row Failed straight away, but its download thread runs until it sees DDL_CANCEL
    myDB.action('INSERT INTO ddl_info VALUES (?, ?, ?, ?)', ['8', 'Series 8', 'Failed', 'iss8'])
    mylar.DDL_CANCEL.update({'8', '4'})
    r = clear('Failed')
    assert r['message'] == ('Cleared 1 failed download from the list. '
                            '1 download is still stopping, so it stayed; try again in a moment')
    assert statuses(myDB) == sorted([(rid, s) for rid, s in ROWS if s != 'Failed'] + [('8', 'Failed')])
    assert mylar.DDL_CANCEL == {'8', '4'}


@pytest.mark.unit
def test_clear_failed_when_only_stopping_downloads_are_left(myDB, method):
    mylar.DDL_CANCEL.add('3')
    r = clear('Failed')
    assert r['message'] == 'Nothing was cleared. 1 download is still stopping, so it stayed; try again in a moment'
    assert ('3', 'Failed') in statuses(myDB)
    mylar.DDL_CANCEL.discard('3')   # the thread let go
    assert clear('Failed')['message'] == 'Cleared 1 failed download from the list'
    assert ('3', 'Failed') not in statuses(myDB)
