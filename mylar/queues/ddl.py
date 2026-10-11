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
WORKER_POLL = 1.0               # seconds an idle worker waits before checking whether to stop
GC_SLOT = threading.Lock()      # held for every GetComics direct download - never two at once,
FAILOVER_SLOT = threading.Lock()  # even if a restarted queue briefly has two workers
FAILOVER_QUEUE = Queue()        # failed downloads, and items JD2 gave up on
FAILOVER = {}                   # str(id) -> {'failed': [link types], 'no_jd2': bool}


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
    ids = _ids(mylar.DDL_QUEUE) | _ids(GC_QUEUE) | _ids(FAILOVER_QUEUE)
    with LOCK:
        ids |= {str(i.get('id')) for i in PENDING}
        ids |= ACTIVE
    return ids


def waiting_count():
    """Items queued but not downloading yet, across every DDL queue."""
    with LOCK:
        pending = len(PENDING)
    return mylar.DDL_QUEUE.qsize() + GC_QUEUE.qsize() + FAILOVER_QUEUE.qsize() + pending


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
    # each worker drains the queue it was started with and stops on its own flag, so a worker
    # still busy when the queue is restarted finishes its item and leaves the rest to its replacement
    gc_queue, failover_queue = GC_QUEUE, FAILOVER_QUEUE
    stop = threading.Event()
    workers = [_start(gc_worker, 'DDL-GETCOMICS', gc_queue, stop),
               _start(failover_worker, 'DDL-FAILOVER', failover_queue, stop)]
    reload_saved(db.DBConnection())
    while True:
        try:
            item = queue.get(timeout=1)
        except Empty:
            item = None

        if item == 'exit':
            logger.info('Cleaning up workers for shutdown')
            STOP.set()
            stop.set()
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
        try:
            _start(host_download, 'DDL-HOST-%s' % item.get('id'), item)
        except Exception as e:
            # out of threads, most likely - put it back and try again on the next pass
            logger.warn('[DDL-QUEUE] Unable to start a download for %s: %s' % (item.get('series'), e))
            with LOCK:
                RUNNING[0] -= 1
                PENDING.appendleft(item)


def _next(q, stop):
    """The next item for a worker, or None once the worker should stop."""
    while not stop.is_set():
        try:
            item = q.get(timeout=WORKER_POLL)
        except Empty:
            continue
        if item == 'exit':
            return None
        if stop.is_set():
            q.put(item)  # leave it for the worker that replaced this one
            return None
        return item
    return None


def gc_worker(gc_queue, stop):
    while True:
        item = _next(gc_queue, stop)
        if item is None:
            break
        with GC_SLOT:
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
        try:
            result = ddl_process(db.DBConnection(), item)
        except Exception as e:
            logger.exception('[DDL-QUEUE] Error while downloading %s: %s' % (item.get('series'), e))
            result = {'success': False, 'filename': None, 'path': None, 'link_type_failure': item.get('link_type')}
        if result is not None:
            try:
                db.DBConnection().upsert('ddl_info', {'status': 'Queued'}, {'id': item['id']})  # not downloading while it waits
            except Exception as e:
                logger.warn('[DDL-QUEUE] Unable to mark %s as waiting for another source: %s' % (item.get('series'), e))
            send_to_failover(item, result)
    finally:
        with LOCK:
            ACTIVE.discard(key)


def send_to_failover(item, result, jd2_gave_up=False):
    FAILOVER_QUEUE.put({'item': item, 'result': result or {}, 'jd2_gave_up': jd2_gave_up})


def repick(item):
    """Restart a GetComics item by choosing its source again on the failover worker, so the source
    order and the big-file rule apply, rather than reusing whichever link was tried last."""
    forget(item['id'])
    FAILOVER_QUEUE.put({'item': item, 'result': {}, 'jd2_gave_up': False, 'repick': True})


def forget(record_id):
    FAILOVER.pop(str(record_id), None)


def failover_worker(failover_queue, stop):
    while True:
        entry = _next(failover_queue, stop)
        if entry is None:
            break
        item = entry['item']
        try:
            with FAILOVER_SLOT:
                handle_failure(db.DBConnection(), item, entry['result'], entry['jd2_gave_up'], entry.get('repick', False))
        except Exception as e:
            logger.exception('[DDL-FAILOVER] Error while looking for another source for %s: %s' % (item.get('series'), e))
            try:
                ddl_give_up(db.DBConnection(), item)
            except Exception as e2:
                logger.warn('[DDL-FAILOVER] Unable to mark %s as failed: %s' % (item.get('series'), e2))


def handle_failure(myDB, item, result, jd2_gave_up=False, repick=False):
    """Queue the item's next source, or mark it Failed when none is left.

    Runs on the one failover thread, so GetComics pages are re-read one at a time. Once JD2
    has given up on an item, only Issuarr's own downloaders are tried for it.
    """
    if str(item['id']) in mylar.DDL_CANCEL:
        ddl_cancelled(item)
        return
    key = str(item['id'])
    with LOCK:
        ACTIVE.add(key)  # counts as queued while it's handled, so a Restart can't queue it twice
    try:
        state = FAILOVER.setdefault(str(item['id']), {'failed': [], 'no_jd2': False})
        if repick:
            logger.info('[DDL-FAILOVER] Restarting %s - choosing its source again.' % item.get('series'))
        elif jd2_gave_up:
            state['no_jd2'] = True
            logger.info('[DDL-FAILOVER] JD2 gave up on %s - trying Issuarr\'s own downloaders.' % item.get('series'))
        else:
            link_type = item.get('link_type') or result.get('link_type_failure')
            if link_type and link_type in state['failed']:
                # this source was already tried and came back - retrying would loop (and re-read the page) forever
                logger.info('[DDL-FAILOVER] %s failed from %s again - giving up.' % (item.get('series'), link_type))
                ddl_give_up(myDB, item)
                return
            if link_type:
                state['failed'].append(link_type)
            logger.info('[DDL-FAILOVER] %s failed from %s - looking for another source.' % (item.get('series'), link_type))

        if item.get('site', 'DDL(GetComics)') != 'DDL(GetComics)':
            myDB.action('DELETE FROM ddl_info where id=?', [item['id']])
            mylar.search.FailedMark(item['issueid'], item['comicid'], item['id'], result.get('filename'), item['site'], retry=True)
            forget(item['id'])
            return

        if 'links_exhausted' in result or not item.get('mainlink'):
            ddl_give_up(myDB, item)
            return

        ggc = getcomics.GC(comicid=item.get('comicid'), issueid=item.get('issueid'), oneoff=item.get('oneoff'))
        if state['no_jd2']:
            ggc.jd2 = None
        # parse_downloadresults saves the next link to ddl_info and puts it back on DDL_QUEUE;
        # when nothing is left it only returns links_exhausted
        redo = ggc.parse_downloadresults(item['id'], item['mainlink'], item.get('comicinfo'), item.get('packinfo'), state['failed'])
        if isinstance(redo, dict) and 'links_exhausted' in redo:
            ddl_give_up(myDB, item)
    finally:
        with LOCK:
            ACTIVE.discard(key)


def ddl_process(myDB, item):
    """Download one item. Returns None when it's finished or dropped, or the failed result for the failover worker."""
    mylar.DDL_QUEUED.add(item['id'])

    if ddl_cancelled(item):
        return None

    logger.info('Now loading request from DDL queue: %s' % item['series'])

    ctrlval = {'id':      item['id']}
    val = {'status':       'Downloading',
           'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
    myDB.upsert('ddl_info', val, ctrlval)

    ddzstat = None
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

    if not ddzstat:
        ddzstat = {'success': False, 'filename': None, 'path': None, 'link_type_failure': item.get('link_type')}

    if ddl_cancelled(item, ddzstat):
        return None

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
        forget(item['id'])

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
        forget(item['id'])
        ddl_cleanup(item['id'])
    else:
        return ddzstat
    return None


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
    forget(item['id'])
    ddl_cleanup(item['id'])
    return True


def ddl_give_up(myDB, item):
    # every source for this item failed - mark it Failed instead of leaving the issue sitting at Snatched
    tried = FAILOVER.get(str(item['id']), {}).get('failed')
    logger.info('[REDO] Exhausted all available links [%s] for issueid %s and was not able to download anything' % (tried, item.get('issueid')))
    myDB.upsert('ddl_info', {'status': 'Failed',
                             'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}, {'id': item['id']})
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
    forget(item['id'])
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
