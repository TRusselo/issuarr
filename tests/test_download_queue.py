import types

import pytest

import mylar
from mylar import db, downloadqueue


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(SAB_HOST='http://sab:8080', SAB_APIKEY='k', EXTRA_TORZNABS=[]), raising=False)
    for flag in ('USE_SABNZBD', 'USE_NZBGET', 'USE_BLACKHOLE', 'USE_QBITTORRENT', 'USE_DELUGE', 'USE_TRANSMISSION',
                 'USE_RTORRENT', 'USE_UTORRENT', 'USE_WATCHDIR'):
        monkeypatch.setattr(mylar, flag, False, raising=False)
    for name in ('fdebug', 'info', 'warn', 'error'):
        monkeypatch.setattr(downloadqueue.logger, name, lambda *a, **k: None)
    downloadqueue._CACHE.update(at=0, key=None, data={}, busy=False)
    d = db.DBConnection()
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE storyarcs (IssueArcID TEXT, Status TEXT)')
    d.action('CREATE TABLE oneoffhistory (IssueID TEXT, Status TEXT)')
    d.action('CREATE TABLE snatched (IssueID TEXT, ComicName TEXT, Issue_Number TEXT, Size INTEGER, DateAdded TEXT, '
             'Status TEXT, FolderName TEXT, ComicID TEXT, Provider TEXT, Hash TEXT, crc TEXT)')
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicVersion TEXT, ComicYear TEXT)')
    d.action('CREATE TABLE ddl_info (ID TEXT UNIQUE, series TEXT, year TEXT, filename TEXT, size TEXT, issueid TEXT, site TEXT, jd2_job_id TEXT, '
             'comicid TEXT, link TEXT, status TEXT, updated_date TEXT, issues TEXT, pack INTEGER, link_type TEXT)')
    return d


def snatch(d, iid, status, provider, when, issue_status=None):
    d.action("INSERT INTO snatched (IssueID, ComicName, Issue_Number, DateAdded, Status, ComicID, Provider) "
             "VALUES (?, 'Alpha', '1', ?, ?, '100', ?)", [iid, when, status, provider])
    if issue_status:
        d.action("INSERT INTO issues (IssueID, ComicID, Issue_Number, Status) VALUES (?, '100', '1', ?)", [iid, issue_status])


@pytest.mark.unit
def test_waiting_usenet_grab_is_listed(myDB):
    snatch(myDB, '1', 'Snatched', 'DOGnzb', '2026-10-11 10:00:00', 'Snatched')
    out = downloadqueue.client_snatches(myDB)
    assert [(r['issueid'], r['provider']) for r in out] == [('1', 'DOGnzb')]


@pytest.mark.unit
def test_processed_failed_and_ddl_grabs_are_not(myDB):
    snatch(myDB, '1', 'Snatched', 'DOGnzb', '2026-10-11 10:00:00', 'Downloaded')
    snatch(myDB, '1', 'Post-Processed', 'DOGnzb', '2026-10-11 10:30:00')
    snatch(myDB, '2', 'Snatched', 'WWT', '2026-10-11 10:00:00', 'Failed')
    snatch(myDB, '3', 'Snatched', 'DDL(GetComics)', '2026-10-11 10:00:00', 'Snatched')
    assert downloadqueue.client_snatches(myDB) == []


@pytest.mark.unit
def test_story_arc_grab_uses_arc_status(myDB):
    snatch(myDB, '55_1', 'Snatched', 'DEM', '2026-10-11 10:00:00')
    myDB.action("INSERT INTO storyarcs (IssueArcID, Status) VALUES ('55_1', 'Snatched')")
    assert [r['issueid'] for r in downloadqueue.client_snatches(myDB)] == ['55_1']
    myDB.action("UPDATE storyarcs SET Status = 'Downloaded'")
    assert downloadqueue.client_snatches(myDB) == []


@pytest.mark.unit
def test_untracked_grab_falls_back_to_snatch_history(myDB):
    snatch(myDB, '9', 'Snatched', 'experimental', '2026-10-11 10:00:00')
    assert len(downloadqueue.client_snatches(myDB)) == 1
    snatch(myDB, '9', 'Downloaded', 'experimental', '2026-10-11 11:00:00')
    assert downloadqueue.client_snatches(myDB) == []


def ddl(d, id, issueid, comicid, series='Alpha 001 (2020)', status='Completed', **kw):
    d.action("INSERT INTO ddl_info (ID, series, year, size, issueid, comicid, status, updated_date, issues, pack, link_type) "
             "VALUES (?, ?, ?, ?, ?, ?, ?, '2026-10-11 10:00', ?, ?, 'GC-Main')",
             [id, series, kw.get('year', '2020'), kw.get('size'), issueid, comicid, status, kw.get('issues'), kw.get('pack', 0)])


@pytest.mark.unit
def test_ddl_queue_lists_annuals_arcs_and_unknown_items(myDB):
    myDB.action("INSERT INTO comics VALUES ('100', 'Alpha', NULL, '2020')")
    myDB.action("INSERT INTO issues (IssueID, ComicID, Issue_Number, Status) VALUES ('1', '100', '1', 'Downloaded')")
    myDB.action("INSERT INTO annuals (IssueID, ComicID, Issue_Number, Status) VALUES ('2', '100', '1', 'Downloaded')")
    ddl(myDB, 'a', '1', '100', size='20 MB ')
    ddl(myDB, 'b', '2', '100')
    ddl(myDB, 'c', '55_3', None, series='Arc Thing 003', year=None)
    ddl(myDB, 'd', '9', '100', series='Alpha 1-6', issues='1-6', pack=1)
    rows = {r['queueid']: r for r in downloadqueue.ddl_queue_rows(myDB)}
    assert rows['a']['series'] == 'Alpha #1 (2020)' and rows['a']['size'] == '20 MB' and rows['a']['comicid'] == '100'
    assert rows['b']['series'] == 'Alpha #1 (2020)'
    assert rows['c']['series'] == 'Arc Thing 003' and rows['c']['comicid'] is None
    assert rows['d']['series'] == 'Alpha 1-6 (2020)' and rows['d']['issue'] == '#1-6'


class FakeResp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


SAB_QUEUE = {'queue': {'kbpersec': '2048', 'slots': [
    {'nzo_id': 'SABnzbd_nzo_1', 'filename': 'Alpha 001 (2020)', 'status': 'Downloading', 'mb': '50', 'mbleft': '25', 'timeleft': '0:00:30'},
    {'nzo_id': 'SABnzbd_nzo_2', 'filename': 'Beta 002 (2020)', 'status': 'Queued', 'mb': '40', 'mbleft': '40', 'timeleft': '0:00:00'}]}}
SAB_HISTORY = {'history': {'slots': [
    {'nzo_id': 'SABnzbd_nzo_3', 'name': 'Gamma 003', 'status': 'Completed', 'bytes': 1000},
    {'nzo_id': 'SABnzbd_nzo_4', 'name': 'Delta 004', 'status': 'Failed', 'fail_message': 'Out of retention'}]}}


def fake_sab(monkeypatch):
    monkeypatch.setattr(downloadqueue.requests, 'get',
                        lambda url, params=None, **k: FakeResp(SAB_QUEUE if params['mode'] == 'queue' else SAB_HISTORY))


@pytest.mark.unit
def test_sab_queue_and_history_are_read(myDB, monkeypatch):
    fake_sab(monkeypatch)
    out = downloadqueue._sab()
    assert out['SABnzbd_nzo_1']['state'] == 'Downloading' and out['SABnzbd_nzo_1']['percent'] == 50
    assert out['SABnzbd_nzo_1']['eta'] == 30 and out['SABnzbd_nzo_1']['speed'] == 2048 * 1024
    assert out['SABnzbd_nzo_2']['state'] == 'Queued' and out['SABnzbd_nzo_2']['speed'] is None
    assert out['SABnzbd_nzo_3']['state'] == 'Processing'
    assert out['SABnzbd_nzo_4']['state'] == 'Failed' and out['SABnzbd_nzo_4']['message'] == 'Out of retention'


@pytest.mark.unit
def test_combined_list_has_direct_and_client_downloads(myDB, monkeypatch):
    monkeypatch.setattr(mylar, 'USE_SABNZBD', True)
    fake_sab(monkeypatch)
    myDB.action("INSERT INTO comics VALUES ('100', 'Alpha', NULL, '2020')")
    snatch(myDB, '1', 'Snatched', 'NZBgeek', '2026-10-11 10:00:00', 'Snatched')
    snatch(myDB, '2', 'Snatched', 'DOGnzb', '2026-10-11 10:05:00', 'Snatched')
    snatch(myDB, '3', 'Snatched', 'DOGnzb', '2026-10-11 10:06:00', 'Snatched')
    downloadqueue.record_job('1', None, '100', 'sabnzbd', 'SABnzbd_nzo_1', 'Alpha 001 (2020)')
    # no job recorded for issue 2: matched to the SAB job by its nzb name instead
    myDB.action("CREATE TABLE nzblog (IssueID TEXT, NZBName TEXT, SARC TEXT, PROVIDER TEXT, ID TEXT, AltNZBName TEXT, OneOff TEXT)")
    myDB.action("INSERT INTO nzblog (IssueID, NZBName, PROVIDER) VALUES ('2', 'Beta.002.(2020).nzb', 'DOGnzb')")
    ddl(myDB, 'd1', '1', '100', status='Downloading')
    rows = {r['key']: r for r in downloadqueue.build(myDB, active={'a_id': 'd1', 'percent': '40%', 'a_speed': '1.0 MB/s'})}
    assert rows['ddl-d1']['percent'] == 40 and rows['ddl-d1']['speed'] == '1.0 MB/s'
    one = rows['client-1']
    assert (one['source'], one['via'], one['status'], one['percent']) == ('SABnzbd', 'NZBgeek', 'Downloading', 50)
    assert one['speed'] == '2.0 MB/s' and one['eta'] == 'under 2 min left'
    assert rows['client-2']['status'] == 'Queued'
    assert rows['client-3']['status'] == 'Sent' and rows['client-3']['source'] == 'SABnzbd'


@pytest.mark.unit
def test_unreachable_client_still_lists_the_grab(myDB, monkeypatch):
    monkeypatch.setattr(mylar, 'USE_SABNZBD', True)

    def boom(*a, **k):
        raise IOError('connection refused')
    monkeypatch.setattr(downloadqueue.requests, 'get', boom)
    snatch(myDB, '1', 'Snatched', 'NZBgeek', '2026-10-11 10:00:00', 'Snatched')
    rows = downloadqueue.build(myDB)
    assert [(r['status'], r['source']) for r in rows] == [('Sent', 'SABnzbd')]


@pytest.mark.unit
def test_qbittorrent_states(monkeypatch):
    from mylar.torrent.clients import qbittorrent

    class Fake:
        def torrents(self, hashes):
            assert hashes == 'aa|bb|cc'
            return [{'hash': 'AA', 'name': 'x', 'progress': 0.5, 'size': 100, 'dlspeed': 10, 'eta': 5, 'state': 'downloading'},
                    {'hash': 'BB', 'name': 'y', 'progress': 1, 'size': 100, 'dlspeed': 0, 'eta': 8640000, 'state': 'stalledUP'},
                    {'hash': 'CC', 'name': 'z', 'progress': 0, 'size': 100, 'dlspeed': 0, 'eta': 8640000, 'state': 'pausedDL'}]
    monkeypatch.setattr(qbittorrent.TorrentClient, 'connect', lambda self, *a, **k: Fake())
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(QBITTORRENT_HOST='h', QBITTORRENT_USERNAME='u', QBITTORRENT_PASSWORD='p'))
    out = downloadqueue._qbittorrent(['aa', 'bb', 'cc'])
    assert (out['aa']['state'], out['aa']['percent'], out['aa']['eta']) == ('Downloading', 50, 5)
    assert out['bb']['state'] == 'Processing' and out['cc']['state'] == 'Paused'


@pytest.mark.unit
def test_every_active_direct_download_shows_progress(myDB, tmp_path):
    myDB.action('ALTER TABLE ddl_info ADD COLUMN tmp_filename TEXT')
    myDB.action('ALTER TABLE ddl_info ADD COLUMN remote_filesize TEXT')
    for did, done in (('d1', 25), ('d2', 50)):
        f = tmp_path / ('%s.cbz' % did)
        f.write_bytes(b'x' * done)
        myDB.action("INSERT INTO ddl_info (ID, series, status, site, link_type, tmp_filename, remote_filesize, updated_date) "
                    "VALUES (?, 'Alpha', 'Downloading', 'DDL(GetComics)', 'GC-Pixel', ?, '100', '2026-10-11 12:18')",
                    [did, str(f)])
    rates = []

    def rate(did, done, total):
        rates.append(did)
        return {'a_speed': '1.0 MB/s', 'a_progress': '%s of %s' % (done, total)}

    rows = {r['queueid']: r for r in downloadqueue.build(myDB, rate=rate) if r['kind'] == 'ddl'}
    assert rows['d1']['percent'] == 25
    assert rows['d2']['percent'] == 50
    assert rows['d1']['speed'] == '1.0 MB/s'
    assert sorted(rates) == ['d1', 'd2']


@pytest.mark.unit
def test_progress_finds_files_recorded_by_name_only(myDB, tmp_path):
    mylar.CONFIG.DDL_LOCATION = str(tmp_path)
    (tmp_path / 'Kick-Ass 3.zip').write_bytes(b'x' * 40)
    row = {'tmp_filename': 'Kick-Ass 3.zip', 'remote_filesize': '80', 'filename': None, 'size': '80 B'}
    assert downloadqueue.ddl_progress(row) == {'done': 40, 'total': 80, 'percent': 50}


@pytest.mark.unit
def test_progress_is_none_before_the_file_exists(myDB, tmp_path):
    mylar.CONFIG.DDL_LOCATION = str(tmp_path)
    assert downloadqueue.ddl_progress({'tmp_filename': None, 'filename': 'missing.cbz', 'remote_filesize': '80'}) is None


@pytest.mark.unit
def test_download_speed_is_tracked_per_download(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(downloadqueue.time, 'time', lambda: now[0])
    downloadqueue._DL_SAMPLE.clear()
    downloadqueue.download_rate('a', 0, 10 * 1048576)
    downloadqueue.download_rate('b', 0, 10 * 1048576)
    now[0] += 4
    a = downloadqueue.download_rate('a', 4 * 1048576, 10 * 1048576)
    b = downloadqueue.download_rate('b', 1048576, 10 * 1048576)
    assert a['a_speed'] == '1.0 MB/s'
    assert b['a_speed'] == '256 KB/s'


@pytest.mark.unit
def test_source_says_who_downloads_and_jd2_promises_no_host(myDB, monkeypatch):
    import queue
    from mylar.queues import jd2
    monkeypatch.setattr(mylar, 'JD2_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(jd2, 'HOLDING', [None])
    for qid, site, link_type, job in (('mega', 'DDL(GetComics)', 'GC-Mega', None),
                                      ('pixel', 'DDL(GetComics)', 'GC-Pixel', None),
                                      ('main', 'DDL(GetComics)', 'GC-Main', None),
                                      ('mirror', 'DDL(GetComics)', 'GC-Mirror', None),
                                      ('ia', 'DDL(Internet Archive)', None, None),
                                      ('handed', 'DDL(GetComics)', 'GC-Mega', None),
                                      ('jd2', 'DDL(GetComics)', 'GC-Media', '17917'),
                                      ('jd2-only', 'DDL(GetComics)', 'Unknown', '17918'),
                                      ('jd2-old', 'DDL(GetComics)', 'GC-Main', '17919')):
        myDB.action("INSERT INTO ddl_info (ID, series, status, site, link_type, jd2_job_id, updated_date) "
                    "VALUES (?, 'Alpha', 'Queued', ?, ?, ?, '2026-10-11 10:00')", [qid, site, link_type, job])
    mylar.JD2_QUEUE.put({'id': 'handed'})       # in the JD2 queue, no job id yet
    rows = {r['queueid']: (r['source'], r['via']) for r in downloadqueue.build(myDB) if r['kind'] == 'ddl'}
    assert rows['mega'] == ('Issuarr', 'Mega')
    assert rows['pixel'] == ('Issuarr', 'Pixeldrain')
    assert rows['main'] == ('GetComics', 'GetComics')
    assert rows['mirror'] == ('GetComics', 'GetComics mirror')
    assert rows['ia'][0] == 'Direct download'
    assert rows['handed'] == ('JDownloader 2', 'Mega or another mirror')
    assert rows['jd2'] == ('JDownloader 2', 'Mediafire or another mirror')
    assert rows['jd2-only'] == ('JDownloader 2', 'Any mirror')
    assert rows['jd2-old'] == ('JDownloader 2', 'Any mirror')
