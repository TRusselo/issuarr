import pytest

from mylar import updater


@pytest.mark.unit
@pytest.mark.parametrize("booktype", ["TPB", "GN", "HC", "One-Shot"])
def test_collected_editions_assume_issue_1(booktype):
    assert updater.numberless_issue(booktype, [{'Issue_Number': '1'}, {'Issue_Number': '2'}]) == '1'


@pytest.mark.unit
def test_single_issue_print_series_takes_its_only_issue():
    # ComicVine can list a one-issue series as regular print ("7174 Annual.cbz", #2).
    assert updater.numberless_issue('Print', [{'Issue_Number': '1'}]) == '1'
    assert updater.numberless_issue('Print', [{'Issue_Number': '0'}]) == '0'
    assert updater.numberless_issue('Print', [{'Issue_Number': None}]) == '1'


@pytest.mark.unit
def test_multi_issue_print_series_stays_unmatched():
    assert updater.numberless_issue('Print', [{'Issue_Number': '1'}, {'Issue_Number': '2'}]) is None
    assert updater.numberless_issue('Print', []) is None


@pytest.mark.unit
def test_annual_file_is_not_given_the_series_issue():
    assert updater.numberless_issue('Print', [{'Issue_Number': '1'}], annualcomicid='12345') is None
