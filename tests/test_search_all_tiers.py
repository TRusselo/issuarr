import queue
import types

import pytest

import mylar
from mylar import config, db, search


@pytest.fixture
def wanted(monkeypatch, tmp_path):
    cfg = types.SimpleNamespace(**{k: v[2] for k, v in config._CONFIG_DEFINITIONS.items()})
    cfg.ENABLE_DDL = True
    cfg.ENABLE_GETCOMICS = True
    cfg.ANNUALS_ON = False
    cfg.SEARCH_STORYARCS = False
    cfg.FAILED_DOWNLOAD_HANDLING = False
    cfg.EXTRA_NEWZNABS = []
    cfg.EXTRA_TORZNABS = []
    monkeypatch.setattr(mylar, 'CONFIG', cfg, raising=False)
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'DB_FILE', str(tmp_path / 'mylar.db'), raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_TIER_DATE', '2026-09-27', raising=False)
    monkeypatch.setattr(mylar, 'SEARCHLOCK', False, raising=False)
    for name in ('fdebug', 'info', 'warn', 'error'):
        monkeypatch.setattr(search.logger, name, lambda *a, **k: None)
    monkeypatch.setattr(search, 'searchforissue_checker', lambda *a, **k: {'status': True})
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicPublisher TEXT, AlternateSearch TEXT, '
             'UseFuzzy TEXT, ComicVersion TEXT, AllowPacks TEXT, TorrentID_32P TEXT, Type TEXT, Corrected_Type TEXT, '
             'IgnoreType TEXT, Status TEXT, ComicName_Filesafe TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, ComicName TEXT, Issue_Number TEXT, Status TEXT, ReleaseDate TEXT, '
             'IssueDate TEXT, DigitalDate TEXT, DateAdded TEXT)')
    d.action("INSERT INTO comics (ComicID, ComicName, ComicYear, Type, Status) VALUES ('1', 'Alpha', '2020', 'Print', 'Active')")
    d.action("INSERT INTO issues VALUES ('new', '1', 'Alpha', '2', 'Wanted', '2026-10-01', '2026-10-01', '0000-00-00', '2026-10-01')")
    d.action("INSERT INTO issues VALUES ('old', '1', 'Alpha', '1', 'Wanted', '2020-01-01', '2020-01-01', '0000-00-00', '2020-01-01')")
    return d


def queued():
    return sorted(x['issueid'] for x in list(mylar.SEARCH_QUEUE.queue))


@pytest.mark.unit
def test_scheduled_search_queues_tier1_only(wanted):
    search.searchforissue()
    assert queued() == ['new']


@pytest.mark.unit
def test_search_all_queues_tier2_too(wanted):
    search.searchforissue(all_tiers=True)
    assert queued() == ['new', 'old']


@pytest.mark.unit
def test_search_all_skips_issues_already_queued(wanted):
    mylar.SEARCH_QUEUE.put({'issueid': 'new'})
    search.searchforissue(all_tiers=True)
    assert queued() == ['new', 'old']


@pytest.mark.unit
def test_search_all_runs_while_the_queue_is_busy_and_leaves_its_lock(wanted):
    mylar.SEARCHLOCK = True
    search.searchforissue(all_tiers=True)
    assert queued() == ['new', 'old']
    assert mylar.SEARCHLOCK is True


@pytest.mark.unit
def test_tier1_search_queues_while_an_issue_is_being_searched_and_leaves_its_lock(wanted):
    # The queue worker holds the lock for each issue it searches. A Tier 1 search (the scheduled
    # one, or the Wanted page's button) only fills the queue, so it used to be dropped for nothing.
    mylar.SEARCHLOCK = True
    search.searchforissue()
    assert queued() == ['new']
    assert mylar.SEARCHLOCK is True


@pytest.mark.unit
def test_tier1_search_skips_issues_already_queued(wanted):
    mylar.SEARCH_QUEUE.put({'issueid': 'new'})
    search.searchforissue()
    assert queued() == ['new']


@pytest.mark.unit
def test_a_single_issue_still_waits_for_the_lock(wanted):
    mylar.SEARCHLOCK = True
    assert search.searchforissue('new') == {'status': 'IN PROGRESS'}
