import pytest

from mylar import ledger


@pytest.mark.unit
def test_runs_follow_issue_order_and_merge_neighbours():
    issues = [
        (3, '2020-03', 'Wanted', '3'),
        (1, '2020-01', 'Downloaded', '1'),
        (2, '2020-02', 'Archived', '2'),
        (5, '2020-05', 'Downloaded', '5'),
        (4, '2020-04', 'Skipped', '4'),
        (6, '2020-06', 'Skipped', '6'),
        (7, '2020-07', 'Skipped', '7'),
    ]
    assert ledger.runs(issues) == [
        ['h', 2, '1', '2'],
        ['w', 1, '3', '3'],
        ['m', 1, '4', '4'],
        ['h', 1, '5', '5'],
        ['m', 2, '6', '7'],
    ]


@pytest.mark.unit
def test_runs_put_unnumbered_issues_last_and_label_them():
    issues = [(None, '2021-01', 'Wanted', None), (1, '2020-01', 'Downloaded', '1')]
    assert ledger.runs(issues) == [['h', 1, '1', '1'], ['w', 1, '?', '?']]


@pytest.mark.unit
@pytest.mark.parametrize('status,code', [('Downloaded', 'h'), ('Archived', 'h'), ('Wanted', 'w'), ('Snatched', 's'),
                                         ('Failed', 'f'), ('Ignored', 'i'), ('Skipped', 'm'), (None, 'm')])
def test_run_code(status, code):
    assert ledger.run_code(status) == code


@pytest.mark.unit
def test_runs_empty():
    assert ledger.runs([]) == []
