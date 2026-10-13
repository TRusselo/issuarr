import pytest

import mylar
from mylar import db
from mylar.PostProcessor import pack_other_series


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, DynamicComicName TEXT)')
    d.action("INSERT INTO comics VALUES ('19020', 'Superman/Batman Annual', '2006', 'supermanbatmanannual'), "
             "('7180', 'Superman/Batman', '2003', 'supermanbatman'), ('77830', 'Superman/Batman', '2014', 'supermanbatman'), "
             "('1', 'Batman', '1940', 'batman')")
    return d


@pytest.mark.unit
def test_a_packs_other_files_are_checked_against_the_series_they_are_named_for(myDB):
    # live 12 Oct: grabbed for Superman/Batman Annual, the pack's 87 issues were only checked against the Annual
    found = pack_other_series(myDB, None, '19020', ['supermanbatman'])
    assert sorted(r['ComicID'] for r in found) == ['7180', '77830']


@pytest.mark.unit
def test_the_packs_own_series_is_not_added_twice(myDB):
    assert pack_other_series(myDB, None, '19020', ['supermanbatmanannual']) == []


@pytest.mark.unit
def test_a_download_for_one_issue_stays_with_its_series(myDB):
    assert pack_other_series(myDB, '12345', '19020', ['supermanbatman']) == []
    assert pack_other_series(myDB, None, None, ['supermanbatman']) == []
    assert pack_other_series(myDB, None, '19020', []) == []
