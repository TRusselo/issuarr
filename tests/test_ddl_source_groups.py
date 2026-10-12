"""The download sources list is four groups: GetComics direct, cloud shares, torrent, and the Internet Archive."""
import types

import pytest

import mylar
from mylar import ddlsources


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_PRIORITY_ORDER='["direct","cloud","torrent"]', DDL_DISABLED_SOURCES='[]',
                                                              DDL_MAIN_LARGE_LAST=False, DDL_MAIN_LARGE_MB=400, ENABLE_ARCHIVEORG=True,
                                                              ENABLE_TORRENTS=True, ENABLE_TORRENT_SEARCH=True), raising=False)
    monkeypatch.setattr(mylar, 'USE_DELUGE', True, raising=False)
    monkeypatch.setattr(ddlsources, 'pixeldrain_fits', lambda b: True)


@pytest.mark.unit
@pytest.mark.parametrize('host, grp', [('main', 'direct'), ('mega', 'cloud'), ('terabox', 'cloud'), ('zippyshare', 'cloud'),
                                       ('torrent', 'torrent')])
def test_every_host_belongs_to_a_group(host, grp):
    assert ddlsources.group(host) == grp


@pytest.mark.unit
def test_a_host_by_host_order_keeps_each_group_where_its_first_host_was():
    # the live order before the groups: Pixeldrain first, GetComics direct last
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["pixeldrain","vikingfile","mega","userscloud","main"]'
    assert ddlsources.configured_groups() == ['cloud', 'direct', 'torrent', 'ia']


@pytest.mark.unit
def test_order_expands_groups_to_hosts():
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["torrent","cloud","direct"]'
    o = ddlsources.order()
    assert o[0] == 'torrent' and o[-1] == 'main' and {'mega', 'mediafire', 'pixeldrain', 'terabox'} <= set(o)


@pytest.mark.unit
def test_a_group_turned_off_is_skipped():
    mylar.CONFIG.DDL_DISABLED_SOURCES = '["cloud"]'
    assert ddlsources.order() == ['main', 'torrent']
    assert not ddlsources.is_enabled('mega') and not ddlsources.is_enabled('zippyshare') and ddlsources.is_enabled('main')


@pytest.mark.unit
def test_old_per_host_switches_only_carry_over_for_direct_and_torrent():
    mylar.CONFIG.DDL_DISABLED_SOURCES = '["mega","main"]'
    assert ddlsources.disabled() == {'direct'}


@pytest.mark.unit
def test_big_files_try_cloud_shares_before_getcomics_but_not_after_torrent():
    mylar.CONFIG.DDL_MAIN_LARGE_LAST = True
    o = ddlsources.order(500 * 1024 * 1024)
    assert o.index('main') > o.index('mega') and o.index('main') < o.index('torrent')


@pytest.mark.unit
def test_torrent_waits_for_a_cloud_share_jd2_handles():
    mylar.CONFIG.DDL_PRIORITY_ORDER = '["cloud","torrent","direct"]'
    assert ddlsources.torrent_first({'terabox', 'main'}) is False
    assert ddlsources.torrent_first({'main'}) is True
