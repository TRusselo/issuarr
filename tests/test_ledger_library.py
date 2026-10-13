import pytest

from mylar import ledger


class FakeDB:
    COMICS = [{'ComicID': '1', 'ComicName': 'Done', 'ComicYear': '2000', 'ComicPublisher': 'P', 'Have': 3, 'Total': 3},
              {'ComicID': '2', 'ComicName': 'Gappy', 'ComicYear': '2001', 'ComicPublisher': 'P', 'Have': 2, 'Total': 3}]
    ISSUES = [dict(IssueID='1-%s' % n, ComicID='1', Issue_Number=str(n), Int_IssueNumber=n, IssueName='', ReleaseDate='2000-01-01',
                   IssueDate='2000-01-01', Status='Downloaded') for n in (1, 2, 3)] + \
             [dict(IssueID='2-%s' % n, ComicID='2', Issue_Number=str(n), Int_IssueNumber=n, IssueName='', ReleaseDate='2001-01-01',
                   IssueDate='2001-01-01', Status=s) for n, s in ((1, 'Downloaded'), (2, 'Wanted'), (3, 'Downloaded'))]

    def select(self, sql, *a):
        return self.COMICS if 'FROM comics' in sql else self.ISSUES


@pytest.mark.unit
def test_the_summary_gets_whole_library_totals_not_just_series_with_gaps(monkeypatch):
    monkeypatch.setattr(ledger.db, 'DBConnection', FakeDB)
    monkeypatch.setattr(ledger, '_lookups', lambda db: ({}, {}))
    monkeypatch.setattr(ledger, '_trades', lambda db, status, tcomics: [])
    m = ledger.missing_data()
    assert m['library'] == {'series': 2, 'have': 5, 'tracked': 6, 'complete': 1}
    assert [r[1] for r in m['rows']] == [m['series'].index(next(s for s in m['series'] if s[0] == 'Gappy'))]


@pytest.mark.unit
def test_the_missing_column_sorts_by_total_missing():
    src = open('data/js/ledger.js').read()
    assert 'x.miss = x.total * 1e6 + x.p[1];' in src
