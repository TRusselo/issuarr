"""The search order lists only providers there is something to search on."""
import configparser
import types

import pytest

from mylar import config as cfg


def order(monkeypatch, **kw):
    monkeypatch.setattr(cfg, 'config', configparser.ConfigParser(), raising=False)
    me = types.SimpleNamespace(ENABLE_TORRENT_SEARCH=False, ENABLE_32P=False, EXPERIMENTAL=False, ENABLE_DDL=False,
                               ENABLE_GETCOMICS=False, ENABLE_ARCHIVEORG=False, ENABLE_EXTERNAL_SERVER=False, ENABLE_AIRDCPP=False,
                               NEWZNAB=False, EXTRA_NEWZNABS=[], ENABLE_TORZNAB=False, EXTRA_TORZNABS=[],
                               PROVIDER_ORDER=None, write_out_provider_searches=lambda: None)
    for k, v in kw.items():
        setattr(me, k, v)
    cfg.Config.provider_sequence(me)
    return [v for k, v in sorted(me.PROVIDER_ORDER.items())]


@pytest.mark.unit
def test_torznab_off_leaves_only_ddl(monkeypatch):
    tz = [('Jackett', 'http://jackett:9117/api', '0', 'key', '7030', '1', 1)]
    assert order(monkeypatch, ENABLE_TORRENT_SEARCH=True, EXTRA_TORZNABS=tz,
                 ENABLE_DDL=True, ENABLE_GETCOMICS=True) == ['DDL(GetComics)']


@pytest.mark.unit
def test_an_indexer_with_an_address_is_listed(monkeypatch):
    tz = [('Jackett', 'http://jackett:9117/api', '0', 'key', '7030', '1', 1)]
    nz = [('DOGnzb', 'https://api.dognzb.cr', '1', 'key', '', '1', 2)]
    assert order(monkeypatch, ENABLE_TORRENT_SEARCH=True, ENABLE_TORZNAB=True, EXTRA_TORZNABS=tz,
                 NEWZNAB=True, EXTRA_NEWZNABS=nz) == ['DOGnzb', 'Jackett']


@pytest.mark.unit
def test_the_blank_default_indexer_is_not_a_provider(monkeypatch):
    blank = [('http://', 'http://', '0', '', '', '1', 1)]
    assert order(monkeypatch, ENABLE_TORRENT_SEARCH=True, ENABLE_TORZNAB=True, EXTRA_TORZNABS=blank,
                 NEWZNAB=True, EXTRA_NEWZNABS=[('', ' ', '0', '', '', '1', 2)],
                 ENABLE_DDL=True, ENABLE_GETCOMICS=True) == ['DDL(GetComics)']


@pytest.mark.unit
def test_an_order_saved_from_settings_is_kept(monkeypatch):
    tz = [('Jackett', 'http://jackett:9117/api', '0', 'key', '7030', '1', 1)]
    nz = [('DOGnzb', 'https://api.dognzb.cr', '1', 'key', '', '1', 2)]
    on = dict(ENABLE_TORRENT_SEARCH=True, ENABLE_TORZNAB=True, EXTRA_TORZNABS=tz, NEWZNAB=True, EXTRA_NEWZNABS=nz,
              ENABLE_DDL=True, ENABLE_GETCOMICS=True)
    assert order(monkeypatch, PROVIDER_ORDER='0, Jackett, 1, DDL(GetComics), 2, DOGnzb', **on) == ['Jackett', 'DDL(GetComics)', 'DOGnzb']


@pytest.mark.unit
def test_a_provider_turned_on_later_joins_the_end(monkeypatch):
    nz = [('DOGnzb', 'https://api.dognzb.cr', '1', 'key', '', '1', 2)]
    assert order(monkeypatch, PROVIDER_ORDER='0, DOGnzb', NEWZNAB=True, EXTRA_NEWZNABS=nz,
                 ENABLE_DDL=True, ENABLE_GETCOMICS=True) == ['DOGnzb', 'DDL(GetComics)']


@pytest.mark.unit
def test_the_internet_archive_follows_getcomics(monkeypatch):
    assert order(monkeypatch, ENABLE_DDL=True, ENABLE_GETCOMICS=True, ENABLE_ARCHIVEORG=True) == ['DDL(GetComics)', 'DDL(Internet Archive)']
    assert order(monkeypatch, ENABLE_DDL=False, ENABLE_ARCHIVEORG=True) == []
