import pytest

import mylar
from mylar import db
from mylar.search_filer import pack_misfit, pack_already_downloaded


@pytest.mark.unit
@pytest.mark.parametrize('title, year, series_year, issue_year, version, fits', [
    # live 13 Oct: grabbed for the wrong volume
    ('Thunderbolts v1 (001-174) (1997-2012)', '1997-2012', '2016', '2016', 'v3', False),
    ('Secret Avengers Vol.1 (001 - 037) (2010-2013)', '2010-2013', '2013', '2013', 'v2', False),
    # the right run
    ('Thunderbolts v1 (001-174) (1997-2012)', '1997-2012', '1997', '1998', None, True),
    ('Ghost Rider Vol. 7 (1-9) (2011-2012)', '2011-2012', '2011', '2012', None, True),
    ('Superman - Batman (01-87 +Annual) (2003-2011)', '2003-2011', '2003', '2004', None, True),
    ('Fearless Defenders #1 - 12 (2013)', '2013', '2013', '2014', None, True),      # cover date runs a year on
    ('Secret Avengers #1 - 16 (2013-2014)', '2013-2014', '2013', '2017', 'v2', False),  # issue outside the pack's years
    # no years: the volume decides, only against a series with one set
    ('Thunderbolts v1 #1 - 174', None, '2016', '2016', 'v3', False),
    ('Thunderbolts v3 #1 - 12', None, '2016', '2016', 'v3', True),
    ('Thunderbolts v1 #1 - 174', None, '1997', '1998', None, True),
    ('Some Pack #1 - 10', None, None, None, None, True),
])
def test_a_pack_must_fit_the_series_and_the_issue(title, year, series_year, issue_year, version, fits):
    assert (pack_misfit(title, year, series_year, issue_year, version) is None) is fits


@pytest.mark.unit
def test_a_pack_already_downloaded_is_not_grabbed_again(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE ddl_info (id TEXT, status TEXT, updated_date TEXT)')
    d.action("INSERT INTO ddl_info VALUES ('14348', 'Completed', '2026-10-12 20:40'), ('777-2', 'Queued', '2026-10-13 09:00'), "
             "('555', 'Failed', '2026-10-13 09:00')")
    assert 'already downloaded' in pack_already_downloaded('14348')   # Superman/Batman #1-87, grabbed twice live
    assert 'already queued' in pack_already_downloaded('777')         # a part of a split pack
    assert pack_already_downloaded('555') is None                     # failed: may try again
    assert pack_already_downloaded('9999') is None
    assert pack_already_downloaded(None) is None
