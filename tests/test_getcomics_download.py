import types

import pytest

import mylar
from mylar import getcomics


class FakeResponse:
    def __init__(self, url, body):
        self.url = url
        self.headers = {'Content-length': str(len(body))}
        self._body = body

    def iter_content(self, chunk_size=1):
        yield self._body

    def close(self):
        pass


class FakeDB:
    def __init__(self):
        self.upserts = []

    def upsert(self, table, vals, ctrl):
        self.upserts.append(vals)


@pytest.fixture
def gc(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_LOCATION=str(tmp_path)), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUED', set(), raising=False)
    fake_db = FakeDB()
    monkeypatch.setattr(getcomics.db, 'DBConnection', lambda *a, **k: fake_db)
    g = getcomics.GC.__new__(getcomics.GC)
    g.headers = {}
    g.cookie_receipt = lambda *a, **k: None
    g.apply_file_clearance = lambda: None
    g.is_challenge = lambda t: False
    g.session = types.SimpleNamespace(
        get=lambda *a, **k: FakeResponse('https://getcomics.org/files/Star-Lord%20004%20(2017).cbz', b'comic'))
    g.fake_db = fake_db
    return g


@pytest.mark.unit
def test_getcomics_download_records_its_full_path(gc, tmp_path):
    result = gc.downloadit('49124', 'https://getcomics.org/dls/x', 'https://getcomics.org/p', issueid='587418')
    path = str(tmp_path / 'Star-Lord 004 (2017)[__587418__].cbz')
    assert result == {'success': True, 'filename': 'Star-Lord 004 (2017)[__587418__].cbz', 'path': path}
    assert {'tmp_filename': path} in gc.fake_db.upserts


@pytest.mark.unit
def test_getcomics_download_runs_even_if_the_old_lock_is_set(gc, monkeypatch):
    # the old global lock made a second download return None, which crashed the worker
    monkeypatch.setattr(mylar, 'DDL_LOCK', True, raising=False)
    result = gc.downloadit('2', 'https://getcomics.org/dls/y', 'https://getcomics.org/p', issueid='2')
    assert result is not None and result['success'] is True


@pytest.mark.unit
def test_user_agent_is_saved_under_the_cookie_lock(monkeypatch, tmp_path):
    entered = []

    class Lock:
        def __enter__(self):
            entered.append(True)

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(getcomics, '_COOKIE_LOCK', Lock(), raising=False)
    g = getcomics.GC.__new__(getcomics.GC)
    g.headers = {}
    g.session_path = str(tmp_path / '.gc_cookies.dat')
    g._save_ua('Mozilla/5.0')
    assert entered == [True]
    assert (tmp_path / '.gc_cookies.dat.ua').read_text() == 'Mozilla/5.0'
