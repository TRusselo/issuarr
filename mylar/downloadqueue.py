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
import os
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
    issues = lookup("SELECT IssueID AS id, ComicID, Issue_Number, Status FROM issues WHERE IssueID IN (%s)", issueids)
    annuals = lookup("SELECT IssueID AS id, ComicID, Issue_Number, Status FROM annuals WHERE IssueID IN (%s)", issueids)
    oneoffs = lookup("SELECT IssueID AS id, ComicID, ComicName, IssueNumber AS Issue_Number, Status FROM oneoffhistory WHERE IssueID IN (%s)", issueids)

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
                           'pack':         bool(r['pack']),
                           'issue_status': _field(iss or oneoff, 'Status') if (iss or oneoff) else None,
                           'updated_date': r['updated_date'],
                           'progress':     '100%' if r['status'] == 'Completed' else '',
                           'site':         r['site'] if 'site' in r.keys() else None,
                           'jd2':          bool(r['jd2_job_id']) if 'jd2_job_id' in r.keys() else False,
                           'filename':     r['filename'] if 'filename' in r.keys() else None,
                           'tmp_filename': r['tmp_filename'] if 'tmp_filename' in r.keys() else None,
                           'remote_filesize': r['remote_filesize'] if 'remote_filesize' in r.keys() else None})
    return resultlist


def _field(row, key):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


# ---- filing ---------------------------------------------------------------
# ddl_info says Completed as soon as the file is down; post-processing files it after that.

FILED = ('Downloaded', 'Archived')


def filing_signals(myDB, rows=()):
    """What's known about filing right now, for filing_stage.

    stages: {ddl id: 'waiting'|'filing'}; flagged: the files Needs attention lists; tagged: for
    `rows` whose file is marked for another issue, that issue's (Status, number).
    """
    from mylar import archives, attention
    stages = {}
    try:
        with mylar.PP_QUEUE.mutex:
            queued = [i.get('download_info') for i in mylar.PP_QUEUE.queue if isinstance(i, dict)]
    except Exception:
        queued = []
    for info in queued:
        if isinstance(info, dict) and info.get('provider') in ('DDL', 'JD2') and info.get('id') is not None:
            stages[str(info['id'])] = 'waiting'
    stages.update(dict(archives.DDL_FILING))
    try:
        flagged = attention.shown_paths(myDB)
    except Exception:
        flagged = []
    other = list({_tag_id(r) for r in rows if _tag_id(r) not in (None, str(r.get('issueid')))})
    tagged = {}
    for sql in ("SELECT IssueID, Status, IssueNumber AS Issue_Number FROM oneoffhistory WHERE IssueID IN (%s)",
                "SELECT IssueID, Status, Issue_Number FROM annuals WHERE IssueID IN (%s)",
                "SELECT IssueID, Status, Issue_Number FROM issues WHERE IssueID IN (%s)"):
        for n in range(0, len(other), 500):
            chunk = other[n:n + 500]
            try:
                tagged.update((str(r['IssueID']), (r['Status'], r['Issue_Number']))
                              for r in myDB.select(sql % ','.join('?' * len(chunk)), chunk))
            except Exception:
                pass
    return {'stages': stages, 'flagged': flagged, 'tagged': tagged}


def _tag_id(d):
    """The issue id in the [__id__] mark on a direct download's file name, if it has one."""
    m = re.search(r'\[__(\d+)__\]', str(d.get('filename') or ''))
    return m.group(1) if m else None


def _tag(d):
    """The [__id__] mark a direct download's file and folder carry, which Needs attention paths keep."""
    tid = _tag_id(d) or d.get('issueid')
    return '[__%s__]' % tid if tid is not None else None


def _in_attention(d, flagged):
    """Whether any of this download's files are listed under Needs attention.

    DDL files carry the [__id__] mark; JD2 ones sit in JD2_DEST_DIR under a folder ending ' - <ddl id>'.
    """
    tag = _tag(d)
    jd2 = getattr(mylar.CONFIG, 'JD2_DEST_DIR', None)
    jd2 = os.path.join(os.path.normpath(jd2), '') if jd2 and jd2 != 'None' else None
    folder = ' - %s%s' % (d['queueid'], os.sep)
    for p in flagged:
        if tag and tag in p:
            return True
        if jd2 and p.startswith(jd2) and folder in p:
            return True
    return False


def filing_stage(d, signals):
    """(status, note) for a downloaded direct download.

    Completed only once it's filed: its issue is Downloaded or Archived, or for a pack, its
    post-processing run has ended and none of its files are waiting under Needs attention.
    """
    stage = signals['stages'].get(str(d['queueid']))
    if stage == 'filing':
        return 'Filing', None
    if stage == 'waiting':
        return 'Waiting to file', None
    if not getattr(mylar.CONFIG, 'POST_PROCESSING', True):
        return 'Completed', None
    if not d.get('pack') and d.get('issue_status') in FILED:
        return 'Completed', None
    if _in_attention(d, signals['flagged']):
        return 'Not filed', 'Filing couldn\'t place it. It\'s waiting under Needs attention.'
    if not d.get('pack') and d.get('issue_status'):
        other = signals.get('tagged', {}).get(_tag_id(d) or '')
        if other and other[0] in FILED and _tag_id(d) != str(d.get('issueid')):
            return 'Not filed', 'Filed as a different issue (#%s); this issue is still %s.' % (other[1], d['issue_status'])
        return 'Not filed', 'Filing didn\'t take it, so the issue is still %s. The log has the details.' % d['issue_status']
    return 'Completed', None


def unfiled_ids(myDB):
    """ddl_info ids that say Completed but aren't filed yet, which Clear finished leaves alone."""
    rows = myDB.select("SELECT * FROM ddl_info WHERE status = 'Completed'")
    known = {}
    for table in ('oneoffhistory', 'annuals', 'issues'):
        try:
            known.update((str(r['IssueID']), r['Status']) for r in myDB.select(
                "SELECT IssueID, Status FROM %s WHERE IssueID IN "
                "(SELECT issueid FROM ddl_info WHERE status = 'Completed')" % table))
        except Exception:
            pass
    rows = [{'queueid': r['ID'], 'issueid': r['issueid'], 'pack': bool(_field(r, 'pack')),
             'filename': _field(r, 'filename'), 'issue_status': known.get(str(r['issueid']))} for r in rows]
    signals = filing_signals(myDB, rows)
    out = []
    for d in rows:
        if filing_stage(d, signals)[0] != 'Completed':
            out.append(str(d['queueid']))
    return out


def ddl_progress(row):
    """How far a direct download has got, read from the file it's writing.

    Returns {'done', 'total', 'percent'}, or None until the file exists. Rows saved before
    downloaders recorded full paths hold a bare file name, found in the download folder.
    """
    location = getattr(mylar.CONFIG, 'DDL_LOCATION', None) or ''
    path = _field(row, 'tmp_filename')
    if path and not os.path.isabs(path):
        path = os.path.join(location, path)
    if not path and _field(row, 'filename'):
        path = os.path.join(location, _field(row, 'filename'))
    if not path:
        return None
    try:
        done = os.stat(path).st_size
    except OSError:
        return None
    try:
        total = int(_field(row, 'remote_filesize') or 0)
    except (TypeError, ValueError):
        total = 0
    if (not total or done > total * 1.02) and _field(row, 'size'):
        try:
            total = int(helpers.human2bytes(re.sub('/s', '', str(_field(row, 'size'))[:-1]).strip()))
        except Exception:
            total = 0
    if not total:
        return {'done': done, 'total': None, 'percent': None}
    return {'done': done, 'total': total, 'percent': min(100, int(done * 100 / total))}


_DL_SAMPLE = {}


def download_rate(did, done, total):
    """Progress text, speed and time left for one download, smoothed between polls."""
    did = str(did)
    now = time.time()
    for k in [k for k, v in _DL_SAMPLE.items() if now - v[1] > 3600]:
        _DL_SAMPLE.pop(k, None)
    prev = _DL_SAMPLE.get(did)
    speed = prev[2] if prev else None
    if prev and done >= prev[0] and now - prev[1] >= 2:
        inst = (done - prev[0]) / (now - prev[1])
        speed = inst if speed is None else speed * 0.6 + inst * 0.4
        _DL_SAMPLE[did] = (done, now, speed)
    elif not prev or done < prev[0]:
        _DL_SAMPLE[did] = (done, now, None)
    out = {'a_progress': '%s of %s' % (_human(done), _human(total))}
    if speed:
        out['a_speed'] = '%s/s' % _human(speed)
        left = max(total - done, 0) / speed
        if left < 90:
            out['a_eta'] = 'under 2 min left'
        elif left < 5400:
            out['a_eta'] = 'about %d min left' % round(left / 60)
        else:
            out['a_eta'] = 'about %.1f h left' % (left / 3600)
    return out


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
# GetComics links that point at a cloud host rather than GetComics' own server
CLOUD_LINKS = ('GC-Mega', 'GC-Media', 'GC-Pixel')

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

def builtin_source(d):
    """Who fetches a direct download that Issuarr runs itself: GetComics' server, or Issuarr from a cloud host."""
    if 'GetComics' not in str(d['site'] or 'GetComics'):
        return 'Direct download'
    return 'Issuarr' if d['linktype'] in CLOUD_LINKS else 'GetComics'


def ddl_source(d, at_jd2=()):
    """(source, via) for a direct download's Source cell.

    JD2 gets every mirror on the post and picks one itself, so its rows name the first choice
    without promising it. A row counts as JD2's once it's in the JD2 queue, before JD2 gives it a job id.
    """
    if d['jd2'] or str(d['queueid']) in at_jd2:
        host = HOSTS[d['linktype']] if d['linktype'] in CLOUD_LINKS else None
        return 'JDownloader 2', ('%s or another mirror' % host if host else 'Any mirror')
    return builtin_source(d), HOSTS.get(d['linktype'], d['linktype'])


def build(myDB, active=None, rate=None):
    """One list of every download: direct ones and the ones at a download client.

    `active` is one DDL item's progress from check_ActiveDDL ({'a_id', 'percent', ...}); every other
    direct download that's running gets its progress from its file, and `rate(id, done, total)`,
    when given, adds speed and time left.
    """
    from mylar.queues import jd2
    at_jd2 = jd2.at_jd2()
    rows = []
    ddl_rows = ddl_queue_rows(myDB)
    downloaded = [d for d in ddl_rows if d['status'] == 'Completed']
    signals = filing_signals(myDB, downloaded) if downloaded else None
    for d in ddl_rows:
        status = d['status'] or 'Queued'
        source, via = ddl_source(d, at_jd2)
        note = None
        if status == 'Completed':
            status, note = filing_stage(d, signals)
        row = {'key': 'ddl-%s' % d['queueid'], 'kind': 'ddl', 'queueid': d['queueid'], 'title': d['series'],
               'comicid': d['comicid'], 'issueid': d['issueid'], 'via': via, 'source': source,
               'status': status, 'percent': 100 if d['status'] == 'Completed' else None, 'size': d['size'] or None,
               'speed': None, 'eta': None, 'progress': None, 'message': note, 'detail': None,
               'updated': d['updated_date']}
        if active and status == 'Downloading' and str(active.get('a_id')) == str(d['queueid']):
            try:
                row['percent'] = int(str(active.get('percent', '')).rstrip('%'))
            except ValueError:
                pass
            row['speed'] = active.get('a_speed')
            row['eta'] = active.get('a_eta')
            row['progress'] = active.get('a_progress')
        elif status == 'Downloading':
            p = ddl_progress(d)
            if p and p['percent'] is not None:
                row['percent'] = p['percent']
                if rate:
                    r = rate(d['queueid'], p['done'], p['total'])
                    row['speed'], row['eta'], row['progress'] = r.get('a_speed'), r.get('a_eta'), r.get('a_progress')
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


# ---- back to Wanted -------------------------------------------------------
# A grab marks its issues Snatched. When the download is removed or stopped before it finished,
# or was lost (a restart while it waited to be filed, old JD2 grabs), nothing changes them again.

# How long a Snatched issue with nothing downloading it is given before stuck_snatched lists it.
STUCK_HOURS = 6
SETTLED = ('Completed', 'Failed')   # every other ddl_info status is still on its way


def unsnatch(myDB, issueids):
    """Put issues that are still Snatched back to Wanted, so they're searched again. Anything
    else (Downloaded, Archived, Failed, already Wanted) is left as it is. Returns the ids changed."""
    changed = []
    for iid in dict.fromkeys(str(i) for i in issueids if i not in (None, '', 'None')):
        if iid.startswith('S'):   # a story-arc issue, as nzblog keeps it
            targets = [('storyarcs', 'IssueArcID', iid[1:])]
        else:
            targets = [('issues', 'IssueID', iid), ('annuals', 'IssueID', iid), ('storyarcs', 'IssueID', iid)]
        hit = False
        for table, key, value in targets:
            try:
                cur = myDB.action("UPDATE %s SET Status='Wanted' WHERE %s=? AND Status='Snatched'" % (table, key), [value])
            except Exception:
                continue   # no annuals or story arcs table yet
            if cur is not None and cur.rowcount:
                hit = True
        if hit:
            changed.append(iid)
    return changed


def grabbed_ids(myDB, row):
    """The issues a direct download marked Snatched: its own, and for a pack every issue it took.

    The pack's issues are known in memory while it's queued (PACK_ISSUEIDS_DONT_QUEUE) and, across
    restarts, from nzblog, which records the ddl_info id against each issue the grab snatched.
    """
    rid = str(_field(row, 'id'))
    ids = [str(row['issueid'])] if row['issueid'] not in (None, '', 'None') else []
    if _field(row, 'pack'):
        ids += [str(i) for i, p in dict(mylar.PACK_ISSUEIDS_DONT_QUEUE).items() if str(p) == rid]
        try:
            ids += [str(r['IssueID']) for r in myDB.select(
                "SELECT IssueID FROM nzblog WHERE ID=? AND PROVIDER LIKE 'DDL%'", [rid])]
        except Exception:
            pass
    return list(dict.fromkeys(ids))


def release(myDB, rows):
    """Direct downloads the owner removed or stopped before they finished: their issues that are
    still Snatched go back to Wanted. Finished downloads are left alone."""
    changed = []
    for row in rows:
        if row is None or row['status'] == 'Completed':
            continue
        rid = str(_field(row, 'id'))
        ids = grabbed_ids(myDB, row)
        # the download thread would otherwise mark the pack's issues Skipped when it drops the item
        for i, p in dict(mylar.PACK_ISSUEIDS_DONT_QUEUE).items():
            if str(p) == rid:
                mylar.PACK_ISSUEIDS_DONT_QUEUE.pop(i, None)
        done = unsnatch(myDB, ids)
        if done:
            logger.info('[DDL-REMOVE] %s %s back to Wanted: %s was removed before it finished.'
                        % (len(done), 'issue is' if len(done) == 1 else 'issues are', row['series'] or rid))
        changed += done
    return changed


def _left_on_disk(rid, row, names, jd2_dirs):
    """Whether a finished direct download's file or folder is still where it was downloaded to."""
    tags = {'[__%s__]' % t for t in (_tag_id({'filename': _field(row, 'filename')}), row['issueid']) if t not in (None, '', 'None')}
    for name in (_field(row, 'filename'), _field(row, 'tmp_filename')):
        if name and (name in names or os.path.splitext(name)[0] in names):
            return True
    if any(t in n for t in tags for n in names):
        return True
    return any(d.endswith(' - %s' % rid) for d in jd2_dirs)


def _listing(path):
    if not path or path == 'None':
        return set()
    try:
        return set(os.listdir(path))
    except OSError:
        return set()


def stuck_snatched(myDB, hours=STUCK_HOURS, now=None):
    """Issues marked Snatched by a direct download more than `hours` ago that nothing is getting.

    Left out: anything a ddl_info row is still downloading or queueing, held by JDownloader 2,
    waiting for or being filed, a grab with a download-client job, a finished download whose file
    is still in the download folder (it can be filed again) or that is waiting in Needs attention,
    and grabs sent to SABnzbd, NZBGet or a torrent client, which can't be seen from here.
    """
    from mylar import archives, attention
    from mylar.queues import ddl, jd2
    now = now or datetime.datetime.now()
    cutoff = (now - datetime.timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')

    snatched = {}
    for sql in ("SELECT IssueID, ComicID, ComicName, Issue_Number FROM issues WHERE Status='Snatched'",
                "SELECT IssueID, ComicID, ReleaseComicName AS ComicName, Issue_Number FROM annuals "
                "WHERE Status='Snatched' AND NOT Deleted"):
        try:
            for r in myDB.select(sql):
                snatched.setdefault(str(r['IssueID']), r)
        except Exception:
            continue
    if not snatched:
        return []

    last = {}
    for r in myDB.select("SELECT IssueID, Provider, DateAdded FROM snatched WHERE Status='Snatched'"):
        iid = str(r['IssueID'])
        if iid in snatched and (r['DateAdded'] or '') >= (last.get(iid, {}).get('at') or ''):
            last[iid] = {'at': r['DateAdded'] or '', 'provider': r['Provider'] or ''}

    rows = {str(r['ID']): r for r in myDB.select('SELECT * FROM ddl_info')}
    linked = {}
    for r in rows.values():
        if r['issueid'] is not None:
            linked.setdefault(str(r['issueid']), set()).add(str(r['ID']))
    try:
        for r in myDB.select("SELECT IssueID, ID FROM nzblog WHERE PROVIDER LIKE 'DDL%'"):
            if r['ID'] is not None:
                linked.setdefault(str(r['IssueID']), set()).add(str(r['ID']))
    except Exception:
        pass
    for i, p in dict(mylar.PACK_ISSUEIDS_DONT_QUEUE).items():
        linked.setdefault(str(i), set()).add(str(p))
    try:
        jobs = {str(r['IssueID']) for r in myDB.select('SELECT IssueID FROM client_jobs') if r['IssueID'] is not None}
    except Exception:
        jobs = set()

    busy = ddl.waiting_ids() | jd2.at_jd2() | {str(i) for i in mylar.DDL_QUEUED} | set(archives.DDL_FILING)
    try:
        flagged = attention.shown_paths(myDB)
    except Exception:
        flagged = []
    names = _listing(getattr(mylar.CONFIG, 'DDL_LOCATION', None))
    jd2_dirs = _listing(getattr(mylar.CONFIG, 'JD2_DEST_DIR', None))

    out = []
    for iid, r in snatched.items():
        grab = last.get(iid)
        if grab is None or not grab['provider'].upper().startswith('DDL') or grab['at'] > cutoff:
            continue
        if iid in jobs or archives.holds(r['ComicID'], iid):
            continue
        if any('[__%s__]' % iid in p for p in flagged):
            continue
        hold = False
        for rid in linked.get(iid, ()):
            row = rows.get(rid)
            if rid in busy or (row is not None and row['status'] not in SETTLED):
                hold = True
            elif row is not None and row['status'] == 'Completed' and _left_on_disk(rid, row, names, jd2_dirs):
                hold = True
            elif row is not None and _in_attention({'filename': _field(row, 'filename'), 'issueid': row['issueid'],
                                                    'queueid': rid}, flagged):
                hold = True
            if hold:
                break
        if hold:
            continue
        out.append({'issueid': iid, 'comicid': r['ComicID'], 'series': r['ComicName'], 'issue': r['Issue_Number'],
                    'snatched': grab['at']})
    out.sort(key=lambda x: (str(x['series'] or '').lower(), _issue_key(x['issue'])))
    return out


def _issue_key(n):
    m = re.match(r'-?\d+(?:\.\d+)?', str(n or ''))
    return (0, float(m.group(0)), str(n)) if m else (1, 0.0, str(n or ''))
