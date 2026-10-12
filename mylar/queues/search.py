"""Search queue worker."""

import time
from pathlib import Path

import mylar
from .. import logger, helpers, archives, activity


# Items put back because filing could include them: issueid -> when it was first held.
HELD = {}
HOLD_LIMIT = 1800


def held(item):
    """Put an item back while filing could still be handling this issue, so an issue that's
    already downloaded isn't grabbed again. Other items search in the meantime."""
    key = item.get('issueid')
    if not archives.holds(item.get('comicid'), key):
        HELD.pop(key, None)
        return False
    first = key not in HELD
    since = HELD.setdefault(key, time.time())
    if time.time() - since > HOLD_LIMIT:
        logger.info('[SEARCH-QUEUE] %s #%s waited %s minutes for filing - searching anyway.'
                    % (item.get('comicname'), item.get('issuenumber'), HOLD_LIMIT // 60))
        HELD.pop(key, None)
        return False
    if first:
        logger.info('[SEARCH-QUEUE] Filing may include %s - searching #%s after it, so an issue already downloaded isn\'t grabbed again.'
                    % (item.get('comicname'), item.get('issuenumber')))
    return True


def search_queue(queue):
    while True:
        if mylar.SEARCHLOCK is True:
            time.sleep(5)

        elif mylar.SEARCHLOCK is False and queue.qsize() >= 1:
            item = queue.get(True)
            if item == 'exit':
                logger.info('[SEARCH-QUEUE] Cleaning up workers for shutdown')
                break
            if isinstance(item, dict) and held(item):
                queue.put(item)
                # every item waiting on filing: don't spin through them
                time.sleep(5 if len(HELD) >= queue.qsize() else 0.2)
                continue

            gumbo_line = True
            if item['issueid'] in mylar.PACK_ISSUEIDS_DONT_QUEUE:
                if mylar.PACK_ISSUEIDS_DONT_QUEUE[item['issueid']] in mylar.DDL_QUEUED:
                    logger.fdebug('[SEARCH-QUEUE-PACK-DETECTION] %s already queued to download via pack...Ignoring' % item['issueid'])
                    gumbo_line = False

            if gumbo_line:
                logger.fdebug('[SEARCH-QUEUE] Now loading item from search queue: %s' % item)
                if mylar.SEARCHLOCK is False:
                    arcid = None
                    comicid = item['comicid']
                    issueid = item['issueid']
                    if issueid is not None and '_' in issueid:
                        arcid = issueid
                        comicid = None
                        issueid = None
                    mofo = mylar.filers.FileHandlers(ComicID=comicid, IssueID=issueid, arcID=arcid)
                    local_check = mofo.walk_the_walk()

                    if local_check['status']:
                        fullpath = Path(local_check['filepath']) / local_check['filename']
                        filecondition = helpers.check_file_condition(fullpath)
                        if not filecondition['status']:
                            logger.warn(f"CRC Check: File {fullpath} failed condition check ({filecondition['quality']}).  Ignoring.")
                            local_check['status'] = False

                    if local_check['status'] is True:
                        activity.searched(item, time.time(), on_disk=True)
                        mylar.PP_QUEUE.put({
                            'nzb_name':     local_check['filename'],
                            'nzb_folder':   local_check['filepath'],
                            'failed':       False,
                            'issueid':      item['issueid'],
                            'comicid':      item['comicid'],
                            'apicall':      True,
                            'ddl':          False,
                            'download_info': None,
                        })
                    else:
                        try:
                            manual = item['manual']
                        except Exception:
                            manual = False
                        mylar.SEARCH_CURRENT = item
                        started = time.time()
                        try:
                            mylar.search.searchforissue(item['issueid'], manual=manual)
                        finally:
                            mylar.SEARCH_CURRENT = None
                            activity.searched(item, started)
                    time.sleep(5)

            if mylar.SEARCHLOCK is True:
                logger.fdebug('[SEARCH-QUEUE] Another item is currently being searched....')
                time.sleep(15)
        else:
            time.sleep(5)
