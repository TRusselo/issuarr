#  This file is part of Issuarr.
#
#  Issuarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Issuarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Issuarr.  If not, see <http://www.gnu.org/licenses/>.

"""The Downloads > Queue list: every download that hasn't been filed yet.

Direct downloads come from ddl_info. Grabs handed to SABnzbd, NZBGet or a
torrent client come from the snatched table, with live progress read from
the client when it can be reached. The client's job id is recorded at send
time in client_jobs so the two can be matched.
"""

import datetime
import re
import threading
import time
import xmlrpc.client

import requests

import mylar
from mylar import db, helpers, logger

def ddl_queue_rows(myDB):
    """Every row of the direct-download queue, named from the library where possible.

    Starts from ddl_info so nothing is dropped: annuals, story-arc issues, packs and
    one-offs used to vanish because the old query needed a matching row in issues.
    """
    def lookup(sql, ids):
        out = {}
        ids = [i for i in ids if i is not None]
        for n in range(0, len(ids), 500):
            chunk = ids[n:n + 500]
            try:
                for r in myDB.select(sql % ','.join('?' * len(chunk)), chunk):
                    out.setdefault(str(r['id']), r)
            except Exception:
                pass
        return out

    rows = myDB.select("SELECT * FROM ddl_info")
    issueids = list({str(r['issueid']) for r in rows if r['issueid'] is not None})
    comicids = list({str(r['comicid']) for r in rows if r['comicid'] is not None})
    comics = lookup("SELECT ComicID AS id, ComicName, ComicVersion, ComicYear FROM comics WHERE ComicID IN (%s)", comicids)
    issues = lookup("SELECT IssueID AS id, ComicID, Issue_Number FROM issues WHERE IssueID IN (%s)", issueids)
    annuals = lookup("SELECT IssueID AS id, ComicID, Issue_Number FROM annuals WHERE IssueID IN (%s)", issueids)
    oneoffs = lookup("SELECT IssueID AS id, ComicID, ComicName, IssueNumber AS Issue_Number FROM oneoffhistory WHERE IssueID IN (%s)", issueids)

    resultlist = []
    for r in rows:
        iid = None if r['issueid'] is None else str(r['issueid'])
        iss = issues.get(iid) or annuals.get(iid)
        oneoff = oneoffs.get(iid) if iss is None else None
        comicid = r['comicid'] or (iss['ComicID'] if iss else None) or (oneoff['ComicID'] if oneoff else None)
        comic = comics.get(str(comicid)) if comicid is not None else None
        name = comic['ComicName'] if comic else (oneoff['ComicName'] if oneoff else None)
        volume = comic['ComicVersion'] if comic else None

        if r['issues'] is not None:
            issue = '#%s' % r['issues']
            year = r['year']
        else:
            number = iss['Issue_Number'] if iss else (oneoff['Issue_Number'] if oneoff else None)
            issue = '#%s' % number if number is not None else None
            year = (comic['ComicYear'] if comic else None) or r['year']

        filename = r['series'] or ''
        if r['pack'] or name is None:
            if year is not None and str(year) not in filename:
                series = '%s (%s)' % (filename, year)
            else:
                series = filename
            if name is None and not r['pack'] and issue is not None and issue not in series:
                series = '%s %s' % (series, issue)
        else:
            parts = [name] + ([volume] if volume else []) + ([issue] if issue else [])
            series = '%s (%s)' % (' '.join(parts), year) if year else ' '.join(parts)

        resultlist.append({'series':       series,
                           'issue':        issue,
                           'queueid':      r['id'],
                           'linktype':     r['link_type'],
                           'volume':       volume,
                           'year':         year,
                           'size':         (r['size'] or '').strip(),
                           'comicid':      comicid if comic else None,
                           'issueid':      r['issueid'],
                           'status':       r['status'],
                           'updated_date': r['updated_date'],
                           'progress':     '100%' if r['status'] == 'Completed' else '',
                           'site':         r['site'] if 'site' in r.keys() else None,
                           'jd2':          bool(r['jd2_job_id']) if 'jd2_job_id' in r.keys() else False})
    return resultlist


def client_snatches(myDB):
    """Grabs handed to SABnzbd, NZBGet or a torrent client that haven't been processed yet.

    Direct downloads are left out because the DDL queue already lists them. A grab counts
    as waiting while its issue (or arc issue, or one-off) is still marked Snatched; that
    status changes when the file is post-processed, fails, or is reset by hand.
    """
    current = {}
    for table, key in (('issues', 'IssueID'), ('annuals', 'IssueID'), ('storyarcs', 'IssueArcID'), ('oneoffhistory', 'IssueID')):
        try:
            for r in myDB.select('SELECT %s AS id, Status FROM %s WHERE Status IS NOT NULL' % (key, table)):
                if r['id'] is not None:
                    current.setdefault(str(r['id']), set()).add(r['Status'])
        except Exception:
            continue

    rows = myDB.select("SELECT IssueID, ComicID, ComicName, Issue_Number, Provider, DateAdded, Status FROM snatched "
                       "WHERE Status IN ('Snatched', 'Downloaded', 'Post-Processed') ORDER BY DateAdded DESC")
    done = {}
    for r in rows:
        if r['Status'] != 'Snatched':
            prev = done.get(r['IssueID'])
            done[r['IssueID']] = max(prev, r['DateAdded'] or '') if prev else (r['DateAdded'] or '')

    out = []
    seen = set()
    for r in rows:
        iid = r['IssueID']
        if r['Status'] != 'Snatched' or iid is None or iid in seen:
            continue
        provider = r['Provider'] or ''
        if provider.upper().startswith('DDL'):
            continue
        statuses = current.get(str(iid))
        if statuses is not None:
            if 'Snatched' not in statuses:
                continue
        elif done.get(iid, '') >= (r['DateAdded'] or ''):
            continue
        seen.add(iid)
        out.append({'issueid': iid,
                    'comicid': r['ComicID'],
                    'series': r['ComicName'],
                    'issue': r['Issue_Number'],
                    'provider': provider or None,
                    'sent': r['DateAdded']})
    return out


# ---- client job ids -------------------------------------------------------

HOSTS = {'GC-Main': 'GetComics', 'GC-Mirror': 'GetComics mirror', 'GC-Pixel': 'Pixeldrain', 'GC-Mega': 'Mega',
         'GC-Media': 'Mediafire', 'DDL-Ext': 'External link'}

CLIENT_NAMES = {'sabnzbd': 'SABnzbd', 'nzbget': 'NZBGet', 'qbittorrent': 'qBittorrent', 'deluge': 'Deluge',
                'transmission': 'Transmission', 'rtorrent': 'rTorrent', 'utorrent': 'uTorrent',
                'watchdir': 'Watch folder', 'blackhole': 'Blackhole folder'}


def record_job(issueid, issuearcid, comicid, client, jobid, name=None):
    """Remember which client job a grab became, so the queue can show its progress."""
    if not client or jobid in (None, ''):
        return
    try:
        myDB = db.DBConnection()
        myDB.action('CREATE TABLE IF NOT EXISTS client_jobs (IssueID TEXT, IssueArcID TEXT, ComicID TEXT, Client TEXT, '
                    'JobID TEXT, Name TEXT, DateAdded TEXT)')
        myDB.action('INSERT INTO client_jobs (IssueID, IssueArcID, ComicID, Client, JobID, Name, DateAdded) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    [None if issueid is None else str(issueid), None if issuearcid is None else str(issuearcid),
                     None if comicid is None else str(comicid), client, str(jobid), name, helpers.now()])
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime('%Y-%m-%d %H:%M:%S')
        myDB.action('DELETE FROM client_jobs WHERE DateAdded < ?', [cutoff])
    except Exception as e:
        logger.fdebug('[QUEUE] Could not record the %s job for %s: %s' % (client, issueid, e))


def _latest_jobs(myDB):
    jobs = {}
    try:
        rows = myDB.select('SELECT IssueID, IssueArcID, Client, JobID, Name, DateAdded FROM client_jobs ORDER BY DateAdded')
    except Exception:
        return jobs
    for r in rows:
        for key in (r['IssueID'], r['IssueArcID']):
            if key is not None:
                jobs[str(key)] = {'client': r['Client'], 'id': str(r['JobID']), 'name': r['Name']}
                jobs[re.sub('^S', '', str(key))] = jobs[str(key)]
    return jobs


# ---- live status from the clients -----------------------------------------

def _norm_name(n):
    return re.sub(r'[^a-z0-9]', '', re.sub(r'\.nzb$', '', str(n or '').lower()))


def _secs(t):
    """'0:12:05' or seconds -> seconds."""
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return int(t) if 0 <= t < 8640000 else None
    try:
        parts = [int(p) for p in str(t).split(':')]
    except ValueError:
        return None
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


def _job(client, state, name=None, done=None, total=None, speed=None, eta=None, message=None):
    pct = None
    if total:
        pct = max(0, min(100, int(round(float(done or 0) * 100 / float(total)))))
    return {'client': CLIENT_NAMES.get(client, client), 'state': state, 'name': name, 'percent': pct,
            'done': done, 'total': total, 'speed': speed, 'eta': _secs(eta), 'message': message}


def _sab():
    out = {}
    base = (mylar.CONFIG.SAB_HOST or '').rstrip('/') + '/api'
    params = {'apikey': mylar.CONFIG.SAB_APIKEY, 'output': 'json'}
    q = requests.get(base, params=dict(params, mode='queue', limit=200), timeout=5, verify=False).json().get('queue', {})
    speed = float(q.get('kbpersec') or 0) * 1024
    for s in q.get('slots', []):
        st = s.get('status', '')
        total = float(s.get('mb') or 0) * 1048576
        left = float(s.get('mbleft') or 0) * 1048576
        state = {'Downloading': 'Downloading', 'Paused': 'Paused'}.get(st, 'Queued')
        out[s.get('nzo_id')] = _job('sabnzbd', state, s.get('filename'), total - left, total,
                                    speed if state == 'Downloading' else None,
                                    s.get('timeleft') if state == 'Downloading' else None)
    h = requests.get(base, params=dict(params, mode='history', limit=60), timeout=5, verify=False).json().get('history', {})
    for s in h.get('slots', []):
        st = s.get('status', '')
        total = s.get('bytes') or None
        if st == 'Failed':
            job = _job('sabnzbd', 'Failed', s.get('name'), message=s.get('fail_message') or None)
        elif st == 'Completed':
            job = _job('sabnzbd', 'Processing', s.get('name'), total, total, message='Finished downloading. Waiting to be filed.')
        else:
            job = _job('sabnzbd', 'Processing', s.get('name'), total, total, message='%s in SABnzbd' % st)
        out.setdefault(s.get('nzo_id'), job)
    return out


class _TimeoutTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = 5
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = 5
        return conn


def _nzbget():
    from mylar import nzbget
    url = nzbget.NZBGet().nzb_url
    server = xmlrpc.client.ServerProxy(url, transport=_TimeoutSafeTransport() if url.startswith('https') else _TimeoutTransport())
    out = {}
    try:
        speed = server.status().get('DownloadRate')
    except Exception:
        speed = None
    for g in server.listgroups():
        st = g.get('Status', '')
        total = float(g.get('FileSizeMB') or 0) * 1048576
        left = float(g.get('RemainingSizeMB') or 0) * 1048576
        if st == 'DOWNLOADING':
            state = 'Downloading'
        elif st == 'PAUSED':
            state = 'Paused'
        elif st in ('QUEUED', 'FETCHING'):
            state = 'Queued'
        else:
            state = 'Processing'
        eta = int(left / speed) if state == 'Downloading' and speed else None
        out[str(g.get('NZBID'))] = _job('nzbget', state, g.get('NZBName'), total - left, total,
                                        speed if state == 'Downloading' else None, eta)
    for g in server.history(False)[:60]:
        st = str(g.get('Status', ''))
        if st.startswith('SUCCESS') or st.startswith('WARNING'):
            total = float(g.get('FileSizeMB') or 0) * 1048576 or None
            job = _job('nzbget', 'Processing', g.get('Name'), total, total, message='Finished downloading. Waiting to be filed.')
        elif st.startswith('FAILURE') or st.startswith('DELETED'):
            job = _job('nzbget', 'Failed', g.get('Name'), message='NZBGet reported %s' % st.lower().replace('/', ': '))
        else:
            continue
        out.setdefault(str(g.get('NZBID')), job)
    return out


def _torrent_state(progress, paused=False, queued=False, error=False, checking=False):
    if error:
        return 'Failed'
    if progress is not None and progress >= 100:
        return 'Processing'
    if paused:
        return 'Paused'
    if queued:
        return 'Queued'
    if checking:
        return 'Checking'
    return 'Downloading'


def _torrent_job(client, name, progress, total, speed, eta, **flags):
    state = _torrent_state(progress, **flags)
    done = total * progress / 100.0 if total and progress is not None else None
    msg = 'Finished downloading. Waiting to be filed.' if state == 'Processing' else None
    return _job(client, state, name, done, total, speed if state == 'Downloading' else None,
                eta if state == 'Downloading' else None, msg)


def _qbittorrent(hashes):
    from mylar.torrent.clients import qbittorrent
    client = qbittorrent.TorrentClient().connect(mylar.CONFIG.QBITTORRENT_HOST, mylar.CONFIG.QBITTORRENT_USERNAME,
                                                 mylar.CONFIG.QBITTORRENT_PASSWORD)
    if isinstance(client, dict):
        raise Exception(client.get('error'))
    out = {}
    for t in client.torrents(hashes='|'.join(hashes)):
        st = t.get('state', '')
        out[t.get('hash', '').lower()] = _torrent_job(
            'qbittorrent', t.get('name'), float(t.get('progress') or 0) * 100, t.get('size'), t.get('dlspeed'), t.get('eta'),
            paused=st.startswith('paused') or st.startswith('stopped'), queued=st.startswith('queued'),
            error=st in ('error', 'missingFiles'), checking=st.startswith('checking'))
    return out


def _deluge(hashes):
    from mylar.torrent.clients import deluge
    dc = deluge.TorrentClient()
    client = dc.connect(mylar.CONFIG.DELUGE_HOST, mylar.CONFIG.DELUGE_USERNAME, mylar.CONFIG.DELUGE_PASSWORD)
    if isinstance(client, dict):
        raise Exception(client.get('error'))

    def dec(v):
        return v.decode('utf-8', 'replace') if isinstance(v, bytes) else v
    res = client.call('core.get_torrents_status', {'id': list(hashes)},
                      ['name', 'progress', 'download_payload_rate', 'eta', 'state', 'total_wanted'])
    out = {}
    for h, t in (res or {}).items():
        t = {dec(k): dec(v) for k, v in t.items()}
        st = str(t.get('state', ''))
        out[dec(h).lower()] = _torrent_job('deluge', t.get('name'), t.get('progress'), t.get('total_wanted'),
                                           t.get('download_payload_rate'), t.get('eta'),
                                           paused=st == 'Paused', queued=st == 'Queued', error=st == 'Error',
                                           checking=st in ('Checking', 'Allocating', 'Moving'))
    return out


def _transmission(hashes):
    from mylar.torrent.clients import transmission
    conn = transmission.TorrentClient().connect(mylar.CONFIG.TRANSMISSION_HOST, mylar.CONFIG.TRANSMISSION_USERNAME,
                                                mylar.CONFIG.TRANSMISSION_PASSWORD)
    if not conn:
        raise Exception('could not connect')
    out = {}
    for t in conn.get_torrents(list(hashes)):
        try:
            eta = int(t.eta.total_seconds())
        except Exception:
            eta = None
        st = str(getattr(t, 'status', ''))
        out[t.hashString.lower()] = _torrent_job('transmission', t.name, t.progress, t.sizeWhenDone, t.rateDownload, eta,
                                                 paused=st == 'stopped', queued=st in ('download pending', 'check pending'),
                                                 error=bool(getattr(t, 'error', 0)), checking=st == 'checking')
    return out


def _rtorrent(hashes):
    from mylar.torrent.clients import rtorrent
    conn = rtorrent.TorrentClient().connect(mylar.CONFIG.RTORRENT_HOST, mylar.CONFIG.RTORRENT_USERNAME,
                                            mylar.CONFIG.RTORRENT_PASSWORD, mylar.CONFIG.RTORRENT_AUTHENTICATION,
                                            mylar.CONFIG.RTORRENT_VERIFY, mylar.CONFIG.RTORRENT_RPC_URL,
                                            mylar.CONFIG.RTORRENT_CA_BUNDLE)
    if isinstance(conn, dict):
        raise Exception(conn.get('error'))
    out = {}
    for h in hashes:
        t = conn.find_torrent(h.upper())
        if not t:
            continue
        total = t.get_size_bytes()
        done = t.get_completed_bytes()
        speed = t.get_down_rate()
        progress = done * 100.0 / total if total else 0
        eta = int((total - done) / speed) if speed else None
        out[h.lower()] = _torrent_job('rtorrent', t.name, progress, total, speed, eta, paused=not t.is_active())
    return out


def _utorrent(hashes):
    from mylar.torrent.clients import utorrent
    conn = utorrent.TorrentClient().connect(mylar.CONFIG.UTORRENT_HOST, mylar.CONFIG.UTORRENT_USERNAME,
                                            mylar.CONFIG.UTORRENT_PASSWORD)
    want = {h.lower() for h in hashes}
    out = {}
    for t in conn.list()[1].get('torrents', []):
        h = str(t[0]).lower()
        if h not in want:
            continue
        bits = int(t[1] or 0)
        out[h] = _torrent_job('utorrent', t[2], (t[4] or 0) / 10.0, t[3], t[9], t[10],
                              paused=bool(bits & 32), queued=not bits & 1, error=bool(bits & 16), checking=bool(bits & 2))
    return out


TORRENT_FETCHERS = (('USE_QBITTORRENT', _qbittorrent), ('USE_DELUGE', _deluge), ('USE_TRANSMISSION', _transmission),
                    ('USE_RTORRENT', _rtorrent), ('USE_UTORRENT', _utorrent))

_CACHE = {'at': 0, 'key': None, 'data': {}, 'busy': False}
_CACHE_LOCK = threading.Lock()


def _fetch_all(hashes):
    data = {}
    fetchers = []
    if mylar.USE_SABNZBD and mylar.CONFIG.SAB_HOST:
        fetchers.append(('sabnzbd', _sab, ()))
    if mylar.USE_NZBGET and mylar.CONFIG.NZBGET_HOST:
        fetchers.append(('nzbget', _nzbget, ()))
    if hashes and getattr(mylar.CONFIG, 'ENABLE_TORRENTS', True):
        for flag, fn in TORRENT_FETCHERS:
            if getattr(mylar, flag, False):
                fetchers.append(('torrent', fn, (hashes,)))
    for kind, fn, args in fetchers:
        try:
            for k, v in fn(*args).items():
                data[(kind, str(k).lower())] = v
        except Exception as e:
            logger.fdebug('[QUEUE] Could not read the queue from %s: %s' % (fn.__name__.strip('_'), e))
    return data


def client_status(hashes=(), wait=3.0):
    """Live status of client jobs, keyed by (kind, job id). Cached for a few seconds.

    Clients can be slow or down, so a refresh runs in the background and this
    waits at most `wait` seconds for it before returning what it already has.
    """
    hashes = tuple(sorted({h.lower() for h in hashes if h}))
    with _CACHE_LOCK:
        fresh = time.time() - _CACHE['at'] < 4 and _CACHE['key'] == hashes
        start = not fresh and not _CACHE['busy']
        if start:
            _CACHE['busy'] = True

    def refresh():
        try:
            data = _fetch_all(hashes)
            with _CACHE_LOCK:
                _CACHE.update(at=time.time(), key=hashes, data=data)
        finally:
            _CACHE['busy'] = False

    if start:
        t = threading.Thread(target=refresh, name='QUEUE-STATUS', daemon=True)
        t.start()
        t.join(wait)
    return _CACHE['data']


# ---- the combined list ----------------------------------------------------

def build(myDB, active=None):
    """One list of every download: direct ones and the ones at a download client.

    `active` is the DDL item being downloaded now ({'a_id', 'percent', 'a_done', 'a_total', ...}).
    """
    rows = []
    for d in ddl_queue_rows(myDB):
        status = d['status'] or 'Queued'
        row = {'key': 'ddl-%s' % d['queueid'], 'kind': 'ddl', 'queueid': d['queueid'], 'title': d['series'],
               'comicid': d['comicid'], 'issueid': d['issueid'], 'via': HOSTS.get(d['linktype'], d['linktype']),
               'source': 'JDownloader 2' if d['jd2'] else ('GetComics' if 'GetComics' in str(d['site'] or 'GetComics') else 'Direct download'),
               'status': status, 'percent': 100 if status == 'Completed' else None, 'size': d['size'] or None,
               'speed': None, 'eta': None, 'progress': None, 'message': None, 'detail': None,
               'updated': d['updated_date']}
        if active and status == 'Downloading' and str(active.get('a_id')) == str(d['queueid']):
            try:
                row['percent'] = int(str(active.get('percent', '')).rstrip('%'))
            except ValueError:
                pass
            row['speed'] = active.get('a_speed')
            row['eta'] = active.get('a_eta')
            row['progress'] = active.get('a_progress')
        rows.append(row)

    waiting = client_snatches(myDB)
    jobs = _latest_jobs(myDB)
    hashes = [jobs[str(w['issueid'])]['id'] for w in waiting
              if str(w['issueid']) in jobs and jobs[str(w['issueid'])]['client'] not in ('sabnzbd', 'nzbget')]
    live = client_status(hashes) if waiting else {}
    by_name = {}
    for (kind, k), v in live.items():
        if kind in ('sabnzbd', 'nzbget') and v.get('name'):
            by_name.setdefault(_norm_name(v['name']), v)
    names = {}
    try:
        for r in myDB.select('SELECT IssueID, NZBName, AltNZBName FROM nzblog'):
            names[re.sub('^S', '', str(r['IssueID']))] = [r['NZBName'], r['AltNZBName']]
    except Exception:
        pass

    for w in waiting:
        iid = str(w['issueid'])
        job = jobs.get(iid)
        info = None
        if job:
            kind = job['client'] if job['client'] in ('sabnzbd', 'nzbget') else 'torrent'
            info = live.get((kind, job['id'].lower()))
        if info is None:
            for n in names.get(re.sub('^S', '', iid), []) + ([job['name']] if job else []):
                if n and _norm_name(n) in by_name:
                    info = by_name[_norm_name(n)]
                    break
        issue = w['issue']
        title = '%s %s' % (w['series'], ('#%s' % issue) if issue and str(issue)[:1].isdigit() else issue) if issue else w['series']
        client = info['client'] if info else (CLIENT_NAMES.get(job['client'], job['client']) if job else _configured_client(w['provider']))
        rows.append({'key': 'client-%s' % iid, 'kind': 'client', 'queueid': None, 'title': title,
                     'comicid': w['comicid'] if '_' not in iid else None, 'issueid': iid, 'source': client,
                     'via': w['provider'], 'status': info['state'] if info else 'Sent',
                     'percent': info['percent'] if info else None,
                     'size': _human(info['total']) if info and info.get('total') else None,
                     'speed': '%s/s' % _human(info['speed']) if info and info.get('speed') else None,
                     'eta': _eta(info['eta']) if info and info.get('eta') is not None else None,
                     'progress': '%s of %s' % (_human(info['done'] or 0), _human(info['total']))
                                 if info and info.get('total') and info['state'] in ('Downloading', 'Paused') else None,
                     'message': info.get('message') if info else None, 'detail': info.get('name') if info else None,
                     'updated': w['sent']})
    rows.sort(key=lambda r: str(r['updated'] or ''), reverse=True)
    return rows


TORRENT_PROVIDERS = ('32P', 'WWT', 'DEM', 'TPSE', 'PUBLIC TORRENTS')


def _configured_client(provider):
    """Best guess at where a grab went when its job id wasn't recorded (grabs made before this was added)."""
    tor = next((name for flag, name in (('USE_QBITTORRENT', 'qBittorrent'), ('USE_DELUGE', 'Deluge'),
                                        ('USE_TRANSMISSION', 'Transmission'), ('USE_RTORRENT', 'rTorrent'),
                                        ('USE_UTORRENT', 'uTorrent'), ('USE_WATCHDIR', 'Watch folder'))
                if getattr(mylar, flag, False)), None) if getattr(mylar.CONFIG, 'ENABLE_TORRENTS', True) else None
    nzb = next((name for flag, name in (('USE_SABNZBD', 'SABnzbd'), ('USE_NZBGET', 'NZBGet'), ('USE_BLACKHOLE', 'Blackhole folder'))
                if getattr(mylar, flag, False)), None)
    p = str(provider or '').upper()
    try:
        torznabs = [str(x[0]).upper() for x in (mylar.CONFIG.EXTRA_TORZNABS or []) if x and x[0]]
    except Exception:
        torznabs = []
    if any(t in p for t in TORRENT_PROVIDERS) or any(t and t in p for t in torznabs):
        return tor or 'Torrent client'
    if nzb and not tor:
        return nzb
    if tor and not nzb:
        return tor
    return 'Download client'


def _human(n):
    n = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return ('%.0f %s' if unit in ('B', 'KB') else '%.1f %s') % (n, unit)
        n /= 1024.0


def _eta(s):
    s = int(s)
    if s < 90:
        return 'under 2 min left'
    if s < 5400:
        return 'about %d min left' % round(s / 60.0)
    return 'about %.1f h left' % (s / 3600.0)
