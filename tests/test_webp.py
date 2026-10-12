import hashlib
import io
import os
import types
import zipfile

import pytest
from PIL import Image, ImageDraw

import mylar
from mylar import webp

COMICINFO = ('<?xml version="1.0"?>\n<ComicInfo><Series>Test Hero</Series><Number>1</Number>'
             '<Year>2019</Year><Month>4</Month><Notes>[CVDB12345]</Notes></ComicInfo>').encode()


def page(w=600, h=900, seed=0, mode='RGB'):
    im = Image.new('RGB', (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=((y + seed * 40) % 256, (y // 3) % 256, (255 - y) % 256))
    for i in range(12):
        x0, y0 = (i * 53 + seed * 17) % (w - 80), (i * 71 + seed * 29) % (h - 80)
        d.ellipse([x0, y0, x0 + 70, y0 + 70], fill=(255, (i * 30) % 256, 40), outline=(0, 0, 0), width=3)
    d.text((20, 20), 'PAGE %s' % seed, fill=(0, 0, 0))
    return im.convert(mode) if mode != 'RGB' else im


def jpeg(im, q=98, **kw):
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=q, **kw)
    return buf.getvalue()


def make_cbz(path, pages, comicinfo=COMICINFO, comment=b'ComicBookLover', extra=None):
    with zipfile.ZipFile(path, 'w') as z:
        z.comment = comment
        for name, data in pages:
            z.writestr(zipfile.ZipInfo(name, date_time=(2020, 1, 2, 3, 4, 6)), data)
        if comicinfo is not None:
            info = zipfile.ZipInfo('ComicInfo.xml', date_time=(2020, 1, 2, 3, 4, 6))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, comicinfo)
        for name, data in (extra or []):
            z.writestr(name, data)
    return str(path)


def entries(path):
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist()}, z.comment, [i.filename for i in z.infolist()]


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


@pytest.fixture(autouse=True)
def cfg(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        WEBP_QUALITY=85, WEBP_MIN_SOURCE_Q=80, WEBP_SINCE='2015', WEBP_THREADS=2, WEBP_ON_IMPORT=True,
        WEBP_BACKUP_DIR=None, DESTINATION_DIR=str(tmp_path), CACHE_DIR=str(tmp_path / 'cache')), raising=False)
    os.makedirs(str(tmp_path / 'cache'), exist_ok=True)
    yield


@pytest.mark.unit
def test_converts_pages_and_keeps_everything_else(tmp_path):
    src = make_cbz(tmp_path / 'a.cbz', [('001.jpg', jpeg(page(seed=1))), ('002.jpg', jpeg(page(seed=2)))],
                   extra=[('credits.txt', b'scanned by nobody')])
    before, comment, _ = entries(src)
    res = webp.convert(src)
    assert res['status'] == 'converted', res
    after, comment2, order = entries(src)
    assert comment2 == comment
    assert after['ComicInfo.xml'] == before['ComicInfo.xml']
    assert after['credits.txt'] == before['credits.txt']
    assert order == ['001.webp', '002.webp', 'ComicInfo.xml', 'credits.txt']
    for name in ('001', '002'):
        new = Image.open(io.BytesIO(after[name + '.webp']))
        old = Image.open(io.BytesIO(before[name + '.jpg']))
        assert new.format == 'WEBP' and new.size == old.size
    assert res['after'] < res['before'] and res['converted'] == 2 and res['kept'] == 0
    assert not [n for n in os.listdir(tmp_path) if n.startswith('.') or n.endswith('.tmp')]


@pytest.mark.unit
def test_low_quality_source_page_is_kept(tmp_path):
    low = jpeg(page(seed=3), q=40)
    src = make_cbz(tmp_path / 'b.cbz', [('001.jpg', jpeg(page(seed=1))), ('002.jpg', low)])
    res = webp.convert(src)
    after, _, order = entries(src)
    assert res['status'] == 'converted' and res['converted'] == 1 and res['kept'] == 1
    assert after['002.jpg'] == low and '001.webp' in order


@pytest.mark.unit
def test_unreadable_and_cmyk_pages_are_never_dropped(tmp_path):
    broken = b'\xff\xd8\xff\xe0 not really a jpeg'
    cmyk = jpeg(page(seed=4, mode='CMYK'))
    src = make_cbz(tmp_path / 'c.cbz', [('001.jpg', jpeg(page(seed=1))), ('002.jpg', broken), ('003.jpg', cmyk)])
    res = webp.convert(src)
    after, _, order = entries(src)
    assert res['status'] == 'converted'
    assert after['002.jpg'] == broken and after['003.jpg'] == cmyk
    assert len([n for n in order if n != 'ComicInfo.xml']) == 3


@pytest.mark.unit
def test_page_kept_when_webp_is_larger(tmp_path, monkeypatch):
    src = make_cbz(tmp_path / 'd.cbz', [('001.jpg', jpeg(page(seed=1)))])
    original = sha(src)
    monkeypatch.setattr(webp, '_encode', lambda im, q, info: b'x' * 50_000_000)
    res = webp.convert(src)
    assert res['status'] == 'skipped' and sha(src) == original


@pytest.mark.unit
def test_nothing_to_gain_leaves_file_untouched(tmp_path):
    src = make_cbz(tmp_path / 'e.cbz', [('001.jpg', jpeg(page(seed=1), q=50))])
    original, mtime = sha(src), os.path.getmtime(src)
    res = webp.convert(src)
    assert res['status'] == 'skipped' and sha(src) == original and os.path.getmtime(src) == mtime


@pytest.mark.unit
def test_already_webp_is_skipped(tmp_path):
    buf = io.BytesIO()
    page(seed=1).save(buf, 'WEBP', quality=85)
    src = make_cbz(tmp_path / 'f.cbz', [('001.webp', buf.getvalue())])
    original = sha(src)
    res = webp.convert(src)
    assert res['status'] == 'skipped' and 'already' in res['reason'] and sha(src) == original


@pytest.mark.unit
def test_backup_copy_is_identical(tmp_path):
    lib = tmp_path / 'lib' / 'Marvel' / 'Hero (2019)'
    lib.mkdir(parents=True)
    src = make_cbz(lib / 'Hero 001 (2019).cbz', [('001.jpg', jpeg(page(seed=1)))])
    original = sha(src)
    res = webp.convert(src, backup_dir=str(tmp_path / 'hold'), backup_root=str(tmp_path / 'lib'))
    assert res['status'] == 'converted'
    kept = tmp_path / 'hold' / 'Marvel' / 'Hero (2019)' / 'Hero 001 (2019).cbz'
    assert res['backup'] == str(kept) and sha(str(kept)) == original


@pytest.mark.unit
def test_failed_verification_keeps_original(tmp_path, monkeypatch):
    src = make_cbz(tmp_path / 'g.cbz', [('001.jpg', jpeg(page(seed=1)))])
    original = sha(src)
    monkeypatch.setattr(webp, '_verify', lambda *a, **k: 'page 001.webp has the wrong size')
    res = webp.convert(src)
    assert res['status'] == 'failed' and 'wrong size' in res['reason']
    assert sha(src) == original and sorted(os.listdir(tmp_path)) == ['cache', 'g.cbz']


@pytest.mark.unit
def test_name_clash_keeps_page(tmp_path):
    clash = io.BytesIO()
    page(seed=9).save(clash, 'WEBP', quality=80)
    src = make_cbz(tmp_path / 'h.cbz', [('001.jpg', jpeg(page(seed=1))), ('001.webp', clash.getvalue()), ('002.jpg', jpeg(page(seed=2)))])
    res = webp.convert(src)
    after, _, order = entries(src)
    assert '001.jpg' in order and '002.webp' in order and len(order) == 4
    assert res['converted'] == 1


@pytest.mark.unit
def test_exif_orientation_survives(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6
    src = make_cbz(tmp_path / 'i.cbz', [('001.jpg', jpeg(page(seed=1), exif=exif.tobytes()))])
    assert webp.convert(src)['status'] == 'converted'
    after, _, _ = entries(src)
    assert Image.open(io.BytesIO(after['001.webp'])).getexif().get(0x0112) == 6


@pytest.mark.unit
def test_non_zip_is_skipped(tmp_path):
    p = tmp_path / 'j.cbr'
    p.write_bytes(b'Rar!\x1a\x07\x00 not handled')
    assert webp.convert(str(p))['status'] == 'skipped'


@pytest.mark.unit
def test_issue_date_from_comicinfo_and_filename(tmp_path):
    a = make_cbz(tmp_path / 'Hero 001 (1979).cbz', [('001.jpg', b'')])
    assert webp.issue_date(a) == (2019, 4)
    b = make_cbz(tmp_path / 'Hero 002 (2016).cbz', [('001.jpg', b'')], comicinfo=None)
    assert webp.issue_date(b) == (2016, 0)
    c = make_cbz(tmp_path / 'Hero 003.cbz', [('001.jpg', b'')], comicinfo=None)
    assert webp.issue_date(c) is None


@pytest.mark.unit
def test_date_filter():
    assert webp.on_or_after((2015, 1), '2015') and webp.on_or_after((2016, 0), '2015-06')
    assert not webp.on_or_after((2015, 3), '2015-06') and not webp.on_or_after((2014, 12), '2015')
    assert webp.on_or_after((2015, 0), '2015-06') is False
    assert webp.on_or_after(None, '2015') is False and webp.on_or_after(None, '2015', unknown=True)


@pytest.mark.unit
def test_import_hook_respects_year_and_switch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(webp, '_enqueue', lambda path: calls.append(path))
    new = make_cbz(tmp_path / 'new.cbz', [('001.jpg', b'')])
    old = make_cbz(tmp_path / 'old.cbz', [('001.jpg', b'')], comicinfo=COMICINFO.replace(b'2019', b'1979'))
    webp.after_import(new)
    webp.after_import(old)
    assert calls == [new]
    mylar.CONFIG.WEBP_ON_IMPORT = False
    webp.after_import(new)
    assert calls == [new]


@pytest.mark.unit
def test_small_saving_leaves_file_untouched(tmp_path):
    pages = [('%03d.jpg' % i, jpeg(page(seed=i), q=50)) for i in range(9)] + [('009.jpg', jpeg(page(w=120, h=180, seed=9)))]
    src = make_cbz(tmp_path / 'k.cbz', pages)
    original = sha(src)
    res = webp.convert(src)
    assert res['status'] == 'skipped' and 'less than' in res['reason'] and sha(src) == original


RAR = os.path.join(os.path.dirname(__file__), 'data', 'rar')


def rar_copy(tmp_path, name, as_name):
    import shutil
    dst = tmp_path / as_name
    shutil.copy(os.path.join(RAR, name), str(dst))
    return str(dst)


def rar_contents(path):
    from lib.rarfile import rarfile
    with rarfile.RarFile(path) as rf:
        return {i.filename: rf.read(i) for i in rf.infolist() if not i.is_dir()}, rf.comment


@pytest.mark.unit
@pytest.mark.parametrize('fixture', ['rar3-subdirs.rar', 'rar5-solid.rar', 'rar3-comment-plain.rar'])
def test_rar_is_repacked_entry_for_entry(tmp_path, fixture):
    src = rar_copy(tmp_path, fixture, 'Hero 001 (2019).cbr')
    before, comment = rar_contents(src)
    res = webp.to_cbz(src)
    assert res['status'] == 'converted' and res['repacked'], res
    assert not os.path.exists(src) and res['target'] == str(tmp_path / 'Hero 001 (2019).cbz')
    after, zcomment, _ = entries(res['target'])
    assert after == before
    if comment:
        assert zcomment.decode() == comment
    assert sorted(os.listdir(tmp_path)) == ['Hero 001 (2019).cbz', 'cache']


@pytest.mark.unit
@pytest.mark.parametrize('fixture,why', [('rar5-psw.rar', 'password'), ('corrupt-data.rar', ''), ('rar5-evil-symlink-traversal.rar', 'unsafe')])
def test_bad_rar_is_left_alone(tmp_path, fixture, why):
    src = rar_copy(tmp_path, fixture, 'Hero 002 (2019).cbr')
    original = sha(src)
    res = webp.to_cbz(src)
    assert res['status'] == 'failed' and why in res['reason'], res
    assert sha(src) == original and sorted(os.listdir(tmp_path)) == ['Hero 002 (2019).cbr', 'cache']


@pytest.mark.unit
def test_existing_cbz_blocks_repack(tmp_path):
    src = rar_copy(tmp_path, 'rar5-solid.rar', 'Hero 003 (2019).cbr')
    (tmp_path / 'Hero 003 (2019).cbz').write_bytes(b'mine')
    res = webp.to_cbz(src)
    assert res['status'] == 'skipped' and os.path.exists(src) and (tmp_path / 'Hero 003 (2019).cbz').read_bytes() == b'mine'


@pytest.mark.unit
def test_zip_named_cbr_is_renamed_then_converted(tmp_path, monkeypatch):
    moved = []
    monkeypatch.setattr(webp, '_relocate', lambda old, new: moved.append((old, new)))
    src = make_cbz(tmp_path / 'Hero 004 (2019).cbr', [('001.jpg', jpeg(page(seed=1))), ('002.jpg', jpeg(page(seed=2)))])
    before, _, _ = entries(src)
    res = webp._process(src)
    target = str(tmp_path / 'Hero 004 (2019).cbz')
    assert moved == [(src, target)] and not os.path.exists(src)
    assert res['status'] == 'converted' and res['path'] == target
    after, _, order = entries(target)
    assert after['ComicInfo.xml'] == before['ComicInfo.xml'] and order == ['001.webp', '002.webp', 'ComicInfo.xml']


@pytest.mark.unit
def test_import_hook_accepts_cbr(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(webp, '_enqueue', lambda path: calls.append(path))
    new = rar_copy(tmp_path, 'rar5-solid.rar', 'Hero 005 (2021).cbr')
    old = rar_copy(tmp_path, 'rar5-solid.rar', 'Hero 006 (1988).cbr')
    webp.after_import(new)
    webp.after_import(old)
    assert calls == [new]
