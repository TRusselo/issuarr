"""The Internet Archive as a search source: every comic file in an item is a result of its own."""
import io
import os
import queue
import types
import zipfile

import pytest

import mylar
from mylar import archiveorg, filechecker

RUN = {'identifier': 'action-comics-408-52p-ctc-01-1972', 'title': 'Action Comics (DC) Vol9 (100 issues)',
       'date': '1970-01-01T00:00:00Z', 'publicdate': '2021-03-02T10:11:12Z'}


def f(name, size=1000, source='original'):
    return {'name': name, 'size': str(size), 'source': source}


def titles(entries):
    return [e['title'] for e in entries]


@pytest.mark.unit
@pytest.mark.parametrize('issue,name,hit', [
    ('401', 'Action Comics 401', True),
    ('401', 'Action Comics 4011', False),
    ('401', 'Action Comics 1401', False),
    ('3', 'Action Comics 003 (DC) (Aug 1938) (c2c)', True),
    ('003', 'Action Comics 3 (1938)', True),
    ('3', 'Action Comics 3.1 (1938)', False),
    ('3', 'Action Comics 022 (03-1940)', False),           # a month, not the issue
    ('5', 'Walt Disney Comics Digest 005 (1968) (c2c) (Walkabout-DCP)', True),
])
def test_the_issue_number_must_stand_alone(issue, name, hit):
    assert bool(archiveorg.number_token(issue).search(name)) is hit


@pytest.mark.unit
def test_a_run_offers_only_the_wanted_issue_with_its_year_added():
    files = [f('Action Comics 401.cbr'), f('Action Comics 402.cbr'), f('Action Comics 401.pdf', source='derivative'),
             f('Action Comics 401_jp2.zip', source='derivative'), f('__ia_thumb.jpg')]
    out = list(archiveorg.entries_for(RUN, files, archiveorg.number_token('401'), 1971))
    assert titles(out) == ['Action Comics 401 (1971)']
    e = out[0]
    assert e['link'] == 'https://archive.org/download/action-comics-408-52p-ctc-01-1972/Action%20Comics%20401.cbr'
    assert e['site'] == 'DDL(Internet Archive)' and e['size'] == '1000' and e['pack'] is False
    assert e['pubdate'] == 'Tue, 02 Mar 2021 10:11:12' and e['id'].startswith('IA-')


@pytest.mark.unit
def test_a_yearless_file_outside_the_runs_years_is_not_offered():
    # Action Comics #1 from 2011 must not take the 1938 run's yearless #1
    files = [f('Action Comics 1.cbr')]
    old_run = dict(RUN, date='1938-06-01')
    assert list(archiveorg.entries_for(old_run, files, archiveorg.number_token('1'), 2011)) == []
    assert list(archiveorg.entries_for(dict(RUN, date=None), files, archiveorg.number_token('1'), 1938)) == []


@pytest.mark.unit
def test_a_file_with_its_own_year_is_left_for_the_matcher():
    files = [f('Action Comics 151 (12-1950).cbr'), f('Walt Disney Comics Digest/Walt Disney Comics Digest 001 (1968) (c2c).zip')]
    out = list(archiveorg.entries_for(RUN, files, archiveorg.number_token('151'), 1950))
    assert titles(out) == ['Action Comics 151 (12-1950)']
    out = list(archiveorg.entries_for(RUN, files, archiveorg.number_token('1'), 2000))
    assert titles(out) == ['Walt Disney Comics Digest 001 (1968) (c2c)']   # the matcher turns the year down
    assert out[0]['link'].endswith('/Walt%20Disney%20Comics%20Digest/Walt%20Disney%20Comics%20Digest%20001%20%281968%29%20%28c2c%29.zip')


@pytest.mark.unit
def test_a_dc_publisher_tag_is_dropped_so_it_isnt_read_as_directors_cut():
    files = [f('Action Comics 001 (DC) (1938) (paper).cbr'), f('Action Comics 3 (DC).cbr')]
    out = list(archiveorg.entries_for(dict(RUN, date='1938-01-01'), files, archiveorg.number_token('1'), 1938))
    assert titles(out) == ['Action Comics 001 (1938) (paper)']
    out = list(archiveorg.entries_for(dict(RUN, date='1938-01-01'), files, archiveorg.number_token('3'), 1938))
    assert titles(out) == ['Action Comics 3 (1938)']


@pytest.mark.unit
def test_items_nearest_the_wanted_year_are_read_first():
    items = [{'identifier': 'new', 'date': '2024-01-01'}, {'identifier': 'none'}, {'identifier': 'run', 'date': '1970-01-01'},
             {'identifier': 'older', 'date': '1951-01-01'}]
    assert [i['identifier'] for i in archiveorg.rank(items, 1972)] == ['run', 'older', 'new', 'none']
    items.append({'identifier': 'action-comics-1068-2024', 'title': 'Action Comics 1068 ( 2024)'})
    assert archiveorg.rank(items, 2024, archiveorg.number_token('1068'))[0]['identifier'] == 'action-comics-1068-2024'


@pytest.mark.unit
def test_the_query_looks_in_the_comics_collection_by_format():
    q = archiveorg.query_for('Batman: The "Long" Halloween')
    assert q.startswith('collection:(comics) AND title:("Batman The Long Halloween") AND format:(')
    assert '"Comic Book RAR"' in q and '"ZIP"' in q


@pytest.mark.unit
@pytest.mark.parametrize('title,series,number,year', [
    ('Action Comics 401 (1971)', 'Action Comics', '401', '1971'),
    ('Action Comics 151 (12-1950)', 'Action Comics', '151', '1950'),
    ('Walt Disney Comics Digest 005 (1968) (c2c) (Walkabout-DCP)', 'Walt Disney Comics Digest', '005', '1968'),
    ('Action Comics 408 52p ctc (01-1972)', 'Action Comics', '408', '1972'),
])
def test_archive_file_names_parse_like_releases(monkeypatch, title, series, number, year):
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'))
    monkeypatch.setattr(mylar.CONFIG, 'IGNORE_SEARCH_WORDS', [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'CUSTOM_ISSUE_EXCEPTIONS', [], raising=False)
    for key in ('ANNUALS_ON', 'ENABLE_TORRENTS', 'FOLDER_SCAN_LOG_VERBOSE'):
        monkeypatch.setattr(mylar.CONFIG, key, False, raising=False)
    parsed = filechecker.FileChecker(file=title, watchcomic=series).listFiles()
    assert parsed['series_name'] == series and parsed['issue_number'] == number and parsed['issue_year'] == year
    assert filechecker.FileChecker(watchcomic=series).matchIT(parsed)['process_status'] == 'match'


def make_zip(path, names):
    with zipfile.ZipFile(path, 'w') as z:
        for n in names:
            z.writestr(n, b'x')


@pytest.mark.unit
def test_a_zip_of_pages_becomes_a_cbz(tmp_path):
    p = tmp_path / 'Walt Disney Comics Digest 001 (1968)[__55__].zip'
    make_zip(p, ['001.jpg', '002.jpg', 'scan.txt'])
    out = archiveorg.as_comic(str(p))
    assert out['success'] and out['filename'] == 'Walt Disney Comics Digest 001 (1968)[__55__].cbz'
    assert os.path.isfile(out['path']) and not p.exists()


@pytest.mark.unit
def test_a_zip_of_comics_is_unpacked_into_a_folder(tmp_path):
    p = tmp_path / 'pack.zip'
    make_zip(p, ['inner/Action Comics 401 (1971).cbr', 'readme.txt'])
    out = archiveorg.as_comic(str(p))
    assert out['success'] and out['filename'] is None
    assert os.listdir(out['path']) == ['Action Comics 401 (1971).cbr'] and not p.exists()


@pytest.mark.unit
def test_a_zip_with_no_comic_in_it_fails(tmp_path):
    p = tmp_path / 'junk.zip'
    make_zip(p, ['readme.txt'])
    assert archiveorg.as_comic(str(p))['success'] is False
    p.write_bytes(b'not a zip')
    assert archiveorg.as_comic(str(p))['link_type_failure'] == 'IA'


class FakeResponse(object):
    def __init__(self, body):
        self.body = body
        self.headers = {'Content-Length': str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.body


@pytest.fixture
def ddl_env(monkeypatch, tmp_path):
    rows = {}

    class DB(object):
        def upsert(self, table, vals, ctrl):
            rows.setdefault(ctrl['id'], {}).update(vals)

    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_LOCATION=str(tmp_path), ENABLE_PROXY=False), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(archiveorg.db, 'DBConnection', DB)
    for name in ('fdebug', 'info', 'warn'):
        monkeypatch.setattr(archiveorg.logger, name, lambda *a, **k: None)
    return rows


@pytest.mark.unit
def test_download_saves_the_file_and_turns_a_page_zip_into_a_cbz(ddl_env, monkeypatch, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('01.jpg', b'x')
    monkeypatch.setattr(archiveorg, 'session', lambda: types.SimpleNamespace(get=lambda *a, **k: FakeResponse(buf.getvalue())))
    item = {'id': 'IA-1', 'issueid': '55', 'link': 'https://archive.org/download/x/Walt%20Disney%20Comics%20Digest%20001%20%281968%29.zip'}
    out = archiveorg.download(item)
    assert out == {'success': True, 'filename': 'Walt Disney Comics Digest 001 (1968)[__55__].cbz',
                   'path': str(tmp_path / 'Walt Disney Comics Digest 001 (1968)[__55__].cbz')}
    assert ddl_env['IA-1']['remote_filesize'] == str(len(buf.getvalue()))


@pytest.mark.unit
def test_a_cancelled_download_leaves_nothing_behind(ddl_env, monkeypatch, tmp_path):
    mylar.DDL_CANCEL.add('IA-2')
    monkeypatch.setattr(archiveorg, 'session', lambda: types.SimpleNamespace(get=lambda *a, **k: FakeResponse(b'abc')))
    out = archiveorg.download({'id': 'IA-2', 'issueid': '9', 'link': 'https://archive.org/download/x/A%201.cbr'})
    assert out['cancelled'] and out['success'] is False and os.listdir(tmp_path) == []


@pytest.mark.unit
def test_a_grab_is_saved_and_queued_as_an_archive_download(ddl_env):
    info = [{'ComicName': 'Action Comics', 'comyear': '1971', 'size': '33.3 MB', 'IssueNumber': '401', 'IssueID': '55',
             'ComicID': '7', 'nzbtitle': 'Action Comics 401 (1971)', 'oneoff': False, 'entry': {'size': '34957320'}}]
    assert archiveorg.queue('IA-3', 'https://archive.org/download/x/A.cbr', info) == {'success': True, 'site': 'IA'}
    row, item = ddl_env['IA-3'], mylar.DDL_QUEUE.get_nowait()
    assert row['site'] == item['site'] == 'DDL(Internet Archive)' and row['link_type'] == item['link_type'] == 'IA'
    assert row['remote_filesize'] == '34957320' and row['size'] == '33.3 MB' and item['issueid'] == '55'


@pytest.mark.unit
def test_the_download_queue_hands_archive_items_to_the_archive_downloader(monkeypatch):
    from mylar.queues import ddl
    assert not ddl.is_getcomics({'site': 'DDL(Internet Archive)', 'link_type': 'IA'})   # parallel, not the GetComics line
    seen = []
    monkeypatch.setattr(archiveorg, 'download', lambda item: seen.append(item['id']) or {'success': False, 'filename': None, 'path': None})
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(POST_PROCESSING=True), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUED', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(ddl.logger, 'info', lambda *a, **k: None)
    db = types.SimpleNamespace(upsert=lambda *a, **k: None)
    out = ddl.ddl_process(db, {'id': 'IA-4', 'site': 'DDL(Internet Archive)', 'link_type': 'IA', 'series': 'Action Comics'})
    assert seen == ['IA-4'] and out['success'] is False
