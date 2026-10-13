import types

import pytest

import mylar
from mylar import archives, db
from mylar.PostProcessor import run_series


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in dict(IGNORE_SEARCH_WORDS=[], ANNUALS_ON=True).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, DynamicComicName TEXT, AlternateSearch TEXT DEFAULT "None")')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT)')
    d.action("INSERT INTO comics (ComicID, ComicName, DynamicComicName) VALUES ('7180', 'Superman/Batman', 'supermanbatman'), ('22', 'Punisher 2099', 'punisher2099'), "
             "('99', 'Franken-Castle', 'frankencastle'), ('1', 'Batman', 'batman')")
    d.action("INSERT INTO issues VALUES ('5001', '1')")
    return d


@pytest.mark.unit
def test_a_folder_run_holds_only_the_series_its_files_are_named_for(myDB):
    files = [{'series_name': 'Superman Batman', 'alt_series': None, 'issueid': None},
             {'series_name': 'Superman Batman Annual', 'alt_series': None, 'issueid': None},
             {'series_name': 'The Punisher 2099', 'alt_series': None, 'issueid': None},
             {'series_name': 'Something Not Watched', 'alt_series': None, 'issueid': None},
             {'series_name': 'Odd Name', 'alt_series': None, 'issueid': '5001'}]
    alt = [{'AS_Alt': ['Franken Castle'], 'AS_DyComicName': 'frankencastle'}]
    files.append({'series_name': 'Franken Castle', 'alt_series': None, 'issueid': None})
    assert run_series(myDB, files, alt) == {'7180', '22', '99', '1'}


@pytest.mark.unit
def test_searches_of_other_series_carry_on_during_a_folder_run(monkeypatch):
    monkeypatch.setattr(archives, 'JOBS', [(frozenset({'7180', '22'}), None)])
    monkeypatch.setattr(mylar, 'PP_QUEUE', types.SimpleNamespace(mutex=__import__('threading').Lock(), queue=[]), raising=False)
    from mylar import autoadd
    monkeypatch.setattr(autoadd, 'running', lambda: False)
    assert archives.holds('7180', '1') is True
    assert archives.holds('22') is True
    assert archives.holds('555', '9') is False
    monkeypatch.setattr(archives, 'JOBS', [(None, None)])
    assert archives.holds('555', '9') is True   # a run that could file anything still holds all


@pytest.mark.unit
def test_a_queued_folder_run_holds_only_its_series_while_it_waits(myDB, tmp_path, monkeypatch):
    # live 12 Oct: Try filing again waited its turn as "could file anything", holding all 570 searches
    from mylar.PostProcessor import folder_job
    for k, v in dict(CUSTOM_ISSUE_EXCEPTIONS=[], FOLDER_SCAN_LOG_VERBOSE=False, ZERO_LEVEL_N=None, ZERO_LEVEL=False,
                     ENABLE_TORRENTS=False).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    folder = tmp_path / 'review'
    folder.mkdir()
    (folder / 'Superman Batman 001 (2003).cbz').write_bytes(b'x')
    (folder / 'The Punisher 2099 005 (1993).cbr').write_bytes(b'x')
    assert folder_job(str(folder)) == (frozenset({'7180', '22'}), None)
    (folder / 'Big Pack.zip').write_bytes(b'x')   # could hold any series once unpacked
    assert folder_job(str(folder)) == (None, None)
    assert folder_job(str(tmp_path / 'missing')) == (None, None)
