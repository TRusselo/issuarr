"""DDL queue worker functions.

A dispatcher thread (DDL-QUEUE) takes every item off mylar.DDL_QUEUE. GetComics' own
server links go to one GetComics worker (DDL-GETCOMICS), so GetComics only ever serves
one download at a time. File-host links (Mega, MediaFire, Pixeldrain, the external
server) each get a thread of their own (DDL-HOST-<id>), as many at once as
CONFIG.DDL_MAX_PARALLEL allows. The setting is read whenever a download is about to
start, so a change applies to the next one; 0 sends everything to the GetComics worker.
"""

import collections
import datetime
import os
import re
import threading
from queue import Empty, Queue

import mylar
from .. import logger, helpers
from mylar import db, getcomics
from mylar.downloaders import mediafire, mega, pixeldrain


GC_LINK_TYPES = (None, 'GC-Main', 'GC-Mirror')

GC_QUEUE = Queue()              # GetComics direct items, one at a time
PENDING = collections.deque()   # file-host items waiting for a free slot
ACTIVE = set()                  # ids downloading right now
RUNNING = [0]                   # file-host downloads running right now
LOCK = threading.Lock()         # guards PENDING, ACTIVE and RUNNING
STOP = threading.Event()
LINK_TYPE_FAILURE = {}          # id -> link types that failed for it


def max_parallel():
    try:
        return max(0, int(getattr(mylar.CONFIG, 'DDL_MAX_PARALLEL', 3)))
    except (TypeError, ValueError):
        return 3


def is_getcomics(item):
    return item.get('site', 'DDL(GetComics)') == 'DDL(GetComics)' and item.get('link_type') in GC_LINK_TYPES


def _ids(q):
    with q.mutex:
        entries = list(q.queue)
    return {str(e.get('item', e).get('id')) for e in entries if isinstance(e, dict)}


def waiting_ids():
    ids = _ids(mylar.DDL_QUEUE) | _ids(GC_QUEUE)
    with LOCK:
        ids |= {str(i.get('id')) for i in PENDING}
        ids |= ACTIVE
    return ids


def waiting_count():
    """Items queued but not downloading yet, across every DDL queue."""
    with LOCK:
        pending = len(PENDING)
    return mylar.DDL_QUEUE.qsize() + GC_QUEUE.qsize() + pending


def reload_saved(myDB):
    try:
        myDB.action("UPDATE ddl_info SET status='Queued' WHERE status='Downloading' AND jd2_job_id IS NULL")
        chk = myDB.selectone("SELECT count(*) AS count FROM ddl_info WHERE status='Queued' AND jd2_job_id IS NULL").fetchone()
        if chk and chk['count']:
            from mylar import webserve
            logger.info('[DDL-QUEUE] Picking up %s downloads that were waiting when Mylar stopped.' % chk['count'])
            webserve.WebInterface().ddl_requeue(mode='restart_queue')
    except Exception as e:
        logger.warn('[DDL-QUEUE] Unable to reload the saved queue: %s' % e)


def _start(target, name, *args):
    thread = threading.Thread(target=target, args=args, name=name, daemon=True)
    thread.start()
    return thread


def ddl_downloader(queue):
    STOP.clear()
    workers = [_start(gc_worker, 'DDL-GETCOMICS')]
    reload_saved(db.DBConnection())
    while True:
        try:
            item = queue.get(timeout=1)
        except Empty:
            item = None

        if item == 'exit':
            logger.info('Cleaning up workers for shutdown')
            STOP.set()
            GC_QUEUE.put('exit')
            for worker in workers:
                worker.join(5)
            break

        if item is not None:
            route(item)
        start_waiting()


def route(item):
    if is_getcomics(item) or max_parallel() == 0:
        GC_QUEUE.put(item)
    else:
        with LOCK:
            PENDING.append(item)


def start_waiting():
    """Start waiting file-host downloads while the setting allows more."""
    limit = max_parallel()
    moved, starting = [], []
    with LOCK:
        if limit == 0:
            moved = list(PENDING)
            PENDING.clear()
        else:
            while PENDING and RUNNING[0] < limit and not STOP.is_set():
                RUNNING[0] += 1
                starting.append(PENDING.popleft())
    for item in moved:
        GC_QUEUE.put(item)
    for item in starting:
        _start(host_download, 'DDL-HOST-%s' % item.get('id'), item)


def gc_worker():
    while True:
        item = GC_QUEUE.get()
        if item == 'exit':
            break
        run_download(item)


def host_download(item):
    try:
        run_download(item)
    finally:
        with LOCK:
            RUNNING[0] -= 1


def run_download(item):
    key = str(item.get('id'))
    with LOCK:
        ACTIVE.add(key)
    try:
        ddl_process(db.DBConnection(), item)
    except Exception as e:
        logger.exception('[DDL-QUEUE] Error while handling %s: %s' % (item.get('series'), e))
        try:
            ddl_give_up(db.DBConnection(), item, {'id': item['id']}, LINK_TYPE_FAILURE)
        except Exception as e2:
            logger.warn('[DDL-QUEUE] Unable to mark %s as failed: %s' % (item.get('series'), e2))
    finally:
        with LOCK:
            ACTIVE.discard(key)


def ddl_process(myDB, item, link_type_failure=None):
    if link_type_failure is None:
        link_type_failure = LINK_TYPE_FAILURE
    mylar.DDL_QUEUED.add(item['id'])

    try:
        link_type_failure[item['id']].append(item['link_type_failure'])
    except Exception:
        pass

    if ddl_cancelled(item):
        return

    logger.info('Now loading request from DDL queue: %s' % item['series'])

    ctrlval = {'id':      item['id']}
    val = {'status':       'Downloading',
           'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
    myDB.upsert('ddl_info', val, ctrlval)

    if item['site'] == 'DDL(GetComics)':
        try:
            remote_filesize = item['remote_filesize']
        except Exception:
            try:
                remote_filesize = helpers.human2bytes(re.sub('/s', '', item['size'][:-1]).strip())
            except Exception:
                remote_filesize = 0

        if any([item['link_type'] == 'GC-Main', item['link_type'] == 'GC-Mirror']):
            ddz = getcomics.GC()
            ddzstat = ddz.downloadit(item['id'], item['link'], item['mainlink'], item['resume'], item['issueid'], remote_filesize)
        elif item['link_type'] == 'GC-Mega':
            meganz = mega.MegaNZ()
            ddzstat = meganz.ddl_download(item['link'], None, item['id'], item['issueid'], item['link_type'])
        elif item['link_type'] == 'GC-Media':
            mediaf = mediafire.MediaFire()
            ddzstat = mediaf.ddl_download(item['link'], item['id'], item['issueid'])
        elif item['link_type'] == 'GC-Pixel':
            pdrain = pixeldrain.PixelDrain()
            ddzstat = pdrain.ddl_download(item['link'], item['id'], item['issueid'])
        else:
            ddzstat = {'success': False, 'filename': None, 'path': None, 'link_type': item['link_type']}

    elif item['site'] == 'DDL(External)':
        meganz = mega.MegaNZ()
        ddzstat = meganz.ddl_download(item['link'], item['filename'], item['id'], item['issueid'], item['link_type'])

    if ddl_cancelled(item, ddzstat):
        return

    if ddzstat['success'] and ddzstat['filename'] is not None:
        filecondition = helpers.check_file_condition(ddzstat['path'])
        if not filecondition['status']:
            logger.warn(f"CRC Check: File {ddzstat['path']} failed condition check ({filecondition['quality']}).  Marking as failed.")
            ddzstat['success'] = False
            ddzstat['link_type_failure'] = item['link_type']

    if ddzstat['success'] is True:
        tdnow = datetime.datetime.now()
        nval = {'status':  'Completed',
                'updated_date': tdnow.strftime('%Y-%m-%d %H:%M')}
        myDB.upsert('ddl_info', nval, ctrlval)

    if all([ddzstat['success'] is True, mylar.CONFIG.POST_PROCESSING is True]):
        try:
            if ddzstat['filename'] is None:
                logger.info('%s successfully downloaded - now initiating post-processing for %s.' % (os.path.basename(ddzstat['path']), ddzstat['path']))
                mylar.PP_QUEUE.put({'nzb_name':     os.path.basename(ddzstat['path']),
                                    'nzb_folder':   ddzstat['path'],
                                    'failed':       False,
                                    'issueid':      None,
                                    'comicid':      item['comicid'],
                                    'apicall':      True,
                                    'ddl':          True,
                                    'download_info': {'provider': 'DDL', 'id': item['id']}})
            else:
                logger.info('%s successfully downloaded - now initiating post-processing for %s' % (ddzstat['filename'], ddzstat['path']))
                mylar.PP_QUEUE.put({'nzb_name':     ddzstat['filename'],
                                    'nzb_folder':   ddzstat['path'],
                                    'failed':       False,
                                    'issueid':      item['issueid'],
                                    'comicid':      item['comicid'],
                                    'apicall':      True,
                                    'ddl':          True,
                                    'download_info': {'provider': 'DDL', 'id': item['id']}})
        except Exception as e:
            logger.error('process error: %s [%s]' %(e, ddzstat))

        mylar.DDL_QUEUED.discard(item['id'])
        try:
            link_type_failure.pop(item['id'])
        except KeyError:
            pass

        try:
            pck_cnt = 0
            if item['comicinfo'][0]['pack'] is True:
                logger.fdebug('[PACK DETECTION] Attempting to remove issueids from the pack dont-queue list')
                for x,y in dict(mylar.PACK_ISSUEIDS_DONT_QUEUE).items():
                    if y == item['id']:
                        pck_cnt +=1
                        mylar.PACK_ISSUEIDS_DONT_QUEUE.pop(x, None)
                logger.fdebug('Successfully removed %s issueids from pack queue list as download is completed.' % pck_cnt)
        except Exception:
            pass

        ddl_cleanup(item['id'])

    elif all([ddzstat['success'] is True, mylar.CONFIG.POST_PROCESSING is False]):
        path = ddzstat['path']
        if ddzstat['filename'] is not None:
            path = os.path.join(path, ddzstat['filename'])
        logger.info('File successfully downloaded. Post Processing is not enabled - item retained here: %s' % (path,))
        ddl_cleanup(item['id'])
    else:
        if item['site'] == 'DDL(GetComics)':
            try:
                ltf = ddzstat['links_exhausted']
            except KeyError:
                logger.info('[Status: %s] Failed to download item from %s : %s ' % (ddzstat['success'], item['link_type'], ddzstat))
                try:
                    link_type_failure[item['id']].append(item['link_type'])
                except KeyError:
                    link_type_failure[item['id']] = [item['link_type']]
                logger.fdebug('[%s] link_type_failure: %s' % (item['id'], link_type_failure))
                ggc = getcomics.GC(comicid=item['comicid'], issueid=item['issueid'], oneoff=item['oneoff'])
                redo = ggc.parse_downloadresults(item['id'], item['mainlink'], item['comicinfo'], item['packinfo'], link_type_failure[item['id']])
                # parse_downloadresults re-queues the next link itself; when none are left it
                # only returns links_exhausted, so the item has to be failed here.
                if isinstance(redo, dict) and 'links_exhausted' in redo:
                    ddl_give_up(myDB, item, ctrlval, link_type_failure)
            else:
                ddl_give_up(myDB, item, ctrlval, link_type_failure)
        else:
            logger.info('[Status: %s] Failed to download item from %s : %s ' % (ddzstat['success'], item['site'], ddzstat))
            myDB.action('DELETE FROM ddl_info where id=?', [item['id']])
            mylar.search.FailedMark(item['issueid'], item['comicid'], item['id'], ddzstat['filename'], item['site'], retry=True)


def ddl_cancelled(item, ddzstat=None):
    if str(item['id']) not in mylar.DDL_CANCEL:
        if ddzstat is None or not ddzstat.get('cancelled'):
            return False
    mylar.DDL_CANCEL.discard(str(item['id']))
    logger.info('[DDL-ABORT] Dropped %s - it was aborted or removed from the queue.' % item['series'])
    if ddzstat and ddzstat.get('success') and ddzstat.get('path'):
        logger.info('[DDL-ABORT] The finished download was left at %s and will not be post-processed.' % ddzstat['path'])
    helpers.reverse_the_pack_snatch(item['id'], item['comicid'])
    for x, y in dict(mylar.PACK_ISSUEIDS_DONT_QUEUE).items():
        if y == item['id']:
            mylar.PACK_ISSUEIDS_DONT_QUEUE.pop(x, None)
    mylar.DDL_QUEUED.discard(item['id'])
    ddl_cleanup(item['id'])
    return True


def ddl_give_up(myDB, item, ctrlval, link_type_failure):
    # every link for this item failed - mark it Failed instead of leaving the issue sitting at Snatched
    logger.info('[REDO] Exhausted all available links [%s] for issueid %s and was not able to download anything' % (link_type_failure.get(item['id']), item['issueid']))
    myDB.upsert('ddl_info', {'status': 'Failed',
                             'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}, ctrlval)
    helpers.reverse_the_pack_snatch(item['id'], item['comicid'])
    try:
        is_pack = item['comicinfo'][0]['pack'] is True
    except Exception:
        is_pack = False
    if all([not is_pack, not item.get('oneoff'), item.get('issueid') is not None]):
        try:
            mylar.search.FailedMark(item['issueid'], item['comicid'], item['id'], item['series'], item['site'], retry=True)
        except Exception as e:
            logger.warn('[REDO] Unable to mark issueid %s as Failed: %s' % (item['issueid'], e))
    mylar.DDL_QUEUED.discard(item['id'])
    link_type_failure.pop(item['id'], None)
    ddl_cleanup(item['id'])


def ddl_cleanup(record_id):
    if getattr(mylar.CONFIG, 'KEEP_HTML_CACHE', False):
        logger.fdebug('[HTML-cleanup] KEEP_HTML_CACHE enabled; skipping removal for %s.', record_id)
        return

    tlnk = 'getcomics-%s.html' % record_id
    cache_path = os.path.join(mylar.CONFIG.CACHE_DIR, 'html_cache', tlnk)
    try:
        os.remove(cache_path)
    except FileNotFoundError:
        logger.fdebug('[HTML-cleanup] %s not found in html_cache. Nothing to remove.', tlnk)
    except Exception as e:
        logger.fdebug('[HTML-cleanup] Unable to remove %s from html_cache: %s. '
                      'Manual removal required or set `cleanup_cache=True` in the config.ini to '
                      'clean cache items on every startup. If this was a Retry - ignore this.',
                      tlnk, e)
