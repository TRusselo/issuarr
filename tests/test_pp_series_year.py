import pytest

from mylar.PostProcessor import series_year_label


@pytest.mark.unit
@pytest.mark.parametrize('file_year, series_year, issue_year, fits', [
    (1993, 1993, 1994, True),    # "The Punisher 2099 005 (1993)": labelled with the year the series began
    (1995, 1993, 1994, True),    # a cover dated the year after release
    (1940, 1937, 1940, True),    # Detective Comics #40 labelled with its own year
    (1937, 1937, 1985, True),    # a decades-long run labelled with its start year
    (2012, 2008, 2008, False),   # Captain Marvel 003 (2012) is the 2012 volume, not #3 of 2008
    (2011, 1937, 1937, False),   # Detective Comics 003 (2011) is New 52, not 1937's #3
    (1992, 1993, 1994, False),   # before the series began
    ('1993', '1993', '1994', True),
    (None, 1993, 1994, False),
    ('None', 1993, 1994, False),
])
def test_a_filename_year_fits_from_the_series_start_to_a_year_after_the_issue(file_year, series_year, issue_year, fits):
    assert series_year_label(file_year, series_year, issue_year) is fits
