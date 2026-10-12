"""A GetComics post's torrent or magnet link is a source like its file hosts, sent to the torrent client."""
import os
import queue
import types

import pytest
from bs4 import BeautifulSoup

import mylar
from mylar import ddlsources, downloadqueue, getcomics, rsscheck

SINGLE = '''<ul>
<li>Aliens Omnibus Vol. 4 (2008) (575 MB)<strong> :</strong><br /><a href="https://getcomics.org/dls/v4main"><span>Main Server</span></a> | <a href="magnet:?xt=urn:btih:abc"><span>Magnet</span></a></li>
</ul>'''

POST = '''<p style="text-align: center;"><strong>Aliens 1</strong><strong>Language</strong><strong>: English</strong><strong>Year</strong><strong>2020</strong><strong>Size</strong><strong>50 MB</strong></p>
<p style="text-align: center;"><div class="aio-pulse"><a href="https://getcomics.org/dls/main" title="Download Now">Download Now</a></div></p>
<p style="text-align: center;"><div class="aio-pulse"><a href="https://getcomics.org/dls/aliens.torrent" title="Torrent Link">Torrent</a></div></p>'''


@pytest.fixture(autouse=True)
def cfg(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        DDL_PRIORITY_ORDER='["main","pixeldrain","mega","mediafire","torrent"]', DDL_DISABLED_SOURCES='[]',
        DDL_MAIN_LARGE_LAST=False, DDL_MAIN_LARGE_MB=400, ENABLE_TORRENTS=True, ENABLE_TORRENT_SEARCH=True,
        AUTO_SNATCH=False, LOCAL_TORRENT_PP=False, CACHE_DIR=str(tmp_path)), raising=False)
    for f in ('USE_UTORRENT', 'USE_RTORRENT', 'USE_TRANSMISSION', 'USE_QBITTORRENT', 'USE_WATCHDIR'):
        monkeypatch.setattr(mylar, f, False, raising=False)
    monkeypatch.setattr(mylar, 'USE_DELUGE', True, raising=False)
    monkeypatch.setattr(mylar, 'SNATCHED_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(ddlsources, 'pixeldrain_fits', lambda b: True)


def gc(jd2=None):
    g = getcomics.GC.__new__(getcomics.GC)
    g.jd2, g.issueid, g.comicid, g.oneoff = jd2, '1', '100', False
    return g


def first(*order):
    mylar.CONFIG.DDL_PRIORITY_ORDER = '[%s]' % ','.join('"%s"' % o for o in order)


INFO = [{'ComicName': 'Aliens Omnibus', 'IssueNumber': '4', 'IssueID': '1', 'ComicID': '100', 'comyear': '2008'}]


@pytest.mark.unit
@pytest.mark.parametrize('label, href', [('Torrent', 'https://x/y'), ('Magnet Link', 'https://x/y'), ('Download', 'magnet:?xt=urn:btih:a'),
                                         ('Download', 'https://getcomics.org/f/aliens.torrent?k=1')])
def test_torrent_and_magnet_links_are_one_source(label, href):
    assert ddlsources.canonical(label, href) == 'torrent'


@pytest.mark.unit
def test_hosts_are_not_torrents():
    assert ddlsources.canonical('Mega Link', 'https://mega.nz/x') == 'mega'
    assert ddlsources.canonical('Download Now', 'https://getcomics.org/dls/a') == 'main'


@pytest.mark.unit
def test_torrent_is_last_by_default_and_listed_in_settings():
    assert ddlsources.DEFAULT_GROUPS[-1] == 'torrent'
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["main","mega"]'
    assert ddlsources.configured_groups() == ['direct', 'cloud', 'torrent']
    assert [s['name'] for s in ddlsources.all_sources()] == ['direct', 'cloud', 'torrent']


@pytest.mark.unit
def test_single_issue_uses_the_order():
    _, chosen = gc()._single_item(BeautifulSoup(SINGLE, 'html.parser'), INFO)
    assert chosen['source'] == 'main'
    first('torrent', 'main')
    _, chosen = gc()._single_item(BeautifulSoup(SINGLE, 'html.parser'), INFO)
    assert chosen['source'] == 'torrent' and chosen['links'].startswith('magnet:')


@pytest.mark.unit
def test_torrent_left_out_when_torrent_search_is_off():
    first('torrent', 'main')
    mylar.CONFIG.ENABLE_TORRENT_SEARCH = False
    entries, chosen = gc()._single_item(BeautifulSoup(SINGLE, 'html.parser'), INFO)
    assert chosen['source'] == 'main' and 'torrent' not in {e['source'] for e in entries}


@pytest.mark.unit
def test_torrent_left_out_without_a_torrent_client():
    first('torrent', 'main')
    mylar.USE_DELUGE = False
    assert ddlsources.torrent_ready() is False
    _, chosen = gc()._single_item(BeautifulSoup(SINGLE, 'html.parser'), INFO)
    assert chosen['source'] == 'main'


@pytest.mark.unit
def test_torrent_used_when_the_direct_link_failed():
    _, chosen = gc()._single_item(BeautifulSoup(SINGLE, 'html.parser'), INFO, ['GC-Main'])
    assert chosen['source'] == 'torrent'


def run_post(monkeypatch, tmp_path, sent, failures=None):
    os.makedirs(tmp_path / 'html_cache', exist_ok=True)
    (tmp_path / 'html_cache' / 'getcomics-p1.html').write_text(POST, encoding='utf-8')
    (tmp_path / 'html_cache' / 'getcomics-p1').write_text('', encoding='utf-8')  # the parser checks for this name before reading the .html
    calls, jobs, queued = [], [], []
    monkeypatch.setattr(rsscheck, 'torsend2client', lambda *a, **k: calls.append(a) or sent)
    monkeypatch.setattr(downloadqueue, 'record_job', lambda *a: jobs.append(a))
    g = gc()
    monkeypatch.setattr(g, '_queue_links', lambda links, *a: queued.append(links) or {'success': True, 'site': 'GC-Main'})
    monkeypatch.setattr(getcomics.db, 'DBConnection', lambda: types.SimpleNamespace(action=lambda *a: None))
    out = g.parse_downloadresults('p1', 'https://getcomics.org/aliens-1', [dict(INFO[0], pack=False)], None, failures)
    return out, calls, jobs, queued


@pytest.mark.unit
def test_whole_post_torrent_first_goes_to_the_client(monkeypatch, tmp_path):
    first('torrent', 'main')
    out, calls, jobs, queued = run_post(monkeypatch, tmp_path, {'hash': 'ABC', 'clientmode': 'deluge'})
    assert out == {'success': True, 'site': 'GC-Torrent', 'torrent': {'hash': 'ABC', 'clientmode': 'deluge'}}
    assert calls[0][3].endswith('aliens.torrent') and calls[0][4] == 'DDL(GetComics)'
    assert jobs == [('1', None, '100', 'deluge', 'ABC', 'Aliens 1')] and not queued


@pytest.mark.unit
def test_whole_post_direct_first_downloads_directly(monkeypatch, tmp_path):
    out, calls, _, queued = run_post(monkeypatch, tmp_path, {'hash': 'ABC'})
    assert out['site'] == 'GC-Main' and not calls and queued


@pytest.mark.unit
def test_client_refuses_the_torrent_so_the_direct_link_is_used(monkeypatch, tmp_path):
    first('torrent', 'main')
    out, calls, jobs, queued = run_post(monkeypatch, tmp_path, 'fail')
    assert len(calls) == 1 and not jobs and out['site'] == 'GC-Main' and queued


@pytest.mark.unit
def test_auto_snatch_watches_the_torrent(monkeypatch, tmp_path):
    first('torrent', 'main')
    mylar.CONFIG.AUTO_SNATCH = True
    run_post(monkeypatch, tmp_path, {'hash': 'ABC', 'clientmode': 'deluge'})
    assert mylar.SNATCHED_QUEUE.get_nowait() == {'issueid': '1', 'comicid': '100', 'hash': 'ABC'}
