import json
import os

import pytest

import mylar
from mylar import imprints

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def quiet_log(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)


def _write(path, version, publishers=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'version': version, 'publishers': publishers or [{'X': []}]}, f)


def _no_network(monkeypatch):
    def fail(*a, **k):
        raise imprints.requests.exceptions.ConnectionError('offline')
    monkeypatch.setattr(imprints.requests, 'get', fail)


def test_bundled_listing_is_valid():
    data = imprints.load(None, ROOT, download=False)
    assert data is not None
    names = [list(p)[0] for p in data['publishers']]
    assert 'DC Comics' in names and 'Marvel' in names


def test_fresh_install_without_network_uses_bundled(tmp_path, monkeypatch):
    _no_network(monkeypatch)
    data = imprints.load(str(tmp_path / 'cache'), ROOT)
    assert data is not None
    assert data['version'] == imprints.load(None, ROOT, download=False)['version']


def test_fresh_install_downloads_listing(tmp_path, monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {'version': '99.0.0', 'publishers': [{'New': []}]}

    monkeypatch.setattr(imprints.requests, 'get', lambda *a, **k: Resp())
    data = imprints.load(str(tmp_path / 'cache'), ROOT)
    assert data['version'] == '99.0.0'
    assert os.path.exists(tmp_path / 'cache' / 'imprints.json')


def test_older_cached_copy_loses_to_bundled(tmp_path, monkeypatch):
    _no_network(monkeypatch)
    _write(str(tmp_path / 'cache' / 'imprints.json'), '0.1')
    data = imprints.load(str(tmp_path / 'cache'), ROOT)
    assert data['version'] != '0.1'


def test_bad_download_is_ignored(tmp_path, monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {'nope': True}

    monkeypatch.setattr(imprints.requests, 'get', lambda *a, **k: Resp())
    data = imprints.load(str(tmp_path / 'cache'), ROOT)
    assert data is not None and 'publishers' in data
    assert not os.path.exists(tmp_path / 'cache' / 'imprints.json')
