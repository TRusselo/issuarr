import pytest

import mylar
from mylar import filechecker, search_filer


def parsed(name, year='2017'):
    return {'series_name': name, 'series_name_decoded': name, 'issue_number': '1', 'issue_year': year}


@pytest.mark.unit
@pytest.mark.parametrize('name,watch', [
    ('Star Wars - Jedi of the Republic - Mace Windu', 'Star Wars: Mace Windu'),
    ('Batman - The Long Halloween - Special', 'Batman: Special'),
])
def test_matches_titles_with_words_added(name, watch):
    out = search_filer.with_extra_words(parsed(name), watch, '2017')
    assert out['series_name'] == watch and out['series_name_decoded'] == watch
    assert out['issue_number'] == '1' and out['issue_year'] == '2017'


@pytest.mark.unit
@pytest.mark.parametrize('name,watch', [
    ('Emperor Aquaman', 'Aquaman'),                          # words before the series name
    ('Star Wars - Mace Windu Annual', 'Star Wars: Mace Windu'),  # words after it
    ('Star Wars - Mace Windu', 'Star Wars: Mace Windu'),     # same name: the strict match decides
    ('Star Wars - Darth Vader', 'Star Wars: Mace Windu'),
    ('Mace Windu - Star Wars', 'Star Wars: Mace Windu'),     # out of order
    ('Aquaman', 'Aquaman'),
])
def test_leaves_other_titles(name, watch):
    assert search_filer.with_extra_words(parsed(name), watch, '2017') is None


@pytest.mark.unit
def test_needs_a_year_on_the_post():
    assert search_filer.with_extra_words(parsed('Star Wars - Jedi of the Republic - Mace Windu', year=None),
                                         'Star Wars: Mace Windu', '2017') is None


@pytest.mark.unit
def test_a_post_from_another_year_is_not_a_match():
    # Star Wars: Age of Republic - Mace Windu (2019) has the same first and last words.
    assert search_filer.with_extra_words(parsed('Star Wars - Age of Republic - Mace Windu', year='2019'),
                                         'Star Wars: Mace Windu', '2017') is None


def match(monkeypatch, title, watch):
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'))
    monkeypatch.setattr(mylar.CONFIG, 'IGNORE_SEARCH_WORDS', [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'CUSTOM_ISSUE_EXCEPTIONS', [], raising=False)
    for key in ('ANNUALS_ON', 'ENABLE_TORRENTS', 'FOLDER_SCAN_LOG_VERBOSE'):
        monkeypatch.setattr(mylar.CONFIG, key, False, raising=False)
    parsed = filechecker.FileChecker(file=title, watchcomic=watch).listFiles()
    assert filechecker.FileChecker(watchcomic=watch).matchIT(parsed)['process_status'] == 'fail'
    retry = search_filer.with_extra_words(parsed, watch, '2017')
    return retry and filechecker.FileChecker(watchcomic=watch).matchIT(retry)


@pytest.mark.unit
def test_getcomics_mace_windu_title_matches_after_the_strict_match_fails(monkeypatch):
    found = match(monkeypatch, 'Star Wars - Jedi of the Republic - Mace Windu #1 (2017)', 'Star Wars: Mace Windu')
    assert found['process_status'] == 'match'
    assert found['justthedigits'] == '1' and found['issue_year'] == '2017'


@pytest.mark.unit
def test_a_longer_series_name_with_the_same_ends_is_still_not_a_match(monkeypatch):
    assert not match(monkeypatch, 'Star Wars - Darth Vader - Dark Lord #1 (2024)', 'Star Wars: Mace Windu')
