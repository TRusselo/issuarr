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

"""Files that need a decision, for Downloads > Needs attention.

Two kinds of file land here: ones filing looked at and couldn't place (recorded with the
reason, while filing still knows it), and every comic in the review folder, where filing
moves issues nothing on the watchlist claimed. A recorded file keeps its reason when it's
moved to review.

From the page a file can be filed as an issue the user picks, which skips the matching that
turned it down; moved to trash, a folder beside the review folder that empties itself after
ATTENTION_TRASH_DAYS; or ignored, which hides it until it moves or changes.
"""

import datetime
import collections
import difflib
import hashlib
import os
import queue
import re
import shutil
import threading
import time

import mylar
from mylar import db, logger

COMIC_EXT = ('.cbz', '.cbr', '.cb7', '.pdf')
# Most telling first: a file that failed on volume for one series and on name for the rest
# failed on volume.
REASONS = ('damaged', 'cover', 'owned', 'volume', 'year', 'issue', 'series', 'unclaimed')
CACHE_SECONDS = 60
_COUNT = [0.0, 0]          # (counted at, count) for the nav badge
_COMICS = [0.0, []]        # (loaded at, watchlist rows) for suggestions
_NAMED = {}                # (series name, comicid, watchlist load time) -> close watchlist names
JOBS = {}                  # path -> {'state': 'waiting'|'filing'|'filed'|'failed', 'note': str}
_LOCK = threading.Lock()
_SUGGESTED = {}            # (path, modified, comicid, watchlist load time) -> (parsed, matches)
SUGGEST_SECONDS = 600
# "Try filing again": filing's own matching, run again over every folder holding a file listed here.
REFILE = {'state': 'idle'}
_REFILE_LOCK = threading.Lock()
REFILE_WAIT = 10           # seconds between looks at the post-processing queue, which goes first
AFTER_UPDATE_DELAY = 300   # after a restart onto a new version, let downloads settle before trying again


def ensure(myDB=None):
    myDB = myDB or db.DBConnection()
    myDB.action(
        'CREATE TABLE IF NOT EXISTS attention (path TEXT PRIMARY KEY, reason TEXT, detail TEXT, comicid TEXT, '
        'status TEXT, added TEXT, size INTEGER)')
    # pick: "comicid|issueid" the user chose with File as, kept (status 'queued') until it's filed,
    # so a restart doesn't lose it
    if 'pick' not in [r[1] for r in myDB.select('PRAGMA table_info(attention)')]:
        myDB.action('ALTER TABLE attention ADD COLUMN pick TEXT')


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def pick(reasons):
    for r in REASONS:
        if r in (reasons or ()):
            return r
    return 'series'


def record(path, reason, detail='', comicid=None):
    """Note a file filing couldn't place. An ignored file stays ignored unless it changed."""
    try:
        myDB = db.DBConnection()
        ensure(myDB)
        row = myDB.selectone('SELECT status, size FROM attention WHERE path=?', [path]).fetchone()
        size = _size(path)
        if row and row['status'] == 'queued':
            status = 'queued'   # the user's File as is still to run
        else:
            status = 'ignored' if row and row['status'] == 'ignored' and row['size'] == size else 'open'
        myDB.upsert('attention', {'reason': reason, 'detail': detail or '', 'comicid': comicid, 'status': status,
                                  'added': _now(), 'size': size}, {'path': path})
        _COUNT[0] = 0
    except Exception as e:
        logger.warn('[ATTENTION] Could not note %s: %s' % (path, e))


def moved(old, new):
    try:
        myDB = db.DBConnection()
        ensure(myDB)
        myDB.action('DELETE FROM attention WHERE path=?', [new])
        myDB.action('UPDATE attention SET path=? WHERE path=?', [new, old])
    except Exception as e:
        logger.fdebug('[ATTENTION] Could not follow %s to %s: %s' % (old, new, e))


def forget(path):
    try:
        myDB = db.DBConnection()
        ensure(myDB)
        myDB.action('DELETE FROM attention WHERE path=?', [path])
        _COUNT[0] = 0
    except Exception as e:
        logger.fdebug('[ATTENTION] Could not forget %s: %s' % (path, e))


def ignore(path):
    myDB = db.DBConnection()
    ensure(myDB)
    if myDB.selectone('SELECT path FROM attention WHERE path=?', [path]).fetchone() is None:
        myDB.upsert('attention', {'reason': 'unclaimed', 'detail': '', 'status': 'ignored', 'added': _now(),
                                  'size': _size(path)}, {'path': path})
    else:
        myDB.upsert('attention', {'status': 'ignored', 'size': _size(path)}, {'path': path})
    _COUNT[0] = 0


def review_dir():
    from mylar import archives
    return archives.review_dir()


def trash_dir():
    return os.path.join(os.path.dirname(os.path.normpath(review_dir())), 'mylar-trash')


def trash_days():
    try:
        return max(1, int(getattr(mylar.CONFIG, 'ATTENTION_TRASH_DAYS', None) or 14))
    except (TypeError, ValueError):
        return 14


def review_files():
    root = review_dir()
    out = []
    if not root or not os.path.isdir(root):
        return out
    for r, dirs, names in os.walk(root):
        for n in names:
            if n.lower().endswith(COMIC_EXT) and not n.startswith('.'):
                out.append(os.path.join(r, n))
    return out


def _rows(myDB):
    ensure(myDB)
    return {r['path']: dict(r) for r in myDB.select('SELECT * FROM attention')}


def _shown(p, r):
    """Whether Needs attention lists this row's file: it's still there and not ignored, or changed since."""
    return os.path.isfile(p) and (r['status'] != 'ignored' or r['size'] != _size(p))


def _open_paths(myDB):
    rows = _rows(myDB)
    paths = {}
    for p, r in rows.items():
        if _shown(p, r):
            paths[p] = r
        elif not os.path.isfile(p):
            myDB.action('DELETE FROM attention WHERE path=?', [p])   # filed, moved or deleted since
    for p in review_files():
        if p not in rows:
            paths[p] = {'path': p, 'reason': 'unclaimed', 'detail': '', 'comicid': None, 'status': 'open', 'added': None}
    return paths


def shown_paths(myDB):
    """The files Needs attention lists, without tidying away rows whose file has gone (the page does that)."""
    rows = _rows(myDB)
    paths = [p for p, r in rows.items() if _shown(p, r)]
    try:
        paths += [p for p in review_files() if p not in rows]
    except Exception:
        pass
    return paths


def count():
    """Files waiting for a decision, for the nav badge. Cached for a minute."""
    if time.time() - _COUNT[0] < CACHE_SECONDS:
        return _COUNT[1]
    try:
        n = len(_open_paths(db.DBConnection()))
    except Exception as e:
        logger.fdebug('[ATTENTION] Could not count: %s' % e)
        n = 0
    _COUNT[:] = [time.time(), n]
    return n


def _norm(name):
    name = re.sub(r'\b(the|and|a|an|of)\b', ' ', str(name or '').lower())
    return re.sub(r'[^a-z0-9]+', ' ', name).strip()


def _watchlist():
    if time.time() - _COMICS[0] < 300 and _COMICS[1]:
        return _COMICS[1]
    rows = db.DBConnection().select('SELECT ComicID, ComicName, ComicYear, ComicVersion, Total FROM comics WHERE ComicName IS NOT NULL')
    rows = [dict(r, norm=_norm(r['ComicName'])) for r in rows]
    for r in rows:
        r['chars'] = collections.Counter(r['norm'])
    _COMICS[:] = [time.time(), rows]
    _NAMED.clear()
    return _COMICS[1]


def parse(path):
    """What the file name says: series, issue, year and volume, as filing reads them."""
    from mylar import filechecker
    name = os.path.basename(path)
    out = {'series': None, 'issue': None, 'year': None, 'volume': None}
    try:
        p = filechecker.FileChecker(file=name).listFiles()
    except Exception as e:
        logger.fdebug('[ATTENTION] Could not read the name %s: %s' % (name, e))
        return out
    if not isinstance(p, dict) or p.get('parse_status') != 'success':
        return out
    out.update(series=p.get('series_name'), issue=p.get('issue_number'), year=p.get('issue_year'), volume=p.get('series_volume'))
    return out


def _num(v):
    from mylar import helpers
    try:
        return helpers.issue_number_parser(str(v)).asInt
    except Exception:
        return None


def _vol(v):
    digits = re.sub(r'[^0-9]', '', str(v or ''))
    return int(digits) if digits and len(digits) < 4 else None


def _named(want, comicid=None, floor=0.75):
    """Watchlist series whose name scores at least floor against want, best first. A name can
    only reach the floor if the lengths and the letters the two share allow it, so those cheap
    bounds (the ones SequenceMatcher's quick ratios use) skip most of a large watchlist before
    the full comparison. Remembered per name until the watchlist is reloaded: a pack's leftovers
    share one series name."""
    comics = _watchlist()
    key = (want, str(comicid or ''), _COMICS[0])
    if key in _NAMED:
        return _NAMED[key]
    named = []
    have = collections.Counter(want)
    total = len(want)
    for c in comics:
        if comicid and str(c['ComicID']) == str(comicid):
            named.append((1.0, c))
            continue
        both = total + len(c['norm'])
        if not both or 2.0 * min(total, len(c['norm'])) / both < floor:
            continue
        if 2.0 * sum((have & c['chars']).values()) / both < floor:
            continue
        s = difflib.SequenceMatcher(None, want, c['norm']).ratio()
        if s >= floor:
            named.append((s, c))
    named.sort(key=lambda x: -x[0])
    if len(_NAMED) > 2000:
        _NAMED.clear()
    _NAMED[key] = named
    return named


def suggest(parsed, limit=3, comicid=None):
    """Watchlist series closest to what the file name says, each with the issue it would be
    and which parts of the name agree. Series with the same name are told apart by whether
    the issue is on them and its year and volume agree."""
    want = _norm(parsed.get('series'))
    if not want and not comicid:
        return []
    named = _named(want, comicid)
    myDB = db.DBConnection()
    target = _num(parsed.get('issue')) if parsed.get('issue') else None
    fyear = str(parsed.get('year') or '')
    out = []
    for s, c in named[:10]:
        issue = None
        if target is not None:
            for r in myDB.select('SELECT IssueID, Issue_Number, Status, IssueDate, ReleaseDate FROM issues WHERE ComicID=?', [c['ComicID']]):
                if _num(r['Issue_Number']) == target:
                    issue = dict(r)
                    break
        iyear = str((issue or {}).get('IssueDate') or (issue or {}).get('ReleaseDate') or '')[:4]
        fvol, svol = _vol(parsed.get('volume')), _vol(c.get('ComicVersion'))
        agree = {
            'series': s >= 0.92,
            'issue': issue is not None,
            'year': fyear == iyear if fyear.isdigit() and iyear.isdigit() else None,
            'volume': None if fvol is None else (fvol == svol or (svol is None and fvol == 1)),
        }
        near = fyear.isdigit() and iyear.isdigit() and abs(int(fyear) - int(iyear)) <= 1   # cover dates run ahead
        rank = s + (0.3 if agree['issue'] else 0) + (0.2 if agree['year'] else 0.1 if near else -0.2 if agree['year'] is False else 0) + \
            {True: 0.1, False: -0.1, None: 0}[agree['volume']]
        out.append({'comicid': c['ComicID'], 'name': c['ComicName'], 'year': c['ComicYear'], 'volume': c['ComicVersion'],
                     'total': c['Total'], 'score': round(s, 2), 'rank': round(rank, 2), 'agree': agree,
                     'issueid': (issue or {}).get('IssueID'), 'number': (issue or {}).get('Issue_Number'),
                     'status': (issue or {}).get('Status'), 'issue_year': iyear or None})
    out.sort(key=lambda m: -m['rank'])
    return out[:limit]


def items():
    """Every file waiting for a decision, newest first, with how its name reads and the
    closest watchlist matches."""
    purge_trash()
    myDB = db.DBConnection()
    review = os.path.normpath(review_dir() or '')
    out = []
    stamp = _COMICS[0]
    for path, row in _open_paths(myDB).items():
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        library = in_library(path)
        key = (path, mtime, row.get('comicid'), stamp)
        hit = _SUGGESTED.get(key)
        if hit is None or time.time() - hit[2] > SUGGEST_SECONDS:
            parsed = parse(path)
            hit = (parsed, [] if library else suggest(parsed, comicid=row.get('comicid')), time.time())
            _SUGGESTED[key] = hit
        parsed, matches = hit[0], hit[1]
        job = JOBS.get(path)
        if job is None and row.get('status') == 'queued':
            job = {'state': 'waiting', 'note': 'Waiting to file'}
        out.append({'path': path, 'name': os.path.basename(path), 'folder': os.path.dirname(path), 'group': group_of(path)[0],
                    'in_review': bool(review) and os.path.normpath(path).startswith(review + os.sep),
                    'in_library': library,
                    'reason': row.get('reason') or 'unclaimed', 'detail': row.get('detail') or '',
                    'size': _size(path), 'modified': mtime, 'parsed': parsed,
                    'matches': matches, 'job': job})
    out.sort(key=lambda i: -i['modified'])
    _COUNT[:] = [time.time(), len(out)]
    live = {(i['path']) for i in out}
    for k in [k for k in _SUGGESTED if k[0] not in live]:
        del _SUGGESTED[k]
    return out


def status():
    """What's changing on the page: file jobs and the Try filing again run. Cheap, for polling."""
    with _REFILE_LOCK:
        refile = {k: v for k, v in REFILE.items() if k not in ('folders', 'stop')}
        refile['stopping'] = bool(REFILE.get('stop'))
    return {'jobs': dict(JOBS), 'refile': refile, 'count': count()}


def search(text, limit=12):
    """Watchlist series for the manual pick."""
    want = _norm(text)
    if not want:
        return []
    hits = []
    for c in _watchlist():
        n = c['norm']
        s = 3.0 if n == want else 2.0 if n.startswith(want) else 1.0 if want in n else difflib.SequenceMatcher(None, want, n).ratio()
        if s >= 0.5:
            hits.append((s, c))
    hits.sort(key=lambda x: (-x[0], x[1]['ComicName']))
    hits.sort(key=lambda x: (-x[0], x[1]['ComicName'], str(x[1]['ComicYear'])))
    return [{'comicid': c['ComicID'], 'name': c['ComicName'], 'year': c['ComicYear'], 'volume': c['ComicVersion']} for s, c in hits[:limit]]


def issues(comicid):
    rows = db.DBConnection().select('SELECT IssueID, Issue_Number, Status, IssueDate FROM issues WHERE ComicID=?', [comicid])
    rows = [dict(r) for r in rows]
    rows.sort(key=lambda r: (_num(r['Issue_Number']) is None, _num(r['Issue_Number']) or 0))
    return rows


def _cover_dir():
    d = os.path.join(mylar.CONFIG.CACHE_DIR or os.path.join(mylar.DATA_DIR or '.', 'cache'), 'attention-covers')
    os.makedirs(d, exist_ok=True)
    return d


# Covers are cut out of whole comics or fetched from ComicVine, which is slow, and the web server
# has few threads. Only COVER_SLOTS covers are made at once; a request that can't get a slot within
# COVER_WAIT seconds is told the server is busy, and the page asks again a little later.
COVER_SLOTS = threading.BoundedSemaphore(2)
COVER_WAIT = 8
BUSY = 'busy'
NO_COVER_DAYS = 1      # how long a missing ComicVine cover is remembered before trying again


def _none_marker(out):
    return out[:-len('.jpg')] + '.none'


def _remembered_none(out, days=None):
    marker = _none_marker(out)
    try:
        return days is None or time.time() - os.path.getmtime(marker) < days * 86400
    except OSError:
        return False


def _remember_none(out):
    try:
        open(_none_marker(out), 'w').close()
    except OSError:
        pass


def file_cover(path):
    """The front cover inside a file, as a cached JPEG path, or None. Picked the way the
    library picks covers; the cache is keyed on the file's size and time, so a changed file
    gets a fresh one."""
    if not _known(path):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = hashlib.sha1(('%s|%s|%s' % (path, st.st_size, st.st_mtime)).encode('utf-8')).hexdigest()
    out = os.path.join(_cover_dir(), 'file-%s.jpg' % key)
    if os.path.isfile(out):
        return out
    if os.path.isfile(_none_marker(out)):
        return None
    if not COVER_SLOTS.acquire(timeout=COVER_WAIT):
        return BUSY
    try:
        if os.path.isfile(out):    # made while this request waited
            return out
        try:
            from mylar import getimage
            res = getimage.extract_image(path, single=True)
            data = (res or {}).get('rawImage')
        except Exception as e:
            logger.fdebug('[ATTENTION] No cover from %s: %s' % (os.path.basename(path), e))
            data = None
        if not data:
            _remember_none(out)
            return None
        with open(out, 'wb') as f:
            f.write(data)
        return out
    finally:
        COVER_SLOTS.release()


def issue_cover(issueid):
    """The issue's cover from ComicVine, fetched once and cached, or None."""
    row = db.DBConnection().selectone('SELECT ImageURL, ImageURL_ALT FROM issues WHERE IssueID=?', [issueid]).fetchone()
    url = row and (row['ImageURL'] or row['ImageURL_ALT'])
    if not url or not str(url).startswith('http'):
        return None
    out = os.path.join(_cover_dir(), 'issue-%s.jpg' % re.sub(r'[^0-9A-Za-z_-]', '', str(issueid)))
    if os.path.isfile(out):
        return out
    if _remembered_none(out, NO_COVER_DAYS):
        return None
    if not COVER_SLOTS.acquire(timeout=COVER_WAIT):
        return BUSY
    try:
        if os.path.isfile(out):
            return out
        import requests
        try:
            r = requests.get(url, headers=getattr(mylar, 'CV_HEADERS', None), timeout=(10, 20),
                             verify=getattr(mylar.CONFIG, 'CV_VERIFY', True))
            r.raise_for_status()
        except Exception as e:
            logger.fdebug('[ATTENTION] Could not fetch the cover for issue %s: %s' % (issueid, e))
            _remember_none(out)
            return None
        if not r.headers.get('Content-Type', '').startswith('image/'):
            _remember_none(out)
            return None
        with open(out, 'wb') as f:
            f.write(r.content)
        return out
    finally:
        COVER_SLOTS.release()


def in_library(path):
    """Whether a listed file is one already filed in the library (one WebP conversion found
    damaged), rather than a download waiting to be filed. Filing it again would copy or move it
    over itself, so the page only offers the trash or ignoring it."""
    try:
        row = db.DBConnection().selectone('SELECT status FROM webp_files WHERE path=?', [path]).fetchone()
    except Exception:   # no WebP conversion has run yet
        return False
    return row is not None


def _known(path):
    """Only files this page lists may be acted on."""
    path = os.path.normpath(path)
    return path in {os.path.normpath(p) for p in _open_paths(db.DBConnection())}


def gone(path):
    """A listed file that was moved or deleted outside Issuarr: drop it from the list."""
    if os.path.exists(path):
        return None
    forget(path)
    JOBS.pop(path, None)
    return {'ok': True, 'gone': True, 'note': 'That file was already moved or deleted, so it\'s off the list.'}


def trash(path):
    left = gone(path)
    if left:
        return left
    if not _known(path):
        return {'ok': False, 'note': 'That file is no longer waiting for a decision.'}
    dest_dir = _trash_file(path)
    logger.info('[ATTENTION] Moved %s to the trash (%s).' % (os.path.basename(path), dest_dir))
    return {'ok': True, 'note': 'Moved to the trash. It\'s deleted for good after %s days.' % trash_days()}


def _trash_file(path):
    dest_dir = os.path.join(trash_dir(), datetime.date.today().isoformat())
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(path))
    if os.path.exists(dest):
        base, ext = os.path.splitext(dest)
        dest = '%s (%s)%s' % (base, int(time.time()), ext)
    shutil.move(path, dest)
    forget(path)
    return dest_dir


def purge_trash():
    root = trash_dir()
    if not os.path.isdir(root):
        return 0
    cutoff = datetime.date.today() - datetime.timedelta(days=trash_days())
    gone = 0
    for d in os.listdir(root):
        try:
            day = datetime.date.fromisoformat(d)
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            gone += 1
    return gone


def file_as(path, comicid, issueid):
    """File a file as the issue the user picked, in the background. The pick stands in for
    filing's matching, so the checks that turned the file down don't run again."""
    if not _known(path):
        return {'ok': False, 'note': 'That file is no longer waiting for a decision.'}
    if in_library(path):
        return {'ok': False, 'note': 'That file is already in your library. Replace it with a good copy, or move it to the trash.'}
    myDB = db.DBConnection()
    issue = myDB.selectone('SELECT i.IssueID, i.Issue_Number, i.ComicID, c.ComicName, c.ComicYear FROM issues i '
                           'JOIN comics c ON c.ComicID=i.ComicID WHERE i.IssueID=? AND i.ComicID=?', [issueid, comicid]).fetchone()
    if issue is None:
        return {'ok': False, 'note': 'That issue isn\'t on your watchlist.'}
    with _LOCK:
        if (JOBS.get(path) or {}).get('state') in ('waiting', 'filing'):
            return {'ok': False, 'note': 'Already being filed.'}
        label = '%s #%s' % (issue['ComicName'], issue['Issue_Number'])
        JOBS[path] = {'state': 'waiting', 'note': 'Waiting to file as %s' % label}
    _keep_pick(path, comicid, issueid)
    threading.Thread(target=_file_now, args=(path, dict(issue)), name='ATTENTION-FILE', daemon=True).start()
    return {'ok': True, 'note': 'Filing as %s. It starts as soon as the filing that\'s running now finishes.' % label}


def _keep_pick(path, comicid, issueid):
    try:
        myDB = db.DBConnection()
        ensure(myDB)
        myDB.upsert('attention', {'status': 'queued', 'pick': '%s|%s' % (comicid, issueid), 'size': _size(path)}, {'path': path})
    except Exception as e:
        logger.warn('[ATTENTION] Could not save the choice for %s: %s' % (path, e))


def _drop_pick(path):
    try:
        myDB = db.DBConnection()
        ensure(myDB)
        myDB.action("UPDATE attention SET status='open', pick=NULL WHERE path=? AND status='queued'", [path])
    except Exception as e:
        logger.fdebug('[ATTENTION] Could not clear the choice for %s: %s' % (path, e))


def resume_picks():
    """File the File as choices a restart interrupted, one after another, in the background."""
    try:
        myDB = db.DBConnection()
        ensure(myDB)
        rows = [dict(r) for r in myDB.select("SELECT path, pick FROM attention WHERE status='queued' AND pick IS NOT NULL")]
    except Exception as e:
        logger.warn('[ATTENTION] Could not look for unfinished File as choices: %s' % e)
        return 0
    todo = []
    for r in rows:
        comicid, _, issueid = (r['pick'] or '').partition('|')
        if not os.path.isfile(r['path']):
            forget(r['path'])
            continue
        issue = myDB.selectone('SELECT i.IssueID, i.Issue_Number, i.ComicID, c.ComicName, c.ComicYear FROM issues i '
                               'JOIN comics c ON c.ComicID=i.ComicID WHERE i.IssueID=? AND i.ComicID=?', [issueid, comicid]).fetchone()
        if issue is None:
            _drop_pick(r['path'])
            continue
        JOBS[r['path']] = {'state': 'waiting', 'note': 'Waiting to file as %s #%s' % (issue['ComicName'], issue['Issue_Number'])}
        todo.append((r['path'], dict(issue)))
    if todo:
        logger.info('[ATTENTION] Filing %s file(s) you chose an issue for before the restart.' % len(todo))

        def run():
            for path, issue in todo:
                _file_now(path, issue)
        threading.Thread(target=run, name='ATTENTION-RESUME', daemon=True).start()
    return len(todo)


def entry_for(path, issue):
    return {'ComicLocation': path, 'ComicID': issue['ComicID'], 'IssueID': issue['IssueID'],
            'IssueNumber': issue['Issue_Number'], 'ComicName': issue['ComicName'], 'SeriesYear': issue['ComicYear'],
            'Series': issue['ComicName'], 'AltSeries': None, 'AnnualType': None, 'AnnualSeries': None,
            'AgeRating': None, 'One-Off': False, 'ForcedMatch': True}   # no IssueArcID: that would start story-arc filing


def _file_now(path, issue):
    from mylar import PostProcessor
    label = '%s #%s' % (issue['ComicName'], issue['Issue_Number'])
    try:
        pp = PostProcessor.PostProcessor('Manual Run', os.path.dirname(path), queue=queue.Queue())
        with PostProcessor.PP_LOCK:
            JOBS[path] = {'state': 'filing', 'note': 'Filing as %s' % label}
            pp.nzb_or_oneoff_pp(manual=[entry_for(path, issue)])
        row = db.DBConnection().selectone('SELECT Status FROM issues WHERE IssueID=?', [issue['IssueID']]).fetchone()
        if row is not None and row['Status'] in ('Downloaded', 'Archived'):
            if os.path.isfile(path):
                # filing copies when set to copy - the original isn't needed here any more
                trash(path)
            forget(path)
            JOBS[path] = {'state': 'filed', 'note': 'Filed as %s' % label}
            logger.info('[ATTENTION] Filed %s as %s.' % (os.path.basename(path), label))
        else:
            _drop_pick(path)
            JOBS[path] = {'state': 'failed', 'note': 'Filing didn\'t finish. The log has the details.'}
            logger.warn('[ATTENTION] Filing %s as %s didn\'t finish.' % (os.path.basename(path), label))
    except Exception as e:
        _drop_pick(path)
        logger.exception('[ATTENTION] Filing %s as %s failed: %s' % (path, label, e))
        JOBS[path] = {'state': 'failed', 'note': 'Filing failed: %s' % e}
    finally:
        _COUNT[0] = 0


def refile_folders(paths):
    """The folders to run filing over again for these files: the review folder as one, any other
    file's own folder, leaving out folders inside one already listed. The review folder goes last,
    as the longest run, so the others don't wait behind it."""
    review = os.path.normpath(review_dir() or '')
    found = set()
    for p in paths:
        p = os.path.normpath(p)
        if review and p.startswith(review + os.sep):
            found.add(review)
        else:
            found.add(os.path.dirname(p))
    keep = []
    for f in sorted(found, key=len):
        if not any(f == k or f.startswith(k + os.sep) for k in keep):
            keep.append(f)
    keep.sort(key=lambda f: (f == review, f))
    return keep


def refile_all(auto=False):
    """Run filing again over every folder holding a file listed here, in the background, so files
    that newer matching would now place get filed. Returns what to tell the user."""
    with _REFILE_LOCK:
        if REFILE.get('state') == 'running':
            return {'ok': False, 'note': 'Already trying again.'}
        try:
            paths = [p for p in _open_paths(db.DBConnection()) if not in_library(p)]
        except Exception as e:
            return {'ok': False, 'note': 'Could not list the files: %s' % e}
        folders = refile_folders(paths)
        if not folders:
            return {'ok': False, 'note': 'Nothing here to try again.'}
        REFILE.clear()
        REFILE.update(state='running', auto=auto, folders=folders, total=len(folders), done=0, current='',
                      before=len(paths), after=None, started=time.time(), finished=None, stop=False)
    threading.Thread(target=_refile_run, args=(folders,), name='ATTENTION-REFILE', daemon=True).start()
    logger.info('[ATTENTION] Trying to file %s file(s) again, in %s folder(s)%s.'
                % (len(paths), len(folders), ' after an update' if auto else ''))
    return {'ok': True, 'note': 'Trying %s files again. New downloads are filed first.' % len(paths)}


def stop_refile():
    with _REFILE_LOCK:
        if REFILE.get('state') == 'running':
            REFILE['stop'] = True
            return True
    return False


def _refile_run(folders):
    from mylar import PostProcessor
    try:
        for n, folder in enumerate(folders):
            # new downloads go first: wait while the post-processing queue has work
            while not REFILE.get('stop') and getattr(mylar, 'PP_QUEUE', None) is not None and mylar.PP_QUEUE.qsize():
                REFILE['current'] = ''
                REFILE['waiting'] = True
                time.sleep(REFILE_WAIT)
            REFILE['waiting'] = False
            if REFILE.get('stop'):
                break
            REFILE['current'] = folder
            if os.path.isdir(folder):
                try:
                    PostProcessor.PostProcessor('Manual Run', folder, queue=queue.Queue()).Process()
                    # a direct-download pack: what still doesn't file isn't wanted
                    from mylar import archives
                    archives.clear_pack(folder)
                except Exception as e:
                    logger.warn('[ATTENTION] Filing %s again failed: %s' % (folder, e))
            REFILE['done'] = n + 1
    finally:
        _COUNT[0] = 0
        try:
            left = len([p for p in _open_paths(db.DBConnection()) if not in_library(p)])
        except Exception:
            left = None
        with _REFILE_LOCK:
            REFILE.update(state='stopped' if REFILE.get('stop') else 'done', after=left, current='',
                          waiting=False, finished=time.time())
        logger.info('[ATTENTION] Finished trying again: %s of %s file(s) still need attention.'
                    % ('?' if left is None else left, REFILE.get('before')))


def _version_key():
    from mylar import appversion
    return '%s %s' % (appversion.VERSION, getattr(mylar, 'CURRENT_VERSION', None) or '')


def refile_after_update(delay=AFTER_UPDATE_DELAY):
    """Once per new version: newer filing may place files an older one couldn't, so try them all again."""
    cache = getattr(mylar.CONFIG, 'CACHE_DIR', None)
    if not cache:
        return False
    marker = os.path.join(cache, 'attention_refiled_for')
    key = _version_key()
    try:
        with open(marker) as fh:
            if fh.read().strip() == key:
                return False
    except OSError:
        pass
    try:
        with open(marker, 'w') as fh:
            fh.write(key)
    except OSError as e:
        logger.warn('[ATTENTION] Could not note the version for trying files again: %s' % e)
        return False

    def later():
        time.sleep(delay)
        refile_all(auto=True)
    threading.Thread(target=later, name='ATTENTION-AFTER-UPDATE', daemon=True).start()
    return True


def after_start():
    resume_picks()
    refile_after_update()


def group_of(path):
    """Which group a listed file belongs to, as (key, label, folder): a collection in the review
    folder (its first sub-folder, "Star Wars"), a download's own folder, or else the file's folder."""
    path = os.path.normpath(path)
    review = os.path.normpath(review_dir() or '')
    ddl = os.path.normpath(getattr(mylar.CONFIG, 'DDL_LOCATION', None) or '') if getattr(mylar.CONFIG, 'DDL_LOCATION', None) else ''
    for base, where in ((review, 'Review folder'), (ddl, 'Downloads')):
        if base and path.startswith(base + os.sep):
            parts = os.path.relpath(path, base).split(os.sep)
            if len(parts) == 1:
                return (base, '%s (loose files)' % where, base)
            folder = os.path.join(base, parts[0])
            return (folder, parts[0], folder)
    folder = os.path.dirname(path)
    return (folder, os.path.basename(folder) or folder, folder)


def groups():
    """The listed files by group, biggest first, with how many and why. Cheap: no suggestions."""
    out = {}
    for path, row in _open_paths(db.DBConnection()).items():
        key, label, folder = group_of(path)
        g = out.setdefault(key, {'key': key, 'label': label, 'folder': folder, 'count': 0, 'size': 0, 'reasons': {}})
        g['count'] += 1
        g['size'] += _size(path) or 0
        reason = row.get('reason') or 'unclaimed'
        g['reasons'][reason] = g['reasons'].get(reason, 0) + 1
    return sorted(out.values(), key=lambda g: (-g['count'], g['label'].lower()))


def group_paths(key):
    return [p for p in _open_paths(db.DBConnection()) if group_of(p)[0] == key]


def group_action(key, action):
    """Do one thing to every listed file in a group: 'trash', 'ignore', or 'add' (find their series
    on ComicVine, add them, then file the group's folder again)."""
    paths = group_paths(key)
    if not paths:
        return {'ok': False, 'note': 'Nothing in that group is waiting any more.'}
    if action == 'add':
        from mylar import autoadd
        folder = group_of(paths[0])[2]
        problem = autoadd.queue(paths, force=True, folder=folder)
        if problem:
            return {'ok': False, 'note': problem}
        return {'ok': True, 'note': 'Looking up the series of %s files on ComicVine. Series found are added, then the folder is filed again.' % len(paths)}
    done, failed = 0, 0
    for p in paths:
        try:
            if action == 'trash':
                if os.path.exists(p):
                    _trash_file(p)
                else:
                    forget(p)
            elif action == 'ignore':
                ignore(p)
            else:
                return {'ok': False, 'note': 'Unknown action.'}
            done += 1
        except Exception as e:
            failed += 1
            logger.warn('[ATTENTION] Could not %s %s: %s' % (action, p, e))
    _COUNT[0] = 0
    what = 'Moved %s files to the trash.' % done if action == 'trash' else 'Hid %s files until they change.' % done
    if action == 'trash':
        logger.info('[ATTENTION] Moved %s file(s) of %s to the trash.' % (done, key))
    return {'ok': failed == 0, 'note': what + (' %s could not be changed - the log has why.' % failed if failed else '')}
