"""Queue info helpers."""

from collections import namedtuple

import mylar

QueueInfo = namedtuple("QueueInfo", ("name", "is_alive", "size"))


def queue_info():
    from .ddl import waiting_count
    yield from (
        QueueInfo(queue_name, thread_obj.is_alive() if thread_obj is not None else None,
                  size() if callable(size) else size.qsize())
        for (queue_name, thread_obj, size) in [
            ("AUTO-COMPLETE-NZB", mylar.NZBPOOL, mylar.NZB_QUEUE),
            ("AUTO-SNATCHER", mylar.SNPOOL, mylar.SNATCHED_QUEUE),
            ("DDL-QUEUE", mylar.DDLPOOL, waiting_count),
            ("JD2-QUEUE", mylar.JD2POOL, mylar.JD2_QUEUE),
            ("POST-PROCESS-QUEUE", mylar.PPPOOL, mylar.PP_QUEUE),
            ("SEARCH-QUEUE", mylar.SEARCHPOOL, mylar.SEARCH_QUEUE),
        ]
    )
