import pytest
from mockito import verify
import mylar
from mylar import helpers
import tests.fixtures
from tests.fixtures import patch_datetime, patch_time

import socket
import stun
import platform
import os
import subprocess

@pytest.mark.parametrize("var,result", [(True, 'Checked'), (False, ''), (None, ''), (1, 'Checked'), (0, '')])
@pytest.mark.unit
def test_checked(var, result):
    assert helpers.checked(var) == result


@pytest.mark.parametrize("var,pos,result", [(0, 0, 'Checked'), (0, 1, ''), (1, 0, ''), (5, 5, 'Checked')])
@pytest.mark.unit
def test_radio(var, pos, result):
    assert helpers.radio(var, pos) == result


@pytest.mark.parametrize("latin,ascii", [('Pàra', 'Para'), ('Æther', 'Aether'), ('', ''), ('Blobby', 'Blobby'), ('Annual²', 'Annual{^2}'), ('Weirdʬ', 'Weird')])
@pytest.mark.unit
def test_latinToAscii(latin, ascii):
    assert helpers.latinToAscii(latin) == ascii


@pytest.mark.unit
def test_today(patch_datetime):
    assert helpers.today() == '2001-12-25'


@pytest.mark.unit
def test_now(patch_datetime):
    assert helpers.now() == '2001-12-25 16:59:30'


@pytest.mark.unit
def test_utctimestamp(patch_time):assert helpers.utctimestamp() == tests.fixtures.TIME_SINCE_EPOCH

# TODO: Expect this to fail currently because of the use of the deprecated naive timestamp methods.  Either replace or revisit after 3.12 and beyond
#@pytest.mark.unit
#def test_utc_date_to_local(patch_datetime):
#    assert helpers.utc_date_to_local(tests.fixtures.USER_TIME) == tests.fixtures.STATIC_TIME.astimezone(tests.fixtures.USER_TZ)

@pytest.mark.parametrize("bytes,result", [(0, '0 bytes'), (1, '1 byte'), (2, '2 bytes'), (1024, '1 KB'), (1025, '1 KB'), (1024*1024, '1.0 MB'), (1.1*1024*1024, '1.1 MB'), (5.356*1024*1024*1024, '5.36 GB')])
@pytest.mark.unit
def test_human_size(bytes, result):
    assert helpers.human_size(bytes) == result


@pytest.mark.parametrize("bytes,result", [(0, '0B'), (1, '1B'), (2, '2B'), (1024, '1K'), (1024*1.5, '1.5K'), (1024*1024, '1.0M'), (round(1.5*1024*1024), '1.5M'), (round(5.356*1024*1024*1024), '5.356G')])
@pytest.mark.unit
def test_human2bytes(bytes, result):
    assert helpers.human2bytes(result) == bytes


@pytest.mark.unit
def test_replace_all_empty():
    assert helpers.replace_all('', {}) == ''


@pytest.mark.unit
def test_replace_all_empty_string():
    assert helpers.replace_all('', {'$Type': 'TPB'}) == ''


@pytest.mark.unit
def test_replace_all_empty_dict():
    assert helpers.replace_all('Alpha Beta Gamma Delta $Type $Year $Volume', {}) == 'Alpha Beta Gamma Delta $Type $Year $Volume'


@pytest.mark.unit
def test_replace_all():
    assert helpers.replace_all('Alpha $first Gamma $second $first', {'$first': 'Beta', '$second': 'Delta'}) == 'Alpha Beta Gamma Delta Beta'


@pytest.mark.unit
def test_cleanName_empty():
    assert helpers.cleanName('') == ''


@pytest.mark.unit
def test_cleanName():
    assert helpers.cleanName('Into the Æther #53') == 'into the aether  53'


@pytest.mark.parametrize("number,result", [("0", True), ("1", True), ("200000", True), ("0.0", True), ("3.14", True), ("-1", True), (".1", True), ("-.1", True), ("Five", False), (None, False)])
@pytest.mark.unit
def test_is_number(number, result):
    assert helpers.is_number(number) == result


apiremove_tests = [
    (("http://some.url.somewhere:5076/api/?apikey=monkeys", "nzb"), "http://some.url.somewhere:5076/api/?apikey=xUDONTNEEDTOKNOWTHISx"),
    # TODO: apiremove: Should this support other positions for apikey?
    # (("http://some.url.somewhere:5076/api/?apikey=monkeys&other=else", "nzb"), "http://some.url.somewhere:5076/api/?apikey=xUDONTNEEDTOKNOWTHISx&other=else")
    (("http://some.url.somewhere:5076/api/?other=else&apikey=monkeys", "nzb"), "http://some.url.somewhere:5076/api/?other=else&apikey=xUDONTNEEDTOKNOWTHISx"),
    (("http://some.url.somewhere:5076/api/?apikey=monkeys", "$"), "http://some.url.somewhere:5076/api/?apikey=xUDONTNEEDTOKNOWTHISx"),
    (("http://some.url.somewhere:5076/api/?apikey=monkeys&other=else", "$"), "http://some.url.somewhere:5076/api/?apikey=xUDONTNEEDTOKNOWTHISx"),
    (("http://some.url.somewhere:5076/api/?other=else&apikey=monkeys", "$"), "http://some.url.somewhere:5076/api/?other=else&apikey=xUDONTNEEDTOKNOWTHISx"),    
    # TODO: apiremove: Should it also account for end of string as well when using &?
    (("http://some.url.somewhere:5076/api/?apikey=monkeys&other=else", "&"), "http://some.url.somewhere:5076/api/?apikey=xUDONTNEEDTOKNOWTHISx&other=else"),
    # (("http://some.url.somewhere:5076/api/?apikey=monkeys", "&"), "http://some.url.somewhere:5076/api/?apikey=xUDONTNEEDTOKNOWTHISx"),
    (("http://some.url.somewhere:5076/api/?apikey=monkeys&other=else", "&"), "http://some.url.somewhere:5076/api/?apikey=xUDONTNEEDTOKNOWTHISx&other=else"),
    # TODO: apiremove: Support %26 r, i filters unless those get refactored out
]


@pytest.mark.parametrize("test,result", apiremove_tests)
@pytest.mark.unit
def test_apiremove(test, result):
    assert helpers.apiremove(*test) == result


fullmonth_tests = [
    (1, 'January'),
    ('1', 'January'),
    ('01', 'January'),
    ('2', 'February'),
    ('3', 'March'),
    ('4', 'April'),
    ('5', 'May'),
    ('6', 'June'),
    ('7', 'July'),
    ('8', 'August'),
    ('9', 'September'),
    ('10', 'October'),
    ('11', 'November'),
    ('12', 'December'),
]


@pytest.mark.parametrize("test,result", fullmonth_tests)
@pytest.mark.unit
def test_fullmonth(test,result):
    assert helpers.fullmonth(test) == result


@pytest.mark.unit
def test_replacetheslash_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert helpers.replacetheslash('/app/mylar3/test') == '/app/mylar3/test'


@pytest.mark.unit
def test_replacetheslash_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    assert helpers.replacetheslash('C:\\mylar3\\test') == 'C:/mylar3/test'


@pytest.mark.parametrize("test,result", [(f'{x}', f'{x:03}') for x in [0, 1, 5, 9, 10, 11, 44, 99, 100, 101, 999, 1000, 1001, 10000000]])
@pytest.mark.unit
def test_renamefile_readingorder(test, result):
    assert helpers.renamefile_readingorder(test) == result


LoadAlternateSearchNames_tests = [
    ((None, None), 'no results'),
    (("None", None), 'no results'),
]


@pytest.mark.parametrize("test,result", LoadAlternateSearchNames_tests)
@pytest.mark.unit
def test_LoadAlternateSearchNames(test, result):
    assert helpers.LoadAlternateSearchNames(*test) == result


filesafe_tests = [
    ("", ""),
    ("This is a — comic", "This is a  -  comic"),
    ("This is a: comic", "This is a comic"),
    ("This is a\ comic", "This is a comic"),
]


@pytest.mark.parametrize("test,result", filesafe_tests)
@pytest.mark.unit
def test_filesafe(test, result):
    assert helpers.filesafe(test) == result


torrent_create_tests = [
    #(('32P', '123'), None),
    (('DEM', '123'), 'https://www.demonoid.pw/files/download/123/'),
    (('WWT', '123'), 'https://worldwidetorrents.to/download.php'),
]


@pytest.mark.parametrize("test,result", torrent_create_tests)
@pytest.mark.unit
def test_torrent_create(monkeypatch, test, result):
    monkeypatch.setattr(mylar, "DEMURL", 'https://www.demonoid.pw/', raising=False)
    monkeypatch.setattr(mylar, "WWTURL", 'https://worldwidetorrents.to/', raising=False)
    assert helpers.torrent_create(*test) == result


@pytest.mark.parametrize("test,result", [((1, 'seconds'), '1 second'), ((60, 'seconds'), '1 minute'), ((90, 'minutes'), '1 hour and 30 minutes')])
@pytest.mark.unit
def test_humanize_time(test, result):
    assert helpers.humanize_time(*test) == result


@pytest.mark.unit
def test_crc(monkeypatch):
    monkeypatch.setattr(mylar, "SYS_ENCODING", 'utf-8')
    assert helpers.crc('testname') == 'afe107acd2e1b816b5da87f79c90fdc7'


@pytest.mark.unit
def test_clean_url():
    assert helpers.clean_url('     http://google.com/       ') == 'http://google.com/'


@pytest.mark.unit
def test_chunker_empty():
    assert helpers.chunker([], 3) == []


@pytest.mark.unit
def test_chunker():
    assert helpers.chunker([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], 3) == [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11]]


@pytest.mark.unit
def test_cleanHost_add_protocol():
    assert helpers.cleanHost('localhost:8090') == 'http://localhost:8090/'


@pytest.mark.unit
def test_cleanHost_remove_protocol():
    assert helpers.cleanHost('http://localhost:8090', protocol=False) == 'localhost:8090'


@pytest.mark.unit
def test_cleanHost_ssl():
    assert helpers.cleanHost('localhost:8090', ssl=True) == 'https://localhost:8090/'

# TODO: Expand for other path configurations / variable substitution
@pytest.mark.unit
def test_arcformat(monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "REPLACE_SPACES", False, raising=False)
    monkeypatch.setattr(mylar.CONFIG, "REPLACE_CHAR", None, raising=False)
    monkeypatch.setattr(mylar.CONFIG, "ARC_FOLDERFORMAT", "$arc ($spanyears)", raising=False)
    monkeypatch.setattr(mylar.CONFIG, "STORYARCDIR", True, raising=False)
    monkeypatch.setattr(mylar.CONFIG, "STORYARC_LOCATION", os.getcwd(), raising=False)
    monkeypatch.setattr(mylar.CONFIG, "COPY2ARCDIR", False, raising=False)
    monkeypatch.setattr(mylar.CONFIG, "GRABBAG_DIR", None, raising=False)

    assert helpers.arcformat('Expensive Crossovers', '2010-2019', 'Marvel') == os.path.join(os.getcwd(), 'Expensive Crossovers (2010-2019)')


# Week N is the Sunday-Saturday week holding the year's Nth Wednesday (TalkHard's numbering):
# 52 or 53 weeks a year, no week 0. Checked against TalkHard: 2025 has a week 53
# (Dec 28 - Jan 3) and week 1 of 2026 starts on January 4.
weekly_info_tests = [
    (('12', '2025'), {'endweek': 'March 22, 2025', 'midweek': '2025-03-19', 'startweek': 'March 16, 2025',
                      'weeknumber': 12, 'year': 2025, 'prev_weeknumber': 11, 'prev_year': 2025, 'next_weeknumber': 13, 'next_year': 2025}),
    (('52', '2025'), {'endweek': 'December 27, 2025', 'midweek': '2025-12-24', 'startweek': 'December 21, 2025',
                      'weeknumber': 52, 'year': 2025, 'prev_weeknumber': 51, 'prev_year': 2025, 'next_weeknumber': 53, 'next_year': 2025}),
    (('53', '2025'), {'endweek': 'January 03, 2026', 'midweek': '2025-12-31', 'startweek': 'December 28, 2025',
                      'weeknumber': 53, 'year': 2025, 'prev_weeknumber': 52, 'prev_year': 2025, 'next_weeknumber': 1, 'next_year': 2026}),
    (('01', '2026'), {'endweek': 'January 10, 2026', 'midweek': '2026-01-07', 'startweek': 'January 04, 2026',
                      'weeknumber': 1, 'year': 2026, 'prev_weeknumber': 53, 'prev_year': 2025, 'next_weeknumber': 2, 'next_year': 2026}),
    (('52', '2026'), {'endweek': 'January 02, 2027', 'midweek': '2026-12-30', 'startweek': 'December 27, 2026',
                      'weeknumber': 52, 'year': 2026, 'prev_weeknumber': 51, 'prev_year': 2026, 'next_weeknumber': 1, 'next_year': 2027}),
    # 2026 has 52 weeks, so week 53 is week 1 of 2027; week 0 is the previous year's last week.
    (('53', '2026'), {'endweek': 'January 09, 2027', 'midweek': '2027-01-06', 'startweek': 'January 03, 2027',
                      'weeknumber': 1, 'year': 2027, 'prev_weeknumber': 52, 'prev_year': 2026, 'next_weeknumber': 2, 'next_year': 2027}),
    (('0', '2026'), {'endweek': 'January 03, 2026', 'midweek': '2025-12-31', 'startweek': 'December 28, 2025',
                      'weeknumber': 53, 'year': 2025, 'prev_weeknumber': 52, 'prev_year': 2025, 'next_weeknumber': 1, 'next_year': 2026}),
    (('01', '2019', '11'), {'endweek': 'January 05, 2019', 'midweek': '2019-01-02', 'startweek': 'December 30, 2018',
                      'weeknumber': 1, 'year': 2019, 'prev_weeknumber': 52, 'prev_year': 2018, 'next_weeknumber': 2, 'next_year': 2019}),
]


def _expected_week(result, folder):
    # The patched "today" (2001-12-25) is in week 52 of 2001.
    return {'current_weeknumber': 52, 'current_year': 2001, 'last_update': 'None', 'week_folder': folder, **result}


@pytest.mark.parametrize("input,result", weekly_info_tests)
@pytest.mark.unit
def test_weekly_info_format0(patch_datetime, monkeypatch, input, result):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "WEEKFOLDER_LOC", None, raising=False)
    monkeypatch.setattr(mylar.CONFIG, "DESTINATION_DIR", os.getcwd(), raising=False)
    monkeypatch.setattr(mylar.CONFIG, "WEEKFOLDER_FORMAT", 0, raising=False)

    folder = os.path.join(os.getcwd(), f"{result['year']}-{result['weeknumber']:02}")
    assert helpers.weekly_info(*input) == _expected_week(result, folder)


@pytest.mark.parametrize("input,result", weekly_info_tests)
@pytest.mark.unit
def test_weekly_info_format1(patch_datetime, monkeypatch, input, result):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "WEEKFOLDER_LOC", None, raising=False)
    monkeypatch.setattr(mylar.CONFIG, "DESTINATION_DIR", os.getcwd(), raising=False)
    monkeypatch.setattr(mylar.CONFIG, "WEEKFOLDER_FORMAT", 1, raising=False)

    assert helpers.weekly_info(*input) == _expected_week(result, os.path.join(os.getcwd(), result['midweek']))


@pytest.mark.unit
@pytest.mark.parametrize("day,expected", [
    ('2025-12-31', (53, 2025)), ('2026-01-03', (53, 2025)), ('2026-01-04', (1, 2026)),
    ('2026-10-11', (41, 2026)), ('2026-10-14', (41, 2026)), ('2027-01-01', (52, 2026)), ('2027-01-03', (1, 2027)),
])
def test_release_week(day, expected):
    import datetime as _dt
    assert helpers.release_week(_dt.date.fromisoformat(day)) == expected


class MockEnvOnSnatchScript():
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def readline(self):
        return "#!/bin/bash"


@pytest.mark.unit
def test_script_env_on_snatch(when, monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "SNATCH_SCRIPT", 'testscript.sh', raising=False)
    monkeypatch.setattr(mylar.CONFIG, "SNATCH_SHELL_LOCATION", os.getcwd(), raising=False)
    monkeypatch.setattr("builtins.open", lambda *_: MockEnvOnSnatchScript())
    monkeypatch.setattr(os, "environ", {}, raising=False)

    snatch_vars = {'comicinfo': {'comicname': "ComicName",
                                 'issuenumber':      "IssueNumber",
                                 'seriesyear':       "ComicYear",
                                 'comicid':          "ComicID",
                                 'issueid':          "IssueID"},
                   'pack':             False,
                   'pack_numbers':     None,
                   'pack_issuelist':   None,
                   'provider':         "fullprov",
                   'method':           'torrent',
                   'clientmode':       "rcheck['clientmode']",
                   'torrentinfo':      {'files': ['test', 'test2']}}

    when(subprocess).call(...)
    helpers.script_env('on-snatch', snatch_vars)
    verify(subprocess, times=1).call(['/bin/bash', 'testscript.sh'],
                                     env={'mylar_release_files': 'test|test2', 'mylar_release_provider': 'fullprov',
                                          'mylar_comicid': 'ComicID', 'mylar_issueid': 'IssueID', 'mylar_comicname': 'ComicName',
                                          'mylar_issuenumber': 'IssueNumber', 'mylar_seriesyear': 'ComicYear', 'mylar_release_pack': 'False',
                                          'mylar_method': 'torrent', 'mylar_client': "rcheck['clientmode']"})


@pytest.mark.unit
def test_block_provider_check(monkeypatch, patch_time):
    monkeypatch.setattr(mylar, "PROVIDER_BLOCKLIST",
                        [{'site': 'nzbHydra', 'resume': tests.fixtures.TIME_SINCE_EPOCH + 120, 'reason': 'pettiness'}],
                        raising=False)

    assert helpers.block_provider_check('nzbHydra', simple=False, force=False) == {'blocked': True, 'remain': 2}


@pytest.mark.unit
def test_disable_provider(monkeypatch, patch_time):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "BLOCKLIST_TIMER", 120, raising=False)
    monkeypatch.setattr(mylar, "PROVIDER_BLOCKLIST", [])

    helpers.disable_provider('nzbHydra', reason='pettiness', delay=120)

    assert mylar.PROVIDER_BLOCKLIST == [{'site': 'nzbHydra', 'resume': tests.fixtures.TIME_SINCE_EPOCH + 120, 'reason': 'pettiness'}]


@pytest.mark.parametrize("test,result", 
                         [((1, 'B'), '1.0B'),
                          ((1024, 'B'), '1.0KiB'),
                          ((1024*1024, 'B'), '1.0MiB'),
                          ((1000000000, 'B'), '953.7MiB')])
@pytest.mark.unit
def test_sizeof_fmt(test, result):
    assert helpers.sizeof_fmt(*test) == result


# TODO: Could data drive this
@pytest.mark.unit
def test_publisherImages(monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "INTERFACE", 'default', raising=False)

    assert helpers.publisherImages('Image Comics') == {
        'publisher_image': 'images/publisherlogos/logo-imagecomics.png',
        'publisher_image_alt': 'Image',
        'publisher_imageH': '125',
        'publisher_imageW': '75'}


@pytest.mark.unit
def test_ignored_publisher_check(monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORED_PUBLISHERS", ['Baguette'], raising=False)

    assert helpers.ignored_publisher_check('Baguette') is True


issue_number_to_int_tests = [
    ((1, None), 1000), ((0.5, None), 500), ((1.75, None), 1750), ((1, "X"), 1120),
    ((-1, None), -1000), ((-0.5, None), -500), ((None, "Alpha"), 518),
]


@pytest.mark.parametrize("test,result", issue_number_to_int_tests)
@pytest.mark.unit
def test_issue_number_to_int(test, result):
    assert helpers.issue_number_to_int(*test) == result


format_issue_number_tests = [
    (('1'), '1'), (('1', 0), '1'), (('1.75', 2), '01.75'), (('123.2', 3), '123.2'),
    (('-1', 3), '-001'), (('-1.33', 3), '-001.33'), (('10.2', 3), '010.2'),
]


@pytest.mark.parametrize("test,result", format_issue_number_tests)
@pytest.mark.unit
def test_format_issue_number(test, result):
    assert helpers.format_issue_number(*test) == result


issue_number_parser_tests_00x = [
    (('1', None, None, False, True), helpers.IssueNumber(1000, '001', None)),
    (('00', None, None, False, True), helpers.IssueNumber(0, '000', None)),
    (('27AU', None, None, False, True), helpers.IssueNumber(27214, '027AU', None)),
    (('T-4', None, None, False, True), helpers.IssueNumber(-4116, 'T-004', None)),
    (('X', None, None, False, True), helpers.IssueNumber(120, 'X', None)),
    (('-½', None, None, False, True), helpers.IssueNumber(-500, '-000.5', None)),
    (('½', None, None, False, True), helpers.IssueNumber(500, '000.5', None)),
    (('1½', None, None, False, True), helpers.IssueNumber(1500, '001.5', None)),
    (('∞', None, None, False, True), helpers.IssueNumber(10000007734, '∞', None)),
    (('92.BEY', None, None, False, True), helpers.IssueNumber(92320, '092.BEY', None)),
    (('3.3', None, None, False, True), helpers.IssueNumber(3300, '003.3', None)),
    (('Alpha', None, None, False, True), helpers.IssueNumber(518, 'Alpha', None)),
    (('0.0001½', None, None, False, True), helpers.IssueNumber(1, '000.00015', None)),
    (('170/123', None, None, False, True), helpers.IssueNumber(170000, '170-123', None)),
    (('15 [16]', None, None, False, True), helpers.IssueNumber(15000, '015', '16')),
]


@pytest.mark.parametrize("test,result", issue_number_parser_tests_00x)
@pytest.mark.unit
def test_issue_number_parser_00x(when, monkeypatch, test, result):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "ZERO_LEVEL_N", '00x', raising=False)
    
    # Patch out issue exceptions for unit tests
    monkeypatch.setattr(helpers, "add_issue_exception", lambda _: True)

    assert helpers.issue_number_parser(*test) == result


@pytest.mark.parametrize("padding", range(4))
@pytest.mark.unit
def test_format_issue_number_numeric(padding):
    assert helpers.format_issue_number('1', padding) == f'{1:0>{padding}}'


@pytest.mark.parametrize("padding", range(4))
@pytest.mark.unit
def test_format_issue_number_decimal(padding):
    assert helpers.format_issue_number('0.1', padding) == f'{0.1:0={padding + 2}.0}'


@pytest.mark.parametrize("padding", range(4))
@pytest.mark.unit
def test_format_issue_number_negative(padding):
    assert helpers.format_issue_number('-1', padding) == f'{-1:0={padding+1}d}'


@pytest.mark.unit
def test_issue_number_parser_basic():
    result = helpers.IssueNumber(10000, '10', None)
    assert helpers.issue_number_parser('10', zero_padding=0, pretty_string=True) == result


@pytest.mark.unit
def test_issue_number_parser_decimal():
    result = helpers.IssueNumber(250, '0.25', None)
    assert helpers.issue_number_parser('0.25', zero_padding=0, pretty_string=True) == result


issueExceptionCheck_tests = [
    (('deaths', True), True),
    (('death', True), False),
    (('deaths', False), True),
    (('-X', True), True),
    (('X', True), True),
]


@pytest.mark.parametrize("test,result", issueExceptionCheck_tests)
@pytest.mark.unit
def test_issue_exception_check(monkeypatch, test, result):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)

    assert helpers.issueExceptionCheck(*test) is result


@pytest.mark.unit
def test_issue_exception_list_exact(monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    assert sorted(helpers.issue_exception_list('Exact')) == sorted([x[0] for x in mylar.INBUILT_ISSUE_EXCEPTIONS if x[1] == 'Exact'])


@pytest.mark.unit
def test_issue_exception_list_pattern(monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    assert sorted(helpers.issue_exception_list('Pattern')) == sorted([x[0] for x in mylar.INBUILT_ISSUE_EXCEPTIONS if x[1] == 'Pattern'])


# TODO: helpers.py: Untested functions (mostly needing DB / service mocks)
# rename_param
# ComicSort
# updateComicLocation
# cleanhtml
# checkthepub
# annual_update
# latestdate_fix
# upgrade_dynamic
# havetotals
# IssueDetails
# get_issue_title
# listPull
# listLibrary
# listStoryArcs
# listoneoffs
# manualArc
# listIssues
# incr_snatched
# duplicate_filecheck
# create_https_certificates cf. PR #1647
# parse_32pfeed
# issue_status
# issue_find_ids
# reverse_the_pack_snatch
# checkthe_id
# updatearc_locs
# spantheyears
# torrentinfo
# ddl_downloader
# job_management
# lookupthebitches
# DateAddedFix
# statusChange
# log_that_exception
# get_the_hash
# newznab_test
# torznab_test
# get_free_space
# add_issue_exception
## Need to mock up some test files
# getImage
# file_ops
# tail_that_log
# check_file_condition
# TODO: helpers.py: Unused / refactorable functions
# remove_apikey
# extract_logline
# cleanTitle
# bytes_to_mb
# convert_seconds
# covert_milliseconds
# multikeysort
# urlretrieve
# checkFolder
# int_num
# conversion
# decimal_issue: should be swapped with other number methods
# apiremove: why does it use %26
# torrent_create: cannot work for the first conditional - will throw an exception
# test_clean_url: Could be simplified, or made even more complex to sanitise inputs
# cleanHost: Should be fixed to use logger (in case it's ever called)
# latestdate_update
# latestissue_update
# stupidchk
# ThreadWithReturnValue class appears unused
# date_conversion


@pytest.mark.unit
@pytest.mark.parametrize("name,expected", [
    ("Spider-Man *", "Spider-Man -"),
    ("Who | What", "Who - What"),
    ("<Angle> Brackets", "Angle Brackets"),
    ("Batman: Year One", "Batman Year One"),
])
def test_filesafe_strips_unsafe_characters(name, expected):
    assert helpers.filesafe(name) == expected


@pytest.mark.unit
@pytest.mark.parametrize('store, digital, expected', [
    ('2026-10-14', '0000-00-00', '2026-10-14'),
    ('2026-10-14', '2026-10-13', '2026-10-13'),
    ('0000-00-00', '2026-10-13', '2026-10-13'),
    ('0000-00-00', '0000-00-00', None),
    (None, None, None),
])
def test_release_date_is_the_earlier_known_date(store, digital, expected):
    assert helpers.release_date(store, digital) == expected


@pytest.mark.unit
def test_search_tier_counts_from_the_later_of_added_and_released(monkeypatch):
    monkeypatch.setattr(helpers, 'today', lambda: '2026-10-11')
    cut = '2026-09-27'
    assert helpers.search_tier('2026-01-01', '2026-10-20', None, cut) == ('soon', '2026-10-20')
    assert helpers.search_tier('2026-01-01', '2026-10-11', None, cut) == (1, '2026-10-11')
    assert helpers.search_tier('2026-01-01', '2026-09-27', None, cut) == (1, '2026-09-27')
    assert helpers.search_tier('2026-01-01', '2026-09-26', None, cut) == (2, '2026-09-26')
    assert helpers.search_tier('2026-10-05', '2020-01-01', None, cut) == (1, '2026-10-05')
    assert helpers.search_tier('2026-01-01', '0000-00-00', '0000-00-00', cut) == (2, '2026-01-01')
    assert helpers.search_tier(None, None, None, cut) == (1, '')
