import datetime
import os
import shutil
import html as _html
import json
import re
import threading
import zipfile
import xml.etree.ElementTree as ET

from collections import defaultdict

import mylar
from mylar import db, logger

OWNED = ('Downloaded', 'Archived')
TRADE_TYPES = ('TPB', 'HC', 'GN')
KINDS = ['gap', 'unrecognised', 'after_last', 'before_first', 'after_cutoff']

# A series as runs of issues in number order, for the bar that shows where its gaps are:
# h on disk, w wanted, s snatched, f failed, i ignored, m missing and not wanted.
RUN_CODES = {'Wanted': 'w', 'Snatched': 's', 'Failed': 'f', 'Ignored': 'i'}


def run_code(status):
    return 'h' if status in OWNED else RUN_CODES.get(status, 'm')


def runs(issues):
    """issues: (Int_IssueNumber, IssueDate, Status, Issue_Number) tuples.
    Returns [[code, count, first issue number, last issue number], ...] in issue order."""
    out = []
    for _, _, status, label in sorted(issues, key=lambda x: (x[0] is None, x[0] if x[0] is not None else 0, x[1] or '')):
        code = run_code(status)
        label = str(label) if label not in (None, '') else '?'
        if out and out[-1][0] == code:
            out[-1][1] += 1
            out[-1][3] = label
        else:
            out.append([code, 1, label, label])
    return out


def series_runs(comicid, myDB=None):
    myDB = myDB or db.DBConnection()
    rows = myDB.select('SELECT Int_IssueNumber, IssueDate, Status, Issue_Number FROM issues WHERE ComicID=?', [comicid])
    return runs((r['Int_IssueNumber'], r['IssueDate'], r['Status'], r['Issue_Number']) for r in rows)

_NUM = r'\d+(?:\.\d+|\.[A-Za-z]+)?'
_RANGE = r'(%s)\s*(?:[-–—]|to|through)\s*(%s)|(%s)' % (_NUM, _NUM, _NUM)
_SEG = re.compile(
    r'((?:[A-Z0-9][\w\'’.:/&!-]*(?:\s+(?:of|the|and|vs\.?|&|in|a|an|to|de|du|[A-Z0-9][\w\'’.:/&!-]*))*?)?)'
    r'\s*(?:\((\d{4})\))?\s*(?:issues?\s*)?#\s*(%s(?:\s*(?:[-–—,&]|and|to)\s*#?\s*%s)*)' % (_NUM, _NUM))

_lock = threading.Lock()
_status = {'running': False, 'done': 0, 'total': 0, 'phase': None, 'started': None, 'finished': None, 'error': None, 'note': None}


def status():
    return dict(_status)


def _clean(text):
    text = re.sub(r'<[^>]+>', ' ', text or '')
    return re.sub(r'\s+', ' ', _html.unescape(text)).strip()


def _clauses(text):
    return [m.group(1) for m in re.finditer(
        r'\bcollect(?:s|ing|ed)?\b[:\s]*(.+?)(?:(?<![#\d])\.(?!\d)\s|[!?]\s|\|\||$)', text, re.I)]


def _numbers(spec):
    nums = []
    for a, b, c in re.findall(_RANGE, spec):
        if c:
            nums.append(c)
        elif a.isdigit() and b.isdigit() and 0 <= int(b) - int(a) <= 200:
            nums.extend(str(n) for n in range(int(a), int(b) + 1))
        else:
            nums.extend([a, b])
    return nums


def parse_collects(text):
    segs = []
    for clause in _clauses(_clean(text)):
        clause = re.split(r'\b(?:and material from|material from|plus material|and the|plus the|plus a|plus an|and a never|and stories from)\b',
                          clause, flags=re.I)[0]
        last = None
        for m in _SEG.finditer(clause):
            name = (m.group(1) or '').strip(' ,&-')
            name = re.sub(r'^\d+(?:[-–]\d+)?[.,]\s+', '', name)
            name = re.sub(r'^\d+\s+(?:and|plus|&)\s+', '', name, flags=re.I)
            name = re.sub(r'^(?:collect(?:s|ing|ed)?|reprints?|and|plus|&|the series|issues?)\s+', '', name, flags=re.I)
            dangling = re.search(r'\s(?:and|plus|&)$', name, flags=re.I)
            name = re.sub(r'\s+(?:and|plus|&)$', '', name, flags=re.I).strip(' ,&-')
            if dangling and re.fullmatch(r'[\d\s.]*', name):
                name = ''
            if name.lower() in ('', 'issues', 'issue', 'and', 'plus'):
                of = re.match(r'\s*of\s+(?:the\s+)?(?:ongoing\s+|original\s+|classic\s+)?([A-Z][\w\'’.:/& -]*?)\s+(?:series|mini-?series|comic|title|run)\b',
                              clause[m.end():])
                name = of.group(1).strip() if of else (last[0] if last else None)
                year = m.group(2) or (last[1] if last else None)
            else:
                year = m.group(2)
            nums = _numbers(m.group(3))
            if nums:
                segs.append((name, year, nums))
                last = (name, year)
    return segs


def _norm(s):
    s = (s or '').lower().replace('&', 'and')
    s = re.sub(r'\(\d{4}\)', '', s)
    s = re.sub(r'^the\s+', '', s.strip())
    return re.sub(r'[^a-z0-9]', '', s)


def _num_key(n):
    n = str(n).strip().upper().lstrip('0')
    return n or '0'


def _trade_base(name):
    name = re.split(r'[:–-]', name or '')[0]
    name = re.sub(r'\b(deluxe|edition|omnibus|vol(ume)?\.?\s*\d*|tpb|hc|collection|complete|the)\b', ' ', name, flags=re.I)
    return re.sub(r'\s+', ' ', name).strip()


class _Library(object):
    def __init__(self, myDB):
        self.comics = {r['ComicID']: dict(r) for r in myDB.select('SELECT ComicID, ComicName, ComicYear FROM comics')}
        self.byname = defaultdict(list)
        for cid, c in self.comics.items():
            self.byname[_norm(c['ComicName'])].append(cid)
        self.issues = defaultdict(dict)
        for i in myDB.select('SELECT IssueID, ComicID, Issue_Number, ReleaseDate FROM issues'):
            self.issues[i['ComicID']][_num_key(i['Issue_Number'])] = dict(i)

    def _pick(self, name, year, nums, before, exclude, slack):
        best = None
        for cid in self.byname.get(_norm(name), []):
            if cid == exclude:
                continue
            c = self.comics[cid]
            if year:
                try:
                    gap = int(c['ComicYear']) - int(year)
                except (TypeError, ValueError):
                    continue
                if (slack is not None and abs(gap) > slack) or (slack is None and gap < 0):
                    continue
            iss = self.issues[cid]
            have = [n for n in nums if _num_key(n) in iss]
            if not have:
                continue
            if before and any((iss[_num_key(n)]['ReleaseDate'] or '') > before for n in have):
                continue
            score = (len(have), str(c['ComicYear']) == str(year), c['ComicYear'] or '')
            if best is None or score > best[0]:
                best = (score, cid)
        return best[1] if best else None

    def pick(self, name, year, nums, before, exclude, context=None):
        names = [name]
        if _norm(name) in ('annual', 'annuals'):
            if not context:
                return None
            for slack in (0, 1, 2):
                cid = self._pick('%s Annual' % context[0], context[1], nums, before, exclude, slack)
                if cid:
                    return cid
            return None
        else:
            bare = re.sub(r'\s*\bvol(?:ume)?\.?\s*\d+\b', ' ', name, flags=re.I).strip()
            if bare != name:
                names.append(bare)
            if re.search(r'\s(?:and|&)\s', name):
                names.append(re.split(r'\s(?:and|&)\s', name)[-1])
        for nm in names:
            slacks = [0, 1] if year else [None]
            if year and before and self._has_volume(nm, year):
                slacks.append(None)
            for slack in slacks:
                cid = self._pick(nm, year, nums, before, exclude, slack)
                if cid:
                    return cid
        return None

    def _has_volume(self, name, year):
        for cid in self.byname.get(_norm(name), []):
            try:
                if abs(int(self.comics[cid]['ComicYear']) - int(year)) <= 1:
                    return True
            except (TypeError, ValueError):
                pass
        return False

    def resolve(self, segs, trade_name, before, exclude):
        found, missing = [], []
        prev = None
        for name, year, nums in segs:
            if name:
                nm = name
                cid = self.pick(nm, year, nums, before, exclude, context=prev)
            else:
                full = _trade_base(re.sub(r'[:–]', ' ', trade_name or ''))
                nm = full
                cid = self.pick(full, year, nums, before, exclude)
                if cid is None and not re.search(r'[:–]', trade_name or ''):
                    nm = _trade_base(trade_name)
                    cid = self.pick(nm, year, nums, before, exclude)
            if cid is not None and _norm(nm) not in ('annual', 'annuals'):
                prev = (self.comics[cid]['ComicName'], self.comics[cid]['ComicYear'])
            if cid is None:
                missing.append({'series': nm, 'year': year, 'nums': nums})
                continue
            for n in nums:
                i = self.issues[cid].get(_num_key(n))
                if i:
                    if i['IssueID'] not in found:
                        found.append(i['IssueID'])
                else:
                    missing.append({'series': nm, 'year': year, 'nums': [n]})
        return found, missing


def _ensure_table(myDB):
    myDB.action('CREATE TABLE IF NOT EXISTS ledger_collects (TradeIssueID TEXT UNIQUE, TradeComicID TEXT, Source TEXT, '
                'Collects TEXT, IssueIDs TEXT, Unresolved TEXT, Updated TEXT)')


def start_build(force=False):
    with _lock:
        if _status['running']:
            return False
        _status.update(running=True, done=0, total=0, phase='Preparing', error=None, note=None,
                       started=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), finished=None)
    threading.Thread(target=_build, args=(force,), name='LedgerBuild').start()
    return True


def _build(force):
    from mylar import cv
    try:
        myDB = db.DBConnection()
        _ensure_table(myDB)
        trades = myDB.select("SELECT i.IssueID, i.ComicID, c.ComicName FROM issues i JOIN comics c ON c.ComicID=i.ComicID "
                             "WHERE coalesce(c.Corrected_Type, c.Type) IN ('TPB','HC','GN')")
        done = set() if force else {r['TradeIssueID'] for r in myDB.select("SELECT TradeIssueID FROM ledger_collects")}
        todo = [t for t in trades if t['IssueID'] not in done]
        _status.update(total=len(todo), phase='Reading ComicVine descriptions')
        lib = _Library(myDB)
        for k in range(0, len(todo), 100):
            batch = todo[k:k + 100]
            url = '%sissues/?api_key=%s&format=json&filter=id:%s&field_list=id,description,deck,store_date,cover_date,volume&limit=100' % (
                mylar.CVURL, mylar.CONFIG.COMICVINE_API, '|'.join(str(t['IssueID']) for t in batch))
            r = cv.cv_request(url, timeout=60)
            results = {str(x['id']): x for x in (r.json().get('results') or [])}
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            for t in batch:
                x = results.get(str(t['IssueID']))
                if x is None:
                    continue
                text = (x.get('description') or '') + ' || ' + (x.get('deck') or '')
                segs = parse_collects(text)
                found, missing = lib.resolve(segs, (x.get('volume') or {}).get('name') or t['ComicName'],
                                             x.get('store_date') or x.get('cover_date'), t['ComicID'])
                clause = _clauses(_clean(text))
                myDB.upsert('ledger_collects', {'TradeComicID': t['ComicID'], 'Source': 'comicvine',
                                                'Collects': clause[0][:400] if clause else None,
                                                'IssueIDs': json.dumps(found), 'Unresolved': json.dumps(missing), 'Updated': now},
                            {'TradeIssueID': t['IssueID']})
            _status['done'] = min(len(todo), k + 100)
        _comicinfo_pass(myDB, lib, force)
        _status.update(phase='Finished', note=None)
        logger.info('[LEDGER] Collected-edition contents read for %s trade issues.' % len(todo))
    except Exception as e:
        logger.warn('[LEDGER] Building collected-edition data failed: %s' % e)
        _status.update(error=str(e), phase='Failed')
    finally:
        _status.update(running=False, finished=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))


def _comicinfo_summary(path):
    try:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().rsplit('/', 1)[-1] == 'comicinfo.xml'), None)
            if not name:
                return None
            root = ET.fromstring(z.read(name))
    except Exception:
        return None
    node = root.find('Summary')
    return node.text if node is not None and node.text else None


def _comicinfo_pass(myDB, lib, force):
    known = {r['TradeIssueID']: r for r in myDB.select('SELECT TradeIssueID, Source, IssueIDs FROM ledger_collects')}
    rows = myDB.select("SELECT i.IssueID, i.ComicID, i.Location, i.ReleaseDate, c.ComicName, c.ComicLocation FROM issues i "
                       "JOIN comics c ON c.ComicID=i.ComicID WHERE coalesce(c.Corrected_Type, c.Type) IN ('TPB','HC','GN') "
                       "AND i.Status IN ('Downloaded','Archived') AND i.Location IS NOT NULL")
    todo = []
    for t in rows:
        k = known.get(t['IssueID'])
        if k is not None and k['IssueIDs'] not in (None, '[]') and not (force and k['Source'] == 'comicinfo'):
            continue
        todo.append(t)
    _status.update(phase='Reading summaries in your trade files', done=0, total=len(todo))
    found_n = 0
    for n, t in enumerate(todo, 1):
        _status['done'] = n
        path = os.path.join(t['ComicLocation'] or '', t['Location'])
        if not path.lower().endswith(('.cbz', '.zip')) or not os.path.isfile(path):
            continue
        text = _comicinfo_summary(path)
        segs = parse_collects(text) if text else []
        if not segs:
            continue
        found, missing = lib.resolve(segs, t['ComicName'], t['ReleaseDate'] or None, t['ComicID'])
        if not found and t['IssueID'] in known:
            continue
        clause = _clauses(_clean(text))
        myDB.upsert('ledger_collects', {'TradeComicID': t['ComicID'], 'Source': 'comicinfo',
                                        'Collects': clause[0][:400] if clause else None,
                                        'IssueIDs': json.dumps(found), 'Unresolved': json.dumps(missing),
                                        'Updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')},
                    {'TradeIssueID': t['IssueID']})
        found_n += 1 if found else 0
    logger.info('[LEDGER] Trade file summaries explained %s trades ComicVine couldn\'t.' % found_n)


COVERAGE = ['fills_gaps', 'covered', 'partly', 'not_in_library', 'unknown']


def _trades(myDB, status, comics):
    _ensure_table(myDB)
    out = []
    for r in myDB.select('SELECT * FROM ledger_collects'):
        t = status.get(r['TradeIssueID'])
        c = comics.get(r['TradeComicID'])
        if t is None or c is None:
            continue
        found = [f for f in json.loads(r['IssueIDs'] or '[]') if f in status and status[f]['ComicID'] in comics]
        unresolved = json.loads(r['Unresolved'] or '[]')
        own = [f for f in found if status[f]['Status'] in OWNED]
        found_names = {_norm(comics[status[f]['ComicID']]['ComicName']) for f in found}
        same = [u for u in unresolved if _norm(u.get('series')) in found_names]
        other = [u for u in unresolved if _norm(u.get('series')) not in found_names]
        if not r['Collects']:
            cov = 'unknown'
        elif not found:
            cov = 'not_in_library' if unresolved else 'unknown'
        elif len(own) < len(found):
            cov = 'fills_gaps'
        elif same:
            cov = 'partly'
        else:
            cov = 'covered'
        out.append({'row': r, 'trade': t, 'comic': c, 'found': found, 'own': own, 'unresolved': unresolved,
                    'other': other, 'coverage': cov})
    return out


def _lookups(myDB):
    status = {r['IssueID']: r for r in myDB.select('SELECT IssueID, ComicID, Issue_Number, Status, Location FROM issues')}
    comics = {r['ComicID']: r for r in myDB.select('SELECT ComicID, ComicName, ComicYear, ComicPublisher, Corrected_Type, Type, Have, Total FROM comics')}
    return status, comics


def missing_data(cutoff=None):
    myDB = db.DBConnection()
    comics = {r['ComicID']: r for r in myDB.select('SELECT ComicID, ComicName, ComicYear, ComicPublisher, Have, Total FROM comics')}
    owned = defaultdict(list)
    rows = []
    every = defaultdict(list)
    for i in myDB.select('SELECT IssueID, ComicID, Issue_Number, Int_IssueNumber, IssueName, ReleaseDate, IssueDate, Status FROM issues'):
        every[i['ComicID']].append((i['Int_IssueNumber'], i['IssueDate'], i['Status'], i['Issue_Number']))
        if i['Status'] in OWNED:
            if i['Int_IssueNumber'] is not None:
                owned[i['ComicID']].append(i['Int_IssueNumber'])
        elif i['Status'] != 'Ignored':
            rows.append(i)
    lo = {c: min(v) for c, v in owned.items()}
    hi = {c: max(v) for c, v in owned.items()}

    status, tcomics = _lookups(myDB)
    trades, by_issue, by_series = [], defaultdict(list), defaultdict(list)
    for x in _trades(myDB, status, tcomics):
        idx = len(trades)
        cids = sorted({status[f]['ComicID'] for f in x['found']})
        trades.append([x['comic']['ComicName'], x['comic']['ComicYear'], x['trade']['Issue_Number'], x['row']['TradeComicID'],
                       1 if x['trade']['Status'] in OWNED else 0, COVERAGE.index(x['coverage'])])
        for f in x['found']:
            by_issue[f].append(idx)
        for cid in cids:
            by_series[cid].append(idx)

    pubs, pidx, series, sidx, out = [], {}, [], {}, []

    def series_index(cid):
        c = comics[cid]
        pub = c['ComicPublisher'] or '?'
        if pub not in pidx:
            pidx[pub] = len(pubs)
            pubs.append(pub)
        if cid not in sidx:
            sidx[cid] = len(series)
            series.append([c['ComicName'], c['ComicYear'], c['Have'] or 0, c['Total'] or 0, pidx[pub], cid, by_series.get(cid, []),
                           runs(every.get(cid, []))])
        return sidx[cid]

    for i in rows:
        c = comics.get(i['ComicID'])
        if c is None:
            continue
        date = next((d for d in (i['ReleaseDate'], i['IssueDate']) if d and not d.startswith('0000')), '')
        n = i['Int_IssueNumber']
        if cutoff and date and date >= cutoff:
            kind = 4
        elif i['ComicID'] not in owned:
            kind = 1
        elif n is not None and lo[i['ComicID']] < n < hi[i['ComicID']]:
            kind = 0
        elif n is not None and n < lo[i['ComicID']]:
            kind = 3
        else:
            kind = 2
        # Where it sits against the issues you have: 0 before the first, 1 in a gap, 2 after the last, -1 none owned.
        if i['ComicID'] not in owned:
            pos = -1
        elif n is not None and n < lo[i['ComicID']]:
            pos = 0
        elif n is not None and n < hi[i['ComicID']]:
            pos = 1
        else:
            pos = 2
        out.append([kind, series_index(i['ComicID']), i['Issue_Number'] or '', n or 0, (i['IssueName'] or '')[:90], date, i['IssueID'], i['Status'],
                    by_issue.get(i['IssueID'], []), pos])
    missing_cids = {i['ComicID'] for i in rows}
    complete = [series_index(cid) for cid, c in comics.items()
                if cid not in missing_cids and (c['Total'] or 0) > 0 and (c['Have'] or 0) >= (c['Total'] or 0)]
    return {'kinds': KINDS, 'pubs': pubs, 'series': series, 'rows': out, 'cutoff': cutoff or '',
            'trades': trades, 'coverage': COVERAGE, 'complete': complete}


def _extra_name(u, found, status, comics):
    name = u.get('series') or ''
    if _norm(name) in ('annual', 'annuals') and found:
        name = '%s Annual' % comics[status[found[0]]['ComicID']]['ComicName']
    elif name.isupper():
        name = name.title()
    return '%s (%s)' % (name, u['year']) if u.get('year') else name


def collected_data():
    myDB = db.DBConnection()
    status, comics = _lookups(myDB)
    out = []
    for x in _trades(myDB, status, comics):
        r, t, c = x['row'], x['trade'], x['comic']
        lacking = [[f, comics[status[f]['ComicID']]['ComicName'], comics[status[f]['ComicID']]['ComicYear'], status[f]['Issue_Number'], status[f]['Status']]
                   for f in x['found'] if f not in x['own']]
        out.append({'iid': r['TradeIssueID'], 'cid': r['TradeComicID'], 'name': c['ComicName'], 'year': c['ComicYear'],
                    'pub': c['ComicPublisher'], 'type': c['Corrected_Type'] or c['Type'], 'num': t['Issue_Number'],
                    'tstatus': t['Status'], 'collects': r['Collects'] or '', 'found': len(x['found']), 'own': len(x['own']),
                    'ondisk': sum(1 for f in x['own'] if status[f]['Location']),
                    'unresolved': sum(len(u['nums']) for u in x['unresolved']), 'lacking': lacking, 'coverage': x['coverage'],
                    'extras': sorted({_extra_name(u, x['found'], status, comics) for u in x['other']})})
    return {'trades': out, 'build': status_summary(myDB)}


def status_summary(myDB=None):
    myDB = myDB or db.DBConnection()
    _ensure_table(myDB)
    row = myDB.selectone('SELECT count(*), max(Updated) FROM ledger_collects').fetchone()
    s = status()
    s.update(stored=row[0], updated=row[1],
             comicinfo_found=myDB.selectone("SELECT count(*) FROM ledger_collects WHERE Source='comicinfo'").fetchone()[0])
    return s


def _holding_dir():
    return os.path.join(mylar.CONFIG.DESTINATION_DIR or '/comics', '_TRADE_DUPLICATES')


def _duplicate_singles(myDB, trade_ids):
    status, comics = _lookups(myDB)
    locs = {r['IssueID']: r['Location'] for r in myDB.select('SELECT IssueID, Location FROM issues')}
    clocs = {r['ComicID']: r['ComicLocation'] for r in myDB.select('SELECT ComicID, ComicLocation FROM comics')}
    wanted = set(str(t) for t in trade_ids)
    files, skipped = {}, []
    for x in _trades(myDB, status, comics):
        tid = x['row']['TradeIssueID']
        if tid not in wanted:
            continue
        tpath = os.path.join(clocs.get(x['row']['TradeComicID']) or '', locs.get(tid) or '')
        if x['trade']['Status'] not in OWNED or not locs.get(tid) or not os.path.isfile(tpath):
            skipped.append('%s (%s) #%s: the trade file isn\'t on disk' % (x['comic']['ComicName'], x['comic']['ComicYear'], x['trade']['Issue_Number']))
            continue
        for f in x['own']:
            cid = status[f]['ComicID']
            if not locs.get(f) or not clocs.get(cid):
                continue
            src = os.path.join(clocs[cid], locs[f])
            if os.path.isfile(src) and src != tpath:
                files[f] = (cid, src)
    return files, skipped


def preview_remove(trade_ids):
    myDB = db.DBConnection()
    files, skipped = _duplicate_singles(myDB, trade_ids)
    size = sum(os.path.getsize(src) for _, src in files.values())
    return {'ok': True, 'count': len(files), 'bytes': size, 'dest': _holding_dir(), 'skipped': skipped}


def remove_singles(trade_ids):
    myDB = db.DBConnection()
    files, skipped = _duplicate_singles(myDB, trade_ids)
    if not files:
        return {'ok': True, 'moved': 0, 'skipped': skipped}
    root = _holding_dir()
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    os.makedirs(root, exist_ok=True)
    undo = os.path.join(root, 'undo-%s.tsv' % stamp)
    moved, failed, series = 0, [], set()
    with open(undo, 'w') as log:
        log.write('# move each file in column 2 back to column 1 to undo, then run Recheck Files on the series\n')
        for iid, (cid, src) in files.items():
            dst_dir = os.path.join(root, os.path.basename(os.path.dirname(src)))
            dst = os.path.join(dst_dir, os.path.basename(src))
            try:
                os.makedirs(dst_dir, exist_ok=True)
                if os.path.exists(dst):
                    base, ext = os.path.splitext(dst)
                    dst = '%s (%s)%s' % (base, stamp, ext)
                shutil.move(src, dst)
            except Exception as e:
                failed.append('%s: %s' % (os.path.basename(src), e))
                continue
            log.write('%s\t%s\n' % (src, dst))
            myDB.upsert('issues', {'Status': 'Archived', 'Location': None}, {'IssueID': iid})
            moved += 1
            series.add(cid)
    logger.info('[LEDGER] Moved %s single issues duplicated by trades to %s (undo list: %s)' % (moved, root, undo))

    def rescan():
        from mylar import updater
        for cid in series:
            try:
                updater.forceRescan(cid)
            except Exception as e:
                logger.warn('[LEDGER] Rescan of %s failed: %s' % (cid, e))
    threading.Thread(target=rescan, name='LEDGER-RESCAN', daemon=True).start()
    return {'ok': not failed, 'moved': moved, 'failed': failed, 'skipped': skipped, 'dest': root, 'undo': undo}
