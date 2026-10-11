import inspect
import types

import pytest

import mylar
from mylar import getcomics
from mylar.downloaders import mediafire, mega, pixeldrain


class FakeResponse:
    def __init__(self, chunks):
        self.chunks = chunks

    def iter_content(self, chunk_size=1):
        for c in self.chunks:
            yield c


class FakeDB:
    def __init__(self):
        self.upserts = []

    def upsert(self, table, vals, ctrl):
        self.upserts.append(vals)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_LOCATION=str(tmp_path)), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    fake_db = FakeDB()
    for module in (mediafire, pixeldrain):
        monkeypatch.setattr(module.db, 'DBConnection', lambda *a, **k: fake_db)
    return fake_db


def pixel(tmp_path, chunks, record_id='344'):
    p = pixeldrain.PixelDrain.__new__(pixeldrain.PixelDrain)
    p.dl_location = str(tmp_path)
    p.headers = {}
    p.id = record_id
    p.session = types.SimpleNamespace(get=lambda *a, **k: FakeResponse(chunks))
    return p


def fire(tmp_path, chunks):
    m = mediafire.MediaFire.__new__(mediafire.MediaFire)
    m.dl_location = str(tmp_path)
    m.headers = {}
    m.session = types.SimpleNamespace(get=lambda *a, **k: FakeResponse(chunks))
    return m


@pytest.mark.unit
def test_pixeldrain_records_the_full_path(env, tmp_path):
    p = pixel(tmp_path, [b'abc'])
    result = p.pixel_ddl('HqyZnRrC', {'filename': 'Kick-Ass 3 02 (2013).cbz', 'filesize': 3}, '420643')
    path = str(tmp_path / 'Kick-Ass 3 02 (2013)[__420643__].cbz')
    assert {'tmp_filename': path} in env.upserts
    assert result['success'] is True


@pytest.mark.unit
def test_pixeldrain_stops_when_aborted(env, tmp_path):
    mylar.DDL_CANCEL.add('344')
    p = pixel(tmp_path, [b'abc', b'def'])
    result = p.pixel_ddl('HqyZnRrC', {'filename': 'Kick-Ass 3 02 (2013).cbz', 'filesize': 6}, '420643')
    assert result['success'] is False
    assert not (tmp_path / 'Kick-Ass 3 02 (2013)[__420643__].cbz').exists()


@pytest.mark.unit
def test_mediafire_records_the_full_path(env, tmp_path):
    m = fire(tmp_path, [b'abc'])
    result = m.mediafire_dl('https://www.mediafire.com/x', '54429', {'filename': 'Age of Ultron 001.cbz', 'filesize': 3}, '390442')
    assert {'tmp_filename': str(tmp_path / 'Age of Ultron 001.cbz')} in env.upserts
    assert result['success'] is True


@pytest.mark.unit
def test_mediafire_stops_when_aborted(env, tmp_path):
    mylar.DDL_CANCEL.add('54429')
    m = fire(tmp_path, [b'abc', b'def'])
    result = m.mediafire_dl('https://www.mediafire.com/x', '54429', {'filename': 'Age of Ultron 001.cbz', 'filesize': 6}, '390442')
    assert result['success'] is False
    assert not (tmp_path / 'Age of Ultron 001.cbz').exists()


@pytest.mark.unit
def test_mega_stops_when_aborted(monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_CANCEL', {'54429'}, raising=False)
    m = mega.MegaNZ.__new__(mega.MegaNZ)
    m.id = '54429'
    m.wrote_tmp = True
    with pytest.raises(getcomics.DownloadCancelled):
        m.testing({'current': 1, 'total': 10, 'tmp_filename': '/tmp/megapy_x', 'name': 'x.zip', 'status': 'downloading'})


@pytest.mark.unit
def test_mega_download_has_a_timeout():
    from mega.mega import Mega
    assert 'requests.get(file_url, stream=True, timeout=(30, 30))' in inspect.getsource(Mega._download_file)
