"""JD2 queue worker."""

import datetime
import os
import time

import mylar
from .. import logger, helpers
from mylar import db
from . import ddl
from mylar.downloaders.jdownloader2 import JDownloader2

# The record id of the item the monitor is working on. It's out of the queue while the monitor
# checks it and sleeps before putting it back, but it's still at JD2.
HOLDING = [None]


def at_jd2():
    """Record ids handed to JD2: waiting in its queue, or being checked by the monitor."""
    ids = ddl._ids(mylar.JD2_QUEUE)
    if HOLDING[0] is not None:
        ids.add(HOLDING[0])
    return ids


def jd2_queue_monitor(queue):
    jd2_client = JDownloader2()
    myDB = db.DBConnection()
    while True:
        if queue.qsize() >= 1:
            item = queue.get(True)
            HOLDING[0] = str(item.get('id') or item.get('ID')) if isinstance(item, dict) else None
            if item == 'exit':
                logger.info('[JD2-QUEUE] Cleaning up workers for shutdown')
                break
            if item == 'startup':
                try:
                    pending_jd2 = myDB.select(
                        "SELECT * FROM ddl_info WHERE jd2_job_id IS NOT NULL AND status = 'Queued'"
                    )

                except Exception as err:
                    logger.warn('[JD2-QUEUE] Unable to repopulate JD2 monitor queue: %s', err)
                else:
                    logger.info('[JD2-QUEUE] Repopulating JD2 monitor queue')
                    for job in pending_jd2 or []:
                        job_data = dict(job)
                        job_id = job_data.get('jd2_job_id')
                        record_id = job_data.get('ID') or job_data.get('id')
                        series = job_data.get('series')
                        year = job_data.get('year')
                        filename = job_data.get('tmp_filename') or job_data.get('filename')
                        if not filename:
                            if series and year:
                                filename = f"{series} ({year}) - {record_id}"
                            elif series:
                                filename = series
                            elif record_id:
                                filename = str(record_id)
                        queue_payload = {
                            'link': job_data.get('link'),
                            'mainlink': job_data.get('mainlink'),
                            'series': series,
                            'year': year,
                            'size': job_data.get('size'),
                            'comicid': job_data.get('comicid'),
                            'issueid': job_data.get('issueid'),
                            'oneoff': job_data.get('oneoff'),
                            'id': record_id,
                            'link_type': job_data.get('link_type'),
                            'filename': filename,
                            'comicinfo': job_data.get('comicinfo'),
                            'packinfo': job_data.get('packinfo'),
                            'site': job_data.get('site') or 'DDL(GetComics)',
                            'remote_filesize': job_data.get('remote_filesize') or 0,
                            'resume': None,
                            'jd2_job_id': job_id,
                        }
                        queue.put(queue_payload)
                continue

            if item.get('jd2_job_id') == 0:
                jd2_priority_links = item.get('jd2_priority_links')
                queue_payload = dict(item)
                queue_payload.pop('jd2_job_id', None)
                queue_payload.pop('jd2_priority_links', None)
                if not jd2_priority_links:
                    logger.warn('Priority links don\'t exist; cannot process JD2 job. Falling back to DDL queue.')
                    mylar.DDL_QUEUE.put(queue_payload)
                    continue
                record_id = item.get('id') or item.get('ID')
                package_name = '%s (%s) - %s' % (item.get('series'), item.get('year'), record_id)
                submit_result = jd2_client.submit(jd2_priority_links, package_name, record_id)

                if not submit_result.get('status'):
                    logger.warn('[JD2] Submission failed for %s; falling back to DDL queue. Details: %s', package_name, submit_result)
                    mylar.DDL_QUEUE.put(queue_payload)
                else:
                    logger.debug('[JD2] Submission response for %s: %s', package_name, submit_result)
                    job_id = submit_result.get('jobid')
                    if not job_id:
                        mylar.DDL_QUEUE.put(queue_payload)
                        continue
                    queue_payload['jd2_job_id'] = job_id
                    mylar.JD2_QUEUE.put(queue_payload)
                    logger.info('[JD2] JD2 job %s submitted for %s', job_id, package_name)
                    time.sleep(10)
                    continue

            logger.info('[JD2-QUEUE] Now loading from queue: %s' % item)
            record_id = item.get('ID') or item.get('id')
            job_id = item.get('jd2_job_id')
            series = item.get('series')
            year = item.get('year')

            job_filename = None

            if jd2_client is not None and job_id:
                try:
                    status_payload = jd2_client.status(job_id, record_id)
                except Exception as err:
                    logger.warn('[JD2-QUEUE] Error polling job %s: %s', job_id, err)
                else:
                    logger.info('[JD2-QUEUE] status update for job %s (record %s): %s', job_id, record_id, status_payload)
                    job_status = (status_payload or {}).get('status')
                    job_found = (status_payload or {}).get('found')

                    completed_states = {'FINISHED', 'Finished', 'finished', 'DONE', 'Done', 'Extraction OK', '[SHA256] CRC OK', 'Finished(Mirror)'}
                    failed_states = {'ERROR', 'FAILED', 'Error', 'Failed'}

                    if not job_found:
                        stale = False
                        try:
                            row = myDB.selectone("SELECT updated_date FROM ddl_info WHERE id=?", [record_id]).fetchone()
                        except Exception as err:
                            logger.warning('JD2 stale check failed for record %s: %s', record_id, err)
                            updated_str = None
                        else:
                            if row is None:
                                logger.info('[JD2-QUEUE] No ddl_info entry found for id %s; dropping job %s from monitoring.', record_id, job_id)
                                continue
                            updated_str = row['updated_date']

                        if updated_str:
                            try:
                                updated_dt = datetime.datetime.strptime(updated_str, '%Y-%m-%d %H:%M')
                            except Exception:
                                stale = False
                            else:
                                stale = (datetime.datetime.now() - updated_dt) >= datetime.timedelta(minutes=3)

                        if stale:
                            jd2_give_up(myDB, item, record_id, 'job %s never reached the JD2 download list (links offline or rejected)' % job_id)
                            continue

                        queue.put(item)
                        time.sleep(10)
                        continue

                    if job_status in completed_states:
                        myDB.upsert(
                                'ddl_info',
                                {
                                    'status': 'Completed',
                                    'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
                                },
                                {'id': record_id},
                            )
                        logger.info('[JD2-QUEUE] Download for %s completed; status marked as Completed.', record_id)

                        job_filename = ((status_payload or {}).get('data') or {}).get('name')

                        if not isinstance(item, dict):
                            logger.warn('[JD2-QUEUE] Unexpected item type %s for job %s; skipping post-processing.', type(item), job_id)
                            continue
                        if mylar.CONFIG.POST_PROCESSING is True:
                            dest_root = getattr(mylar.CONFIG, 'JD2_DEST_DIR', None) or None
                            folder_name = (
                                "%s - %s" % (item.get('filename'), record_id)
                                if item.get('filename')
                                else "%s (%s) - %s" % (series, year, record_id)
                            )
                            nzb_folder = os.path.join(dest_root, folder_name)

                            if nzb_folder:
                                try:
                                    mylar.PP_QUEUE.put({
                                        'nzb_name': job_filename or 'Manual Run',
                                        'nzb_folder': nzb_folder,
                                        'failed': False,
                                        'issueid': item.get('issueid'),
                                        'comicid': item.get('comicid'),
                                        'apicall': True,
                                        'ddl': True,
                                        'download_info': {'provider': 'JD2', 'id': record_id, 'job_id': job_id},
                                    })
                                    logger.info('[JD2-QUEUE] Submitted %s for post-processing (folder: %s).', job_filename, nzb_folder)
                                    jd2_client.remove(job_id, record_id)
                                except Exception as err:
                                    logger.warn('[JD2-QUEUE] Unable to enqueue %s for post-processing: %s', job_filename, err)
                            else:
                                logger.warn('[JD2-QUEUE] JD2 destination is not configured; skipping post-processing enqueue for %s.', job_filename)
                        else:
                            logger.info('[JD2-QUEUE] Post-processing disabled, please manually handle your files.')
                        continue

                    if job_status in failed_states or jd2_status_is_dead(job_status):
                        reason = (status_payload or {}).get('reason') or job_status
                        logger.warn('[JD2-QUEUE] Download %s can not complete in JD2 (%s).', job_filename or record_id, reason)
                        jd2_client.remove(job_id, record_id)
                        jd2_give_up(myDB, item, record_id, 'JD2 status %s' % reason)
                        continue

                    if job_status not in completed_states:
                        time.sleep(10)
                        queue.put(item)
                        continue
            else:
                logger.warn('[JD2-QUEUE] Missing JD2 client or job id for item: %s', item)
                jd2_give_up(myDB, item, record_id, 'no JD2 job id to monitor')
        else:
            HOLDING[0] = None
            time.sleep(10)


JD2_DEAD_STATUS = ('offline', 'file not found', 'not available', 'plugin defect', 'aborted', 'blocked by cloudflare')


def jd2_give_up(myDB, item, record_id, reason):
    """JD2 couldn't finish the download. The DDL failover worker tries Issuarr's own downloaders
    for the same post, file hosts first for big files, and never JD2 again. Only when direct
    downloads are off, or the post can't be read again, is the issue marked Failed here."""
    job_id = item.get('jd2_job_id')
    if job_id:
        try:
            row = myDB.selectone('SELECT jd2_job_id FROM ddl_info WHERE id=?', [record_id]).fetchone()
        except Exception as err:
            logger.warn('[JD2-QUEUE] Unable to check the JD2 job for %s: %s', record_id, err)
            row = None
        current = row['jd2_job_id'] if row else None
        if current and str(current) != str(job_id):
            # Restart sent the item to JD2 again; the newer job carries on.
            logger.info('[JD2-QUEUE] Ignoring JD2 job %s for %s: it was replaced by job %s.', job_id, item.get('series') or record_id, current)
            return
    if HOLDING[0] == str(record_id):
        HOLDING[0] = None  # let go of it, or failover would think JD2 still has it
    if not item.get('mainlink') or not getattr(mylar.CONFIG, 'ENABLE_DDL', False):
        jd2_mark_failed(myDB, item, record_id, reason)
        return
    logger.info('[JD2-QUEUE] JD2 gave up on %s (%s) - trying Issuarr\'s own downloaders.', item.get('series') or record_id, reason)
    payload = dict(item)
    for k in ('jd2_job_id', 'jd2_priority_links', 'main_link'):
        payload.pop(k, None)
    payload['id'] = record_id
    payload.setdefault('resume', None)
    try:
        myDB.upsert('ddl_info', {'status': 'Queued', 'jd2_job_id': None,
                                 'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}, {'id': record_id})
    except Exception as err:
        logger.warn('[JD2-QUEUE] Unable to reset %s for the built-in downloaders: %s', record_id, err)
    ddl.send_to_failover(payload, {'success': False, 'reason': reason}, jd2_gave_up=True)


def jd2_status_is_dead(job_status):
    if not job_status:
        return False
    return any(x in str(job_status).lower() for x in JD2_DEAD_STATUS)


def jd2_mark_failed(myDB, item, record_id, reason):
    # mark both the ddl_info row and the issue itself Failed, so the issue doesn't sit at Snatched forever
    logger.info('[JD2-QUEUE] Giving up on %s: %s', item.get('series') or record_id, reason)
    try:
        myDB.upsert('ddl_info', {'status': 'Failed',
                                 'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')},
                    {'id': record_id})
    except Exception as err:
        logger.warn('[JD2-QUEUE] Unable to mark ddl_info %s as Failed: %s', record_id, err)

    issueid = item.get('issueid') or item.get('IssueID')
    comicid = item.get('comicid') or item.get('ComicID')
    pack = bool(item.get('pack'))
    try:
        pack = pack or item['comicinfo'][0]['pack'] is True
    except Exception:
        pass
    if not issueid and record_id:
        try:
            row = myDB.selectone('SELECT issueid, comicid, pack FROM ddl_info WHERE id=?', [record_id]).fetchone()
        except Exception:
            row = None
        if row is not None:
            issueid = row['issueid']
            comicid = comicid or row['comicid']
            pack = pack or bool(row['pack'])

    if pack:
        helpers.reverse_the_pack_snatch(record_id, comicid)
    elif all([issueid, issueid != 'None', not item.get('oneoff')]):
        try:
            mylar.search.FailedMark(issueid, comicid, record_id, item.get('series') or str(record_id), item.get('site') or 'DDL(GetComics)', retry=True)
        except Exception as err:
            logger.warn('[JD2-QUEUE] Unable to mark issueid %s as Failed: %s', issueid, err)
