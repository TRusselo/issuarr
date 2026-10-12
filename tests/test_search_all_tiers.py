import datetime
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
    d.action("INSERT INTO issues VALUES ('new', '1', 'Alpha', '2', 'Wanted', ?, ?, '0000-00-00', ?)", [day(-10), day(-10), day(-10)])
    d.action("INSERT INTO issues VALUES ('old', '1', 'Alpha', '1', 'Wanted', '2020-01-01', '2020-01-01', '0000-00-00', '2020-01-01')")
    return d


def day(offset):
    return (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()


def add(d, iid, release, added, digital='0000-00-00', status='Wanted'):
    d.action("INSERT INTO issues VALUES (?, '1', 'Alpha', ?, ?, ?, ?, ?, ?)", [iid, iid, status, release, release, digital, added])


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


@pytest.mark.unit
def test_an_issue_that_isnt_out_yet_isnt_searched(wanted):
    add(wanted, 'future', day(4), day(-60))
    search.searchforissue()
    search.searchforissue(all_tiers=True)
    assert 'future' not in queued()


@pytest.mark.unit
def test_an_issue_is_searched_from_its_release_day(wanted):
    add(wanted, 'today', day(0), day(-60))
    search.searchforissue()
    assert 'today' in queued()


@pytest.mark.unit
def test_an_early_digital_release_counts_as_out(wanted):
    add(wanted, 'digital', day(5), day(-60), digital=day(-1))
    search.searchforissue()
    assert 'digital' in queued()


@pytest.mark.unit
def test_an_issue_wanted_long_before_release_stays_tier1_after_it_comes_out(wanted):
    # added to Wanted two months ago from the solicits, came out 3 days ago
    add(wanted, 'recent', day(-3), day(-60))
    search.searchforissue()
    assert queued() == ['new', 'recent']


@pytest.mark.unit
def test_tier2_starts_cutoff_days_after_release(wanted):
    add(wanted, 'edge', day(-14), day(-60))
    add(wanted, 'past', day(-15), day(-60))
    search.searchforissue()
    assert 'edge' in queued() and 'past' not in queued()


@pytest.mark.unit
def test_marking_wanted_doesnt_search_what_isnt_out_yet(wanted):
    add(wanted, 'future', day(4), day(0))
    search.searchIssueIDList(['future', 'new'])
    assert queued() == ['new']
