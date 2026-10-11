import types

import pytest

import mylar
from mylar import db, webserve


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(), raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE storyarcs (IssueArcID TEXT, Status TEXT)')
    d.action('CREATE TABLE oneoffhistory (IssueID TEXT, Status TEXT)')
    d.action('CREATE TABLE snatched (IssueID TEXT, ComicName TEXT, Issue_Number TEXT, Size INTEGER, DateAdded TEXT, '
             'Status TEXT, FolderName TEXT, ComicID TEXT, Provider TEXT, Hash TEXT, crc TEXT)')
    return d


def snatch(d, iid, status, provider, when, issue_status=None):
    d.action("INSERT INTO snatched (IssueID, ComicName, Issue_Number, DateAdded, Status, ComicID, Provider) "
             "VALUES (?, 'Alpha', '1', ?, ?, '100', ?)", [iid, when, status, provider])
    if issue_status:
        d.action("INSERT INTO issues (IssueID, ComicID, Issue_Number, Status) VALUES (?, '100', '1', ?)", [iid, issue_status])


@pytest.mark.unit
def test_waiting_usenet_grab_is_listed(myDB):
    snatch(myDB, '1', 'Snatched', 'DOGnzb', '2026-10-11 10:00:00', 'Snatched')
    out = webserve.client_snatches(myDB)
    assert [(r['issueid'], r['provider']) for r in out] == [('1', 'DOGnzb')]


@pytest.mark.unit
def test_processed_failed_and_ddl_grabs_are_not(myDB):
    snatch(myDB, '1', 'Snatched', 'DOGnzb', '2026-10-11 10:00:00', 'Downloaded')
    snatch(myDB, '1', 'Post-Processed', 'DOGnzb', '2026-10-11 10:30:00')
    snatch(myDB, '2', 'Snatched', 'WWT', '2026-10-11 10:00:00', 'Failed')
    snatch(myDB, '3', 'Snatched', 'DDL(GetComics)', '2026-10-11 10:00:00', 'Snatched')
    assert webserve.client_snatches(myDB) == []


@pytest.mark.unit
def test_story_arc_grab_uses_arc_status(myDB):
    snatch(myDB, '55_1', 'Snatched', 'DEM', '2026-10-11 10:00:00')
    myDB.action("INSERT INTO storyarcs (IssueArcID, Status) VALUES ('55_1', 'Snatched')")
    assert [r['issueid'] for r in webserve.client_snatches(myDB)] == ['55_1']
    myDB.action("UPDATE storyarcs SET Status = 'Downloaded'")
    assert webserve.client_snatches(myDB) == []


@pytest.mark.unit
def test_untracked_grab_falls_back_to_snatch_history(myDB):
    snatch(myDB, '9', 'Snatched', 'experimental', '2026-10-11 10:00:00')
    assert len(webserve.client_snatches(myDB)) == 1
    snatch(myDB, '9', 'Downloaded', 'experimental', '2026-10-11 11:00:00')
    assert webserve.client_snatches(myDB) == []
