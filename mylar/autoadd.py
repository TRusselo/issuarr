import datetime
import json
import os
import re
import threading
import time
import urllib.parse
import zipfile

import mylar
from mylar import db, logger

_lock = threading.Lock()
_running = threading.Event()


def enabled():
    return bool(getattr(mylar.CONFIG, 'ARCHIVE_AUTO_ADD', False)) and bool(mylar.CONFIG.COMICVINE_API)


def _registry_path():
    return os.path.join(mylar.CONFIG.CACHE_DIR or mylar.DATA_DIR, 'autoadd_attempts.json')


def _load():
    try:
        with open(_registry_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(reg):
    cutoff = time.time() - 30 * 86400
    reg = {k: v for k, v in reg.items() if v.get('at', 0) > cutoff}
    try:
        with open(_registry_path(), 'w') as f:
            json.dump(reg, f)
    except Exception as e:
        logger.warn('[AUTO-ADD] Unable to save the attempt list: %s' % e)


def running():
    return _running.is_set()


def attempted(path):
    return path in _load()


def _norm(name):
    name = (name or '').lower().replace('&', 'and')
    name = re.sub(r'\bversus\b|\bvs\b\.?', 'vs', name)
    name = re.sub(r'\(\d{4}\)', '', name)
    name = re.sub(r'^the\s+', '', name.strip())
    return re.sub(r'[^a-z0-9]', '', name)


def _pack_date(path):
    for part in reversed(os.path.normpath(path).split(os.sep)[:-1]):
        m = re.match(r'(\d{4})[.\-_](\d{2})[.\-_](\d{2})', part)
        if m:
            try:
                return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _comicinfo_issueid(path):
    try:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().rsplit('/', 1)[-1] == 'comicinfo.xml'), None)
            if not name:
                return None
            text = z.read(name).decode('utf-8', 'ignore')
    except Exception:
        return None
    m = re.search(r'CVDB(\d+)|comicvine\.gamespot\.com/[^<]*?4000-(\d+)', text, re.I)
    return (m.group(1) or m.group(2)) if m else None


def _parse(path):
    from mylar import filechecker
    try:
        res = filechecker.FileChecker(dir=os.path.dirname(path), file=os.path.basename(path)).listFiles()
    except Exception:
        return None
    if not res or res.get('parse_status') != 'success' or not res.get('series_name') or not res.get('issue_number'):
        return None
    return {'series': res['series_name'], 'issue': str(res['issue_number']).lstrip('0') or '0', 'year': res.get('issue_year')}


def _cv(resource, params):
    from mylar import cv
    params = dict(params, api_key=mylar.CONFIG.COMICVINE_API, format='json')
    url = '%s%s/?%s' % (mylar.CVURL, resource, urllib.parse.urlencode(params, safe=':|,'))
    r = cv.cv_request(url, timeout=60)
    return (r.json() or {}).get('results') or []


def _date(s):
    try:
        return datetime.date.fromisoformat((s or '')[:10])
    except ValueError:
        return None


def _volume_for_issue(issueid):
    res = _cv('issue/4000-%s' % issueid, {'field_list': 'volume'})
    vol = res.get('volume') if isinstance(res, dict) else None
    return str(vol['id']) if vol and vol.get('id') else None


def _find_volume(series, issue, year, packdate):
    vols = [v for v in _cv('search', {'resources': 'volume', 'query': series, 'limit': 20,
                                      'field_list': 'id,name,start_year,count_of_issues'})
            if _norm(v.get('name')) == _norm(series)]
    if not vols:
        return None
    issues = _cv('issues', {'filter': 'volume:%s,issue_number:%s' % ('|'.join(str(v['id']) for v in vols), issue),
                            'field_list': 'id,volume,store_date,cover_date', 'limit': 100})
    best = None
    for i in issues:
        store, cover = _date(i.get('store_date')), _date(i.get('cover_date'))
        if packdate:
            if store:
                gap = abs((store - packdate).days)
                ok = gap <= 21
            elif cover:
                gap = abs((cover - packdate).days)
                ok = gap <= 120
            else:
                continue
        else:
            when = store or cover
            if not when or not year:
                continue
            gap = abs(when.year - int(year)) * 365
            ok = gap <= 365
        if ok and (best is None or gap < best[0]):
            best = (gap, str(i['volume']['id']))
    return best[1] if best else None


def queue(paths):
    if not enabled() or not paths:
        return
    reg = _load()
    fresh = [p for p in paths if p not in reg]
    if not fresh or _running.is_set():
        return
    threading.Thread(target=_run, args=(fresh,), name='AUTO-ADD', daemon=True).start()


def _run(paths):
    from mylar import importer, archives
    with _lock:
        _running.set()
        try:
            myDB = db.DBConnection()
            watched = {str(r['ComicID']) for r in myDB.select('SELECT ComicID FROM comics')}
            from mylar.PostProcessor import PP_LOCK
            reg = _load()
            groups = {}
            with PP_LOCK:
                for p in paths:
                    reg[p] = {'at': time.time()}
                    if not os.path.isfile(p):
                        continue
                    info = _parse(p)
                    if not info:
                        continue
                    key = (_norm(info['series']), info['year'], _pack_date(p))
                    groups.setdefault(key, {'info': info, 'files': [], 'cvid': None})['files'].append(p)
                    if not groups[key]['cvid']:
                        groups[key]['cvid'] = _comicinfo_issueid(p)
            added, unknown = [], []
            archives.busy('Finding series for %s unclaimed issues' % len(paths))
            for (nm, year, packdate), g in groups.items():
                try:
                    volid = _volume_for_issue(g['cvid']) if g['cvid'] else None
                    if volid is None:
                        volid = _find_volume(g['info']['series'], g['info']['issue'], year, packdate)
                except Exception as e:
                    logger.warn('[AUTO-ADD] ComicVine lookup failed for %s: %s' % (g['info']['series'], e))
                    volid = None
                if volid is None:
                    unknown.append(g['info']['series'])
                    continue
                if volid in watched:
                    continue
                logger.info('[AUTO-ADD] Adding %s (ComicVine %s) for %s file(s) found in the monitored folder.' % (g['info']['series'], volid, len(g['files'])))
                try:
                    importer.addComictoDB(volid, 'no')
                    watched.add(volid)
                    added.append(g['info']['series'])
                except Exception as e:
                    logger.warn('[AUTO-ADD] Unable to add %s: %s' % (g['info']['series'], e))
            _save(reg)
            if added:
                archives.note('added %s series: %s' % (len(added), ', '.join(sorted(set(added)))))
            if unknown:
                archives.note('could not identify %s series' % len(set(unknown)))
            logger.info('[AUTO-ADD] Added %s series; %s could not be identified.' % (len(added), len(set(unknown))))
            if added and mylar.CONFIG.CHECK_FOLDER:
                logger.info('[AUTO-ADD] Filing the issues of the new series now.')
                mylar.PP_QUEUE.put({'nzb_name': 'Manual Run', 'nzb_folder': mylar.CONFIG.CHECK_FOLDER, 'failed': False, 'issueid': None,
                                    'comicid': None, 'apicall': False, 'ddl': False, 'download_info': None})
            archives.done('Auto-add finished.')
        finally:
            archives.done('Auto-add stopped early - check the log.')
            _running.clear()
