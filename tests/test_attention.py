"""Downloads > Needs attention: files filing couldn't place, and what's in the review folder."""
import datetime
import os
import threading
import types

import pytest

import mylar
from mylar import attention, db


@pytest.fixture
def env(monkeypatch, tmp_path):
    review = tmp_path / 'mylar-review'
    review.mkdir()
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in dict(IGNORE_SEARCH_WORDS=[], CUSTOM_ISSUE_EXCEPTIONS=[], ANNUALS_ON=False, FOLDER_SCAN_LOG_VERBOSE=False,
                     ARCHIVE_REVIEW_DIR=str(review), ATTENTION_TRASH_DAYS=14, ZERO_LEVEL_N=None, ZERO_LEVEL=False).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    for name in ('fdebug', 'info', 'warn'):
        monkeypatch.setattr(attention.logger, name, lambda *a, **k: None)
    monkeypatch.setattr(attention, '_COUNT', [0.0, 0])
    monkeypatch.setattr(attention, '_COMICS', [0.0, []])
    monkeypatch.setattr(attention, 'JOBS', {})
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicVersion TEXT, Total INTEGER)')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT, IssueDate TEXT, ReleaseDate TEXT)')
    d.action("INSERT INTO comics VALUES ('85120', 'Marvel Universe Guardians of the Galaxy', '2015', NULL, 23), "
             "('94801', 'Great Lakes Avengers', '2016', NULL, 7)")
    d.action("INSERT INTO issues VALUES ('547001', '85120', '3', 'Snatched', '2016-02-01', NULL), "
             "('562595', '94801', '2', 'Snatched', '2017-01-01', NULL)")
    return types.SimpleNamespace(root=tmp_path, review=review, db=d)


def touch(path, data=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return str(path)


@pytest.mark.unit
def test_the_most_telling_reason_wins():
    assert attention.pick({'series', 'volume'}) == 'volume'
    assert attention.pick({'year', 'issue'}) == 'year'
    assert attention.pick(set()) == 'series'


@pytest.mark.unit
def test_a_recorded_reject_is_listed_with_its_reason_and_closest_match(env):
    p = touch(env.root / 'dl' / 'Marvel Universe Guardians of the Galaxy v2 003 (2016).cbr')
    attention.record(p, 'volume', 'The file says v2; Marvel Universe Guardians of the Galaxy has no volume set.', '85120')
    [item] = attention.items()
    assert item['reason'] == 'volume' and item['detail'].startswith('The file says v2')
    assert item['parsed']['series'] == 'Marvel Universe Guardians of the Galaxy' and item['parsed']['issue'] == '003'
    best = item['matches'][0]
    assert (best['name'], best['issueid'], best['number']) == ('Marvel Universe Guardians of the Galaxy', '547001', '3')
    assert best['agree']['series'] and best['agree']['issue'] and best['agree']['volume'] is False
    assert attention.count() == 1


@pytest.mark.unit
def test_everything_in_the_review_folder_is_listed(env):
    touch(env.review / 'Jungle Action' / 'Great Lakes Avengers 002 (2017).cbz')
    touch(env.review / 'notes.txt')
    [item] = attention.items()
    assert item['reason'] == 'unclaimed' and item['in_review'] is True
    assert item['matches'][0]['issueid'] == '562595'


@pytest.mark.unit
def test_a_moved_file_keeps_its_reason_and_a_gone_file_drops_off(env):
    old = touch(env.root / 'dl' / 'Foo 001 (2020).cbr')
    attention.record(old, 'year', 'The file says 2020.')
    new = str(env.review / 'Foo 001 (2020).cbr')
    os.replace(old, new)
    attention.moved(old, new)
    assert [(i['path'], i['reason']) for i in attention.items()] == [(new, 'year')]
    os.remove(new)
    assert attention.items() == []
    assert env.db.select('SELECT * FROM attention') == []


@pytest.mark.unit
def test_an_ignored_file_stays_hidden_until_it_changes(env):
    p = touch(env.review / 'Foo 001 (2020).cbr')
    attention.ignore(p)
    assert attention.items() == []
    touch(p, b'a bigger file now')
    assert len(attention.items()) == 1


@pytest.mark.unit
def test_trash_moves_the_file_into_todays_folder_and_old_days_are_purged(env):
    p = touch(env.review / 'Foo 001 (2020).cbr')
    out = attention.trash(p)
    assert out['ok'] and 'after 14 days' in out['note']
    today = os.path.join(attention.trash_dir(), datetime.date.today().isoformat())
    assert os.listdir(today) == ['Foo 001 (2020).cbr'] and not os.path.exists(p)
    old = os.path.join(attention.trash_dir(), (datetime.date.today() - datetime.timedelta(days=20)).isoformat())
    touch(os.path.join(old, 'gone.cbr'))
    assert attention.purge_trash() == 1 and not os.path.exists(old) and os.path.isdir(today)


@pytest.mark.unit
def test_only_files_on_the_page_can_be_acted_on(env):
    outside = touch(env.root / 'library' / 'Keep Me 001 (2020).cbz')
    assert attention.trash(outside)['ok'] is False and os.path.exists(outside)
    assert attention.file_as(outside, '94801', '562595')['ok'] is False


@pytest.mark.unit
def test_file_as_refuses_an_issue_not_on_that_series(env):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    assert attention.file_as(p, '85120', '562595') == {'ok': False, 'note': 'That issue isn\'t on your watchlist.'}


@pytest.mark.unit
def test_file_as_hands_filing_the_users_pick_as_a_forced_match(env, monkeypatch):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    seen = []

    class FakePP(object):
        def __init__(self, nzb_name, folder, queue=None):
            seen.append((nzb_name, folder))

        def nzb_or_oneoff_pp(self, manual=None):
            seen.append(manual)
            os.replace(p, str(env.root / 'library.cbz'))           # filed: moved into the library
            db.DBConnection().action("UPDATE issues SET Status='Downloaded' WHERE IssueID='562595'")

    from mylar import PostProcessor
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: target(*args)))
    out = attention.file_as(p, '94801', '562595')
    assert out == {'ok': True, 'note': "Filing as Great Lakes Avengers #2. It starts as soon as the filing that's running now finishes."}
    assert seen[0] == ('Manual Run', str(env.review))
    [entry] = seen[1]
    assert entry['ComicLocation'] == p and entry['IssueID'] == '562595' and entry['ForcedMatch'] is True
    assert attention.JOBS[p] == {'state': 'filed', 'note': 'Filed as Great Lakes Avengers #2'}
    assert attention.items() == []


@pytest.mark.unit
def test_filing_that_doesnt_finish_says_so(env, monkeypatch):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')

    class FakePP(object):
        def __init__(self, *a, **k):
            pass

        def nzb_or_oneoff_pp(self, manual=None):
            pass

    from mylar import PostProcessor
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: target(*args)))
    attention.file_as(p, '94801', '562595')
    assert attention.JOBS[p]['state'] == 'failed'
    assert attention.items()[0]['job']['state'] == 'failed'


@pytest.mark.unit
def test_search_finds_watchlist_series_by_part_of_the_name(env):
    assert [s['comicid'] for s in attention.search('guardians')] == ['85120']
    assert attention.search('') == []


@pytest.mark.unit
def test_filing_records_only_the_files_it_left_unplaced(env, monkeypatch):
    from mylar import PostProcessor
    recorded = []
    monkeypatch.setattr(attention, 'record', lambda path, reason, detail='', comicid=None: recorded.append((os.path.basename(path), reason, detail, comicid)))
    a = touch(env.root / 'dl' / 'Marvel Universe Guardians of the Galaxy v2 003 (2016).cbr')
    b = touch(env.root / 'dl' / 'Marvel Universe Guardians of the Galaxy 001 (2015).cbr')
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp.comicid = None
    manual = []
    for path in (a, b):
        pp._att_start({'comiclocation': os.path.dirname(path), 'sub': None, 'comicfilename': os.path.basename(path)}, (len(manual), 0, 0))
        if path == a:
            pp._att_why('series')
            pp._att_why('volume', 'The file says v2; it has no volume set.', '85120')
        else:
            manual.append({'ComicLocation': path})     # this one was placed
    pp._att_settle((len(manual), 0, 0))
    assert recorded == [('Marvel Universe Guardians of the Galaxy v2 003 (2016).cbr', 'volume', 'The file says v2; it has no volume set.', '85120')]


@pytest.mark.unit
def test_series_with_the_same_name_are_told_apart_by_the_issues_year(env):
    env.db.action("INSERT INTO comics VALUES ('1001', 'X-Factor', '1986', NULL, 259), ('1002', 'X-Factor', '2020', NULL, 10), "
                  "('1003', 'Battle Scars', '2012', NULL, 6)")
    env.db.action("INSERT INTO issues VALUES ('a3', '1001', '3', 'Downloaded', '1986-04-01', NULL), "
                  "('b3', '1002', '3', 'Wanted', '2020-09-01', NULL), ('c3', '1003', '3', 'Wanted', '2012-03-01', NULL)")
    out = attention.suggest({'series': 'X-Factor', 'issue': '003', 'year': '2020', 'volume': None})
    assert [(m['comicid'], m['agree']['year']) for m in out] == [('1002', True), ('1001', False)]
    assert attention.suggest({'series': 'Untitled scan', 'issue': '0003', 'year': None, 'volume': None}) == []


@pytest.mark.unit
def test_search_puts_the_exact_name_first(env):
    env.db.action("INSERT INTO comics VALUES ('1001', 'X-Factor', '1986', NULL, 259), ('2001', 'All-New X-Factor', '2014', NULL, 20)")
    assert [s['name'] for s in attention.search('x-factor')][:2] == ['X-Factor', 'All-New X-Factor']


def cbz_with_cover(path):
    import io, zipfile
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        for n, colour in ((1, (200, 30, 30)), (2, (240, 240, 240))):
            b = io.BytesIO()
            Image.new('RGB', (400, 600), colour).save(b, 'JPEG')
            z.writestr('Great Lakes Avengers 002-%03d.jpg' % n, b.getvalue())
    return str(path)


@pytest.mark.unit
def test_the_files_front_cover_is_extracted_and_cached(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    p = cbz_with_cover(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    out = attention.file_cover(p)
    from PIL import Image
    with Image.open(out) as im:
        assert im.format == 'JPEG' and im.getpixel((10, 10))[0] > 150     # the red first page, not the white second
    assert attention.file_cover(p) == out
    assert attention.file_cover(str(env.root / 'library' / 'x.cbz')) is None


@pytest.mark.unit
def test_the_issue_cover_comes_from_comicvine_once(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL TEXT")
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL_ALT TEXT")
    env.db.action("UPDATE issues SET ImageURL='https://comicvine.gamespot.com/a/uploads/scale_small/gla2.jpg' WHERE IssueID='562595'")
    calls = []
    import requests

    def get(url, **kw):
        calls.append(url)
        return types.SimpleNamespace(content=b'\xff\xd8jpeg', headers={'Content-Type': 'image/jpeg'}, raise_for_status=lambda: None)
    monkeypatch.setattr(requests, 'get', get)
    out = attention.issue_cover('562595')
    assert open(out, 'rb').read() == b'\xff\xd8jpeg'
    assert attention.issue_cover('562595') == out and len(calls) == 1
    assert attention.issue_cover('547001') is None                   # no image on record


@pytest.mark.unit
def test_a_page_that_isnt_an_image_is_not_kept_as_a_cover(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL TEXT")
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL_ALT TEXT")
    env.db.action("UPDATE issues SET ImageURL='https://comicvine.gamespot.com/x.jpg' WHERE IssueID='562595'")
    import requests
    monkeypatch.setattr(requests, 'get', lambda url, **kw: types.SimpleNamespace(content=b'<html>', headers={'Content-Type': 'text/html'}, raise_for_status=lambda: None))
    assert attention.issue_cover('562595') is None


@pytest.mark.unit
def test_quick_bounds_never_drop_a_close_name(monkeypatch):
    # the length and shared-letter bounds must keep every series the full comparison would keep
    import collections
    import difflib
    names = ['X-Factor', 'All-New X-Factor', 'X-Force', 'Uncanny X-Men', 'X-Men', 'Batman', 'Batman Beyond',
             'Spider-Man', 'Superior Spider-Man', 'Spider-Woman', 'Powers', 'Power Pack', 'Hetalia Axis Powers',
             'Supergirl', 'Supergirl Being Super', 'Ragnarok', 'Jungle Action', 'Great Lakes Avengers']
    rows = [{'ComicID': str(i), 'ComicName': n, 'norm': attention._norm(n), 'chars': collections.Counter(attention._norm(n))}
            for i, n in enumerate(names)]
    monkeypatch.setattr(attention, '_watchlist', lambda: rows)
    attention._NAMED.clear()
    for want in ['x factor', 'xfactor', 'x men', 'spiderman', 'spider man', 'power', 'supergirl', 'batman beyon', 'ragnarok']:
        brute = sorted(r['ComicID'] for r in rows if difflib.SequenceMatcher(None, want, r['norm']).ratio() >= 0.75)
        assert sorted(c['ComicID'] for s, c in attention._named(want)) == brute, want


@pytest.mark.unit
def test_a_cover_request_gives_up_with_busy_when_every_slot_is_taken(env, monkeypatch):
    # cover requests must not pile up on the web server's few threads
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    monkeypatch.setattr(attention, 'COVER_WAIT', 0.05)
    p = cbz_with_cover(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    taken = [attention.COVER_SLOTS.acquire(timeout=0) for _ in range(5)]
    try:
        assert attention.file_cover(p) == attention.BUSY
    finally:
        for got in taken:
            if got:
                attention.COVER_SLOTS.release()
    assert attention.file_cover(p) not in (None, attention.BUSY)


@pytest.mark.unit
def test_a_file_without_a_cover_is_only_opened_once(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    p = env.review / 'Broken 001 (2020).cbz'
    p.write_bytes(b'not a zip')
    from mylar import getimage
    calls = []
    monkeypatch.setattr(getimage, 'extract_image', lambda *a, **k: calls.append(a) or None)
    assert attention.file_cover(str(p)) is None
    assert attention.file_cover(str(p)) is None and len(calls) == 1


@pytest.mark.unit
def test_a_failed_comicvine_cover_is_not_fetched_again_straight_away(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL TEXT")
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL_ALT TEXT")
    env.db.action("UPDATE issues SET ImageURL='https://comicvine.gamespot.com/x.jpg' WHERE IssueID='562595'")
    import requests
    calls = []

    def get(url, **kw):
        calls.append(url)
        raise requests.exceptions.ConnectTimeout('slow')
    monkeypatch.setattr(requests, 'get', get)
    assert attention.issue_cover('562595') is None
    assert attention.issue_cover('562595') is None and len(calls) == 1


@pytest.mark.unit
def test_the_cover_endpoint_says_busy_with_a_503(monkeypatch):
    import cherrypy
    from mylar.webserve import WebInterface
    monkeypatch.setattr(attention, 'file_cover', lambda path: attention.BUSY)
    with pytest.raises(cherrypy.HTTPError) as e:
        WebInterface().attention_cover('/x.cbz', v='1', r='2')
    assert e.value.status == 503


def _no_thread(monkeypatch):
    started = []
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args=(), **k: types.SimpleNamespace(start=lambda: started.append((target, args))))
    return started


@pytest.mark.unit
def test_a_file_as_choice_survives_a_restart(env, monkeypatch):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    started = _no_thread(monkeypatch)
    assert attention.file_as(p, '94801', '562595')['ok'] is True
    assert attention.JOBS[p]['state'] == 'waiting'
    row = env.db.selectone('SELECT status, pick FROM attention WHERE path=?', [p]).fetchone()
    assert (row['status'], row['pick']) == ('queued', '94801|562595')
    # filing turning the file down again doesn't drop the user's choice
    attention.record(p, 'series')
    assert env.db.selectone('SELECT status FROM attention WHERE path=?', [p]).fetchone()['status'] == 'queued'
    # restart: jobs in memory are gone, the choice is picked up again
    attention.JOBS.clear()
    assert [i['job'] for i in attention.items()] == [{'state': 'waiting', 'note': 'Waiting to file'}]
    del started[:]
    assert attention.resume_picks() == 1
    assert attention.JOBS[p]['note'] == 'Waiting to file as Great Lakes Avengers #2'
    assert len(started) == 1


@pytest.mark.unit
def test_a_choice_that_fails_goes_back_to_open(env, monkeypatch):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')

    class FakePP(object):
        def __init__(self, *a, **k):
            pass

        def nzb_or_oneoff_pp(self, manual=None):
            pass   # nothing filed

    from mylar import PostProcessor
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: target(*args)))
    attention.file_as(p, '94801', '562595')
    assert attention.JOBS[p]['state'] == 'failed'
    row = env.db.selectone('SELECT status, pick FROM attention WHERE path=?', [p]).fetchone()
    assert (row['status'], row['pick']) == ('open', None)


@pytest.mark.unit
def test_a_file_already_moved_by_hand_just_leaves_the_list(env):
    p = touch(env.root / 'downloads' / 'Some Comic 001 (2020).cbz')
    attention.record(p, 'series')
    os.remove(p)
    out = attention.trash(p)
    assert out['ok'] is True and out['gone'] is True
    assert env.db.selectone('SELECT path FROM attention WHERE path=?', [p]).fetchone() is None


@pytest.mark.unit
def test_refile_folders_groups_review_runs_it_last_and_skips_nested(env):
    review = str(env.review)
    paths = [os.path.join(review, 'a.cbz'), os.path.join(review, 'sub', 'b.cbz'),
             '/dl/Pack (2003)/x.cbz', '/dl/Pack (2003)/Annuals/y.cbz', '/dl/Other/z.cbz', '/dl/Pack (2003)/Annuals/w.cbz']
    assert attention.refile_folders(paths) == ['/dl/Other', '/dl/Pack (2003)', review]


@pytest.mark.unit
def test_try_filing_again_runs_filing_over_each_folder_after_new_downloads(env, monkeypatch):
    a = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    b = touch(env.root / 'dl' / 'Pack' / 'Other 001 (2001).cbz')
    attention.record(b, 'year')
    ran, waits = [], []
    sizes = [2, 1, 0]
    monkeypatch.setattr(mylar, 'PP_QUEUE', types.SimpleNamespace(qsize=lambda: sizes.pop(0) if sizes else 0), raising=False)
    monkeypatch.setattr(attention.time, 'sleep', waits.append)

    class FakePP(object):
        def __init__(self, name, folder, queue=None):
            self.folder = folder
            ran.append((name, folder))

        def Process(self):
            if self.folder == str(env.review):
                os.remove(a)   # filed

    from mylar import PostProcessor
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args=(), **k: types.SimpleNamespace(start=lambda: target(*args)))
    out = attention.refile_all()
    assert out['ok'] is True
    assert ran == [('Manual Run', str(env.root / 'dl' / 'Pack')), ('Manual Run', str(env.review))]
    assert len(waits) == 2   # waited twice for the queue to empty before starting
    st = attention.status()['refile']
    assert (st['state'], st['before'], st['after'], st['done'], st['total']) == ('done', 2, 1, 2, 2)


@pytest.mark.unit
def test_everything_is_tried_again_once_per_new_version(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root), raising=False)
    monkeypatch.setattr(mylar, 'CURRENT_VERSION', 'abc123', raising=False)
    calls = []
    monkeypatch.setattr(attention, 'refile_all', lambda auto=False: calls.append(auto))
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args=(), **k: types.SimpleNamespace(start=lambda: target(*args)))
    monkeypatch.setattr(attention.time, 'sleep', lambda s: None)
    assert attention.refile_after_update() is True
    assert attention.refile_after_update() is False
    monkeypatch.setattr(mylar, 'CURRENT_VERSION', 'def456', raising=False)
    assert attention.refile_after_update() is True
    assert calls == [True, True]
