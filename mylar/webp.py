import io
import json
import os
import queue
import random
import re
import shutil
import threading
import time
import zipfile
import zlib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import mylar
from mylar import logger

CONVERT_EXT = ('.jpg', '.jpeg', '.png')
PAGE_EXT = CONVERT_EXT + ('.webp', '.gif', '.bmp', '.avif', '.jxl')
MAX_SIDE = 16383


def _cpus():
    try:
        return len(os.sched_getaffinity(0))
    except Exception:
        return os.cpu_count() or 4


MAX_THREADS = max(1, _cpus())
MAX_FILES = 8
SAMPLE_FILES = 150
MIN_SAVING = 0.10
STD = (16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
       18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99)
SAVINGS = ((80, 0.0), (86, 0.25), (92, 0.45), (99, 0.8))

_busy = set()
_busy_lock = threading.Lock()
_queue = queue.Queue()
_worker = [None]
_bulk_lock = threading.Lock()
BULK = {'state': 'idle'}


def available():
    try:
        from PIL import features
        return bool(features.check('webp'))
    except Exception:
        return False


def _cfg(name, default):
    value = getattr(mylar.CONFIG, name, None)
    return default if value in (None, '', 'None') else value


def jpeg_quality(im):
    tables = getattr(im, 'quantization', None)
    if not tables or 0 not in tables:
        return None
    scale = sum(float(a) / b for a, b in zip(tables[0], STD)) / len(STD) * 100
    return round(100 - scale / 2) if scale <= 100 else round(5000 / scale)


def _encode(im, q, info):
    buf = io.BytesIO()
    kw = {'quality': q, 'method': 4}
    if info.get('icc_profile'):
        kw['icc_profile'] = info['icc_profile']
    if info.get('exif'):
        kw['exif'] = info['exif']
    im.save(buf, 'WEBP', **kw)
    return buf.getvalue()


def _page(data, quality, min_q):
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return None, 'unreadable'
    if getattr(im, 'n_frames', 1) > 1 or max(im.size) > MAX_SIDE:
        return None, 'unsupported'
    if im.format == 'JPEG':
        if im.mode not in ('L', 'RGB'):
            return None, 'colour mode %s' % im.mode
        q = jpeg_quality(im)
        if q is not None and q < min_q:
            return None, 'low quality source'
    elif im.format == 'PNG':
        if im.mode not in ('1', 'L', 'LA', 'P', 'RGB', 'RGBA'):
            return None, 'colour mode %s' % im.mode
    else:
        return None, 'not jpeg/png'
    alpha = im.mode in ('LA', 'RGBA') or (im.mode == 'P' and 'transparency' in im.info)
    try:
        out = _encode(im.convert('RGBA' if alpha else 'RGB'), quality, im.info)
    except Exception:
        return None, 'encode failed'
    if len(out) >= len(data):
        return None, 'larger as webp'
    return (out, im.size), None


def _natural(name):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', name.lower())]


def _is_page(name):
    return name.lower().endswith(PAGE_EXT) and not name.startswith('__MACOSX') and not name.endswith('/')


def _decoded_size(data):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    return im.size


def _verify(tmp, src, converted, threads=1, pool=None):
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(tmp) as b:
        if b.comment != a.comment:
            return 'archive comment changed'
        old = [i.filename for i in a.infolist()]
        expect = [converted[n][0] if n in converted else n for n in old]
        if [i.filename for i in b.infolist()] != expect:
            return 'entry list changed'
        pages = []
        for name in old:
            if name.endswith('/'):
                continue
            if name in converted:
                new, _, size = converted[name]
                pages.append((new, size, b.read(new)))
            elif a.read(name) != b.read(name):
                return '%s changed' % name
        ex = pool or ThreadPoolExecutor(max(1, threads))
        try:
            for (new, size, _), got in zip(pages, ex.map(_decoded_size, [p[2] for p in pages])):
                if got != size:
                    return 'page %s has the wrong size' % new
        finally:
            if pool is None:
                ex.shutdown()
        back = {converted[n][0] if n in converted else n: n for n in old}
        before = sorted([n for n in old if _is_page(n)], key=_natural)
        after = [back[n] for n in sorted([n for n in expect if _is_page(n)], key=_natural)]
        if before != after:
            return 'page order would change'
    return None


def _backup_target(path, backup_dir, backup_root):
    rel = os.path.basename(path)
    if backup_root:
        r = os.path.relpath(path, backup_root)
        if not r.startswith('..'):
            rel = r
    target = os.path.join(backup_dir, rel)
    if os.path.exists(target):
        base, ext = os.path.splitext(target)
        target = '%s (%s)%s' % (base, int(time.time()), ext)
    return target


def convert(path, quality=None, min_source_q=None, backup_dir=None, backup_root=None, threads=None, pool=None):
    quality = int(quality or _cfg('WEBP_QUALITY', 85))
    min_q = int(_cfg('WEBP_MIN_SOURCE_Q', 80) if min_source_q is None else min_source_q)
    threads = max(1, int(threads or _cfg('WEBP_THREADS', 2)))
    res = {'path': path, 'status': 'skipped', 'reason': '', 'before': 0, 'after': 0, 'pages': 0, 'converted': 0, 'kept': 0, 'backup': None}
    try:
        st = os.stat(path)
    except OSError as e:
        return dict(res, status='failed', reason='missing: %s' % e)
    res['before'] = res['after'] = st.st_size
    if not zipfile.is_zipfile(path):
        return dict(res, reason='not a cbz')
    with _busy_lock:
        if path in _busy:
            return dict(res, reason='already being converted')
        _busy.add(path)
    tmp = os.path.join(os.path.dirname(path), '.%s.webp-tmp' % os.path.basename(path))
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = {i.filename for i in infos}
            pages = [i for i in infos if _is_page(i.filename)]
            todo = [i for i in pages if i.filename.lower().endswith(CONVERT_EXT)]
            res['pages'] = len(pages)
            if not todo:
                return dict(res, reason='already webp' if pages else 'no pages')
            taken = set(names)
            work = []
            for info in todo:
                target = os.path.splitext(info.filename)[0] + '.webp'
                if target in taken:
                    continue
                taken.add(target)
                work.append((info, target))
            ex = pool or ThreadPoolExecutor(threads)
            try:
                futures = [(info, target, ex.submit(_page, z.read(info), quality, min_q)) for info, target in work]
                converted = {}
                for info, target, fut in futures:
                    done, why = fut.result()
                    if done:
                        converted[info.filename] = (target, done[0], done[1])
            finally:
                if pool is None:
                    ex.shutdown()
            res['converted'] = len(converted)
            res['kept'] = len(todo) - len(converted)
            if not converted:
                return dict(res, reason='nothing to gain')
            need = st.st_size * (2.1 if backup_dir else 1.1)
            if shutil.disk_usage(os.path.dirname(path)).free < need:
                return dict(res, status='failed', reason='not enough free space')
            with zipfile.ZipFile(tmp, 'w', allowZip64=True) as zo:
                zo.comment = z.comment
                for info in infos:
                    if info.filename in converted:
                        target, blob, _ = converted[info.filename]
                        zi = zipfile.ZipInfo(target, date_time=info.date_time)
                        zi.compress_type = zipfile.ZIP_STORED
                        zi.external_attr = info.external_attr
                        zo.writestr(zi, blob)
                    else:
                        zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                        zi.compress_type = info.compress_type
                        zi.external_attr = info.external_attr
                        zi.comment = info.comment
                        zi.create_system = info.create_system
                        zo.writestr(zi, b'' if info.filename.endswith('/') else z.read(info))
        check = {n: (v[0], None, v[2]) for n, v in converted.items()}
        problem = _verify(tmp, path, check, threads, pool)
        if problem:
            return dict(res, status='failed', reason=problem)
        new_size = os.path.getsize(tmp)
        if new_size > st.st_size * (1 - MIN_SAVING):
            return dict(res, reason='saves less than %d%%' % (MIN_SAVING * 100))
        now = os.stat(path)
        if (now.st_size, now.st_mtime) != (st.st_size, st.st_mtime):
            return dict(res, status='failed', reason='file changed while converting')
        if backup_dir:
            target = _backup_target(path, backup_dir, backup_root)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(path, target)
            if os.path.getsize(target) != st.st_size:
                return dict(res, status='failed', reason='backup copy is incomplete')
            res['backup'] = target
        shutil.copymode(path, tmp)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except Exception:
            pass
        os.replace(tmp, path)
        res.update(status='converted', after=new_size)
        _update_size(path, new_size)
        return res
    except Exception as e:
        return dict(res, status='failed', reason='%s: %s' % (type(e).__name__, e))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        with _busy_lock:
            _busy.discard(path)


def _update_size(path, size):
    try:
        from mylar import db
        myDB = db.DBConnection()
        folder = os.path.dirname(path)
        for table in ('issues', 'annuals'):
            myDB.action('UPDATE %s SET ComicSize=? WHERE Location=? AND ComicID IN '
                        '(SELECT ComicID FROM comics WHERE ComicLocation IN (?, ?))' % table,
                        [str(size), os.path.basename(path), folder, folder + os.sep])
    except Exception as e:
        logger.fdebug('[WEBP] Unable to update the stored size of %s: %s' % (path, e))


def _journal(res):
    try:
        folder = mylar.CONFIG.CACHE_DIR or mylar.DATA_DIR
        with open(os.path.join(folder, 'webp_journal.jsonl'), 'a') as f:
            f.write(json.dumps(dict(res, at=time.strftime('%Y-%m-%d %H:%M:%S'))) + '\n')
    except Exception as e:
        logger.fdebug('[WEBP] Unable to write the journal: %s' % e)


def _mb(n):
    return '%.1f MB' % (n / 1048576.0)


def _log(res, label):
    name = os.path.basename(res['path'])
    if res['status'] == 'converted':
        logger.info('[WEBP]%s %s: %s -> %s (%s of %s pages%s)' % (
            label, name, _mb(res['before']), _mb(res['after']), res['converted'], res['pages'],
            ', original kept in %s' % res['backup'] if res['backup'] else ''))
    elif res['status'] == 'failed':
        logger.warn('[WEBP]%s %s was left unchanged: %s' % (label, name, res['reason']))
    else:
        logger.fdebug('[WEBP]%s %s skipped: %s' % (label, name, res['reason']))


def issue_date(path):
    text = ''
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                ci = next((i for i in z.infolist() if i.filename.lower().rsplit('/', 1)[-1] == 'comicinfo.xml'), None)
                text = z.read(ci).decode('utf-8', 'ignore') if ci and ci.file_size < 2000000 else ''
        else:
            from mylar import comicinfo
            text = (comicinfo.read_raw(path) or b'').decode('utf-8', 'ignore')
    except Exception:
        text = ''
    year = re.search(r'<Year>\s*(\d{4})\s*</Year>', text)
    if year:
        month = re.search(r'<Month>\s*(\d{1,2})\s*</Month>', text)
        return int(year.group(1)), int(month.group(1)) if month else 0
    found = re.findall(r'\((\d{4})\)', os.path.basename(path))
    if found:
        return int(found[-1]), 0
    return None


def _since(since):
    m = re.match(r'\s*(\d{4})(?:[-/.](\d{1,2}))?', str(since or ''))
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def on_or_after(date, since, unknown=False):
    cut = _since(since)
    if cut is None:
        return True
    if date is None:
        return bool(unknown)
    if date[0] != cut[0]:
        return date[0] > cut[0]
    if not cut[1]:
        return True
    return bool(date[1]) and date[1] >= cut[1]


def _pp_lock():
    try:
        from mylar.PostProcessor import PP_LOCK
        return PP_LOCK
    except Exception:
        return threading.RLock()


def _safe_name(name):
    parts = name.replace('\\', '/').split('/')
    return not name.startswith(('/', '\\')) and '..' not in parts and ':' not in parts[0]


def _zip_time(dt):
    try:
        dt = tuple(int(x) for x in dt[:6])
        return dt if dt[0] >= 1980 else (1980, 1, 1, 0, 0, 0)
    except Exception:
        return (1980, 1, 1, 0, 0, 0)


def _repack_rar(path, tmp):
    from lib.rarfile import rarfile
    with rarfile.RarFile(path) as rf:
        if rf.needs_password():
            return 'password protected'
        infos = [i for i in rf.infolist() if not i.is_dir()]
        if not infos:
            return 'empty archive'
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            return 'duplicate names in the archive'
        for i in infos:
            if i.is_symlink() or not _safe_name(i.filename):
                return 'unsafe entry %s' % i.filename
        sums = {}
        with zipfile.ZipFile(tmp, 'w', allowZip64=True) as zo:
            if rf.comment:
                zo.comment = rf.comment.encode('utf-8')[:65535]
            for i in infos:
                data = rf.read(i)
                if len(data) != i.file_size:
                    return '%s is incomplete' % i.filename
                zi = zipfile.ZipInfo(i.filename, date_time=_zip_time(i.date_time))
                zi.compress_type = zipfile.ZIP_STORED if _is_page(i.filename) else zipfile.ZIP_DEFLATED
                zo.writestr(zi, data)
                sums[i.filename] = (len(data), zlib.crc32(data))
    with zipfile.ZipFile(tmp) as z:
        if [i.filename for i in z.infolist()] != names:
            return 'entry list changed'
        for name in names:
            data = z.read(name)
            if (len(data), zlib.crc32(data)) != sums[name]:
                return '%s changed' % name
    return None


def _relocate(old, new):
    try:
        from mylar import db
        myDB = db.DBConnection()
        folder = os.path.dirname(old)
        for table in ('issues', 'annuals'):
            myDB.action('UPDATE %s SET Location=? WHERE Location=? AND ComicID IN '
                        '(SELECT ComicID FROM comics WHERE ComicLocation IN (?, ?))' % table,
                        [os.path.basename(new), os.path.basename(old), folder, folder + os.sep])
        myDB.action('UPDATE storyarcs SET Location=? WHERE Location=?', [new, old])
    except Exception as e:
        logger.warn('[WEBP] Renamed %s to .cbz but could not update the database: %s' % (os.path.basename(old), e))


def to_cbz(path):
    target = os.path.splitext(path)[0] + '.cbz'
    res = {'path': path, 'target': target, 'status': 'failed', 'reason': '', 'repacked': False}
    try:
        st = os.stat(path)
    except OSError as e:
        return dict(res, reason='missing: %s' % e)
    if os.path.exists(target):
        return dict(res, status='skipped', reason='%s already exists' % os.path.basename(target))
    tmp = os.path.join(os.path.dirname(path), '.%s.cbz-tmp' % os.path.basename(target))
    try:
        if not zipfile.is_zipfile(path):
            from lib.rarfile import rarfile
            if not rarfile.is_rarfile(path):
                return dict(res, status='skipped', reason='not a rar or zip archive')
            if shutil.disk_usage(os.path.dirname(path)).free < st.st_size * 1.2:
                return dict(res, reason='not enough free space')
            problem = _repack_rar(path, tmp)
            if problem:
                return dict(res, reason=problem)
            res['repacked'] = True
        with _pp_lock():
            now = os.stat(path)
            if (now.st_size, now.st_mtime) != (st.st_size, st.st_mtime):
                return dict(res, reason='file changed while repacking')
            if os.path.exists(target):
                return dict(res, status='skipped', reason='%s already exists' % os.path.basename(target))
            if res['repacked']:
                shutil.copymode(path, tmp)
                try:
                    os.chown(tmp, st.st_uid, st.st_gid)
                except Exception:
                    pass
                os.rename(tmp, target)
                os.remove(path)
            else:
                os.rename(path, target)
            _relocate(path, target)
        return dict(res, status='converted')
    except Exception as e:
        return dict(res, reason='%s: %s' % (type(e).__name__, e))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def after_import(path, issueyear=None):
    if not _cfg('WEBP_ON_IMPORT', False) or not path:
        return
    if not path.lower().endswith(('.cbz', '.cbr')):
        return
    date = issue_date(path)
    if date is None and str(issueyear or '')[:4].isdigit():
        date = (int(str(issueyear)[:4]), 0)
    since = _cfg('WEBP_SINCE', '')
    if not on_or_after(date, since):
        logger.fdebug('[WEBP] %s is dated before %s - leaving it as it is.' % (os.path.basename(path), since))
        return
    _enqueue(path)


def _enqueue(path):
    _queue.put(path)
    if _worker[0] is None or not _worker[0].is_alive():
        _worker[0] = threading.Thread(target=_drain, name='WEBP-IMPORT', daemon=True)
        _worker[0].start()


def _drain():
    while True:
        try:
            path = _queue.get(timeout=60)
        except queue.Empty:
            return
        try:
            _process(path)
        except Exception as e:
            logger.warn('[WEBP] Unable to convert %s: %s' % (path, e))


def _process(path):
    if not available():
        logger.warn('[WEBP] This install of Pillow cannot write WebP - leaving %s as it is.' % os.path.basename(path))
        return None
    if path.lower().endswith('.cbr'):
        rp = to_cbz(path)
        if rp['status'] != 'converted':
            logger.warn('[WEBP][IMPORT] %s was left as a .cbr: %s' % (os.path.basename(path), rp['reason']))
            _journal(dict(rp, source='import-cbz'))
            return rp
        logger.info('[WEBP][IMPORT] %s %s to %s before converting.' % (
            'Repacked' if rp['repacked'] else 'Renamed', os.path.basename(path), os.path.basename(rp['target'])))
        _journal(dict(rp, source='import-cbz'))
        path = rp['target']
    res = convert(path)
    _log(res, '[IMPORT]')
    if res['status'] != 'skipped':
        _journal(dict(res, source='import'))
    return res


def default_root():
    return _cfg('DESTINATION_DIR', '')


def _estimate(q):
    if q is None:
        return 0.3
    if q <= SAVINGS[0][0]:
        return 0.0
    for (q0, s0), (q1, s1) in zip(SAVINGS, SAVINGS[1:]):
        if q <= q1:
            return s0 + (s1 - s0) * (q - q0) / float(q1 - q0)
    return SAVINGS[-1][1]


def _sample_quality(path):
    from PIL import Image
    try:
        with zipfile.ZipFile(path) as z:
            pages = sorted([n for n in z.namelist() if _is_page(n)], key=_natural)
            if not pages:
                return None
            name = pages[len(pages) // 2]
            if not name.lower().endswith(('.jpg', '.jpeg')):
                return None
            with z.open(name) as fh:
                return jpeg_quality(Image.open(fh))
    except Exception:
        return None


def _webp_already(path):
    try:
        with zipfile.ZipFile(path) as z:
            pages = [n for n in z.namelist() if _is_page(n)]
    except Exception:
        return None
    if not pages:
        return None
    return not any(n.lower().endswith(CONVERT_EXT) for n in pages)


def status():
    with _bulk_lock:
        snap = {k: v for k, v in BULK.items() if k not in ('files', 'stop')}
    snap['stopping'] = bool(BULK.get('stop'))
    snap['available'] = available()
    snap['import_queue'] = _queue.qsize()
    return snap


def _set(**kw):
    with _bulk_lock:
        BULK.update(kw)


def options(root=None, since=None, unknown=False, limit=0, quality=None, min_q=None, backup_dir=None, no_backup=False, threads=None, files=None):
    root = (root or default_root() or '').strip()
    return {'root': root, 'since': str(since if since is not None else _cfg('WEBP_SINCE', '2015')).strip(),
            'unknown': bool(unknown), 'limit': max(0, int(limit or 0)),
            'quality': min(100, max(50, int(quality or _cfg('WEBP_QUALITY', 85)))),
            'min_q': min(100, max(0, int(_cfg('WEBP_MIN_SOURCE_Q', 80) if min_q in (None, '') else min_q))),
            'backup_dir': '' if no_backup else (backup_dir or _cfg('WEBP_BACKUP_DIR', '') or '').strip(),
            'no_backup': bool(no_backup), 'threads': min(MAX_THREADS, max(1, int(threads or max(2, MAX_THREADS // 2)))),
            'files': min(MAX_FILES, max(1, int(files or 4))), 'max_threads': MAX_THREADS}


def check_options(opts):
    if not available():
        return 'This install of Pillow cannot write WebP.'
    if not opts['root'] or not os.path.isdir(opts['root']):
        return 'The folder to convert does not exist: %s' % (opts['root'] or '(none)')
    if not opts['no_backup']:
        if not opts['backup_dir']:
            return 'Choose a holding folder for the originals, or tick the box to not keep them.'
        b, r = os.path.realpath(opts['backup_dir']), os.path.realpath(opts['root'])
        if b == r or b.startswith(r + os.sep):
            return 'The holding folder must be outside the folder being converted.'
    return None


def start_preview(opts):
    with _bulk_lock:
        if BULK.get('state') in ('previewing', 'running'):
            return False
        BULK.clear()
        BULK.update(state='previewing', opts=opts, scanned=0, started=time.time())
    threading.Thread(target=_preview, args=(opts,), name='WEBP-PREVIEW', daemon=True).start()
    return True


def _preview(opts):
    files, too_old, no_date, already, other, size = [], 0, 0, 0, 0, 0
    try:
        for root, dirs, names in os.walk(opts['root']):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
            for name in sorted(names):
                if BULK.get('stop'):
                    raise StopIteration
                if not name.lower().endswith('.cbz'):
                    if name.lower().endswith(('.cbr', '.cb7', '.pdf')):
                        other += 1
                    continue
                path = os.path.join(root, name)
                _set(scanned=BULK.get('scanned', 0) + 1, current=path)
                date = issue_date(path)
                if date is None and not opts['unknown']:
                    no_date += 1
                    continue
                if not on_or_after(date, opts['since'], opts['unknown']):
                    too_old += 1
                    continue
                if _webp_already(path):
                    already += 1
                    continue
                try:
                    s = os.path.getsize(path)
                except OSError:
                    continue
                files.append(path)
                size += s
                if opts['limit'] and len(files) >= opts['limit']:
                    raise StopIteration
    except StopIteration:
        pass
    except Exception as e:
        _set(state='idle', error='Preview failed: %s' % e)
        return
    if BULK.get('stop') and not (opts['limit'] and len(files) >= opts['limit']):
        _set(state='idle', stop=False, error='Preview stopped.')
        return
    sample = random.sample(files, min(SAMPLE_FILES, len(files)))
    _set(current='Sampling page quality in %s files' % len(sample))
    rates = [_estimate(_sample_quality(p)) for p in sample]
    rate = sum(rates) / len(rates) if rates else 0
    backup = opts['backup_dir']
    free = None
    if backup:
        probe = backup
        while probe and not os.path.isdir(probe):
            probe = os.path.dirname(probe)
        try:
            free = shutil.disk_usage(probe or '/').free
        except Exception:
            free = None
    token = '%x' % random.getrandbits(48)
    _set(state='previewed', files=files, token=token, current='', count=len(files), bytes=size, est_saving=int(size * rate),
         too_old=too_old, no_date=no_date, already=already, other=other, backup_free=free,
         examples=[os.path.relpath(p, opts['root']) for p in files[:8]], finished=time.time())


def start_run(token, confirm):
    with _bulk_lock:
        if BULK.get('state') != 'previewed' or token != BULK.get('token'):
            return 'Run the preview again first - the options or the file list have changed.'
        if str(confirm).strip() != str(BULK.get('count')):
            return 'Type the number of files (%s) to confirm.' % BULK.get('count')
        opts = BULK['opts']
        problem = check_options(opts)
        if problem:
            return problem
        if opts['backup_dir'] and BULK.get('backup_free') is not None and BULK['backup_free'] < BULK['bytes'] * 1.05:
            return 'The holding folder does not have room for the originals.'
        files = BULK['files']
        BULK.update(state='running', total=len(files), done=0, converted=0, skipped=0, failed=0, saved=0, before=0, after=0,
                    errors=[], started=time.time(), finished=None, stop=False, token=None, current='')
    threading.Thread(target=_run, args=(files, opts), name='WEBP-BULK', daemon=True).start()
    return None


def stop():
    with _bulk_lock:
        if BULK.get('state') in ('previewing', 'running'):
            BULK['stop'] = True
            return True
    return False


def reset():
    with _bulk_lock:
        if BULK.get('state') in ('previewing', 'running'):
            return False
        BULK.clear()
        BULK['state'] = 'idle'
    return True


def _one(path, opts):
    with _bulk_lock:
        BULK.setdefault('active', []).append(path)
        BULK['current'] = ', '.join(os.path.basename(p) for p in BULK['active'])
    try:
        res = convert(path, quality=opts['quality'], min_source_q=opts['min_q'], threads=opts['threads'],
                      backup_dir=opts['backup_dir'] or None, backup_root=opts['root'], pool=opts.get('pool'))
    except Exception as e:
        res = {'path': path, 'status': 'failed', 'reason': str(e), 'before': 0, 'after': 0}
    _log(res, '[BULK]')
    if res['status'] != 'skipped':
        _journal(dict(res, source='bulk'))
    with _bulk_lock:
        BULK['active'].remove(path)
        BULK['current'] = ', '.join(os.path.basename(p) for p in BULK['active'])
        BULK['done'] += 1
        BULK[res['status']] = BULK.get(res['status'], 0) + 1
        if res['status'] == 'converted':
            BULK['before'] += res['before']
            BULK['after'] += res['after']
            BULK['saved'] = BULK['before'] - BULK['after']
        elif res['status'] == 'failed':
            BULK['errors'] = (BULK['errors'] + ['%s: %s' % (os.path.relpath(path, opts['root']), res['reason'])])[-20:]


def _run(files, opts):
    logger.info('[WEBP] Converting %s files under %s to WebP q%s (dated %s or later), %s files at once on %s CPU threads%s.' % (
        len(files), opts['root'], opts['quality'], opts['since'] or 'any time', opts['files'], opts['threads'],
        ', originals kept in %s' % opts['backup_dir'] if opts['backup_dir'] else ', originals NOT kept'))
    stopped = False
    with _bulk_lock:
        BULK['active'] = []
    pool = None
    try:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        pool = ProcessPoolExecutor(opts['threads'], mp_context=multiprocessing.get_context('spawn'))
    except Exception as e:
        logger.warn('[WEBP] Unable to start worker processes, using threads instead: %s' % e)
    opts = dict(opts, pool=pool)
    with ThreadPoolExecutor(opts['files']) as ex:
        pending = set()
        for path in files:
            if BULK.get('stop'):
                stopped = True
                break
            while len(pending) >= opts['files']:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
            pending.add(ex.submit(_one, path, opts))
        wait(pending)
    if pool is not None:
        pool.shutdown()
    with _bulk_lock:
        BULK.update(state='stopped' if stopped else 'finished', current='', active=[], finished=time.time(), stop=False, files=[])
        snap = dict(BULK)
    logger.info('[WEBP] %s: %s converted, %s skipped, %s failed, %s saved.' % (
        'Stopped' if stopped else 'Finished', snap['converted'], snap['skipped'], snap['failed'], _mb(snap['saved'])))
