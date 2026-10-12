"""The Internet Archive is the fourth download sources group; its torrents rank with the torrent group."""
import types

import pytest

import mylar
from mylar import archiveorg, ddlsources


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_PRIORITY_ORDER='["direct","cloud","torrent","ia"]', DDL_DISABLED_SOURCES='[]',
                                                              DDL_MAIN_LARGE_LAST=False, DDL_MAIN_LARGE_MB=400, ENABLE_ARCHIVEORG=True,
                                                              ENABLE_TORRENTS=True, ENABLE_TORRENT_SEARCH=True), raising=False)
    monkeypatch.setattr(mylar, 'USE_DELUGE', True, raising=False)
    monkeypatch.setattr(ddlsources, 'pixeldrain_fits', lambda b: True)


def one_issue_item():
    return {'identifier': 'ActionComics252', 'date': '1959'}, [
        {'name': 'Action Comics 252 (1959).cbr', 'source': 'original', 'size': '8940531'},
        {'name': 'Action Comics 252 (1959)_jp2.zip', 'source': 'derivative', 'size': '20000000'},
        {'name': 'ActionComics252_archive.torrent', 'source': 'metadata', 'size': '40000'}]


@pytest.mark.unit
def test_an_order_saved_before_the_internet_archive_gets_it_last():
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["torrent","direct","cloud"]'
    assert ddlsources.configured_groups() == ['torrent', 'direct', 'cloud', 'ia']
    assert [s['name'] for s in ddlsources.all_sources()][-1] == 'ia'


@pytest.mark.unit
def test_the_internet_archive_switch_is_enable_archiveorg():
    assert 'ia' not in ddlsources.disabled()
    mylar.CONFIG.ENABLE_ARCHIVEORG = False
    assert 'ia' in ddlsources.disabled()
    assert next(s for s in ddlsources.all_sources() if s['name'] == 'ia')['enabled'] is False
    # a stale "ia" in the disabled list doesn't override the switch
    mylar.CONFIG.ENABLE_ARCHIVEORG = True
    mylar.CONFIG.DDL_DISABLED_SOURCES = '["ia"]'
    assert 'ia' not in ddlsources.disabled()


@pytest.mark.unit
def test_getcomics_host_order_has_no_internet_archive_entry():
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["ia","direct","cloud","torrent"]'
    o = ddlsources.order()
    assert 'ia' not in o and o[0] == 'main' and o[-1] == 'torrent'


@pytest.mark.unit
@pytest.mark.parametrize('order, before', [('["ia","direct","cloud","torrent"]', True),
                                           ('["direct","cloud","torrent","ia"]', False),
                                           ('["direct","ia","cloud","torrent"]', False)])
def test_internet_archive_is_searched_before_getcomics_only_when_above_all_its_groups(order, before):
    mylar.CONFIG.DDL_PRIORITY_ORDER = order
    assert ddlsources.ia_before_getcomics() is before
    provs = ['32p', 'DDL(Internet Archive)', 'Experimental', 'DDL(GetComics)', 'nzbgeek']
    placed = ddlsources.place_ia(provs)
    gc = placed.index('DDL(GetComics)')
    assert placed.index('DDL(Internet Archive)') == (gc - 1 if before else gc + 1)
    assert [p for p in placed if 'Archive' not in p] == ['32p', 'Experimental', 'DDL(GetComics)', 'nzbgeek']


@pytest.mark.unit
def test_groups_getcomics_cant_use_dont_hold_the_internet_archive_back():
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["torrent","ia","direct","cloud"]'
    assert not ddlsources.ia_before_getcomics()
    mylar.CONFIG.ENABLE_TORRENT_SEARCH = False      # no torrents: the IA is above both groups left
    assert ddlsources.ia_before_getcomics()


@pytest.mark.unit
def test_without_getcomics_the_internet_archive_keeps_its_place():
    provs = ['DDL(Internet Archive)', 'Experimental']
    assert ddlsources.place_ia(provs) == provs


@pytest.mark.unit
def test_a_one_issue_item_offers_its_torrent():
    item, files = one_issue_item()
    e = next(archiveorg.entries_for(item, files, archiveorg.number_token('252'), 1959))
    assert e['torrent'] == 'https://archive.org/download/ActionComics252/ActionComics252_archive.torrent'


@pytest.mark.unit
def test_a_run_of_issues_never_offers_its_torrent():
    item = {'identifier': 'action-run', 'date': '1972'}
    files = [{'name': 'Action Comics %s.cbr' % n, 'source': 'original', 'size': '1'} for n in (401, 402, 403)]
    files.append({'name': 'action-run_archive.torrent', 'source': 'metadata'})
    e = next(archiveorg.entries_for(item, files, archiveorg.number_token('402'), 1972))
    assert e['torrent'] is None


def _queue(monkeypatch, sent_hash):
    calls = []
    monkeypatch.setattr(ddlsources, 'send_torrent', lambda *a: calls.append(a) or ({'hash': sent_hash} if sent_hash else None))
    puts = []
    monkeypatch.setattr(mylar, 'DDL_QUEUE', types.SimpleNamespace(put=puts.append), raising=False)
    monkeypatch.setattr(archiveorg.db, 'DBConnection', lambda: types.SimpleNamespace(upsert=lambda *a: None))
    info = [{'ComicName': 'Action Comics', 'IssueNumber': '252', 'comyear': '1959', 'IssueID': '9', 'ComicID': '1',
             'nzbtitle': 'Action Comics 252 (1959)', 'size': '8 MB', 'oneoff': False}]
    r = archiveorg.queue('IA-x', 'https://archive.org/download/a/b.cbr', info, 'https://archive.org/download/a/a_archive.torrent')
    return r, calls, puts


@pytest.mark.unit
def test_torrent_above_internet_archive_sends_the_torrent(monkeypatch):
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["direct","torrent","cloud","ia"]'
    r, calls, puts = _queue(monkeypatch, 'abc')
    assert r['site'] == 'IA-Torrent' and len(calls) == 1 and not puts


@pytest.mark.unit
def test_internet_archive_above_torrent_downloads_and_keeps_the_torrent_as_fallback(monkeypatch):
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["direct","cloud","ia","torrent"]'
    r, calls, puts = _queue(monkeypatch, 'abc')
    assert r['site'] == archiveorg.LINK_TYPE and not calls
    assert puts[0]['torrent'].endswith('_archive.torrent')


@pytest.mark.unit
def test_a_refused_torrent_falls_back_to_archive_org(monkeypatch):
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["torrent","ia","direct","cloud"]'
    r, calls, puts = _queue(monkeypatch, None)
    assert r['site'] == archiveorg.LINK_TYPE and len(calls) == 1 and puts[0]['torrent'] is None


@pytest.mark.unit
def test_failed_download_falls_back_to_the_torrent_only_when_torrents_are_on(monkeypatch):
    sent = []
    monkeypatch.setattr(ddlsources, 'send_torrent', lambda *a: sent.append(a) or {'hash': 'h'})
    item = {'torrent': 'https://archive.org/download/a/a_archive.torrent', 'series': 'Action Comics', 'issueid': '9',
            'comicid': '1', 'comicinfo': [{'IssueNumber': '252', 'comyear': '1959'}]}
    assert archiveorg.torrent_fallback(item) and sent[0][0] == 'Action Comics'
    mylar.CONFIG.DDL_DISABLED_SOURCES = '["torrent"]'
    assert not archiveorg.torrent_fallback(item)
    assert not archiveorg.torrent_fallback(dict(item, torrent=None))


@pytest.mark.unit
def test_saving_settings_with_the_internet_archive_on_records_its_provider(monkeypatch, tmp_path):
    # the provider table step used to crash on the Internet Archive, so settings were never written
    import sqlite3
    from mylar import config, db
    path = str(tmp_path / 'mylar.db')
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE provider_searches (id INTEGER UNIQUE, provider TEXT UNIQUE, type TEXT, lastrun INTEGER, active TEXT, hits INTEGER DEFAULT 0)')
    con.execute("INSERT INTO provider_searches VALUES (200, 'DDL(GetComics)', 'DDL', 0, '1', 3)")
    con.commit()
    monkeypatch.setattr(db, 'dbFilename', lambda filename='mylar.db': path)
    cfg = types.SimpleNamespace(PROVIDER_ORDER={'0': 'DDL(GetComics)', '1': 'DDL(Internet Archive)'}, EXTRA_NEWZNABS=[], EXTRA_TORZNABS=[])
    config.Config.write_out_provider_searches(cfg)
    rows = dict(sqlite3.connect(path).execute('SELECT provider, id FROM provider_searches').fetchall())
    assert rows == {'DDL(GetComics)': 200, 'DDL(Internet Archive)': 203}
