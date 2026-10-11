import types

import pytest
from bs4 import BeautifulSoup

import mylar
from mylar import ddlsources, getcomics

PAGE = '''<ul>
<li>Aliens Omnibus Vol. 3 (2008) (630 MB)<strong> :</strong><br /><a href="https://getcomics.org/dls/v3main"><span>Main Server</span></a> | <a href="https://getcomics.org/dls/v3mega"><span>Mega</span></a></li>
<li>Aliens Omnibus Vol. 4 (2008) (575 MB)<strong> :</strong><br /><a href="https://getcomics.org/dls/v4main"><span>Main Server</span></a> |<a href="https://userscloud.com/x"> <span>Userscloud</span></a> | <a href="https://getcomics.org/dls/v4mega"><span>Mega</span></a> | <a href="https://getcomics.org/dls/v4mf"><span>Mediafire</span></a></li>
</ul>
<p style="text-align: center;"><div class="aio-pulse"><a href="https://getcomics.org/dls/pack" title="Download Now">Download Now</a></div></p>'''


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        DDL_PRIORITY_ORDER='["main","pixeldrain","mega","mediafire","userscloud"]', DDL_DISABLED_SOURCES='[]',
        DDL_MAIN_LARGE_LAST=True, DDL_MAIN_LARGE_MB=400), raising=False)
    monkeypatch.setattr(ddlsources, 'pixeldrain_fits', lambda b: True)


def pick(issue, name='Aliens Omnibus'):
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.jd2 = object()  # JD2 configured, so hosts only JD2 handles are listed too
    return gc._single_item(BeautifulSoup(PAGE, 'html.parser'), [{'ComicName': name, 'IssueNumber': issue, 'IssueID': '1'}])


@pytest.mark.unit
def test_picks_only_the_wanted_volume_and_skips_main_when_large():
    entries, chosen = pick('4')
    assert chosen['series'] == 'Aliens Omnibus Vol. 4' and chosen['size'] == '575 MB'
    assert chosen['links'].endswith('v4mega') and chosen['pack'] is False
    assert {e['source'] for e in entries} == {'main', 'mega', 'mediafire', 'userscloud'}


@pytest.mark.unit
def test_main_first_when_large_rule_off():
    mylar.CONFIG.DDL_MAIN_LARGE_LAST = False
    _, chosen = pick('4')
    assert chosen['site'] == 'Main Server' and chosen['links'].endswith('v4main')


@pytest.mark.unit
def test_no_match_falls_back():
    assert pick('5') is None
    assert pick('4', name='Predator Omnibus') is None


HOSTS_PAGE = '''<ul>
<li>Aliens Omnibus Vol. 5 (2009) (630 MB)<strong> :</strong><br /><a href="https://getcomics.org/dls/v5px"><span>Pixeldrain</span></a> | <a href="https://getcomics.org/dls/v5vk"><span>VikingFile</span></a></li>
</ul>'''


def pick_hosts(jd2, failed):
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.jd2 = jd2
    return gc._single_item(BeautifulSoup(HOSTS_PAGE, 'html.parser'),
                           [{'ComicName': 'Aliens Omnibus', 'IssueNumber': '5', 'IssueID': '1'}], failed)


@pytest.mark.unit
def test_without_jd2_a_host_only_jd2_handles_is_never_picked():
    # after JD2 gave up, picking VikingFile queued an 'Unknown' link that failed and was picked again forever
    single = pick_hosts(None, ['GC-Pixel'])
    assert single is None or single[1]['source'] != 'vikingfile'


@pytest.mark.unit
def test_with_jd2_a_host_only_jd2_handles_can_still_be_picked():
    single = pick_hosts(object(), ['GC-Pixel'])
    assert single[1]['source'] == 'vikingfile'
