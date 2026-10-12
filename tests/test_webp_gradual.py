"""WebP conversion that moves on through the library: what each file came to is remembered, the
largest files go first, damaged files go to Needs attention, and a nightly window does the rest."""
import json
import os
import types

import pytest

import mylar
from mylar import attention, db, webp

from .test_webp import COMICINFO, jpeg, make_cbz, page


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    lib = tmp_path / 'comics'
    lib.mkdir()
    (tmp_path / 'cache').mkdir()
    saved = {}

    def writeconfig(values=None, **kw):
        for k, v in (values or {}).items():
            setattr(cfg, k.upper(), v)
            saved[k] = v

    cfg = types.SimpleNamespace(
        WEBP_QUALITY=85, WEBP_MIN_SOURCE_Q=80, WEBP_SINCE='2015', WEBP_THREADS=2, WEBP_ON_IMPORT=True,
        WEBP_BACKUP_DIR=None, DESTINATION_DIR=str(lib), CACHE_DIR=str(tmp_path / 'cache'),
        ARCHIVE_REVIEW_DIR=str(tmp_path / 'review'), ATTENTION_TRASH_DAYS=14, writeconfig=writeconfig)
    monkeypatch.setattr(mylar, 'CONFIG', cfg, raising=False)
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(webp, '_ensured', [None])
    monkeypatch.setattr(webp, 'BULK', {'state': 'idle'})
    monkeypatch.setattr(webp, 'GRADUAL', {'state': 'idle'})
    monkeypatch.setattr(webp, '_queue', webp.queue.Queue())
    monkeypatch.setattr(webp, '_importing', [None])
    monkeypatch.setattr(attention, '_COUNT', [0.0, 0])
    for name in ('fdebug', 'info', 'warn'):
        monkeypatch.setattr(webp.logger, name, lambda *a, **k: None)
    return types.SimpleNamespace(root=tmp_path, lib=lib, cfg=cfg, saved=saved)


def cbz(env, name, pages=2, seed=0, comicinfo=COMICINFO):
    folder = env.lib / 'Hero'
    folder.mkdir(exist_ok=True)
    return make_cbz(folder / name, [('%03d.jpg' % i, jpeg(page(seed=seed + i))) for i in range(pages)], comicinfo=comicinfo)


def damage(path):
    # flip bytes inside the first page's data, so reading it fails its checksum
    data = bytearray(open(path, 'rb').read())
    at = data.index(b'\xff\xd8\xff') + 2000
    data[at:at + 16] = bytes(16)
    with open(path, 'wb') as f:
        f.write(data)


def select(env, **kw):
    return webp.select(str(env.lib), kw.pop('since', '2015'), **kw)


# --- what each file came to is remembered ---

@pytest.mark.unit
def test_selection_skips_handled_files_and_repicks_changed_ones(env):
    a, b = cbz(env, 'Hero 001 (2019).cbz'), cbz(env, 'Hero 002 (2019).cbz', seed=5)
    assert sorted(select(env)['files']) == sorted([a, b])
    webp.remember({'path': a, 'status': 'skipped', 'reason': 'nothing to gain'})
    found = select(env)
    assert found['files'] == [b] and found['remembered'] == 1
    with open(a, 'ab') as f:   # the file changed since: looked at again
        f.write(b'\0')
    assert a in select(env)['files']


@pytest.mark.unit
def test_a_converted_file_is_not_picked_again(env):
    a = cbz(env, 'Hero 001 (2019).cbz')
    res = webp.convert(a)
    assert res['status'] == 'converted'
    assert webp.remember(res) == 'converted'
    row = webp.remembered()[a]
    assert row['size'] == os.path.getsize(a) and row['saved'] == res['before'] - res['after']
    assert select(env)['files'] == []


@pytest.mark.unit
def test_largest_files_go_first(env):
    small = cbz(env, 'Hero 001 (2019).cbz', pages=1)
    big = cbz(env, 'Hero 002 (2019).cbz', pages=4)
    mid = cbz(env, 'Hero 003 (2019).cbz', pages=2)
    assert select(env)['files'] == [big, mid, small]
    assert select(env, limit=2)['files'] == [big, mid]


@pytest.mark.unit
def test_already_webp_is_remembered_by_the_scan(env):
    from .test_webp import make_cbz as mk
    import io
    from PIL import Image
    buf = io.BytesIO()
    page(seed=1).save(buf, 'WEBP')
    (env.lib / 'Hero').mkdir()
    p = mk(env.lib / 'Hero' / 'Hero 004 (2019).cbz', [('001.webp', buf.getvalue())])
    assert select(env)['already'] == 1
    assert webp.remembered()[p]['status'] == 'already webp'
    found = select(env)
    assert found['already'] == 0 and found['remembered'] == 1


@pytest.mark.unit
def test_transient_failures_are_retried_others_wait_for_a_change(env):
    a, b = cbz(env, 'Hero 001 (2019).cbz'), cbz(env, 'Hero 002 (2019).cbz', seed=5)
    webp.remember({'path': a, 'status': 'failed', 'reason': 'not enough free space'})
    webp.remember({'path': b, 'status': 'failed', 'reason': 'page order would change'})
    assert select(env)['files'] == [a]


@pytest.mark.unit
def test_recheck_reopens_nothing_to_gain_only(env):
    a, b = cbz(env, 'Hero 001 (2019).cbz'), cbz(env, 'Hero 002 (2019).cbz', seed=5)
    webp.remember({'path': a, 'status': 'skipped', 'reason': 'nothing to gain'})
    webp.remember({'path': b, 'status': 'skipped', 'reason': 'already webp'})
    assert webp.recheck() == 1
    assert select(env)['files'] == [a]


@pytest.mark.unit
def test_bulk_run_remembers_what_it_skipped(env, monkeypatch):
    a = cbz(env, 'Hero 001 (2019).cbz')
    monkeypatch.setattr(webp, 'convert', lambda path, **kw: {'path': path, 'status': 'skipped', 'reason': 'nothing to gain',
                                                              'before': 1, 'after': 1})
    webp.BULK.update(active=[], done=0, errors=[])
    webp._one(a, webp.options(root=str(env.lib)))
    assert webp.remembered()[a]['status'] == 'nothing to gain'


# --- damaged files go to Needs attention ---

@pytest.mark.unit
def test_damaged_archive_goes_to_needs_attention_and_is_not_retried(env):
    a = cbz(env, 'Hero 001 (2019).cbz')
    damage(a)
    res = webp.convert(a)
    assert res['status'] == 'failed' and res['damaged'] is True, res
    assert webp.remember(res) == 'damaged'
    row = db.DBConnection().selectone('SELECT reason, detail FROM attention WHERE path=?', [a]).fetchone()
    assert row['reason'] == 'damaged'
    assert row['detail'].startswith('Found while converting to WebP: Bad CRC-32') and 'BadZipFile' not in row['detail']
    assert select(env)['files'] == []


@pytest.mark.unit
def test_not_a_zip_is_damaged_but_a_rar_named_cbz_is_not(env):
    (env.lib / 'Hero').mkdir()
    junk = env.lib / 'Hero' / 'Hero 001 (2019).cbz'
    junk.write_bytes(b'not an archive at all' * 100)
    assert webp.remember(webp.convert(str(junk))) == 'damaged'
    rar = env.lib / 'Hero' / 'Hero 002 (2019).cbz'
    rar.write_bytes(open(os.path.join(os.path.dirname(__file__), 'data', 'rar', 'rar5-solid.rar'), 'rb').read())
    assert webp.remember(webp.convert(str(rar))) == 'failed'
    assert db.DBConnection().selectone('SELECT path FROM attention WHERE path=?', [str(rar)]).fetchone() is None


@pytest.mark.unit
def test_a_replaced_damaged_file_leaves_needs_attention(env):
    a = cbz(env, 'Hero 001 (2019).cbz')
    damage(a)
    webp.remember(webp.convert(a))
    cbz(env, 'Hero 001 (2019).cbz', seed=3)   # a good copy put in its place
    assert select(env)['files'] == [a]
    assert webp.remember(webp.convert(a)) == 'converted'
    assert db.DBConnection().selectone('SELECT path FROM attention WHERE path=?', [a]).fetchone() is None


@pytest.mark.unit
def test_needs_attention_only_offers_trash_and_ignore_for_a_library_file(env, monkeypatch):
    monkeypatch.setattr(attention, 'review_dir', lambda: str(env.root / 'review'))
    a = cbz(env, 'Hero 001 (2019).cbz')
    damage(a)
    webp.remember(webp.convert(a))
    db.DBConnection().action('CREATE TABLE IF NOT EXISTS comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, '
                             'ComicVersion TEXT, Total INTEGER)')
    [item] = attention.items()
    assert item['in_library'] is True and item['reason'] == 'damaged' and item['matches'] == []
    out = attention.file_as(a, '1', '2')
    assert out['ok'] is False and 'already in your library' in out['note']
    attention.ignore(a)
    assert attention.items() == []
    with open(a, 'ab') as f:   # changed: listed again, and can go to the trash
        f.write(b'\0')
    assert [i['path'] for i in attention.items()] == [a]
    assert attention.trash(a)['ok'] is True and not os.path.exists(a)


# --- the old journal ---

@pytest.mark.unit
def test_the_journal_is_brought_in_on_first_use(env):
    a = cbz(env, 'Hero 001 (2019).cbz')
    b = cbz(env, 'Hero 002 (2019).cbz', seed=5)
    c = cbz(env, 'Hero 003 (2019).cbz', seed=9)
    lines = [
        # the real shape: conversions with sizes, and .cbr repacks with a target
        {'path': a, 'status': 'converted', 'reason': '', 'before': 99999999, 'after': os.path.getsize(a), 'pages': 2,
         'converted': 2, 'kept': 0, 'backup': None, 'source': 'bulk', 'at': '2026-10-05 02:24:31'},
        {'path': b, 'status': 'converted', 'reason': '', 'before': 99999999, 'after': 12, 'source': 'bulk', 'at': 'x'},
        {'path': c[:-4] + '.cbr', 'target': c, 'status': 'converted', 'reason': '', 'repacked': True,
         'source': 'import-cbz', 'at': '2026-10-12 02:42:49'},
        {'path': c, 'status': 'failed', 'reason': 'page order would change', 'source': 'import', 'at': 'y'},
    ]
    with open(env.root / 'cache' / 'webp_journal.jsonl', 'w') as f:
        f.write('\n'.join(json.dumps(x) for x in lines) + '\nnot json\n')
    rows = webp.remembered()
    assert rows[a]['status'] == 'converted' and rows[a]['saved'] == 99999999 - os.path.getsize(a)
    assert b not in rows   # its size changed since the journal saw it
    assert rows[c]['status'] == 'failed' and c[:-4] + '.cbr' not in rows
    assert select(env)['files'] == [b]


def _web(monkeypatch, method):
    import cherrypy
    from mylar import webserve
    monkeypatch.setattr(cherrypy.request, 'method', method, raising=False)
    return webserve.WebInterface()


@pytest.mark.unit
def test_recheck_is_post_only(env, monkeypatch):
    import cherrypy
    a = cbz(env, 'Hero 001 (2019).cbz')
    webp.remember({'path': a, 'status': 'skipped', 'reason': 'nothing to gain'})
    with pytest.raises(cherrypy.HTTPError) as e:
        _web(monkeypatch, 'GET').webp_recheck()
    assert e.value.status == 405 and select(env)['files'] == []
    out = json.loads(_web(monkeypatch, 'POST').webp_recheck())
    assert out['reopened'] == 1 and select(env)['files'] == [a]


# --- saved choices and defaults ---

@pytest.mark.unit
def test_defaults_are_two_threads_and_one_file_however_many_cores(env, monkeypatch):
    monkeypatch.setattr(webp, 'MAX_THREADS', 64)
    del env.cfg.WEBP_THREADS
    o = webp.options()
    assert (o['threads'], o['files'], o['limit'], o['max_threads']) == (2, 1, 20, 64)
    assert webp.options(threads=48, files=6)['threads'] == 48


@pytest.mark.unit
def test_a_run_saves_its_choices_and_the_form_opens_with_them(env, monkeypatch):
    monkeypatch.setattr(webp, 'MAX_THREADS', 16)
    monkeypatch.setattr(webp, 'available', lambda: True)
    monkeypatch.setattr(webp.threading, 'Thread', lambda **kw: types.SimpleNamespace(start=lambda: None))
    backup = env.root / 'originals'
    opts = webp.options(root=str(env.lib), since='', limit=500, quality=78, min_q=70, backup_dir=str(backup), threads=6, files=3)
    webp.BULK.update(state='previewed', token='t', count=1, opts=opts, files=['x'], bytes=1, backup_free=None)
    assert webp.start_run('t', '1') is None
    assert env.saved == {'webp_since': 'any', 'webp_limit': 500, 'webp_quality': 78, 'webp_min_source_q': 70,
                         'webp_threads': 6, 'webp_files': 3, 'webp_backup_dir': str(backup)}
    o = webp.options()
    assert (o['since'], o['limit'], o['quality'], o['min_q'], o['threads'], o['files'], o['backup_dir']) == \
        ('', 500, 78, 70, 6, 3, str(backup))
    assert webp.on_or_after((1970, 1), o['since'])


@pytest.mark.unit
def test_cpu_limit_reads_the_container_allowance(tmp_path):
    (tmp_path / 'cpu.max').write_text('250000 100000\n')
    assert webp._cgroup_cpus(str(tmp_path)) == 3
    (tmp_path / 'cpu.max').write_text('max 100000\n')
    assert webp._cgroup_cpus(str(tmp_path)) is None
    (tmp_path / 'cpu.max').unlink()
    (tmp_path / 'cpu').mkdir()
    (tmp_path / 'cpu' / 'cpu.cfs_quota_us').write_text('150000')
    (tmp_path / 'cpu' / 'cpu.cfs_period_us').write_text('100000')
    assert webp._cgroup_cpus(str(tmp_path)) == 2
