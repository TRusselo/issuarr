import pytest

from mylar.webserve import WebInterface

ROWS = [
    {'comicname': 'Midnight Fantastic Four', 'publisher': 'Marvel', 'comicyear': '2026', 'type': 'Print', 'volume': None},
    {'comicname': 'Midnight Sons', 'publisher': 'Marvel', 'comicyear': '1993', 'type': 'Print', 'volume': None},
    {'comicname': 'Midnight', 'publisher': 'Image', 'comicyear': '2026', 'type': 'TPB', 'volume': 'v2'},
    {'comicname': 'Fantastic Four', 'publisher': 'Marvel', 'comicyear': '2026', 'type': None, 'volume': None},
]


def names(text):
    return [r['comicname'] for r in WebInterface._filter_search_results(ROWS, text)]


@pytest.mark.unit
@pytest.mark.parametrize('text,expected', [
    ('', ['Midnight Fantastic Four', 'Midnight Sons', 'Midnight', 'Fantastic Four']),
    ('marvel 2026', ['Midnight Fantastic Four', 'Fantastic Four']),
    ('midnight marvel', ['Midnight Fantastic Four', 'Midnight Sons']),
    ('midnight 2026', ['Midnight Fantastic Four', 'Midnight']),
    ('MIDNIGHT tpb', ['Midnight']),
    ('midnight :-marvel', ['Midnight']),
    ('four :-midnight', ['Fantastic Four']),
    ('dc', []),
])
def test_every_word_matches_some_field(text, expected):
    assert names(text) == expected
