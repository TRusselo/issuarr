import pytest

from mylar import getcomics, helpers


@pytest.mark.unit
@pytest.mark.parametrize('pack,expected', [
    ('#1 - 12', [str(x) for x in range(1, 13)]),
    ('1 - 6', ['1', '2', '3', '4', '5', '6']),
    ('#1 - 10AI', [str(x) for x in range(1, 11)] + ['10AI']),
    ('#-1 - 3', ['-1', '0', '1', '2', '3']),
    ('#1-3, #7', ['1', '2', '3', '7']),
    ('1, 2, 5', ['1', '2', '5']),
    ('#0 - 2', ['0', '1', '2']),
])
def test_pack_issue_numbers(pack, expected):
    assert helpers.pack_issue_numbers(pack) == expected


def check(title):
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.pack_receipts = ['+ TPBs', '+TPBs', '+ TPB', '+TPB', 'TPB', '+ Deluxe Books', '+ Annuals', '+Annuals', ' & ']
    return gc.check_for_pack(title)


@pytest.mark.unit
def test_range_starting_below_zero():
    r = check('What If? Vol. 2 #-1 – 114 (1989-1998)')
    assert (r['pack'], r['series'], r['volume'], r['issues'], r['year']) == (True, 'What If?', '2', '#-1 - 114', '1989-1998')


@pytest.mark.unit
@pytest.mark.parametrize('title,series,issues', [
    ('Fearless Defenders #1 – 12 (2013)', 'Fearless Defenders', '#1 - 12'),
    ('Age of Ultron #1 – 10AI (2013)', 'Age of Ultron', '#1 - 10AI'),
    ('What If? Vol. 1 #1 – 47 (1977-1984)', 'What If?', '#1 - 47'),
])
def test_ordinary_ranges_unchanged(title, series, issues):
    r = check(title)
    assert (r['pack'], r['series'], r['issues']) == (True, series, issues)
