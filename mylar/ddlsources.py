import base64
import datetime
import json
import os
import re
import threading
import time

import requests

import mylar
from mylar import db, logger

BUILTIN = ['main', 'mega', 'mediafire', 'pixeldrain']
KNOWN = ['main', 'pixeldrain', 'mega', 'mediafire', 'vikingfile', 'datanodes', 'ufile', 'terabox', 'torrent']
LABELS = {'main': 'GetComics direct (Download Now / Main Server / Mirror)', 'mega': 'Mega', 'mediafire': 'Mediafire',
          'pixeldrain': 'Pixeldrain', 'vikingfile': 'VikingFile', 'datanodes': 'DataNodes', 'ufile': 'Ufile', 'terabox': 'TeraBox',
          'torrent': 'Torrent or magnet link'}
JD2_ONLY = {'vikingfile': 'JD2', 'datanodes': 'JD2', 'ufile': 'JD2', 'terabox': 'JD2 (may need a TeraBox account in JD2)'}
DEFAULT_ORDER = list(KNOWN)

_pd_lock = threading.Lock()
_pd_cache = {'at': 0, 'data': None}


def canonical(label, href=None):
    s = re.sub(r'\blink\b', '', (label or '').lower()).strip()
    if is_torrent(label, href):
        return 'torrent'
    if s in ('download now', 'main server', 'mirror download') or 'main server' in s:
        return 'main'
    for k in ('mega', 'mediafire', 'pixeldrain'):
        if k[:5] in s:
            return k
    return re.sub(r'[^a-z0-9]+', '', s) or None


def is_torrent(label, href=None):
    """A post's torrent or magnet button, by its label or where it points."""
    h = str(href or '').strip().lower()
    return (h.startswith('magnet:') or h.split('?')[0].endswith('.torrent')
            or bool(re.search(r'\b(torrent|magnet)\b', str(label or '').lower())))


def torrent_ready():
    """Torrent links can be used: torrent search is on and there's a torrent client or watch folder to send them to."""
    c = mylar.CONFIG
    if not (getattr(c, 'ENABLE_TORRENTS', False) and getattr(c, 'ENABLE_TORRENT_SEARCH', False)):
        return False
    return any(getattr(mylar, f, False) for f in ('USE_UTORRENT', 'USE_RTORRENT', 'USE_TRANSMISSION', 'USE_DELUGE',
                                                   'USE_QBITTORRENT', 'USE_WATCHDIR'))


def torrent_first(available, size_bytes=None):
    """Whether a post's torrent comes before every other source it has that Issuarr can use."""
    o = order(size_bytes)
    if 'torrent' not in o or not torrent_ready():
        return False
    ranks = [o.index(s) for s in available if s in o and s != 'torrent']
    return not ranks or o.index('torrent') < min(ranks)


def _ensure(myDB):
    myDB.action('CREATE TABLE IF NOT EXISTS ddl_sources (Name TEXT UNIQUE, Label TEXT, FirstSeen TEXT, LastSeen TEXT, Seen INTEGER)')


def record(labels):
    names = {}
    for label in labels or []:
        n = canonical(label)
        if n and n != 'readonline':
            names.setdefault(n, label)
    if not names:
        return
    try:
        myDB = db.DBConnection()
        _ensure(myDB)
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        for n, label in names.items():
            row = myDB.selectone('SELECT Seen FROM ddl_sources WHERE Name=?', [n]).fetchone()
            vals = {'Label': label, 'LastSeen': now, 'Seen': (row['Seen'] or 0) + 1 if row else 1}
            if not row:
                vals['FirstSeen'] = now
            myDB.upsert('ddl_sources', vals, {'Name': n})
    except Exception as e:
        logger.fdebug('[DDL-SOURCES] Unable to record sources %s: %s' % (list(names), e))


def _as_list(value):
    if isinstance(value, list):
        return [str(v).lower() for v in value]
    try:
        v = json.loads(value or '[]')
        return [str(x).lower() for x in v] if isinstance(v, list) else []
    except Exception:
        return []


def configured_order():
    order = _as_list(getattr(mylar.CONFIG, 'DDL_PRIORITY_ORDER', None)) or list(DEFAULT_ORDER)
    for b in KNOWN:
        if b not in order:
            order.append(b)
    return order


def disabled():
    return set(_as_list(getattr(mylar.CONFIG, 'DDL_DISABLED_SOURCES', None)))


def all_sources():
    seen = {}
    try:
        myDB = db.DBConnection()
        _ensure(myDB)
        seen = {r['Name']: dict(r) for r in myDB.select('SELECT * FROM ddl_sources')}
    except Exception:
        pass
    order = configured_order()
    for n in seen:
        if n not in order:
            order.append(n)
    off = disabled()
    out = []
    for n in order:
        s = seen.get(n, {})
        out.append({'name': n, 'label': LABELS.get(n) or s.get('Label') or n, 'builtin': n in BUILTIN,
                    'via': 'Mylar or JD2' if n in BUILTIN and n != 'main' else ('Mylar (FlareSolverr)' if n == 'main' else
                           'your torrent client, when torrent search is on' if n == 'torrent' else JD2_ONLY.get(n, 'JD2, if it supports the host')),
                    'enabled': n not in off, 'last_seen': s.get('LastSeen'), 'seen': s.get('Seen') or 0})
    return out


def size_bytes(text):
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*([KMGT]?)(?:i?B)?\b', str(text or ''), re.I)
    if not m:
        return None
    return int(float(m.group(1).replace(',', '.')) * 1024 ** ' KMGT'.index(m.group(2).upper() or ' '))


def large_limit():
    if not getattr(mylar.CONFIG, 'DDL_MAIN_LARGE_LAST', False):
        return None
    try:
        mb = int(getattr(mylar.CONFIG, 'DDL_MAIN_LARGE_MB', 400) or 400)
    except (TypeError, ValueError):
        mb = 400
    return mb * 1024 * 1024


def order(size_bytes=None):
    off = disabled()
    result = [n for n in configured_order() if n not in off]
    if 'pixeldrain' in result and size_bytes and not pixeldrain_fits(size_bytes):
        result.remove('pixeldrain')
        result.append('pixeldrain')
        logger.fdebug('[DDL-SOURCES] Pixeldrain allowance too low for %s bytes - trying it last.' % size_bytes)
    limit = large_limit()
    if 'main' in result and size_bytes and limit and size_bytes > limit and result[-1] != 'main':
        result.remove('main')
        result.append('main')
        logger.info('[DDL-SOURCES] %s MB is over the %s MB limit for the GetComics server - trying the other hosts first.' % (size_bytes // 1048576, limit // 1048576))
    return result


def is_enabled(name):
    return name not in disabled()


def pixeldrain_key():
    key = os.environ.get('PIXELDRAIN_API_KEY') or getattr(mylar.CONFIG, 'PIXELDRAIN_API_KEY', None)
    return key if key and key != 'None' else None


def pixeldrain_auth_header(key=None):
    key = key or pixeldrain_key()
    if not key:
        return {}
    return {'Authorization': 'Basic ' + base64.b64encode((':' + key).encode()).decode()}


def pixeldrain_status(force=False, key=None):
    with _pd_lock:
        if not force and key is None and _pd_cache['data'] and time.time() - _pd_cache['at'] < 300:
            return _pd_cache['data']
    out = {'ok': False}
    try:
        headers = {'User-Agent': 'Mylar3'}
        headers.update(pixeldrain_auth_header(key))
        r = requests.get('https://pixeldrain.com/api/misc/rate_limits', headers=headers, timeout=15)
        d = r.json()
        out = {'ok': True, 'limit': d.get('transfer_limit') or 0, 'used': d.get('transfer_limit_used') or 0,
               'speed_limit': d.get('speed_limit'), 'overloaded': d.get('server_overload'), 'account': bool(key or pixeldrain_key())}
        if key or pixeldrain_key():
            u = requests.get('https://pixeldrain.com/api/user', headers=headers, timeout=15)
            if u.status_code == 200:
                ud = u.json()
                out['user'] = ud.get('username')
                sub = ud.get('subscription') or {}
                out['plan'] = sub.get('name')
            elif u.status_code in (401, 403):
                out.update(ok=False, error='Pixeldrain rejected the API key.')
    except Exception as e:
        out = {'ok': False, 'error': 'Could not reach Pixeldrain: %s' % e}
    if key is None:
        with _pd_lock:
            _pd_cache.update(at=time.time(), data=out)
    return out


def pixeldrain_fits(size_bytes):
    s = pixeldrain_status()
    if not s.get('ok') or not s.get('limit'):
        return True
    return (s['limit'] - s['used']) >= size_bytes
