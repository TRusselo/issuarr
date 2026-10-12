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

"""The way from Wanted into the library, for the flow line on Wanted and Downloads > Queue.

An issue goes Wanted -> searched -> downloading -> filed. Each step keeps its own state
(the search queue, ddl_info, the download clients, post-processing); flow() puts them side
by side, says what happened to each issue lately, and why a step is idle when it is.
"""

import collections
import datetime
import threading
import time

import mylar
from mylar import archives, db, downloadqueue, helpers, logger

# How searches from the search queue ended. Kept in memory: a restart starts it empty.
RECENT = collections.deque(maxlen=60)
_LOCK = threading.Lock()


def _stamp(text):
    """'2026-10-11 16:31:39' or '2026-10-11 16:31' (local time) -> epoch seconds."""
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return time.mktime(datetime.datetime.strptime(str(text)[:19], fmt).timetuple())
        except (TypeError, ValueError):
            continue
    return None


def _name(item):
    return {'issueid': None if item.get('issueid') is None else str(item.get('issueid')),
            'comicid': item.get('comicid'), 'name': item.get('comicname'), 'number': item.get('issuenumber')}


def searched(item, started, on_disk=False):
    """Note how one search-queue item ended: sent to download, already on disk, or nothing found.

    A search that finds something marks the issue Snatched and writes a snatched row at send
    time, so a snatched row newer than the start of the search means it was found.
    """
    entry = dict(_name(item), at=time.time(), took=round(time.time() - started), outcome='none', provider=None)
    if on_disk:
        entry['outcome'] = 'on_disk'
    else:
        try:
            iid = entry['issueid']
            since = datetime.datetime.fromtimestamp(started).strftime('%Y-%m-%d %H:%M:%S')
            row = db.DBConnection().selectone(
                "SELECT Provider FROM snatched WHERE IssueID IN (?, ?) AND Status='Snatched' AND DateAdded >= ? "
                "ORDER BY DateAdded DESC", [iid, 'S%s' % iid, since]).fetchone()
            if row is not None:
                entry.update(outcome='found', provider=row['Provider'])
        except Exception as e:
            logger.fdebug('[ACTIVITY] Could not tell how the search for %s ended: %s' % (entry['issueid'], e))
    with _LOCK:
        RECENT.appendleft(entry)


def _wanted(myDB):
    """Wanted issues, as the Wanted page counts them: how many are Tier 1 and how many aren't out yet."""
    out = {'count': 0, 'tier1': 0, 'soon': 0, 'next_out': None}
    tier_date = helpers.search_tier_date()
    seen = set()
    queries = ["SELECT IssueID, DateAdded, ReleaseDate, DigitalDate FROM issues WHERE Status='Wanted'"]
    if mylar.CONFIG.ANNUALS_ON:
        queries.append("SELECT IssueID, DateAdded, ReleaseDate, DigitalDate FROM annuals WHERE NOT Deleted AND Status='Wanted'")
    if mylar.CONFIG.UPCOMING_STORYARCS:
        queries.append("SELECT IssueID, DateAdded, ReleaseDate, DigitalDate FROM storyarcs WHERE Status='Wanted'")
    for q in queries:
        try:
            rows = myDB.select(q)
        except Exception:
            continue
        for r in rows:
            if r['IssueID'] in seen:
                continue
            seen.add(r['IssueID'])
            out['count'] += 1
            tier, since = helpers.search_tier(r['DateAdded'], r['ReleaseDate'], r['DigitalDate'], tier_date)
            if tier == 'soon':
                out['soon'] += 1
                if not out['next_out'] or since < out['next_out']:
                    out['next_out'] = since
            elif tier == 1:
                out['tier1'] += 1
    return out


def _search(issues):
    from mylar import search
    from mylar.queues import search as search_worker
    st = search.search_status()
    current, waiting = st['current'], st['waiting']
    blocked = None
    if not current and waiting:
        if st['busy']:
            blocked = 'rss'
        elif search_worker.HELD and len(search_worker.HELD) >= len(waiting):
            blocked = 'filing'   # everything waiting is a series being filed
    try:
        job = mylar.SCHED.get_job('search')
        nxt = job.next_run_time.timestamp() if job and job.next_run_time else None
    except Exception:
        nxt = None
    if current and current.get('issueid') is not None:
        issues.setdefault(str(current['issueid']), {'stage': 'search', 'state': 'searching'})
    for n, w in enumerate(waiting):
        if w.get('issueid') is not None:
            issues.setdefault(str(w['issueid']), {'stage': 'search', 'state': 'waiting', 'place': n + 1})
    return {'current': current, 'waiting': len(waiting), 'next': [w for w in waiting[:3]],
            'busy': st['busy'], 'blocked': blocked, 'next_run': nxt}


def _ddl(rows, issues):
    """What the direct-download rows are doing: (running now, queued and not at JD2, incomplete)."""
    from mylar.queues import jd2
    at_jd2 = jd2.at_jd2()
    now, queued, held = [], 0, 0
    for d in rows:
        status = d['status'] or 'Queued'
        iid = None if d['issueid'] is None else str(d['issueid'])
        if status == 'Downloading':
            p = downloadqueue.ddl_progress(d)
            pct = p['percent'] if p else None
            now.append({'title': d['series'], 'percent': pct, 'issueid': iid, 'comicid': d['comicid'], 'via': 'GetComics'})
            if iid:
                issues[iid] = {'stage': 'download', 'state': 'downloading', 'percent': pct}
        elif status == 'Queued':
            # JD2's rows stay Queued while it works on them, so only rows it doesn't hold are waiting
            if str(d['queueid']) in at_jd2:
                now.append({'title': d['series'], 'percent': None, 'issueid': iid, 'comicid': d['comicid'], 'via': 'JDownloader 2'})
                if iid:
                    issues[iid] = {'stage': 'download', 'state': 'jd2'}
            else:
                queued += 1
                if iid:
                    issues[iid] = {'stage': 'download', 'state': 'queued'}
        elif status == 'Incomplete':
            held += 1
    return now, queued, held


def _stalled(now, queued):
    """Queued direct downloads that nothing is working on or about to pick up.

    Work at JD2 doesn't count as moving: it never picks up these rows, and a job it can't finish
    can sit there for hours.
    """
    from mylar.queues import ddl
    try:
        moving = ddl.waiting_count()
    except Exception:
        moving = 0
    busy = any(n['via'] != 'JDownloader 2' for n in now)
    return bool(queued) and not busy and not moving


def stalled_downloads(myDB):
    """How many direct downloads look stalled, or 0 when they aren't. Same rule as the flow line."""
    now, queued, _ = _ddl(downloadqueue.ddl_queue_rows(myDB), {})
    return queued if _stalled(now, queued) else 0


def _downloads(myDB, issues):
    now, queued, held = _ddl(downloadqueue.ddl_queue_rows(myDB), issues)
    sent = downloadqueue.client_snatches(myDB)
    for w in sent:
        issues.setdefault(str(w['issueid']), {'stage': 'download', 'state': 'client'})
    return {'now': now, 'queued': queued, 'client': len(sent), 'incomplete': held, 'stalled': _stalled(now, queued)}


def _filing():
    snap = archives.snapshot()
    try:
        queued = mylar.PP_QUEUE.qsize()
    except Exception:
        queued = 0
    return {'working': snap.get('state') == 'Working' or archives.processing(), 'detail': snap.get('detail') or '',
            'queued': queued, 'last': snap.get('last') or '', 'last_at': snap.get('last_at')}


def _events(myDB, limit):
    """What happened lately, newest first: grabs, filed issues, failed downloads and empty searches."""
    events = []
    since = (datetime.datetime.now() - datetime.timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
    try:
        rows = myDB.select("SELECT IssueID, ComicID, ComicName, Issue_Number, Provider, Status, DateAdded FROM snatched "
                           "WHERE DateAdded >= ? AND Status IN ('Snatched', 'Post-Processed', 'Downloaded') "
                           "ORDER BY DateAdded DESC LIMIT ?", [since, 400])  # enough for a whole pack to group
    except Exception:
        rows = []
    for r in rows:
        events.append({'kind': 'found' if r['Status'] == 'Snatched' else 'filed', 'at': _stamp(r['DateAdded']),
                       'issueid': r['IssueID'], 'comicid': r['ComicID'], 'name': r['ComicName'],
                       'number': r['Issue_Number'], 'provider': r['Provider']})
    try:
        failed = myDB.select("SELECT issueid, comicid, series, updated_date FROM ddl_info WHERE status='Failed' "
                             "AND updated_date >= ? ORDER BY updated_date DESC LIMIT ?", [since[:16], limit])
    except Exception:
        failed = []
    for r in failed:
        events.append({'kind': 'failed', 'at': _stamp(r['updated_date']), 'issueid': r['issueid'],
                       'comicid': r['comicid'], 'name': r['series'], 'number': None, 'provider': None})
    with _LOCK:
        recent = list(RECENT)
    for s in recent:
        if s['outcome'] != 'found':
            events.append({'kind': 'nothing' if s['outcome'] == 'none' else 'on_disk', 'at': s['at'], 'issueid': s['issueid'],
                           'comicid': s['comicid'], 'name': s['name'], 'number': s['number'], 'provider': None})
    events = [e for e in events if e['at']]
    events.sort(key=lambda e: e['at'], reverse=True)
    return _grouped(events)[:limit], recent


def _grouped(events, window=120):
    """One line for a pack: the same thing happening to one series' issues within a couple of minutes."""
    out = []
    for e in events:
        prev = out[-1] if out else None
        if (prev and e['comicid'] and prev['comicid'] == e['comicid'] and prev['kind'] == e['kind']
                and prev['first_at'] - e['at'] <= window):
            prev['count'] += 1
            prev['first_at'] = e['at']
            continue
        out.append(dict(e, count=1, first_at=e['at']))
    for e in out:
        e.pop('first_at')
        if e['count'] > 1:
            e['number'] = None
    return out


def flow(events=8):
    """Every step from Wanted to the library, plus where each issue in flight is."""
    myDB = db.DBConnection()
    issues = {}
    out = {'search': _search(issues)}
    try:
        out['download'] = _downloads(myDB, issues)
    except Exception as e:
        logger.fdebug('[ACTIVITY] Could not read the download queue: %s' % e)
        out['download'] = {'now': [], 'queued': 0, 'client': 0, 'incomplete': 0, 'stalled': False}
    out['filing'] = _filing()
    out['wanted'] = _wanted(myDB)
    today = datetime.datetime.now().strftime('%Y-%m-%d 00:00:00')
    try:
        out['added_today'] = myDB.selectone("SELECT count(DISTINCT IssueID) AS n FROM snatched WHERE DateAdded >= ? "
                                            "AND Status IN ('Post-Processed', 'Downloaded')", [today]).fetchone()['n']
    except Exception:
        out['added_today'] = 0
    out['events'], recent = _events(myDB, events)
    # the last search of a Wanted issue that found nothing, so its row can say so
    for s in recent:
        if s['issueid'] and s['issueid'] not in issues and s['outcome'] == 'none':
            issues[s['issueid']] = {'stage': 'wanted', 'state': 'nothing', 'at': s['at']}
    out['issues'] = issues
    out['now'] = time.time()
    return out
