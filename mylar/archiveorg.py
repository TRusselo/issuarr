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

"""The Internet Archive as a direct-download search source for Wanted issues.

Comics there live in the "comics" collection as items holding one issue or a run of 50 or
100, each issue an original .cbr/.cbz/.zip named like a release ("Action Comics 151
(12-1950).cbr"). An item can be filed as texts or image, so the search goes by collection
and file format, not media type. Every comic file is offered to the usual matcher as a
result of its own, so a pack item works like a shelf of single issues.

Files in runs often carry no year ("Action Comics 401.cbr"). Those only count when the
item's date puts the wanted issue inside the run, and get the issue's year added so the
matcher's year check still guards against a later volume with the same numbers.

A .zip of page images is renamed .cbz once downloaded, so filing, WebP conversion and
tagging treat it like any other comic.
"""

import datetime
import hashlib
import os
import re
import time
import urllib.parse
import zipfile

import requests

import mylar
from mylar import db, logger, search_filer

SITE = 'DDL(Internet Archive)'
LINK_TYPE = 'IA'
SEARCH_URL = 'https://archive.org/advancedsearch.php'
META_URL = 'https://archive.org/metadata/%s'
DOWNLOAD_URL = 'https://archive.org/download/%s/%s'
FORMATS = ('Comic Book RAR', 'Comic Book ZIP', 'Comic Book 7Z', 'ZIP')
COMIC_EXT = ('.cbr', '.cbz', '.cb7', '.zip')
PAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.jxl', '.avif')
ITEMS = 20              # items whose file lists are read for one search
RUN_YEARS = 12          # how far past its date an item's year-less files may reach
CACHE_TTL = 6 * 3600    # file lists are kept this long: a series' Wanted issues share items
_CACHE = {}             # identifier -> (fetched at, files)
HEADERS = {'User-Agent': 'Issuarr (+https://github.com/issuarr/issuarr)'}


def session():
    s = requests.Session()
    s.headers.update(HEADERS)
    if getattr(mylar.CONFIG, 'ENABLE_PROXY', False):
        s.proxies.update({'http': mylar.CONFIG.HTTP_PROXY, 'https': mylar.CONFIG.HTTPS_PROXY})
    return s


def _year(text):
    m = re.search(r'(?<!\d)(1[89]\d\d|20\d\d)(?!\d)', str(text or ''))
    return int(m.group(1)) if m else None


def number_token(issue):
    """'0401' -> a pattern for 401 standing alone in a file name; None when there's no number."""
    issue = str(issue or '').strip()
    if not issue or issue == 'None':
        return None
    m = re.match(r'^0*(\d+)(.*)$', issue)
    if m:
        return re.compile(r'(?<![\d.(])0*%s%s(?!\d|\.\d)' % (m.group(1), re.escape(m.group(2))), re.I)
    return re.compile(r'(?<!\w)%s(?!\w)' % re.escape(issue), re.I)


def query_for(name):
    words = re.sub(r'\s+', ' ', re.sub(r'[^\w\s\']', ' ', str(name or ''))).strip()
    formats = ' OR '.join('"%s"' % f for f in FORMATS)
    return 'collection:(comics) AND title:("%s") AND format:(%s)' % (words.replace('"', ''), formats)


def _stamp(iso):
    """'2021-08-14T19:23:02Z' -> the RFC 822 date the matcher reads posting dates in."""
    try:
        dt = datetime.datetime.strptime(str(iso)[:19], '%Y-%m-%dT%H:%M:%S')
    except (TypeError, ValueError):
        dt = datetime.datetime.now()
    return dt.strftime('%a, %d %b %Y %H:%M:%S')


def rank(items, year, token=None):
    """Items named for the wanted issue first, then those nearest its year (a run starts on
    its date), undated ones last."""
    def key(it):
        named = token is not None and any(token.search(str(it.get(k) or '').replace('-', ' ')) for k in ('title', 'identifier'))
        y = _year(it.get('date'))
        if y is None or not year:
            return (0 if named else 1, 2, 0)
        return (0 if named else 1, 0 if y <= year else 1, abs(year - y))
    return sorted(items, key=key)


def comic_files(files):
    for f in files or []:
        name = f.get('name') or ''
        if f.get('source') == 'original' and name.lower().endswith(COMIC_EXT):
            yield f


def entries_for(item, files, token, year):
    """Search results for the files of one item that might be the wanted issue."""
    item_year = _year(item.get('date'))
    for f in comic_files(files):
        base, ext = os.path.splitext(os.path.basename(f['name']))
        if token is not None and not token.search(base):
            continue
        # "(DC)" is the publisher here, but the file name parser reads it as Director's Cut
        title = re.sub(r'\s*\(DC\)', '', base).strip()
        if _year(base) is None:
            # a run's file without a year: only when the run's date reaches the wanted issue
            if not (year and item_year and item_year - 1 <= year <= item_year + RUN_YEARS):
                continue
            title = '%s (%s)' % (title, year)
        try:
            size = int(f.get('size') or 0)
        except (TypeError, ValueError):
            size = 0
        yield {
            'title': title,
            'filename': os.path.basename(f['name']),
            'pubdate': _stamp(item.get('publicdate')),
            'size': str(size),
            'pack': False,
            'issues': None,
            'series': None,
            'year': str(year or item_year or ''),
            'link': DOWNLOAD_URL % (item['identifier'], urllib.parse.quote(f['name'])),
            'id': 'IA-' + hashlib.sha1(('%s/%s' % (item['identifier'], f['name'])).encode('utf-8')).hexdigest()[:16],
            'item': item['identifier'],
            'site': SITE,
        }


class IA(object):

    def __init__(self, query=None, provider_stat=None):
        self.query = query or {}
        self.provider_stat = provider_stat or {'lastrun': 0, 'hits': 0}
        self.session = session()

    def items(self):
        r = self.session.get(SEARCH_URL, timeout=(30, 30), params={
            'q': query_for(self.query.get('comicname')), 'fl[]': ['identifier', 'title', 'date', 'publicdate'],
            'rows': 100, 'output': 'json'})
        r.raise_for_status()
        try:
            from mylar import search
            now = time.time()
            search.last_run_check(write={SITE: {'id': 202, 'active': True, 'lastrun': now, 'type': 'DDL',
                                                'hits': self.provider_stat.get('hits', 0) + 1}})
            self.provider_stat['lastrun'] = now
        except Exception as e:
            logger.fdebug('[INTERNET-ARCHIVE] Could not note the search time: %s' % e)
        docs = r.json().get('response', {}).get('docs', [])
        logger.fdebug('[INTERNET-ARCHIVE] %s items for %s' % (len(docs), self.query.get('comicname')))
        return docs

    def files(self, identifier):
        hit = _CACHE.get(identifier)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        r = self.session.get(META_URL % identifier, timeout=(30, 30))
        r.raise_for_status()
        files = r.json().get('files', [])
        _CACHE[identifier] = (time.time(), files)
        return files

    def results(self, year):
        token = number_token(self.query.get('issue'))
        for item in rank(self.items(), year, token)[:ITEMS]:
            try:
                files = self.files(item['identifier'])
            except Exception as e:
                logger.fdebug('[INTERNET-ARCHIVE] Could not list %s: %s' % (item['identifier'], e))
                continue
            for entry in entries_for(item, files, token, year):
                yield entry

    def search(self, is_info=None):
        try:
            year = int(str((is_info or {}).get('ComicYear') or self.query.get('year'))[:4])
        except (TypeError, ValueError):
            year = None
        try:
            match = search_filer.search_check().check_for_first_result(self.results(year), is_info, prefer_pack=False)
        except requests.exceptions.RequestException as e:
            logger.warn('[INTERNET-ARCHIVE] Search failed: %s' % e)
            return 'no results'
        return [match] if match is not None else 'no results'


def queue(nzbid, link, comicinfo):
    """Save the grab to ddl_info and hand it to the download queue."""
    info = comicinfo[0]
    issueid = info.get('IssueArcID') if info.get('IssueID') is None else info.get('IssueID')
    entry = info.get('entry') or {}
    vals = {'series': info.get('ComicName'), 'year': info.get('comyear'), 'size': info.get('size'),
            'issues': info.get('IssueNumber'), 'issueid': issueid, 'comicid': info.get('ComicID'), 'link': link,
            'mainlink': link, 'site': SITE, 'pack': False, 'link_type': LINK_TYPE, 'filename': info.get('nzbtitle'),
            'remote_filesize': str(entry.get('size') or 0), 'status': 'Queued', 'tmp_filename': None,
            'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
    db.DBConnection().upsert('ddl_info', vals, {'id': nzbid})
    mylar.DDL_QUEUE.put({'link': link, 'mainlink': link, 'series': vals['series'], 'year': vals['year'], 'size': vals['size'],
                         'comicid': vals['comicid'], 'issueid': issueid, 'oneoff': info.get('oneoff'), 'id': nzbid,
                         'link_type': LINK_TYPE, 'filename': vals['filename'], 'comicinfo': comicinfo, 'packinfo': None,
                         'site': SITE, 'remote_filesize': vals['remote_filesize'], 'resume': None})
    return {'success': True, 'site': LINK_TYPE}


class Cancelled(Exception):
    pass


def as_comic(path):
    """A downloaded .zip as something filing reads: page images become a .cbz, a zip of
    comics is unpacked into a folder. Returns {'success', 'filename', 'path'}."""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if not n.endswith('/')]
    except zipfile.BadZipFile as e:
        logger.warn('[INTERNET-ARCHIVE] %s is not a readable zip: %s' % (os.path.basename(path), e))
        return {'success': False, 'filename': None, 'path': None, 'link_type_failure': LINK_TYPE}
    comics = [n for n in names if n.lower().endswith(COMIC_EXT[:-1])]
    pages = [n for n in names if n.lower().endswith(PAGE_EXT)]
    if pages and not comics:
        target = os.path.splitext(path)[0] + '.cbz'
        os.replace(path, target)
        return {'success': True, 'filename': os.path.basename(target), 'path': target}
    if comics:
        folder = os.path.splitext(path)[0]
        with zipfile.ZipFile(path) as z:
            for n in comics:
                out = os.path.join(folder, os.path.basename(n))
                os.makedirs(folder, exist_ok=True)
                with z.open(n) as src, open(out, 'wb') as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
        os.remove(path)
        return {'success': True, 'filename': None, 'path': folder}
    logger.warn('[INTERNET-ARCHIVE] %s holds no pages or comics.' % os.path.basename(path))
    return {'success': False, 'filename': None, 'path': None, 'link_type_failure': LINK_TYPE}


def download(item):
    """Download one queued file. Returns the result ddl_process expects."""
    fail = {'success': False, 'filename': None, 'path': None, 'link_type_failure': LINK_TYPE}
    location = mylar.CONFIG.DDL_LOCATION
    if location and not os.path.isdir(location):
        if not mylar.filechecker.validateAndCreateDirectory(location, True):
            logger.warn('[INTERNET-ARCHIVE] Could not create the download folder %s' % location)
            return fail
    name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(item['link']).path))
    base, ext = os.path.splitext(name)
    filename = '%s[__%s__]%s' % (base, item['issueid'], ext)
    path = os.path.join(location, filename)
    myDB = db.DBConnection()
    myDB.upsert('ddl_info', {'tmp_filename': path, 'filename': filename}, {'id': item['id']})
    try:
        with session().get(item['link'], stream=True, timeout=(30, 60)) as r:
            r.raise_for_status()
            total = r.headers.get('Content-Length')
            if total:
                myDB.upsert('ddl_info', {'remote_filesize': str(total)}, {'id': item['id']})
            with open(path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if str(item['id']) in mylar.DDL_CANCEL:
                        raise Cancelled()
                    if chunk:
                        f.write(chunk)
    except Cancelled:
        logger.info('[INTERNET-ARCHIVE] Stopped downloading %s - it was cancelled.' % name)
        try:
            os.remove(path)
        except OSError:
            pass
        return dict(fail, cancelled=True)
    except Exception as e:
        logger.warn('[INTERNET-ARCHIVE] Download of %s failed: %s' % (name, e))
        try:
            os.remove(path)
        except OSError:
            pass
        return fail
    logger.info('[INTERNET-ARCHIVE] Downloaded %s' % name)
    if ext.lower() == '.zip':
        return as_comic(path)
    return {'success': True, 'filename': filename, 'path': path}
