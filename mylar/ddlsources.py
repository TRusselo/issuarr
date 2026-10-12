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
# to (any host other than those two), torrent or magnet links (a GetComics post's or an
# Internet Archive item's), and files straight from the Internet Archive.
GROUPS = ['direct', 'cloud', 'torrent', 'ia']
GROUP_LABELS = {'direct': 'GetComics direct', 'cloud': 'Cloud shares', 'torrent': 'Torrent or magnet link',
                'ia': 'Internet Archive'}
GROUP_VIA = {'direct': 'Download Now, Main Server and Mirror, through FlareSolverr',
             'cloud': 'Mega, MediaFire and Pixeldrain by Issuarr; other hosts such as TeraBox through JD2',
             'torrent': 'Sent to your torrent client, when torrent search is on. Includes Internet Archive torrents',
             'ia': 'Searches archive.org for Wanted issues, mostly older ones, and downloads the file from there'}
GETCOMICS = ['direct', 'cloud', 'torrent']
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
    """Groups that are turned off. Of the old per-host switches only GetComics direct and torrent carry over.
    The Internet Archive's switch is ENABLE_ARCHIVEORG, which also turns its search on or off."""
    off = {group(n) for n in _as_list(getattr(mylar.CONFIG, 'DDL_DISABLED_SOURCES', None)) if n in GROUPS or n in ('main', 'torrent')}
    off.discard('ia')
    if not getattr(mylar.CONFIG, 'ENABLE_ARCHIVEORG', False):
        off.add('ia')
    return off


def ia_before_getcomics():
    """Whether the Internet Archive is searched before GetComics: it is when its group is above
    every GetComics group that can be used, otherwise it's searched right after GetComics."""
    groups = [g for g in configured_groups() if g not in disabled()]
    if 'ia' not in groups:
        return False
    gc = [groups.index(g) for g in GETCOMICS if g in groups and (g != 'torrent' or torrent_ready())]
    return not gc or groups.index('ia') < min(gc)


def place_ia(providers, gc_name='DDL(GetComics)', ia_name='DDL(Internet Archive)'):
    """The search order with the Internet Archive moved next to GetComics, before or after it
    as the download sources list puts it. Without GetComics it keeps its own place."""
    if gc_name not in providers or ia_name not in providers:
        return providers
    out = [p for p in providers if p != ia_name]
    at = out.index(gc_name)
    out.insert(at if ia_before_getcomics() else at + 1, ia_name)
    return out


def send_torrent(name, issue, year, url, site, issueid, comicid, label):
    """Send a torrent or magnet link to the torrent client and watch the job like any other
    snatched torrent. Returns what torsend2client gave back, or None if the client didn't take it."""
    from mylar import downloadqueue, rsscheck
    try:
        sent = rsscheck.torsend2client(name, issue or '', year or '', url, site)
    except Exception as e:
        logger.warn('[DDL] Sending the torrent failed: %s' % e)
        return None
    if not isinstance(sent, dict) or not sent.get('hash'):
        return None
    downloadqueue.record_job(issueid, None, comicid, sent.get('clientmode'), sent['hash'], label)
    if (getattr(mylar, 'USE_RTORRENT', False) or getattr(mylar, 'USE_DELUGE', False)) and \
            (mylar.CONFIG.AUTO_SNATCH or mylar.CONFIG.LOCAL_TORRENT_PP):
        mylar.SNATCHED_QUEUE.put({'issueid': issueid, 'comicid': comicid, 'hash': sent['hash']})
    return sent


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
    """Every GetComics source, host by host, in the order to try them."""
    off = disabled()
    cloud = list(CLOUD)
    if size_bytes and not pixeldrain_fits(size_bytes):
        cloud.remove('pixeldrain')
        cloud.append('pixeldrain')
        logger.fdebug('[DDL-SOURCES] Pixeldrain allowance too low for %s bytes - trying it last of the cloud shares.' % size_bytes)
    hosts = {'direct': ['main'], 'cloud': cloud, 'torrent': ['torrent'], 'ia': []}  # the Internet Archive isn't a GetComics source
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
