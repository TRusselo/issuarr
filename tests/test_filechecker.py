import pytest
import csv
from pathlib import Path
import mylar
from mylar import filechecker


def empty_string_to_none(input):
    return None if input == '' else input


def none_string_to_none(input):
    return None if input == 'None' else input


def load_filename_parsing_tests():
    test_filechecker_data = Path(Path(__file__).parents[0], "data", "filename_tests.csv")

    test_list = []

    with open(test_filechecker_data) as csvfile:
        reader = csv.DictReader(csvfile, delimiter=',', quotechar='"', )
        entry_counter = 0
        for entry in reader:
            entry_counter += 1
            test_id = f"{entry_counter:03}:{entry['filename']}"
            
            test_list.append(
                pytest.param(entry['filename'], entry['series'], none_string_to_none(entry['issue']),
                             none_string_to_none(entry['year']), none_string_to_none(entry['volume']),
                             (entry['xfail'].lower() == "true"), id=test_id))
            # Retaining for reference - alternative approach to expected failures to report them (and unexpected passes) but not
            # fail the suite.
            # if entry['xfail'].lower() == "true":
            #     test_list.append(
            #         pytest.param(entry['filename'], entry['series'], none_string_to_none(entry['issue']),
            #                      none_string_to_none(entry['year']), none_string_to_none(entry['volume']),
            #                      True, id=test_id, marks=pytest.mark.xfail(reason=entry['testnotes'])))
            # else:
            #     test_list.append(
            #         pytest.param(entry['filename'], entry['series'], none_string_to_none(entry['issue']),
            #                      none_string_to_none(entry['year']), none_string_to_none(entry['volume']),
            #                      False, id=test_id))

    return test_list


@pytest.mark.parametrize("filename,series,issue,year,volume,xfail", load_filename_parsing_tests())
@pytest.mark.unit
def test_manual_filename_parsing(monkeypatch, filename, series, issue, year, volume, xfail):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)

    fc_obj = filechecker.FileChecker(file=filename, justparse=True, manual=True)
    parsed = fc_obj.parseit(path='/dummypath/', filename=filename)

    # Rather than multiple asserts and early exit, checks all at once (skipping blanks)
    if xfail:
        assert ((parsed['series_name'] .lower(),
                None if volume is None else parsed['series_volume'],
                None if year is None else parsed['issue_year'],
                None if issue is None else parsed['issue_number'])
                !=
                (series.lower(),
                volume,
                year,
                issue))
    else:
        assert ((parsed['series_name'] .lower(),
                None if volume is None else parsed['series_volume'],
                None if year is None else parsed['issue_year'],
                None if issue is None else parsed['issue_number'])
                ==
                (series.lower(),
                volume,
                year,
                issue))



@pytest.mark.unit
@pytest.mark.parametrize("filename,issue", [
    ("American Vampire 1976 007.cbz", "007"),
    ("American Vampire 1976 001.cbz", "001"),
    ("American Vampire 1976 001 (2020).cbz", "001"),
    ("American Vampire 1976 #1.cbz", "1"),
    ("American Vampire 1976 v1 001 (2020).cbz", "001"),
])
def test_series_title_with_trailing_year_retained_when_watchcomic_known(monkeypatch, filename, issue):
    # Some real titles end in a bare year ("American Vampire 1976"). When the known series name
    # (watchcomic) says so, the year stays part of the title instead of being dropped.
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    fc_obj = filechecker.FileChecker(watchcomic="American Vampire 1976", file=filename, justparse=True, manual=True)
    parsed = fc_obj.parseit(path='/dummypath/', filename=filename)
    assert parsed['series_name'] == "American Vampire 1976"
    assert parsed['issue_number'] == issue


@pytest.mark.unit
def test_launch_year_still_dropped_when_not_in_title(monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    filename = "Batman 2016 001.cbz"
    fc_obj = filechecker.FileChecker(watchcomic="Batman", file=filename, justparse=True, manual=True)
    parsed = fc_obj.parseit(path='/dummypath/', filename=filename)
    assert parsed['series_name'] == "Batman"
    assert parsed['issue_number'] == "001"


@pytest.mark.unit
@pytest.mark.parametrize("watchcomic,filename,issue", [
    ("Cyberpunk 2077", "Cyberpunk 2077 001.cbz", "001"),
    ("Cyberpunk 2077", "Cyberpunk 2077 001 (2020).cbz", "001"),
    ("7174 Annual", "7174 Annual 001.cbz", "001"),
    ("7174 Annual", "7174 Annual.cbz", None),
    ("100 Bullets", "100 Bullets 012.cbz", "012"),
])
def test_numeric_series_title_matches_known_series(monkeypatch, watchcomic, filename, issue):
    # Titles that are or contain a number (#2): the number stays in the series name and the
    # file still matches the series on rescan. A file with no issue number matches too; the
    # rescan decides which issue it is (updater.numberless_issue).
    monkeypatch.setattr(mylar, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "ANNUALS_ON", False, raising=False)
    fc_obj = filechecker.FileChecker(dir='/dummypath/', watchcomic=watchcomic)
    parsed = fc_obj.parseit('/dummypath/', filename)
    assert parsed['process_status'] == 'match'
    assert parsed['series_name'] == watchcomic
    assert parsed['justthedigits'] == issue
