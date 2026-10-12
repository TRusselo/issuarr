"""The flow line: search, download and filing side by side, and what happened to each issue lately."""
import collections
import datetime
import json
import queue
import time
import types

import pytest

import mylar
from mylar import activity, archives, db
from mylar.queues import ddl, jd2


def ago(**kw):
    return (datetime.datetime.now() - datetime.timedelta(**kw)).strftime('%Y-%m-%d %H:%M:%S')


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ANNUALS_ON=False, UPCOMING_STORYARCS=False, EXTRA_TORZNABS=[],
                                                              DDL_LOCATION=str(tmp_path)), raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_CURRENT', None, raising=False)
    monkeypatch.setattr(mylar, 'SEARCHLOCK', False, raising=False)
    monkeypatch.setattr(mylar, 'PP_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'JD2_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'SCHED', None, raising=False)
    monkeypatch.setattr(ddl, 'GC_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'FAILOVER_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'PENDING', collections.deque())
    monkeypatch.setattr(ddl, 'ACTIVE', set())
    monkeypatch.setattr(jd2, 'HOLDING', [None])
    monkeypatch.setattr(activity, 'RECENT', collections.deque(maxlen=60))
    monkeypatch.setattr(archives, 'processing', lambda: False)
    monkeypatch.setattr(archives, 'ACTIVITY', {'state': 'Idle', 'detail': '', 'since': None, 'last': '', 'last_at': None, 'notes': []})
    for flag in ('USE_SABNZBD', 'USE_NZBGET', 'USE_BLACKHOLE', 'USE_QBITTORRENT', 'USE_DELUGE', 'USE_TRANSMISSION',
                 'USE_RTORRENT', 'USE_UTORRENT', 'USE_WATCHDIR'):
        monkeypatch.setattr(mylar, flag, False, raising=False)
    for name in ('fdebug', 'info', 'warn', 'error'):
        monkeypatch.setattr(activity.logger, name, lambda *a, **k: None)
    d = db.DBConnection()
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, ComicName TEXT, Issue_Number TEXT, Status TEXT, DateAdded TEXT, '
             'ReleaseDate TEXT, DigitalDate TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE storyarcs (IssueArcID TEXT, Status TEXT)')
    d.action('CREATE TABLE oneoffhistory (IssueID TEXT, Status TEXT)')
    d.action('CREATE TABLE snatched (IssueID TEXT, ComicName TEXT, Issue_Number TEXT, Size INTEGER, DateAdded TEXT, '
             'Status TEXT, FolderName TEXT, ComicID TEXT, Provider TEXT, Hash TEXT, crc TEXT)')
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicVersion TEXT, ComicYear TEXT)')
    d.action('CREATE TABLE ddl_info (ID TEXT UNIQUE, series TEXT, year TEXT, filename TEXT, size TEXT, issueid TEXT, site TEXT, '
             'jd2_job_id TEXT, comicid TEXT, link TEXT, status TEXT, updated_date TEXT, issues TEXT, pack INTEGER, link_type TEXT, '
             'tmp_filename TEXT, remote_filesize TEXT)')
    return d


def item(iid='1', name='Iron Man', number='18'):
    return {'issueid': iid, 'comicid': '100', 'comicname': name, 'issuenumber': number}


def ddl_row(d, qid, iid, status, series='Iron Man', updated=None, jd2_job=None, link_type='GC-Main'):
    d.action("INSERT INTO ddl_info (ID, series, issueid, comicid, status, updated_date, site, jd2_job_id, link_type) "
             "VALUES (?, ?, ?, '100', ?, ?, 'DDL(GetComics)', ?, ?)",
             [qid, series, iid, status, updated or ago(minutes=1)[:16], jd2_job, link_type])


@pytest.mark.unit
def test_a_search_that_sent_something_counts_as_found(myDB):
    started = time.time() - 30
    myDB.action("INSERT INTO snatched (IssueID, DateAdded, Status, Provider) VALUES ('1', ?, 'Snatched', 'DDL(GetComics)')", [ago(seconds=5)])
    activity.searched(item(), started)
    assert activity.RECENT[0]['outcome'] == 'found' and activity.RECENT[0]['provider'] == 'DDL(GetComics)'


@pytest.mark.unit
def test_an_older_grab_of_the_same_issue_doesnt_count(myDB):
    myDB.action("INSERT INTO snatched (IssueID, DateAdded, Status, Provider) VALUES ('1', ?, 'Snatched', 'DOGnzb')", [ago(days=3)])
    activity.searched(item(), time.time() - 30)
    assert activity.RECENT[0]['outcome'] == 'none'


@pytest.mark.unit
def test_an_empty_search_shows_on_the_issue_and_in_the_events(myDB):
    activity.searched(item(), time.time() - 30)
    out = activity.flow()
    assert out['issues']['1'] == {'stage': 'wanted', 'state': 'nothing', 'at': pytest.approx(time.time(), abs=5)}
    assert [(e['kind'], e['name'], e['number']) for e in out['events']] == [('nothing', 'Iron Man', '18')]


@pytest.mark.unit
def test_issue_already_on_disk_is_reported(myDB):
    activity.searched(item(), time.time(), on_disk=True)
    assert activity.flow()['events'][0]['kind'] == 'on_disk'


@pytest.mark.unit
def test_search_stage_shows_current_and_queue_places(myDB, monkeypatch):
    monkeypatch.setattr(mylar, 'SEARCH_CURRENT', item('1'))
    mylar.SEARCH_QUEUE.put(item('2', 'X-Factor', '4'))
    mylar.SEARCH_QUEUE.put(item('3', 'MAD', '601'))
    out = activity.flow()
    assert out['search']['current']['name'] == 'Iron Man' and out['search']['waiting'] == 2
    assert out['issues']['1']['state'] == 'searching'
    assert out['issues']['3'] == {'stage': 'search', 'state': 'waiting', 'place': 2}


@pytest.mark.unit
def test_search_waiting_on_filing_says_so(myDB, monkeypatch):
    from mylar.queues import search as worker
    monkeypatch.setattr(worker, 'HELD', {})
    mylar.SEARCH_QUEUE.put(item('2'))
    mylar.SEARCH_QUEUE.put(item('3'))
    worker.HELD['2'] = time.time()
    assert activity.flow()['search']['blocked'] is None          # 3 can search meanwhile
    worker.HELD['3'] = time.time()
    assert activity.flow()['search']['blocked'] == 'filing'


@pytest.mark.unit
def test_download_stage_tells_downloading_from_queued_and_jd2(myDB):
    ddl_row(myDB, 'a', '1', 'Downloading')
    ddl_row(myDB, 'b', '2', 'Queued', series='X-Factor')
    ddl_row(myDB, 'c', '3', 'Queued', series='MAD', jd2_job='17917')
    mylar.JD2_QUEUE.put({'id': 'c'})
    mylar.DDL_QUEUE.put({'id': 'b'})
    out = activity.flow()
    assert [n['via'] for n in out['download']['now']] == ['GetComics', 'JDownloader 2']
    assert out['download']['queued'] == 1 and not out['download']['stalled']
    assert out['issues']['1']['state'] == 'downloading'
    assert out['issues']['2']['state'] == 'queued'
    assert out['issues']['3']['state'] == 'jd2'


@pytest.mark.unit
def test_builtin_cloud_download_is_issuarrs_not_getcomics(myDB):
    ddl_row(myDB, 'a', '1', 'Downloading', link_type='GC-Mega')
    assert [n['via'] for n in activity.flow()['download']['now']] == ['Issuarr']


@pytest.mark.unit
def test_queued_downloads_with_nothing_moving_are_stalled(myDB):
    ddl_row(myDB, 'b', '2', 'Queued')
    assert activity.flow()['download']['stalled'] is True


@pytest.mark.unit
def test_rows_jd2_is_holding_are_not_stalled(myDB):
    # JD2's rows stay Queued while it works on them; the Queue page notice must not count them
    ddl_row(myDB, 'c', '3', 'Queued', jd2_job='17917')
    ddl_row(myDB, 'd', '4', 'Queued', jd2_job='17918')
    mylar.JD2_QUEUE.put({'id': 'c'})
    jd2.HOLDING[0] = 'd'
    assert activity.stalled_downloads(myDB) == 0
    assert activity.flow()['download']['stalled'] is False


@pytest.mark.unit
def test_a_stuck_row_next_to_jd2_work_is_still_stalled(myDB):
    ddl_row(myDB, 'b', '2', 'Queued')
    ddl_row(myDB, 'c', '3', 'Queued', jd2_job='17917')
    mylar.JD2_QUEUE.put({'id': 'c'})
    jd2.HOLDING[0] = 'c'
    # JD2 never picks up row b, so its job (stuck or not) doesn't hide b
    assert activity.stalled_downloads(myDB) == 1
    assert activity.flow()['download']['stalled'] is True
    ddl_row(myDB, 'a', '1', 'Downloading')
    assert activity.stalled_downloads(myDB) == 0


@pytest.mark.unit
def test_a_leftover_jd2_job_id_nothing_holds_counts_as_stalled(myDB):
    ddl_row(myDB, 'b', '2', 'Queued')
    ddl_row(myDB, 'c', '3', 'Queued', jd2_job='17917')     # JD2 no longer watching it
    assert activity.stalled_downloads(myDB) == 2


@pytest.mark.unit
def test_queued_rows_waiting_their_turn_are_not_stalled(myDB):
    ddl_row(myDB, 'b', '2', 'Queued')
    mylar.DDL_QUEUE.put({'id': 'b'})
    assert activity.stalled_downloads(myDB) == 0


@pytest.mark.unit
def test_a_ghost_row_is_stalled_even_while_others_wait_their_turn(myDB):
    ddl_row(myDB, 'b', '2', 'Queued')                       # in no queue: nothing will pick it up
    ddl_row(myDB, 'e', '5', 'Queued')
    ddl.GC_QUEUE.put({'id': 'e'})
    assert activity.stalled_downloads(myDB) == 1
    assert activity.flow()['download']['queued'] == 2


@pytest.mark.unit
def test_a_row_a_worker_or_failover_is_handling_is_not_stalled(myDB):
    # it stays Queued while its link is resolved or failover picks the next source
    ddl_row(myDB, 'b', '2', 'Queued')
    ddl.ACTIVE.add('b')
    assert activity.stalled_downloads(myDB) == 0
    ddl.ACTIVE.clear()
    ddl.PENDING.append({'id': 'b'})
    assert activity.stalled_downloads(myDB) == 0


@pytest.mark.unit
def test_jd2_rows_are_not_stalled_before_its_monitor_reloads_them(myDB, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'JD2_ENABLE', True, raising=False)
    monkeypatch.setattr(jd2, 'LOADED', jd2.threading.Event())
    ddl_row(myDB, 'c', '3', 'Queued', jd2_job='17917')
    assert activity.stalled_downloads(myDB) == 0
    assert activity.flow()['issues']['3']['state'] == 'jd2'
    jd2.LOADED.set()                                        # reloaded, and c wasn't among them
    assert activity.stalled_downloads(myDB) == 1


@pytest.mark.unit
def test_download_queue_json_carries_the_stalled_count(myDB, monkeypatch):
    from mylar import webserve
    ddl_row(myDB, 'b', '2', 'Queued')
    ddl_row(myDB, 'c', '3', 'Queued', jd2_job='17917')
    mylar.JD2_QUEUE.put({'id': 'c'})
    monkeypatch.setattr(webserve.downloadqueue, 'client_snatches', lambda d: [])
    out = json.loads(webserve.WebInterface().downloadQueue())
    assert {i['queueid'] for i in out['items'] if i['kind'] == 'ddl'} == {'b', 'c'}
    assert out['stalled'] == 1                                  # b only: JD2 is holding c
    mylar.JD2_QUEUE.get()
    assert json.loads(webserve.WebInterface().downloadQueue())['stalled'] == 2


@pytest.mark.unit
def test_a_download_in_flight_wins_over_an_old_empty_search(myDB):
    activity.searched(item(), time.time() - 600)
    ddl_row(myDB, 'a', '1', 'Queued')
    mylar.DDL_QUEUE.put({'id': 'a'})
    assert activity.flow()['issues']['1']['state'] == 'queued'


@pytest.mark.unit
def test_wanted_counts_tiers_and_events_run_newest_first(myDB):
    filed = ago(minutes=5)
    soon = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    myDB.action("INSERT INTO issues (IssueID, Status, DateAdded, ReleaseDate) VALUES ('1', 'Wanted', ?, NULL), ('2', 'Wanted', ?, NULL), "
                "('3', 'Downloaded', ?, NULL), ('5', 'Wanted', ?, ?)", [ago(days=1)[:10], ago(days=60)[:10], ago(days=1)[:10], ago(days=60)[:10], soon])
    myDB.action("INSERT INTO snatched (IssueID, ComicName, Issue_Number, DateAdded, Status, Provider) VALUES "
                "('3', 'Alpha', '1', ?, 'Snatched', 'DDL(GetComics)'), ('3', 'Alpha', '1', ?, 'Post-Processed', 'DDL(GetComics)')",
                [ago(minutes=20), filed])
    ddl_row(myDB, 'f', '4', 'Failed', series='Beta', updated=ago(minutes=10)[:16])
    out = activity.flow()
    assert out['wanted'] == {'count': 3, 'tier1': 1, 'soon': 1, 'next_out': soon}
    assert [e['kind'] for e in out['events']] == ['filed', 'failed', 'found']
    assert out['added_today'] == (1 if filed[:10] == ago()[:10] else 0)


@pytest.mark.unit
def test_a_pack_is_one_event(myDB):
    for n in range(1, 25):
        myDB.action("INSERT INTO snatched (IssueID, ComicID, ComicName, Issue_Number, DateAdded, Status, Provider) "
                    "VALUES (?, '2574', 'Jungle Action', ?, ?, 'Snatched', 'DDL(GetComics)')", [str(n), str(n), ago(minutes=3, seconds=n % 2)])
    myDB.action("INSERT INTO snatched (IssueID, ComicID, ComicName, Issue_Number, DateAdded, Status, Provider) "
                "VALUES ('99', '7', 'Beta', '1', ?, 'Post-Processed', 'DOGnzb')", [ago(minutes=1)])
    out = activity.flow()['events']
    assert [(e['kind'], e['name'], e['count'], e['number']) for e in out] == [('filed', 'Beta', 1, '1'), ('found', 'Jungle Action', 24, None)]
