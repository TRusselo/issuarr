import base64
import json
import os
import re
import threading
import time

import requests

import mylar
from mylar import logger

# What the download sources list orders: GetComics' own server, the cloud shares a post links
# to (any host other than those two), and its torrent or magnet link.
GROUPS = ['direct', 'cloud', 'torrent']
GROUP_LABELS = {'direct': 'GetComics direct', 'cloud': 'Cloud shares', 'torrent': 'Torrent or magnet link'}
GROUP_VIA = {'direct': 'Download Now, Main Server and Mirror, through FlareSolverr',
             'cloud': 'Mega, MediaFire and Pixeldrain by Issuarr; other hosts such as TeraBox through JD2',
             'torrent': 'Sent to your torrent client, when torrent search is on'}
DEFAULT_GROUPS = list(GROUPS)
BUILTIN = ['main', 'mega', 'mediafire', 'pixeldrain']
# cloud shares in the order they're tried; the order inside the group doesn't matter much
CLOUD = ['pixeldrain', 'mega', 'mediafire', 'vikingfile', 'datanodes', 'ufile', 'terabox']

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


def group(name):
    """'direct', 'cloud' or 'torrent' for a source a post links to."""
    if name in GROUPS:
        return name
    return 'direct' if name == 'main' else 'torrent' if name == 'torrent' else 'cloud'


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
    groups = [g for g in configured_groups() if g not in disabled()]
    if 'torrent' not in groups or not torrent_ready():
        return False
    ranks = [groups.index(group(s)) for s in available if s and s != 'torrent' and group(s) in groups]
    return not ranks or groups.index('torrent') < min(ranks)


def _as_list(value):
    if isinstance(value, list):
        return [str(v).lower() for v in value]
    try:
        v = json.loads(value or '[]')
        return [str(x).lower() for x in v] if isinstance(v, list) else []
    except Exception:
        return []


def configured_groups():
    """The groups in the order to try them. An order saved as host names (before the groups) keeps
    each group where its first host was."""
    out = []
    for n in _as_list(getattr(mylar.CONFIG, 'DDL_PRIORITY_ORDER', None)) or DEFAULT_GROUPS:
        g = group(n)
        if g not in out:
            out.append(g)
    return out + [g for g in GROUPS if g not in out]


def disabled():
    """Groups that are turned off. Of the old per-host switches only GetComics direct and torrent carry over."""
    return {group(n) for n in _as_list(getattr(mylar.CONFIG, 'DDL_DISABLED_SOURCES', None)) if n in GROUPS or n in ('main', 'torrent')}


def all_sources():
    off = disabled()
    return [{'name': g, 'label': GROUP_LABELS[g], 'via': GROUP_VIA[g], 'enabled': g not in off} for g in configured_groups()]


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
    """Every source, host by host, in the order to try them."""
    off = disabled()
    cloud = list(CLOUD)
    if size_bytes and not pixeldrain_fits(size_bytes):
        cloud.remove('pixeldrain')
        cloud.append('pixeldrain')
        logger.fdebug('[DDL-SOURCES] Pixeldrain allowance too low for %s bytes - trying it last of the cloud shares.' % size_bytes)
    hosts = {'direct': ['main'], 'cloud': cloud, 'torrent': ['torrent']}
    groups = [g for g in configured_groups() if g not in off]
    limit = large_limit()
    if 'direct' in groups and 'cloud' in groups and size_bytes and limit and size_bytes > limit \
            and groups.index('direct') < groups.index('cloud'):
        groups.remove('direct')
        groups.insert(groups.index('cloud') + 1, 'direct')
        logger.info('[DDL-SOURCES] %s MB is over the %s MB limit for the GetComics server - trying the cloud shares first.' % (size_bytes // 1048576, limit // 1048576))
    return [h for g in groups for h in hosts[g]]


def is_enabled(name):
    return group(name) not in disabled()


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
