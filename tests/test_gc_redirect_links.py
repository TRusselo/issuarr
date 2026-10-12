"""GetComics download buttons forward to the file host. Downloaders and JD2 get the host's address,
and a JD2 job that finishes on something that isn't a comic counts as failed."""
import queue
import types

import pytest

import mylar
from mylar import getcomics
from mylar.queues import ddl, jd2

BUTTON = 'https://getcomics.org/dls/m1JOiFByhY0r38X+JSeTVxrOd2/6qfF5DU=:dYD0cJrxz0f7w/l5E5L+1w=='
MEGA = 'https://mega.nz/file/b88jwJ4A#XY7ajFNzD_vJunyDxLw4ZnLDA6yD37JqIq-xGxxcfDc'


class Resp(object):
    def __init__(self, status, location=None, ctype='text/html'):
        self.status_code = status
        self.headers = {'Content-Type': ctype}
        if location:
            self.headers['Location'] = location

    def close(self):
        pass


def gc_with(monkeypatch, responses, cleared=True):
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.headers = {}
    calls = []

    def get(url, **kw):
        assert kw['allow_redirects'] is False
        calls.append(url)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    gc.session = types.SimpleNamespace(get=get)
    gc.cookie_receipt = lambda *a: None
    gc.apply_file_clearance = lambda: None
    gc.refresh_clearance = lambda url: cleared
    for name in ('fdebug', 'warn', 'info'):
        monkeypatch.setattr(getcomics.logger, name, lambda *a, **k: None)
    return gc, calls


@pytest.mark.unit
@pytest.mark.parametrize('link,button', [
    (BUTTON, True), ('https://getcomics.info/dls/abc', True), ('https://www.getcomics.org/dls/abc', True),
    (MEGA, False), ('https://getcomics.org/marvel/some-post/', False), (None, False),
])
def test_tells_a_download_button_from_a_real_address(link, button):
    assert getcomics.is_redirect_link(link) is button


@pytest.mark.unit
def test_a_button_resolves_to_where_it_forwards(monkeypatch):
    gc, calls = gc_with(monkeypatch, [Resp(302, MEGA)])
    assert gc.resolve_link(BUTTON) == MEGA
    assert calls == [BUTTON]   # the + and = in the token are sent as they are


@pytest.mark.unit
def test_a_button_that_forwards_to_another_button_is_followed(monkeypatch):
    gc, calls = gc_with(monkeypatch, [Resp(302, '/dls/second'), Resp(301, MEGA)])
    assert gc.resolve_link(BUTTON) == MEGA
    assert calls == [BUTTON, 'https://getcomics.org/dls/second']


@pytest.mark.unit
def test_a_real_address_is_left_alone(monkeypatch):
    gc, calls = gc_with(monkeypatch, [])
    assert gc.resolve_link(MEGA) == MEGA and calls == []


@pytest.mark.unit
def test_a_cloudflare_check_is_cleared_through_flaresolverr_once(monkeypatch):
    gc, calls = gc_with(monkeypatch, [Resp(403), Resp(302, MEGA)])
    assert gc.resolve_link(BUTTON) == MEGA and len(calls) == 2
    gc, calls = gc_with(monkeypatch, [Resp(403), Resp(403)])
    assert gc.resolve_link(BUTTON) is None and len(calls) == 2


@pytest.mark.unit
def test_a_button_that_goes_nowhere_resolves_to_nothing(monkeypatch):
    gc, _ = gc_with(monkeypatch, [Resp(200)], cleared=False)
    assert gc.resolve_link(BUTTON) is None
    import requests
    gc, _ = gc_with(monkeypatch, [requests.exceptions.ConnectionError('down')])
    assert gc.resolve_link(BUTTON) is None


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(POST_PROCESSING=True), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUED', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(ddl.logger, 'info', lambda *a, **k: None)
    mega_calls = []

    class Mega(object):
        def ddl_download(self, link, filename, id, issueid, site):
            mega_calls.append(link)
            return {'success': False, 'filename': None, 'path': None, 'link_type_failure': site}
    monkeypatch.setattr(ddl.mega, 'MegaNZ', Mega)
    return mega_calls


def mega_item():
    return {'id': '169176', 'site': 'DDL(GetComics)', 'link_type': 'GC-Mega', 'link': BUTTON, 'series': 'Injustice - Year Zero #3',
            'issueid': '786288', 'mainlink': 'https://getcomics.org/dc/injustice-year-zero-1-3-2020/', 'resume': None}


@pytest.mark.unit
def test_the_mega_downloader_gets_the_mega_address(worker, monkeypatch):
    monkeypatch.setattr(getcomics.GC, '__new__', lambda cls, *a, **k: types.SimpleNamespace(resolve_link=lambda l: MEGA))
    monkeypatch.setattr(getcomics.GC, '__init__', lambda self, *a, **k: None)
    ddl.ddl_process(types.SimpleNamespace(upsert=lambda *a, **k: None), mega_item())
    assert worker == [MEGA]


@pytest.mark.unit
def test_a_button_that_goes_nowhere_fails_over_without_trying_mega(worker, monkeypatch):
    monkeypatch.setattr(getcomics.GC, '__new__', lambda cls, *a, **k: types.SimpleNamespace(resolve_link=lambda l: None))
    monkeypatch.setattr(getcomics.GC, '__init__', lambda self, *a, **k: None)
    out = ddl.ddl_process(types.SimpleNamespace(upsert=lambda *a, **k: None), mega_item())
    assert worker == [] and out['success'] is False and out['link_type_failure'] == 'GC-Mega'


@pytest.mark.unit
def test_jd2_gets_host_addresses_and_loses_dead_buttons(monkeypatch):
    real = {BUTTON: MEGA, 'https://getcomics.org/dls/media': 'https://www.mediafire.com/file/x', 'https://getcomics.org/dls/dead': None}
    monkeypatch.setattr(getcomics.GC, '__new__', lambda cls, *a, **k: types.SimpleNamespace(resolve_link=real.get))
    monkeypatch.setattr(getcomics.GC, '__init__', lambda self, *a, **k: None)
    monkeypatch.setattr(jd2.logger, 'info', lambda *a, **k: None)
    links = {BUTTON: 'HIGHEST', 'https://getcomics.org/dls/media': 'HIGH', 'https://getcomics.org/dls/dead': 'DEFAULT'}
    assert jd2.resolve_links(links) == {MEGA: 'HIGHEST', 'https://www.mediafire.com/file/x': 'HIGH'}
    assert jd2.resolve_links({MEGA: 'HIGHEST'}) == {MEGA: 'HIGHEST'}
    assert jd2.resolve_links(None) is None


@pytest.mark.unit
@pytest.mark.parametrize('name,comic', [
    ('bootstrap4.bundle.min.js', False), ('index.html', False), ('Injustice - Year Zero 003 (2020).cbr', True),
    ('Jungle Action Vol. 2 #1-24.zip', True), ('X-Factor 003 (2020).CBZ', True), (None, True),
])
def test_what_counts_as_a_comic_from_jd2(name, comic):
    assert jd2.is_comic_name(name) is comic


def run_monitor(monkeypatch, filename):
    """One finished JD2 job through the monitor; returns (gave up on, post-processing queue)."""
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(POST_PROCESSING=True, JD2_DEST_DIR='/downloads/jd'), raising=False)
    monkeypatch.setattr(mylar, 'PP_QUEUE', queue.Queue(), raising=False)
    removed, gave_up = [], []

    class Client(object):
        def status(self, job_id, record_id):
            return {'found': True, 'status': 'Finished', 'data': {'name': filename}}

        def remove(self, job_id, record_id):
            removed.append(job_id)
    monkeypatch.setattr(jd2, 'JDownloader2', Client)
    monkeypatch.setattr(jd2.db, 'DBConnection', lambda: types.SimpleNamespace(upsert=lambda *a, **k: None, action=lambda *a, **k: None))
    monkeypatch.setattr(jd2, 'jd2_give_up', lambda myDB, item, record_id, reason: gave_up.append((record_id, reason)))
    for name in ('info', 'warn', 'debug'):
        monkeypatch.setattr(jd2.logger, name, lambda *a, **k: None)
    q = queue.Queue()
    q.put({'id': '169176', 'jd2_job_id': '1791766601125', 'series': 'Injustice - Year Zero #3', 'year': '2020',
           'filename': 'Injustice - Year Zero #3 (2020)', 'issueid': '786288', 'comicid': '129213'})
    q.put('exit')
    jd2.jd2_queue_monitor(q)
    return gave_up, removed, mylar.PP_QUEUE


@pytest.mark.unit
def test_a_jd2_job_that_finishes_on_a_script_fails_over_instead_of_filing(monkeypatch):
    gave_up, removed, pp = run_monitor(monkeypatch, 'bootstrap4.bundle.min.js')
    assert gave_up == [('169176', 'JD2 downloaded bootstrap4.bundle.min.js, not a comic')]
    assert removed == ['1791766601125'] and pp.empty()


@pytest.mark.unit
def test_a_jd2_job_that_finishes_on_a_comic_is_filed(monkeypatch):
    gave_up, removed, pp = run_monitor(monkeypatch, 'Injustice - Year Zero 003 (2020).cbr')
    assert gave_up == []
    job = pp.get_nowait()
    assert job['nzb_name'] == 'Injustice - Year Zero 003 (2020).cbr'
    assert job['nzb_folder'] == '/downloads/jd/Injustice - Year Zero #3 (2020) - 169176'
