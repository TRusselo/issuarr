import types

import pytest

import mylar
from mylar import getcomics, search_filer


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(PACK_PRIORITY=False, DDL_QUERY_DELAY=15), raising=False)


def queries_sent(monkeypatch, name, issue, year, chktpb=0):
    """Run GC.search() with every query missing and return the query lines sent to GetComics."""
    sent, slept = [], []
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.query = {'comicname': name, 'issue': issue, 'year': year}
    gc.search_format = ['"%s #%s (%s)"', '%s #%s (%s)', '%s #%s', '%s %s']
    gc.issueid, gc.comicid = '1', '2'
    monkeypatch.setattr(gc, 'cookie_receipt', lambda: None, raising=False)
    monkeypatch.setattr(gc, 'perform_search_queries', lambda q: sent.append(q) or iter(()), raising=False)
    monkeypatch.setattr(search_filer, 'search_check', lambda: types.SimpleNamespace(
        check_for_first_result=lambda results, is_info, prefer_pack=False: None))
    monkeypatch.setattr(getcomics.time, 'sleep', slept.append)
    gc.search(is_info={'chktpb': chktpb})
    return sent, slept


@pytest.mark.unit
def test_a_trade_queries_the_series_name_once(monkeypatch):
    sent, slept = queries_sent(monkeypatch, 'Aquaman', '5', '2016', chktpb=1)
    assert sent.count('Aquaman') == 1
    assert sent == ['Aquaman', '"Aquaman #5 (2016)"', 'Aquaman #5', 'Aquaman 2016']
    assert slept == [15] * len(sent)  # a skipped query costs no wait; the others keep theirs


@pytest.mark.unit
def test_quoted_and_hash_forms_are_sent_once(monkeypatch):
    # GetComics ignores quotes and '#': in the live log 214 such pairs returned the same counts
    sent, _ = queries_sent(monkeypatch, 'Powers', '1', '2009')
    assert sent == ['"Powers #1 (2009)"', 'Powers #1', 'Powers 2009']


@pytest.mark.unit
def test_queries_that_differ_in_more_than_quotes_or_hash_all_run(monkeypatch):
    # the colon is only taken out of the unquoted form, so both are still sent
    sent, _ = queries_sent(monkeypatch, 'Alpha: Big Time', '.1', '2013')
    assert sent == ['"Alpha: Big Time #.1 (2013)"', 'Alpha Big Time #.1 (2013)', 'Alpha Big Time #.1',
                    'Alpha Big Time 2013']
    # the cleaned trade query drops 'The', so the plain name is a different search
    sent, _ = queries_sent(monkeypatch, 'Batman The Dark Prince Charming', '1', '2017', chktpb=1)
    assert sent[0] == 'Batman Dark Prince Charming'
    assert 'Batman The Dark Prince Charming' in sent


@pytest.mark.unit
@pytest.mark.parametrize('issue', [None, 'None'])
def test_an_issue_with_no_number_never_searches_none(monkeypatch, issue):
    sent, _ = queries_sent(monkeypatch, 'Ghost Rider', issue, '2007')
    assert not any('None' in q for q in sent)
    assert sent == ['"Ghost Rider (2007)"', 'Ghost Rider']


@pytest.mark.unit
def test_query_key():
    assert getcomics.query_key('"Powers #1 (2009)"') == getcomics.query_key('powers  1 (2009)')
    assert getcomics.query_key('Powers #1 (2009)') != getcomics.query_key('Powers #1 (2010)')
    assert getcomics.query_key('Powers #1') != getcomics.query_key('Powers #11')
