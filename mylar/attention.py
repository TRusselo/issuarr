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
REASONS = ('damaged', 'cover', 'volume', 'year', 'issue', 'series', 'unclaimed')
CACHE_SECONDS = 60
_COUNT = [0.0, 0]          # (counted at, count) for the nav badge
_COMICS = [0.0, []]        # (loaded at, watchlist rows) for suggestions
JOBS = {}                  # path -> {'state': 'filing'|'filed'|'failed', 'note': str}
_LOCK = threading.Lock()


def ensure(myDB=None):
    (myDB or db.DBConnection()).action(
        'CREATE TABLE IF NOT EXISTS attention (path TEXT PRIMARY KEY, reason TEXT, detail TEXT, comicid TEXT, '
        'status TEXT, added TEXT, size INTEGER)')


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
    _COMICS[:] = [time.time(), [dict(r, norm=_norm(r['ComicName'])) for r in rows]]
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


def suggest(parsed, limit=3, comicid=None):
    """Watchlist series closest to what the file name says, each with the issue it would be
    and which parts of the name agree. Series with the same name are told apart by whether
    the issue is on them and its year and volume agree."""
    want = _norm(parsed.get('series'))
    if not want and not comicid:
        return []
    named = []
    for c in _watchlist():
        s = 1.0 if comicid and str(c['ComicID']) == str(comicid) else difflib.SequenceMatcher(None, want, c['norm']).ratio()
        if s >= 0.75:
            named.append((s, c))
    named.sort(key=lambda x: -x[0])
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
    for path, row in _open_paths(myDB).items():
        parsed = parse(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        out.append({'path': path, 'name': os.path.basename(path), 'folder': os.path.dirname(path),
                    'in_review': bool(review) and os.path.normpath(path).startswith(review + os.sep),
                    'reason': row.get('reason') or 'unclaimed', 'detail': row.get('detail') or '',
                    'size': _size(path), 'modified': mtime, 'parsed': parsed,
                    'matches': suggest(parsed, comicid=row.get('comicid')), 'job': JOBS.get(path)})
    out.sort(key=lambda i: -i['modified'])
    _COUNT[:] = [time.time(), len(out)]
    return out


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
    try:
        from mylar import getimage
        res = getimage.extract_image(path, single=True)
        data = (res or {}).get('rawImage')
    except Exception as e:
        logger.fdebug('[ATTENTION] No cover from %s: %s' % (os.path.basename(path), e))
        data = None
    if not data:
        return None
    with open(out, 'wb') as f:
        f.write(data)
    return out


def issue_cover(issueid):
    """The issue's cover from ComicVine, fetched once and cached, or None."""
    row = db.DBConnection().selectone('SELECT ImageURL, ImageURL_ALT FROM issues WHERE IssueID=?', [issueid]).fetchone()
    url = row and (row['ImageURL'] or row['ImageURL_ALT'])
    if not url or not str(url).startswith('http'):
        return None
    out = os.path.join(_cover_dir(), 'issue-%s.jpg' % re.sub(r'[^0-9A-Za-z_-]', '', str(issueid)))
    if os.path.isfile(out):
        return out
    import requests
    try:
        r = requests.get(url, headers=getattr(mylar, 'CV_HEADERS', None), timeout=(15, 30),
                         verify=getattr(mylar.CONFIG, 'CV_VERIFY', True))
        r.raise_for_status()
    except Exception as e:
        logger.fdebug('[ATTENTION] Could not fetch the cover for issue %s: %s' % (issueid, e))
        return None
    if not r.headers.get('Content-Type', '').startswith('image/'):
        return None
    with open(out, 'wb') as f:
        f.write(r.content)
    return out


def _known(path):
    """Only files this page lists may be acted on."""
    path = os.path.normpath(path)
    return path in {os.path.normpath(p) for p in _open_paths(db.DBConnection())}


def trash(path):
    if not _known(path):
        return {'ok': False, 'note': 'That file is no longer waiting for a decision.'}
    dest_dir = os.path.join(trash_dir(), datetime.date.today().isoformat())
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(path))
    if os.path.exists(dest):
        base, ext = os.path.splitext(dest)
        dest = '%s (%s)%s' % (base, int(time.time()), ext)
    shutil.move(path, dest)
    forget(path)
    logger.info('[ATTENTION] Moved %s to the trash (%s).' % (os.path.basename(path), dest_dir))
    return {'ok': True, 'note': 'Moved to the trash. It\'s deleted for good after %s days.' % trash_days()}


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
    myDB = db.DBConnection()
    issue = myDB.selectone('SELECT i.IssueID, i.Issue_Number, i.ComicID, c.ComicName, c.ComicYear FROM issues i '
                           'JOIN comics c ON c.ComicID=i.ComicID WHERE i.IssueID=? AND i.ComicID=?', [issueid, comicid]).fetchone()
    if issue is None:
        return {'ok': False, 'note': 'That issue isn\'t on your watchlist.'}
    with _LOCK:
        if (JOBS.get(path) or {}).get('state') == 'filing':
            return {'ok': False, 'note': 'Already being filed.'}
        note = 'Filing as %s #%s' % (issue['ComicName'], issue['Issue_Number'])
        JOBS[path] = {'state': 'filing', 'note': note}
    threading.Thread(target=_file_now, args=(path, dict(issue)), name='ATTENTION-FILE', daemon=True).start()
    return {'ok': True, 'note': note}


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
            JOBS[path] = {'state': 'failed', 'note': 'Filing didn\'t finish. The log has the details.'}
    except Exception as e:
        logger.exception('[ATTENTION] Filing %s as %s failed: %s' % (path, label, e))
        JOBS[path] = {'state': 'failed', 'note': 'Filing failed: %s' % e}
    finally:
        _COUNT[0] = 0
