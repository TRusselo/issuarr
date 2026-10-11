# Parallel direct downloads

Design · 2026-10-11 · draft for review
Follow-up: spec B, leftover files and resuming after a restart.

## What happened on 2026-10-11

- JD2 got four jobs and gave up on all four: Fearless Defenders (offline), Age of Ultron #1–10AI (blocked by Cloudflare on the GetComics link), What If? Vol. 2 and Kick-Ass 3 #1–8 (file not found after "rate limit reached").
- When JD2 gives up, `jd2_fallback` (`mylar/queues/jd2.py`) hands the item to GetComics direct, whatever its size, and never tries Issuarr's own Mega, MediaFire or Pixeldrain downloaders. Age of Ultron is 617 MB, over the 400 MB big-file limit, and came from the GetComics server at about 420 KB/s from 12:10.
- Direct downloads run on one thread (`ddl_downloader`, `mylar/queues/ddl.py`). Star-Lord #4, I Am Groot #1 and #4, Guardians of the Galaxy – The Telltale Series #2 (all GetComics direct) and Kick-Ass 3 (handed back by JD2) waited behind Age of Ultron.
- After a restart at 12:18, Kick-Ass 3 went to Issuarr's own Pixeldrain downloader and arrived in 61 seconds (442 MB, about 7 MB/s). It only went there because its `ddl_info` row still said Pixeldrain: `jd2_fallback` changes the link in memory but not in the database.

Everything ended up on one thread and on the GetComics server, the opposite of what we want.

## Goals

1. GetComics direct downloads (Main Server, Download Now and Mirror Download links: `GC-Main`, `GC-Mirror`) run one at a time, never more, so GetComics isn't swamped.
2. File-host downloads (Mega, MediaFire, Pixeldrain and the external server) run in parallel, up to a setting.
3. A slow or stuck download only holds up its own worker.
4. Download workers only download and check the file. Finished files go to the post-processing queue, as today. Every failure, from Issuarr's downloaders or from JD2, goes to one failover worker that picks the next source or gives up.
5. When JD2 gives up, the next source follows the source order and the big-file rule, so big items go to file hosts before GetComics direct.
6. Downloads > Queue shows progress for every active download.

## Not in this spec

- How JD2 itself downloads. Its Cloudflare and rate-limit failures today are worth a separate look.
- SABnzbd, NZBGet and torrent clients.
- Leftover files, resuming after a restart and cleanup: spec B. This spec only makes every downloader record its file path, which spec B needs.
- A minimum-speed rule. A slow download that's still moving isn't a failure.

## Design

```
search / requeue / restart
          │
      DDL_QUEUE  (entry point, unchanged)
          │
     dispatcher ─────────── by link type ───────────┐
          │                                          │
 GetComics worker (1)                   file-host workers (N, default 3)
          │                                          │
          ├─ success ─► Completed ─► post-processing queue (unchanged)
          └─ failure ─► failover queue ◄── JD2 gives up
                              │
                      failover worker (1)
                              ├─ next source ─► DDL_QUEUE, or JD2 unless JD2 already gave up on the item
                              └─ none left ───► Failed (ddl_give_up, unchanged)
```

### Routing

| Item | Worker |
|---|---|
| GetComics site, link type `GC-Main`, `GC-Mirror` or none (older rows) | GetComics worker |
| everything else (`GC-Mega`, `GC-Media`, `GC-Pixel`, the external server) | file-host workers |

Unknown link types go to the file-host workers and fail there, as today.

### Setting

`DDL_MAX_PARALLEL` (int, DDL section, default 3), shown as "Simultaneous file-host downloads" on the settings page next to "Big means over". 0 sends every item to the GetComics worker: one download at a time, as before. It takes effect after a restart. The GetComics worker is always one and isn't a setting.

### Workers

Threads, started and stopped where the DDL queue is today (`mylar/__init__.py`).

- **Dispatcher**, named `DDL-QUEUE` so the status page still finds it. At startup it reloads saved items (`reload_saved`), as today. Then it moves each item from `DDL_QUEUE` to its worker's queue.
- **GetComics worker** `DDL-GETCOMICS`: one thread, its own queue.
- **File-host workers** `DDL-HOST-1` … `DDL-HOST-N`: N threads sharing one queue.
- **Failover worker** `DDL-FAILOVER`: one thread, its own queue. It owns the per-item list of failed link types (`link_type_failure`), which today lives inside the single worker.

A download worker runs today's `ddl_process` up to the download result. Success is handled as today: file check, `Completed`, post-processing queue, pack bookkeeping. On failure it puts the item and the result on the failover queue and takes its next item. An exception during a download counts as a failed attempt on that link.

The failover worker runs today's failure branch: `parse_downloadresults` with the failed link types queues the next source, or `ddl_give_up` marks the item Failed. `parse_downloadresults` writes the new `link` and `link_type` to `ddl_info` (in `_queue_links`), so the row always matches what's queued. An exception inside the failover worker gives up on the item, as today.

There's one failover worker, so GetComics pages are re-read one at a time, as today. It reads the cached page first when there is one.

### JD2 giving up

Today `jd2_fallback` swaps in the GetComics link and queues the item for GetComics direct. Instead, a JD2 give-up goes to the failover worker with JD2 marked as tried for that item. The failover worker picks the next source among Issuarr's own downloaders (GetComics direct, Mega, MediaFire, Pixeldrain) using the source order and the big-file rule, as at search time, and doesn't send the item back to JD2. When none is left, the item is marked Failed, as `jd2_mark_failed` does today.

### Shared state that assumes one download

| What | Today | Change |
|---|---|---|
| `mylar.DDL_LOCK` | `getcomics.downloadit()` sets it for the whole download and returns `None` if it's already set; `ddl_process` then indexes the `None` and the item ends up Failed | removed: the GetComics worker is the only thread that calls `downloadit` |
| `queues.ddl.ACTIVE` | one slot | set of active ids behind a lock |
| `waiting_ids()` | `DDL_QUEUE` plus the one active id | every queue plus every active id |
| waiting counts (`queue_info`, `check_ActiveDDL`) | `DDL_QUEUE.qsize()` | total across all queues |
| `mylar.DDL_QUEUED` | list; `downloadit` and `ddl_process` both append the same id; `remove` raises if it's gone | set: `add`, `discard` |
| `PACK_ISSUEIDS_DONT_QUEUE` in `ddl.py` | `del` while looping | `pop(key, None)` |
| `link_type_failure` | dict inside the single worker | owned by the failover worker |
| `_download_rate` (`webserve.py`) | one speed sample | one sample per download |
| `_active_ddl` / `check_ActiveDDL` | one active download | progress for every `Downloading` row; `check_ActiveDDL` still returns one, the most recently started, for the status bar |
| GetComics cookie file (`GC.cookie_receipt`) | written by the search thread and the download thread | writes go through a lock (the failover worker is a third writer) |

The database layer is already safe across threads (`db_lock` in `mylar/db.py`), and each worker opens its own connection, as the single worker does today.

### File path and progress

Every built-in downloader stores the full path of the file it's writing in `ddl_info.tmp_filename` before the first byte.

| Downloader | Today |
|---|---|
| GetComics direct | nothing |
| MediaFire | file name only |
| Pixeldrain | file name only; the progress code treats it as a path, so it can't find the file |
| Mega | full path of the library's temp file |

One function works out progress for any `Downloading` row from that path and `remote_filesize`. Downloads > Queue, `check_ActiveDDL` and the status bar use it.

### Stuck downloads and abort

- GetComics direct, MediaFire and Pixeldrain give up after 30 s without data (`timeout=(30, 30)`). The vendored Mega library has no timeout on the download (`lib/mega/mega.py:705`, `requests.get(file_url, stream=True)`); it gets the same one.
- Abort and Remove stop a download mid-transfer only for GetComics direct today. MediaFire's and Pixeldrain's chunk loops and Mega's progress hook will check `DDL_CANCEL` too, so aborting one download stops just that one.

### Shutdown and startup

Shutdown puts `exit` on `DDL_QUEUE`. The dispatcher passes it to every worker and the failover worker, and each is joined for up to 5 s, as today. Running downloads aren't waited for: Docker stop ends them, as it does today. Their rows stay `Downloading`, and `reload_saved` queues them again at the next start. Resuming them instead of starting over is spec B.

## Testing

pytest and mockito, next to `tests/test_queues.py`. Fake downloaders block on a `threading.Event`, so the tests control timing.

1. A stuck file-host download doesn't stop another file-host item from finishing.
2. A stuck file-host download doesn't stop a GetComics item.
3. Two GetComics items never download at the same time.
4. File-host downloads never exceed the setting; at 0 everything runs one at a time on the GetComics worker.
5. A failed download reaches the failover worker, which queues the next source; with none left the item ends Failed.
6. An exception during a download goes to failover.
7. A JD2 give-up for a big item goes to a file host before GetComics direct, and never back to JD2.
8. `waiting_ids()` includes items in every queue and every active download.
9. Downloads > Queue shows a percentage for two active downloads at once.
10. Shutdown stops the dispatcher, the workers and the failover worker.

The full suite (`run_all_tests`) passes.

On the server after deploying: the log shows two file-host downloads at the same time, and never two GetComics direct downloads at the same time.

## Rollout and rollback

Ships with 3 file-host workers. If something misbehaves, set "Simultaneous file-host downloads" to 0 and restart to get one download at a time again.

## Decisions to confirm

1. GetComics direct is fixed at one download at a time and isn't a setting.
2. The default is 3 simultaneous file-host downloads.
3. Changing the setting takes effect after a restart.
4. File-host links on GetComics are `getcomics.org/dls/…` redirects, so each file-host download starts with one small request to GetComics. With 3 workers that's at most 3 such requests at once. They aren't spaced out.
5. An exception during a download tries the next source instead of giving up straight away.
6. When JD2 gives up, Issuarr's own file-host downloaders are tried before GetComics direct, following the source order and the big-file rule. Today it goes straight to GetComics direct.
7. Abort works mid-download on every host.

**Settings change, no code:** the live source order is `["main","pixeldrain","vikingfile","mega","mediafire",…]`, so GetComics direct is the first choice for anything under 400 MB. Moving it after the file hosts would put most downloads on the parallel workers and take load off GetComics.

## Files

`mylar/queues/ddl.py` (dispatcher, workers, failover), `mylar/queues/jd2.py`, `mylar/queues/utils.py`, `mylar/__init__.py`, `mylar/getcomics.py`, `mylar/downloaders/mediafire.py`, `mylar/downloaders/pixeldrain.py`, `mylar/downloaders/mega.py`, `lib/mega/mega.py`, `mylar/config.py`, `mylar/webserve.py`, `mylar/downloadqueue.py`, `data/interfaces/default/config.html`, and tests.

## Spec B: leftovers (next)

Where leftover files come from:

- Partial GetComics direct files. A restart queues them with `resume=None`, so the old file is deleted and the download starts over. When the row's link was stale, the file is left behind instead (today's 197 MB Age of Ultron zip).
- Unpacked pack folders post-processing can't empty ("not empty. Skipping removal").
- Downloads that finish after an abort ("will not be post-processed").
- Mega temp files (`megapy_*`), written to the system temp folder with `delete=False`.
