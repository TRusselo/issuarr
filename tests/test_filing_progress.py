import pytest

from mylar import archives


@pytest.mark.unit
def test_progress_updates_the_running_job_and_never_starts_one(monkeypatch):
    monkeypatch.setattr(archives, 'ACTIVE', {})
    archives.progress('Checking file 1 of 3 against the watchlist')
    assert archives.ACTIVE == {}   # File as runs without a job: nothing left showing "Filing"
    archives.busy('Post-processing 3 files')
    archives.progress('Checking file 2 of 3 against the watchlist')
    [job] = archives.ACTIVE.values()
    assert job['detail'] == 'Checking file 2 of 3 against the watchlist'


@pytest.mark.unit
def test_the_matching_and_filing_loops_report_progress():
    src = open('mylar/PostProcessor.py').read()
    assert "archives.progress('Checking file %s of %s against the watchlist' % (checked, checking))" in src
    assert src.count("archives.progress('Filing %s of %s matched issues' % (i, len(manual_list)))") == 2
