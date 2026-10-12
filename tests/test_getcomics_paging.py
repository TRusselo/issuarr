import types

import pytest

import mylar
from mylar import getcomics


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(PACK_PRIORITY=False, DDL_QUERY_DELAY=15), raising=False)
    monkeypatch.setattr(mylar.search, 'check_time', lambda lastrun: 999)
    monkeypatch.setattr(mylar.search, 'last_run_check', lambda write=None: None)
    monkeypatch.setattr(getcomics, '_page_cache', {})
    monkeypatch.setattr(getcomics, '_last_fetch', [0.0])


def post(title, n):
    return {'title': title, 'series': title, 'link': 'https://getcomics.org/p/%s' % n}


def read_pages(monkeypatch, pages, name='Powers', names=None, max_pages=getcomics.MAX_SEARCH_PAGES, query=None):
    """Page through fake GetComics results; return the posts handed to matching, the number
    of pages fetched and the info lines logged."""
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.url = 'https://getcomics.org'
    gc.headers = {}
    gc.query = {'comicname': name, 'issue': '1', 'year': '2009'}
    if names is not None:
        gc.series_names = names
    gc.provider_stat = {'lastrun': 0, 'hits': 0}
    fetched, logged = [], []
    gc.session = types.SimpleNamespace(
        get=lambda url, **kw: fetched.append(url) or types.SimpleNamespace(status_code=200, text=url))

    def parse(html, status):
        # the fake page's text is its address, so a page served from the cache parses the same
        n = int(html.rsplit('/', 2)[-2]) if '/page/' in html else 1
        return pages[n - 1], ('https://getcomics.org/page/%s' % (n + 1) if n < len(pages) else None)
    monkeypatch.setattr(gc, 'parse_search_result', parse, raising=False)
    monkeypatch.setattr(getcomics.logger, 'info', lambda msg, *a: logged.append(msg % a if a else msg))
    yielded = [r['title'] for r in gc.perform_search_queries(query or '%s #1' % name, max_pages=max_pages)]
    return yielded, len(fetched), logged


def page(*titles):
    return [post(t, '%s-%s' % (t, i)) for i, t in enumerate(titles)]


OTHER = page('Power Rangers - Green #1 (2026)', 'Absolute Power #1 (2024)')
AXIS = page('Hetalia - Axis Powers Vol. 1 (2011)', 'Pounds of Power #1 (2026)')


@pytest.mark.unit
def test_stops_after_two_pages_with_nothing_from_the_series(monkeypatch):
    # live log 11 Oct: "Powers #1" read all 14 pages, mostly Power Rangers
    pages = [page('Powers - The Bureau #1 - 12 (2013-2014)'), OTHER, AXIS, page('Powers #1 (2009)')]
    yielded, fetched, _ = read_pages(monkeypatch, pages)
    assert fetched == 3
    assert 'Powers #1 (2009)' not in yielded


@pytest.mark.unit
def test_one_page_without_the_series_is_not_enough_to_stop(monkeypatch):
    # results are newest first, so the series can come back after a page of other posts
    pages = [OTHER, page('Powers Vol. 1 (TPB) (2018)'), OTHER, page('Powers #1 (2009)')]
    yielded, fetched, _ = read_pages(monkeypatch, pages)
    assert fetched == 4
    assert 'Powers #1 (2009)' in yielded


@pytest.mark.unit
def test_keeps_reading_while_pages_name_the_series_and_a_late_match_is_found(monkeypatch):
    # the trade search for Birds of Prey #1 matched on page 8 of 8
    pages = [page('Birds of Prey #%s (2024)' % n) for n in range(7)] + [page('Birds of Prey Vol. 1 - Trouble in Mind (2012)')]
    yielded, fetched, logged = read_pages(monkeypatch, pages, name='Birds of Prey')
    assert fetched == 8
    assert yielded[-1] == 'Birds of Prey Vol. 1 - Trouble in Mind (2012)'
    assert not any('page limit' in line for line in logged)


@pytest.mark.unit
def test_page_limit_is_logged(monkeypatch):
    pages = [page('Aquaman #%s (2016)' % n) for n in range(17)]
    yielded, fetched, logged = read_pages(monkeypatch, pages, name='Aquaman')
    assert fetched == getcomics.MAX_SEARCH_PAGES
    assert len(yielded) == getcomics.MAX_SEARCH_PAGES
    assert any('Aquaman #1' in line and 'page limit' in line for line in logged)


@pytest.mark.unit
def test_pack_titles_count_as_the_series(monkeypatch):
    # check_for_pack takes the year and range off a pack's title: "Fearless Defenders"
    pages = [OTHER, page('Fearless Defenders'), OTHER, page('Fearless Defenders #1 (2013)')]
    yielded, fetched, _ = read_pages(monkeypatch, pages, name='Fearless Defenders')
    assert fetched == 4
    assert yielded[-1] == 'Fearless Defenders #1 (2013)'


@pytest.mark.unit
def test_the_series_own_name_counts_when_searching_an_alternate_name(monkeypatch):
    pages = [OTHER, page('Captain Marvel #1 (2012)'), OTHER, page('Captain Marvel #1 (2019)')]
    _, fetched, _ = read_pages(monkeypatch, pages, name='Carol Danvers', names=['Carol Danvers', 'Captain Marvel'])
    assert fetched == 4
    getcomics._page_cache.clear()  # the same search again, fetched fresh
    _, fetched, _ = read_pages(monkeypatch, pages, name='Carol Danvers')
    assert fetched == 2


@pytest.mark.unit
def test_search_remembers_the_series_and_searched_names(monkeypatch):
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.query = {'comicname': 'Carol Danvers', 'issue': '1', 'year': '2012'}
    gc.search_format = ['%s #%s']
    gc.issueid, gc.comicid = '1', '2'
    monkeypatch.setattr(gc, 'cookie_receipt', lambda: None, raising=False)
    monkeypatch.setattr(gc, 'perform_search_queries', lambda q, max_pages=None: iter(()), raising=False)
    monkeypatch.setattr(getcomics.time, 'sleep', lambda s: None)
    gc.search(is_info={'chktpb': 0, 'ComicName': 'Captain Marvel'})
    assert gc.series_names == ['Carol Danvers', 'Captain Marvel']


@pytest.mark.unit
@pytest.mark.parametrize('title,name,expected', [
    ('Powers - The Bureau', 'Powers', True),
    ('Powers Vol. 1 (TPB) (2018)', 'Powers', True),
    ('Hetalia - Axis Powers Vol. 1 (2011)', 'Powers', False),
    ('Power Rangers - Green #1 (2026)', 'Powers', False),
    ('Spider-Man #1 (2022)', 'Spiderman', True),
    ('Batman Adventures #1 - 4 (2016)', 'The Batman Adventures', True),
    ('Star Wars - Jedi of the Republic - Mace Windu #1 (2017)', 'Star Wars: Mace Windu', True),
    ('Mighty Morphin Power Rangers - Rita’s Rewind #1 (2025)', 'Rita\'s Rewind', False),
    ('Ragnarok #1 (2019)', 'Ragnarök', True),
    ('The 7th Sword #1 (2021)', 'The 7ᵗʰ Sword', True),
    ('Nightwing - Bludhaven #1 (2025)', 'Nightwing: Blüdhaven', True),
    ('Arana - Heart of the Spider #1 (2005)', 'Araña: Heart of the Spider', True),
    (None, 'Powers', False),
])
def test_names_series(title, name, expected):
    assert getcomics.names_series(title, [name]) is expected


@pytest.mark.unit
def test_an_issue_query_reads_at_most_three_pages(monkeypatch):
    # 11-12 Oct: 185 of 188 matches were on pages 1-3; later ones were all trades searched by name
    pages = [page('Powers #%s (2009)' % n) for n in range(2, 12)]
    _, fetched, logged = read_pages(monkeypatch, pages, max_pages=getcomics.ISSUE_SEARCH_PAGES)
    assert fetched == 3
    assert any('3-page limit' in m for m in logged)


@pytest.mark.unit
def test_a_repeated_query_is_answered_from_the_last_fetch(monkeypatch):
    pages = [page('Powers #2 (2009)'), page('Powers #3 (2009)')]
    first, fetched, _ = read_pages(monkeypatch, pages)
    again, fetched_again, _ = read_pages(monkeypatch, pages, query='"Powers 1"')  # GetComics reads it the same
    assert fetched == 2 and fetched_again == 0
    assert again == first


@pytest.mark.unit
def test_cached_pages_expire(monkeypatch):
    pages = [page('Powers #2 (2009)')]
    read_pages(monkeypatch, pages)
    now = getcomics.time.time()
    monkeypatch.setattr(getcomics.time, 'time', lambda: now + getcomics.PAGE_CACHE_SECS + 1)
    _, fetched, _ = read_pages(monkeypatch, pages)
    assert fetched == 1


@pytest.mark.unit
def test_the_wait_between_pages_holds_across_issues(monkeypatch):
    # each issue's search starts from a stale provider lastrun; the process-wide clock still counts
    waited = []
    monkeypatch.setattr(mylar.search, 'check_time', lambda last: getcomics.time.time() - last)
    monkeypatch.setattr(getcomics.time, 'sleep', waited.append)
    read_pages(monkeypatch, [page('Powers #2 (2009)')], query='Powers #1')
    read_pages(monkeypatch, [page('Powers #3 (2009)')], query='Powers #2')
    assert len(waited) == 1 and waited[0] >= 14
