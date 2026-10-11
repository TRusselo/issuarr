# Parallel Direct Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** File-host downloads (Mega, MediaFire, Pixeldrain, external server) run in parallel up to a live setting, GetComics direct downloads stay one at a time, and every failed download, JD2 give-ups included, goes to one failover worker.

**Architecture:** The single DDL thread (`ddl_downloader` in `mylar/queues/ddl.py`) becomes a dispatcher. It sends GetComics direct items to one GetComics worker thread and starts a short-lived thread per file-host item while fewer than `DDL_MAX_PARALLEL` are running, reading the setting each time. Download threads only download; failures go to one failover thread that runs today's "pick the next source" logic. Producers keep putting items on `mylar.DDL_QUEUE` unchanged.

**Tech Stack:** Python 3 (stdlib `threading`, `queue`, `collections`), SQLite through `mylar.db`, Mako templates, pytest + mockito.

**Spec:** `docs/superpowers/specs/2026-10-11-parallel-direct-downloads-design.md`

## Global Constraints

- GetComics direct (site `DDL(GetComics)` with link type `GC-Main`, `GC-Mirror` or none) downloads one at a time. This is not a setting.
- Setting `DDL_MAX_PARALLEL`: int, config section `DDL`, default `3`, labelled "Simultaneous file-host downloads". `0` sends every item to the GetComics worker (one at a time, as before). Read every time a file-host download is about to start; a negative value counts as `0`, an unreadable one as `3`.
- Changing the setting never interrupts a running download.
- Every producer keeps putting items on `mylar.DDL_QUEUE`; the item dict shape doesn't change.
- Thread names: `DDL-QUEUE` (dispatcher), `DDL-GETCOMICS`, `DDL-HOST-<id>`, `DDL-FAILOVER`.
- Python 3.8 syntax (the test README targets 3.8): no `match`, no `X | Y` type unions.
- New tests are marked `@pytest.mark.unit`; `tests/conftest.py` blocks `requests.get`, so no test touches the network.
- Run tests from the repo root: `python -m pytest <path> -q -p no:cacheprovider`. Baseline before Task 1: 452 passed, 1 failed (`tests/test_queues.py::test_ddl_cleanup_keep_cache`, fixed in Task 1 Step 1).

## Review Focus

1. The setting holds something unreadable (blank, text, negative): the dispatcher must not crash; blank/text means 3, negative means 0. (Task 1, `test_max_parallel_reads_bad_values_safely`)
2. A download raises: its slot must be freed so the next waiting item still starts. (Task 2, `test_exception_goes_to_failover_and_frees_the_slot`)
3. An item reaches failover without a `mainlink` (old requeued rows): it's marked Failed, no crash. (Task 2, `test_item_without_mainlink_is_marked_failed`)
4. JD2 gives up while direct downloads are turned off: the issue is marked Failed as before, not left at Queued. (Task 3, `test_jd2_give_up_with_direct_downloads_off_marks_failed`)
5. Rows saved before this change hold a bare file name in `tmp_filename`: progress still finds the file in the download folder. (Task 6, `test_progress_finds_files_recorded_by_name_only`)

---

### Task 1: Dispatcher, GetComics worker and file-host threads

**Files:**
- Modify: `mylar/queues/ddl.py` (top of file through the end of `ddl_downloader`; small edits in `ddl_process`, `ddl_cancelled`, `ddl_give_up`)
- Modify: `mylar/__init__.py:164` (`DDL_QUEUED`)
- Modify: `mylar/getcomics.py:1333` (`DDL_QUEUED.append`)
- Modify: `mylar/webserve.py` (`_active_ddl`, the `ACTIVE` lookup; `config` dict near line 7376)
- Modify: `mylar/config.py:393` (new setting)
- Modify: `data/interfaces/default/config.html:500` (new field)
- Modify: `tests/test_queues.py` (fix the pre-existing failure)
- Test: `tests/test_ddl_parallel.py` (new)

**Interfaces:**
- Produces (in `mylar.queues.ddl`): `max_parallel() -> int`, `is_getcomics(item: dict) -> bool`, `waiting_ids() -> set[str]`, `waiting_count() -> int`, `route(item)`, `start_waiting()`, `run_download(item)`, `gc_worker()`, `host_download(item)`; module state `GC_QUEUE`, `PENDING`, `ACTIVE` (set of str ids), `RUNNING` (`[int]`), `LOCK`, `STOP`, `LINK_TYPE_FAILURE` (removed again in Task 2). `ddl_process(myDB, item, link_type_failure=None)` keeps working as today.
- Produces: config `DDL_MAX_PARALLEL`.

- [ ] **Step 1: Fix the pre-existing test failure**

In `tests/test_queues.py`, `test_ddl_cleanup_keep_cache` calls mockito's `verify` on `os` without stubbing it. Replace the test with:

```python
@pytest.mark.unit
def test_ddl_cleanup_keep_cache(when, monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "CACHE_DIR", os.getcwd(), raising=False)
    monkeypatch.setattr(mylar.CONFIG, "KEEP_HTML_CACHE", True, raising=False)
    when(os).remove(...)
    ddl_cleanup('1234')
    verify(os, times=0).remove(os.path.join(os.getcwd(), "html_cache", "getcomics-1234.html"))
```

Run: `python -m pytest tests/test_queues.py -q -p no:cacheprovider`
Expected: 2 passed.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ddl_parallel.py`:

```python
import collections
import queue
import threading
import time
import types

import pytest

import mylar
from mylar import config as mylar_config
from mylar.queues import ddl


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class FakeDownloads:
    """Stands in for ddl_process: each item blocks until its gate opens."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = collections.Counter()
        self.peak = collections.Counter()
        self.started = []
        self.done = []
        self.gates = collections.defaultdict(threading.Event)

    def __call__(self, myDB, item):
        group = 'gc' if threading.current_thread().name == 'DDL-GETCOMICS' else 'host'
        with self.lock:
            self.running[group] += 1
            self.peak[group] = max(self.peak[group], self.running[group])
            self.started.append(item['id'])
        try:
            self.gates[item['id']].wait(5)
        finally:
            with self.lock:
                self.running[group] -= 1
        with self.lock:
            self.done.append(item['id'])
        return None

    def release(self, *ids):
        for i in ids:
            self.gates[i].set()


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_MAX_PARALLEL=2), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(ddl, 'GC_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'PENDING', collections.deque())
    monkeypatch.setattr(ddl, 'ACTIVE', set())
    monkeypatch.setattr(ddl, 'RUNNING', [0])
    monkeypatch.setattr(ddl, 'STOP', threading.Event())
    monkeypatch.setattr(ddl, 'reload_saved', lambda myDB: None)
    monkeypatch.setattr(ddl.db, 'DBConnection', lambda *a, **k: None)
    fake = FakeDownloads()
    monkeypatch.setattr(ddl, 'ddl_process', fake)
    fake.dispatcher = threading.Thread(target=ddl.ddl_downloader, args=(mylar.DDL_QUEUE,), name='DDL-QUEUE', daemon=True)
    fake.dispatcher.start()
    yield fake
    for gate in list(fake.gates.values()):
        gate.set()
    mylar.DDL_QUEUE.put('exit')
    fake.dispatcher.join(5)


def gc_item(i):
    return {'id': i, 'site': 'DDL(GetComics)', 'link_type': 'GC-Main', 'series': 'gc %s' % i}


def host_item(i, link_type='GC-Pixel'):
    return {'id': i, 'site': 'DDL(GetComics)', 'link_type': link_type, 'series': 'host %s' % i}


@pytest.mark.unit
def test_stuck_file_host_download_does_not_hold_up_another(lanes):
    mylar.DDL_QUEUE.put(host_item('slow'))
    assert wait_for(lambda: 'slow' in lanes.started)
    mylar.DDL_QUEUE.put(host_item('quick', 'GC-Mega'))
    lanes.release('quick')
    assert wait_for(lambda: 'quick' in lanes.done)
    assert 'slow' not in lanes.done


@pytest.mark.unit
def test_stuck_file_host_download_does_not_hold_up_getcomics(lanes):
    mylar.DDL_QUEUE.put(host_item('slow'))
    assert wait_for(lambda: 'slow' in lanes.started)
    mylar.DDL_QUEUE.put(gc_item('gc1'))
    lanes.release('gc1')
    assert wait_for(lambda: 'gc1' in lanes.done)


@pytest.mark.unit
def test_getcomics_downloads_one_at_a_time(lanes):
    for i in ('a', 'b', 'c'):
        mylar.DDL_QUEUE.put(gc_item(i))
    assert wait_for(lambda: 'a' in lanes.started)
    time.sleep(0.2)
    assert lanes.started == ['a']
    lanes.release('a', 'b', 'c')
    assert wait_for(lambda: len(lanes.done) == 3)
    assert lanes.peak['gc'] == 1
    assert lanes.done == ['a', 'b', 'c']


@pytest.mark.unit
def test_file_host_downloads_never_exceed_the_setting(lanes):
    for i in ('a', 'b', 'c', 'd'):
        mylar.DDL_QUEUE.put(host_item(i))
    assert wait_for(lambda: len(lanes.started) == 2)
    time.sleep(0.2)
    assert len(lanes.started) == 2
    lanes.release('a', 'b', 'c', 'd')
    assert wait_for(lambda: len(lanes.done) == 4)
    assert lanes.peak['host'] == 2


@pytest.mark.unit
def test_zero_runs_everything_on_the_getcomics_worker(lanes):
    mylar.CONFIG.DDL_MAX_PARALLEL = 0
    mylar.DDL_QUEUE.put(host_item('a'))
    mylar.DDL_QUEUE.put(host_item('b'))
    lanes.release('a', 'b')
    assert wait_for(lambda: len(lanes.done) == 2)
    assert lanes.peak['host'] == 0
    assert lanes.peak['gc'] == 1


@pytest.mark.unit
def test_raising_the_setting_starts_the_next_waiting_download(lanes):
    mylar.CONFIG.DDL_MAX_PARALLEL = 1
    mylar.DDL_QUEUE.put(host_item('a'))
    mylar.DDL_QUEUE.put(host_item('b'))
    assert wait_for(lambda: lanes.started == ['a'])
    time.sleep(0.2)
    assert lanes.started == ['a']
    mylar.CONFIG.DDL_MAX_PARALLEL = 2
    assert wait_for(lambda: lanes.started == ['a', 'b'])


@pytest.mark.unit
def test_lowering_the_setting_waits_for_running_downloads(lanes):
    for i in ('a', 'b', 'c'):
        mylar.DDL_QUEUE.put(host_item(i))
    assert wait_for(lambda: len(lanes.started) == 2)
    mylar.CONFIG.DDL_MAX_PARALLEL = 1
    first, second = lanes.started[0], lanes.started[1]
    lanes.release(first)
    assert wait_for(lambda: first in lanes.done)
    time.sleep(0.2)
    assert 'c' not in lanes.started
    lanes.release(second)
    assert wait_for(lambda: 'c' in lanes.started)


@pytest.mark.unit
def test_setting_zero_moves_waiting_items_to_the_getcomics_worker(lanes):
    mylar.CONFIG.DDL_MAX_PARALLEL = 1
    mylar.DDL_QUEUE.put(host_item('a'))
    mylar.DDL_QUEUE.put(host_item('b'))
    assert wait_for(lambda: lanes.started == ['a'])
    mylar.CONFIG.DDL_MAX_PARALLEL = 0
    lanes.release('b')
    assert wait_for(lambda: 'b' in lanes.done)
    assert 'a' not in lanes.done


@pytest.mark.unit
def test_waiting_ids_cover_every_queue_and_active_download(lanes):
    mylar.CONFIG.DDL_MAX_PARALLEL = 1
    for item in (host_item('a'), host_item('b'), gc_item('g1'), gc_item('g2')):
        mylar.DDL_QUEUE.put(item)
    assert wait_for(lambda: set(lanes.started) == {'a', 'g1'})
    assert {'a', 'b', 'g1', 'g2'} <= ddl.waiting_ids()
    assert ddl.waiting_count() == 2


@pytest.mark.unit
def test_shutdown_stops_the_dispatcher_and_the_getcomics_worker(lanes):
    mylar.DDL_QUEUE.put('exit')
    assert wait_for(lambda: not lanes.dispatcher.is_alive())
    ddl.GC_QUEUE.put(gc_item('late'))
    time.sleep(0.2)
    assert 'late' not in lanes.started


@pytest.mark.unit
@pytest.mark.parametrize('value, expected', [(3, 3), ('2', 2), (-1, 0), ('', 3), (None, 3), ('abc', 3)])
def test_max_parallel_reads_bad_values_safely(monkeypatch, value, expected):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_MAX_PARALLEL=value), raising=False)
    assert ddl.max_parallel() == expected


@pytest.mark.unit
def test_setting_is_defined_and_on_the_settings_page():
    assert mylar_config._CONFIG_DEFINITIONS['DDL_MAX_PARALLEL'] == (int, 'DDL', 3)
    with open('data/interfaces/default/config.html', encoding='utf-8') as f:
        assert 'name="ddl_max_parallel"' in f.read()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_ddl_parallel.py -q -p no:cacheprovider`
Expected: FAIL. The fixture errors with `AttributeError: <module 'mylar.queues.ddl'> has no attribute 'GC_QUEUE'`, and the setting test fails with `KeyError: 'DDL_MAX_PARALLEL'`.

- [ ] **Step 4: Replace the top of `mylar/queues/ddl.py`**

Replace everything from the first line of `mylar/queues/ddl.py` through the end of `def ddl_downloader(queue):` (the line `            time.sleep(5)` before `def ddl_process`) with:

```python
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
```

(`time` is no longer imported: nothing left in the module sleeps.)

- [ ] **Step 5: Adjust `ddl_process`, `ddl_cancelled` and `ddl_give_up` for the set and the shared failure dict**

In `mylar/queues/ddl.py`:

```python
def ddl_process(myDB, item, link_type_failure=None):
    if link_type_failure is None:
        link_type_failure = LINK_TYPE_FAILURE
    mylar.DDL_QUEUED.add(item['id'])
```

(this replaces the old first three lines: the `def` line, `if item['id'] not in mylar.DDL_QUEUED:` and its `append`).

Further down in `ddl_process`, replace `mylar.DDL_QUEUED.remove(item['id'])` with `mylar.DDL_QUEUED.discard(item['id'])`, and replace the pack loop body `del mylar.PACK_ISSUEIDS_DONT_QUEUE[x]` with `mylar.PACK_ISSUEIDS_DONT_QUEUE.pop(x, None)`.

In `ddl_cancelled`, replace `del mylar.PACK_ISSUEIDS_DONT_QUEUE[x]` with `mylar.PACK_ISSUEIDS_DONT_QUEUE.pop(x, None)`, and replace the two lines

```python
    if item['id'] in mylar.DDL_QUEUED:
        mylar.DDL_QUEUED.remove(item['id'])
```

with `    mylar.DDL_QUEUED.discard(item['id'])`. Make the same two-line replacement in `ddl_give_up`.

- [ ] **Step 6: Make `DDL_QUEUED` a set everywhere**

`mylar/__init__.py:164`: `DDL_QUEUED = []` becomes `DDL_QUEUED = set()`.

`mylar/getcomics.py:1333` (in `downloadit`): `mylar.DDL_QUEUED.append(id)` becomes `mylar.DDL_QUEUED.add(id)`.

Check nothing else appends: `grep -rn "DDL_QUEUED\.\(append\|remove\)" mylar/` prints nothing.

- [ ] **Step 7: Stop `webserve._active_ddl` reading the old one-slot `ACTIVE`**

In `mylar/webserve.py`, `def _active_ddl(self):` starts with:

```python
         myDB = db.DBConnection()
         from mylar.queues.ddl import ACTIVE
         active = None
         if ACTIVE[0] is not None:
             active = myDB.selectone("SELECT * FROM DDL_INFO WHERE ID = ? AND STATUS = 'Downloading'", [ACTIVE[0]]).fetchone()
         if active is None:
             active = myDB.selectone("SELECT * FROM DDL_INFO WHERE STATUS = 'Downloading'").fetchone()
```

Replace those lines with:

```python
         myDB = db.DBConnection()
         # several downloads can run at once - report the one that started last
         active = myDB.selectone("SELECT * FROM DDL_INFO WHERE STATUS = 'Downloading' ORDER BY updated_date DESC").fetchone()
```

(Task 6 rewrites the rest of this method.)

- [ ] **Step 8: Add the setting**

`mylar/config.py`, after the line `    'DDL_AUTORESUME': (bool, 'DDL', True),` add:

```python
    'DDL_MAX_PARALLEL': (int, 'DDL', 3),
```

`mylar/webserve.py`, in the settings-page `config` dict after `"ddl_main_large_mb": mylar.CONFIG.DDL_MAIN_LARGE_MB,` add:

```python
                    "ddl_max_parallel": mylar.CONFIG.DDL_MAX_PARALLEL,
```

`data/interfaces/default/config.html`: after the `</div>` that closes the "Big means over" `set-sub` block (the `set-sub` div holding `ddl_main_large_mb`) and before `<div class="set-row">` for `ddl_location`, add:

```html
                    <div class="set-row">
                        <label class="set-label" for="ddl_max_parallel"><b>Simultaneous file-host downloads</b><span>How many Mega, MediaFire and Pixeldrain downloads run at once. GetComics' own server always gets one at a time. 0 downloads everything one at a time. Changes apply to the next download that starts.</span></label>
                        <div class="set-ctl"><input type="number" name="ddl_max_parallel" id="ddl_max_parallel" value="${config['ddl_max_parallel'] | h}" min="0" max="10" step="1" class="set-num" /></div>
                    </div>
```

The form is saved through `CONFIG.process_kwargs`, which already handles any defined key, so no save code is needed. Because `process_kwargs` updates `mylar.CONFIG` in place and `max_parallel()` reads it on every start, a saved change applies to the next download without a restart.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python -m pytest tests/test_ddl_parallel.py tests/test_queues.py -q -p no:cacheprovider`
Expected: all pass (17 in `test_ddl_parallel.py`, 2 in `test_queues.py`).

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 10: Commit**

```bash
git add mylar/queues/ddl.py mylar/__init__.py mylar/getcomics.py mylar/webserve.py mylar/config.py data/interfaces/default/config.html tests/test_ddl_parallel.py tests/test_queues.py
git commit -m "feat(ddl): download from file hosts in parallel, GetComics one at a time"
```

---

### Task 2: Failover worker

**Files:**
- Modify: `mylar/queues/ddl.py`
- Modify: `tests/test_ddl_parallel.py` (fixture, fake, two tests)
- Test: `tests/test_ddl_failover.py` (new)

**Interfaces:**
- Consumes: Task 1's dispatcher, `run_download`, `waiting_ids`, `waiting_count`, `_ids`.
- Produces (in `mylar.queues.ddl`): `FAILOVER_QUEUE`, `FAILOVER` (dict `str(id) -> {'failed': [link types], 'no_jd2': bool}`), `send_to_failover(item: dict, result: dict, jd2_gave_up: bool = False)`, `failover_worker()`, `handle_failure(myDB, item, result, jd2_gave_up=False)`, `forget(record_id)`, `ddl_process(myDB, item) -> dict | None` (the failed result, or `None` when finished or dropped), `ddl_give_up(myDB, item)`. `LINK_TYPE_FAILURE` is removed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ddl_failover.py`:

```python
import queue
import types

import pytest

import mylar
import mylar.search  # noqa: F401 - makes mylar.search available to patch
from mylar.queues import ddl


class FakeGC:
    instances = []
    reply = {'success': True, 'site': 'GC-Media'}

    def __init__(self, query=None, issueid=None, comicid=None, oneoff=False, **kwargs):
        self.jd2 = 'jd2-helper'
        self.calls = []
        FakeGC.instances.append(self)

    def parse_downloadresults(self, id, mainlink, comicinfo=None, packinfo=None, link_type_failure=None):
        self.calls.append({'id': id, 'mainlink': mainlink, 'failed': list(link_type_failure or [])})
        return FakeGC.reply


@pytest.fixture
def failover(monkeypatch):
    FakeGC.instances = []
    FakeGC.reply = {'success': True, 'site': 'GC-Media'}
    monkeypatch.setattr(ddl, 'FAILOVER', {})
    monkeypatch.setattr(ddl.getcomics, 'GC', FakeGC)
    gave_up = []
    monkeypatch.setattr(ddl, 'ddl_give_up', lambda myDB, item: gave_up.append(item['id']))
    return gave_up


def item(**kwargs):
    base = {'id': '54429', 'series': 'Age of Ultron', 'site': 'DDL(GetComics)', 'link_type': 'GC-Mega',
            'mainlink': 'https://getcomics.org/marvel/age-of-ultron-1-10ai-2013/', 'comicid': '58436',
            'issueid': '390442', 'oneoff': False, 'comicinfo': None, 'packinfo': None}
    base.update(kwargs)
    return base


@pytest.mark.unit
def test_failed_link_is_skipped_on_the_next_try(failover):
    ddl.handle_failure(None, item(), {'success': False})
    gc = FakeGC.instances[0]
    assert gc.calls == [{'id': '54429', 'mainlink': item()['mainlink'], 'failed': ['GC-Mega']}]
    assert gc.jd2 == 'jd2-helper'
    assert failover == []


@pytest.mark.unit
def test_jd2_give_up_tries_own_downloaders_without_jd2(failover):
    ddl.handle_failure(None, item(), {}, jd2_gave_up=True)
    gc = FakeGC.instances[0]
    assert gc.jd2 is None
    assert gc.calls[0]['failed'] == []


@pytest.mark.unit
def test_item_jd2_gave_up_on_never_goes_back_to_jd2(failover):
    ddl.handle_failure(None, item(), {}, jd2_gave_up=True)
    ddl.handle_failure(None, item(), {'success': False})
    second = FakeGC.instances[1]
    assert second.jd2 is None
    assert second.calls[0]['failed'] == ['GC-Mega']


@pytest.mark.unit
def test_no_links_left_marks_failed(failover):
    FakeGC.reply = {'success': False, 'links_exhausted': ['GC-Mega']}
    ddl.handle_failure(None, item(), {'success': False})
    assert failover == ['54429']


@pytest.mark.unit
def test_exhausted_result_gives_up_without_rereading_the_page(failover):
    ddl.handle_failure(None, item(), {'success': False, 'links_exhausted': ['GC-Main']})
    assert failover == ['54429']
    assert FakeGC.instances == []


@pytest.mark.unit
def test_item_without_mainlink_is_marked_failed(failover):
    ddl.handle_failure(None, item(mainlink=None), {'success': False})
    assert failover == ['54429']
    assert FakeGC.instances == []


@pytest.mark.unit
def test_external_server_failure_marks_issue_failed(failover, monkeypatch):
    marked, deleted = [], []
    monkeypatch.setattr(mylar.search, 'FailedMark', lambda *a, **k: marked.append(a))
    fake_db = types.SimpleNamespace(action=lambda sql, args: deleted.append(args))
    ddl.handle_failure(fake_db, item(site='DDL(External)', link_type='DDL-Ext'), {'success': False, 'filename': 'x.cbz'})
    assert deleted == [['54429']]
    assert marked[0][:3] == ('390442', '58436', '54429')
    assert '54429' not in ddl.FAILOVER


@pytest.mark.unit
def test_items_waiting_for_failover_count_as_queued(monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(ddl, 'FAILOVER_QUEUE', queue.Queue())
    ddl.send_to_failover({'id': 'x'}, {'success': False})
    assert 'x' in ddl.waiting_ids()
    assert ddl.waiting_count() == 1
```

In `tests/test_ddl_parallel.py`, replace `class FakeDownloads` and the `lanes` fixture with the versions below (they add per-item results, raising items and a failover recorder), and add the two tests at the end of the file:

```python
class FakeDownloads:
    """Stands in for ddl_process: each item blocks until its gate opens."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = collections.Counter()
        self.peak = collections.Counter()
        self.started = []
        self.done = []
        self.failed = []
        self.results = {}
        self.raises = set()
        self.gates = collections.defaultdict(threading.Event)

    def __call__(self, myDB, item):
        group = 'gc' if threading.current_thread().name == 'DDL-GETCOMICS' else 'host'
        with self.lock:
            self.running[group] += 1
            self.peak[group] = max(self.peak[group], self.running[group])
            self.started.append(item['id'])
        try:
            self.gates[item['id']].wait(5)
            if item['id'] in self.raises:
                raise RuntimeError('boom')
        finally:
            with self.lock:
                self.running[group] -= 1
        with self.lock:
            self.done.append(item['id'])
        return self.results.get(item['id'])

    def release(self, *ids):
        for i in ids:
            self.gates[i].set()


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_MAX_PARALLEL=2), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(ddl, 'GC_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'FAILOVER_QUEUE', queue.Queue())
    monkeypatch.setattr(ddl, 'FAILOVER', {})
    monkeypatch.setattr(ddl, 'PENDING', collections.deque())
    monkeypatch.setattr(ddl, 'ACTIVE', set())
    monkeypatch.setattr(ddl, 'RUNNING', [0])
    monkeypatch.setattr(ddl, 'STOP', threading.Event())
    monkeypatch.setattr(ddl, 'reload_saved', lambda myDB: None)
    monkeypatch.setattr(ddl.db, 'DBConnection', lambda *a, **k: None)
    fake = FakeDownloads()
    monkeypatch.setattr(ddl, 'ddl_process', fake)
    monkeypatch.setattr(ddl, 'handle_failure',
                        lambda myDB, item, result, jd2_gave_up=False: fake.failed.append((item, result, jd2_gave_up)))
    fake.dispatcher = threading.Thread(target=ddl.ddl_downloader, args=(mylar.DDL_QUEUE,), name='DDL-QUEUE', daemon=True)
    fake.dispatcher.start()
    yield fake
    for gate in list(fake.gates.values()):
        gate.set()
    mylar.DDL_QUEUE.put('exit')
    fake.dispatcher.join(5)


@pytest.mark.unit
def test_failed_download_goes_to_the_failover_worker(lanes):
    lanes.results['a'] = {'success': False, 'link_type_failure': 'GC-Pixel'}
    lanes.release('a')
    mylar.DDL_QUEUE.put(host_item('a'))
    assert wait_for(lambda: lanes.failed)
    failed_item, result, jd2_gave_up = lanes.failed[0]
    assert failed_item['id'] == 'a'
    assert result['link_type_failure'] == 'GC-Pixel'
    assert jd2_gave_up is False


@pytest.mark.unit
def test_exception_goes_to_failover_and_frees_the_slot(lanes):
    mylar.CONFIG.DDL_MAX_PARALLEL = 1
    lanes.raises.add('a')
    lanes.release('a', 'b')
    mylar.DDL_QUEUE.put(host_item('a'))
    mylar.DDL_QUEUE.put(host_item('b'))
    assert wait_for(lambda: 'b' in lanes.done)
    assert wait_for(lambda: [f[0]['id'] for f in lanes.failed] == ['a'])
    assert lanes.failed[0][1]['link_type_failure'] == 'GC-Pixel'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_ddl_failover.py tests/test_ddl_parallel.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: ... has no attribute 'FAILOVER'` / `'handle_failure'` / `'send_to_failover'`.

- [ ] **Step 3: Add the failover worker and route failures to it**

In `mylar/queues/ddl.py`:

1. Replace the line `LINK_TYPE_FAILURE = {}          # id -> link types that failed for it` with:

```python
FAILOVER_QUEUE = Queue()        # failed downloads, and items JD2 gave up on
FAILOVER = {}                   # str(id) -> {'failed': [link types], 'no_jd2': bool}
```

2. In `waiting_ids`, change the first line to `    ids = _ids(mylar.DDL_QUEUE) | _ids(GC_QUEUE) | _ids(FAILOVER_QUEUE)`. In `waiting_count`, change the return to `    return mylar.DDL_QUEUE.qsize() + GC_QUEUE.qsize() + FAILOVER_QUEUE.qsize() + pending`.

3. In `ddl_downloader`, change the workers line to

```python
    workers = [_start(gc_worker, 'DDL-GETCOMICS'), _start(failover_worker, 'DDL-FAILOVER')]
```

and after `GC_QUEUE.put('exit')` add `            FAILOVER_QUEUE.put('exit')`.

4. Replace `run_download` with:

```python
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
            send_to_failover(item, result)
    finally:
        with LOCK:
            ACTIVE.discard(key)
```

5. Add after `run_download`:

```python
def send_to_failover(item, result, jd2_gave_up=False):
    FAILOVER_QUEUE.put({'item': item, 'result': result or {}, 'jd2_gave_up': jd2_gave_up})


def forget(record_id):
    FAILOVER.pop(str(record_id), None)


def failover_worker():
    while True:
        entry = FAILOVER_QUEUE.get()
        if entry == 'exit':
            break
        item = entry['item']
        try:
            handle_failure(db.DBConnection(), item, entry['result'], entry['jd2_gave_up'])
        except Exception as e:
            logger.exception('[DDL-FAILOVER] Error while looking for another source for %s: %s' % (item.get('series'), e))
            try:
                ddl_give_up(db.DBConnection(), item)
            except Exception as e2:
                logger.warn('[DDL-FAILOVER] Unable to mark %s as failed: %s' % (item.get('series'), e2))


def handle_failure(myDB, item, result, jd2_gave_up=False):
    """Queue the item's next source, or mark it Failed when none is left.

    Runs on the one failover thread, so GetComics pages are re-read one at a time. Once JD2
    has given up on an item, only Issuarr's own downloaders are tried for it.
    """
    state = FAILOVER.setdefault(str(item['id']), {'failed': [], 'no_jd2': False})
    if jd2_gave_up:
        state['no_jd2'] = True
        logger.info('[DDL-FAILOVER] JD2 gave up on %s - trying Issuarr\'s own downloaders.' % item.get('series'))
    else:
        link_type = item.get('link_type') or result.get('link_type_failure')
        if link_type and link_type not in state['failed']:
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
```

6. Change `ddl_process` so it returns the failed result instead of handling it:

- Replace its first three lines (from Task 1 Step 5) with:

```python
def ddl_process(myDB, item):
    """Download one item. Returns None when it's finished or dropped, or the failed result for the failover worker."""
    mylar.DDL_QUEUED.add(item['id'])
```

- Delete the block right after it:

```python
    try:
        link_type_failure[item['id']].append(item['link_type_failure'])
    except Exception:
        pass
```

- Change both `return` statements after `if ddl_cancelled(...)` to `return None`.
- Insert `    ddzstat = None` immediately before `    if item['site'] == 'DDL(GetComics)':` (the one that picks the downloader), and insert immediately before `    if ddl_cancelled(item, ddzstat):`:

```python
    if not ddzstat:
        ddzstat = {'success': False, 'filename': None, 'path': None, 'link_type_failure': item.get('link_type')}
```

- In the success branch, replace

```python
        try:
            link_type_failure.pop(item['id'])
        except KeyError:
            pass
```

with `        forget(item['id'])`. In the `POST_PROCESSING is False` branch, add `        forget(item['id'])` before `        ddl_cleanup(item['id'])`.
- Replace the whole final `else:` branch of `ddl_process` (from `    else:` / `        if item['site'] == 'DDL(GetComics)':` to the end of the function) with:

```python
    else:
        return ddzstat
    return None
```

7. Replace `ddl_give_up` with:

```python
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
```

8. Check nothing still refers to the old names: `grep -n "LINK_TYPE_FAILURE\|link_type_failure\[" mylar/queues/ddl.py` prints nothing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_ddl_failover.py tests/test_ddl_parallel.py -q -p no:cacheprovider`
Expected: all pass.

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 5: Commit**

```bash
git add mylar/queues/ddl.py tests/test_ddl_failover.py tests/test_ddl_parallel.py
git commit -m "feat(ddl): one failover worker picks the next source for every failed download"
```

---

### Task 3: JD2 give-ups go to the failover worker

**Files:**
- Modify: `mylar/queues/jd2.py` (replace `jd2_fallback`; three call sites in `jd2_queue_monitor`)
- Modify: `docs/JDOWNLOADER2.md:11-12`
- Test: `tests/test_jd2_giveup.py` (new)

**Interfaces:**
- Consumes: `ddl.send_to_failover(item, result, jd2_gave_up=True)` from Task 2.
- Produces: `jd2.jd2_give_up(myDB, item, record_id, reason)`. `jd2.jd2_fallback` is removed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jd2_giveup.py`:

```python
import queue
import types

import pytest

import mylar
from mylar import getcomics
from mylar.queues import ddl, jd2


class FakeDB:
    def __init__(self):
        self.upserts = []

    def upsert(self, table, vals, ctrl):
        self.upserts.append((table, vals, ctrl))


@pytest.fixture
def sent(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_DDL=True), raising=False)
    out = []
    monkeypatch.setattr(ddl, 'send_to_failover', lambda item, result, jd2_gave_up=False: out.append((item, result, jd2_gave_up)))
    return out


def jd2_item(**kwargs):
    base = {'id': '54429', 'series': 'Age of Ultron #1 – 10AI (2013)', 'link_type': 'GC-Mega',
            'mainlink': 'https://getcomics.org/marvel/age-of-ultron-1-10ai-2013/', 'link': 'https://getcomics.org/dls/mega',
            'main_link': 'https://getcomics.org/dls/main', 'jd2_job_id': '1791741854472',
            'jd2_priority_links': {'https://getcomics.org/dls/mega': 'HIGHEST'}, 'comicid': '58436', 'issueid': '390442'}
    base.update(kwargs)
    return base


@pytest.mark.unit
def test_jd2_give_up_hands_the_item_to_failover(sent):
    fake_db = FakeDB()
    jd2.jd2_give_up(fake_db, jd2_item(), '54429', 'JD2 status Blocked by Cloudflare')
    item, result, jd2_gave_up = sent[0]
    assert jd2_gave_up is True
    assert 'jd2_job_id' not in item and 'jd2_priority_links' not in item and 'main_link' not in item
    assert item['id'] == '54429' and item['link_type'] == 'GC-Mega'
    table, vals, ctrl = fake_db.upserts[0]
    assert (table, ctrl) == ('ddl_info', {'id': '54429'})
    assert vals['status'] == 'Queued' and vals['jd2_job_id'] is None


@pytest.mark.unit
def test_jd2_give_up_with_direct_downloads_off_marks_failed(sent, monkeypatch):
    mylar.CONFIG.ENABLE_DDL = False
    failed = []
    monkeypatch.setattr(jd2, 'jd2_mark_failed', lambda myDB, item, record_id, reason: failed.append(record_id))
    jd2.jd2_give_up(FakeDB(), jd2_item(), '54429', 'offline')
    assert failed == ['54429']
    assert sent == []


@pytest.mark.unit
def test_jd2_fallback_to_getcomics_direct_is_gone():
    assert not hasattr(jd2, 'jd2_fallback')


@pytest.mark.unit
def test_without_jd2_links_go_straight_to_the_built_in_downloaders(monkeypatch):
    # what the failover worker relies on after setting ggc.jd2 = None
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'JD2_QUEUE', queue.Queue(), raising=False)
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.jd2 = None
    gc.issueid, gc.comicid, gc.oneoff = '390442', '58436', False
    link = {'series': 'Age of Ultron #1 – 10AI', 'site': 'mega', 'year': '2013', 'size': '617 MB',
            'issues': None, 'links': 'https://getcomics.org/dls/mega', 'pack': True}
    fake_db = FakeDB()
    gc._queue_links([link], [link], [], '54429', 'https://getcomics.org/marvel/age-of-ultron-1-10ai-2013/', None, None, [], fake_db)
    queued = mylar.DDL_QUEUE.get_nowait()
    assert queued['link_type'] == 'GC-Mega'
    assert mylar.JD2_QUEUE.empty()
    vals = fake_db.upserts[0][1]
    assert vals['link'] == 'https://getcomics.org/dls/mega' and vals['link_type'] == 'GC-Mega'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_jd2_giveup.py -q -p no:cacheprovider`
Expected: FAIL. `jd2_give_up` doesn't exist and `jd2_fallback` still does. `test_without_jd2_links_go_straight_to_the_built_in_downloaders` already passes: it pins existing behaviour the failover worker depends on.

- [ ] **Step 3: Replace `jd2_fallback` with `jd2_give_up`**

In `mylar/queues/jd2.py`, add `from . import ddl` under `from mylar import db`. Replace the whole `def jd2_fallback(myDB, item, record_id):` function with:

```python
def jd2_give_up(myDB, item, record_id, reason):
    """JD2 couldn't finish the download. The DDL failover worker tries Issuarr's own downloaders
    for the same post, file hosts first for big files, and never JD2 again. Only when direct
    downloads are off, or the post can't be read again, is the issue marked Failed here."""
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
```

In `jd2_queue_monitor`, make these three replacements:

```python
                            jd2_mark_failed(myDB, item, record_id, 'job %s never reached the JD2 download list (links offline or rejected)' % job_id)
```
becomes
```python
                            jd2_give_up(myDB, item, record_id, 'job %s never reached the JD2 download list (links offline or rejected)' % job_id)
```

```python
                        if not jd2_fallback(myDB, item, record_id):
                            jd2_mark_failed(myDB, item, record_id, 'JD2 status %s' % reason)
```
becomes
```python
                        jd2_give_up(myDB, item, record_id, 'JD2 status %s' % reason)
```

```python
                jd2_mark_failed(myDB, item, record_id, 'no JD2 job id to monitor')
```
becomes
```python
                jd2_give_up(myDB, item, record_id, 'no JD2 job id to monitor')
```

Check: `grep -n "jd2_fallback" -r mylar/` prints nothing.

- [ ] **Step 4: Update the JD2 page**

In `docs/JDOWNLOADER2.md`, replace the two bullets

```markdown
- If JD2 can't be reached or refuses the links, Issuarr hands the download back to its built-in downloader.
- If a job never shows up in JD2's download list (for example because every link is offline), Issuarr gives up after about three minutes and marks the issue Failed, so it doesn't sit at Snatched.
```

with

```markdown
- If JD2 can't be reached or refuses the links, Issuarr hands the download back to its built-in downloader.
- If JD2 gives up on a download (links offline, blocked, or the job never shows up in JD2's download list within about three minutes), Issuarr tries its own downloaders for the same post: file hosts first for big files, GetComics' own server last. The issue is marked Failed only when none of them work, so it doesn't sit at Snatched.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_jd2_giveup.py -q -p no:cacheprovider`
Expected: 4 passed.

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 6: Commit**

```bash
git add mylar/queues/jd2.py docs/JDOWNLOADER2.md tests/test_jd2_giveup.py
git commit -m "feat(jd2): when JD2 gives up, try Issuarr's own downloaders before GetComics direct"
```

---

### Task 4: GetComics direct without the global lock

**Files:**
- Modify: `mylar/getcomics.py` (`downloadit`, `zip_zip`, `cookie_receipt`, `_save_ua`, imports)
- Modify: `mylar/__init__.py` (`DDL_LOCK`)
- Test: `tests/test_getcomics_download.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks (Task 1 already changed `DDL_QUEUED.append` here).
- Produces: `downloadit()` always returns a result dict and stores the full path it writes in `ddl_info.tmp_filename`; module-level `getcomics._COOKIE_LOCK`. `mylar.DDL_LOCK` no longer exists.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_getcomics_download.py`:

```python
import types

import pytest

import mylar
from mylar import getcomics


class FakeResponse:
    def __init__(self, url, body):
        self.url = url
        self.headers = {'Content-length': str(len(body))}
        self._body = body

    def iter_content(self, chunk_size=1):
        yield self._body

    def close(self):
        pass


class FakeDB:
    def __init__(self):
        self.upserts = []

    def upsert(self, table, vals, ctrl):
        self.upserts.append(vals)


@pytest.fixture
def gc(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_LOCATION=str(tmp_path)), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_QUEUED', set(), raising=False)
    fake_db = FakeDB()
    monkeypatch.setattr(getcomics.db, 'DBConnection', lambda *a, **k: fake_db)
    g = getcomics.GC.__new__(getcomics.GC)
    g.headers = {}
    g.cookie_receipt = lambda *a, **k: None
    g.apply_file_clearance = lambda: None
    g.is_challenge = lambda t: False
    g.session = types.SimpleNamespace(
        get=lambda *a, **k: FakeResponse('https://getcomics.org/files/Star-Lord%20004%20(2017).cbz', b'comic'))
    g.fake_db = fake_db
    return g


@pytest.mark.unit
def test_getcomics_download_records_its_full_path(gc, tmp_path):
    result = gc.downloadit('49124', 'https://getcomics.org/dls/x', 'https://getcomics.org/p', issueid='587418')
    path = str(tmp_path / 'Star-Lord 004 (2017)[__587418__].cbz')
    assert result == {'success': True, 'filename': 'Star-Lord 004 (2017)[__587418__].cbz', 'path': path}
    assert {'tmp_filename': path} in gc.fake_db.upserts


@pytest.mark.unit
def test_getcomics_download_runs_even_if_the_old_lock_is_set(gc, monkeypatch):
    # the old global lock made a second download return None, which crashed the worker
    monkeypatch.setattr(mylar, 'DDL_LOCK', True, raising=False)
    result = gc.downloadit('2', 'https://getcomics.org/dls/y', 'https://getcomics.org/p', issueid='2')
    assert result is not None and result['success'] is True


@pytest.mark.unit
def test_user_agent_is_saved_under_the_cookie_lock(monkeypatch, tmp_path):
    entered = []

    class Lock:
        def __enter__(self):
            entered.append(True)

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(getcomics, '_COOKIE_LOCK', Lock(), raising=False)
    g = getcomics.GC.__new__(getcomics.GC)
    g.headers = {}
    g.session_path = str(tmp_path / '.gc_cookies.dat')
    g._save_ua('Mozilla/5.0')
    assert entered == [True]
    assert (tmp_path / '.gc_cookies.dat.ua').read_text() == 'Mozilla/5.0'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_getcomics_download.py -q -p no:cacheprovider`
Expected: FAIL. No `tmp_filename` upsert is recorded, the second test gets `None`, and the third records no lock entry.

- [ ] **Step 3: Remove the global lock from `downloadit` and `zip_zip`**

In `mylar/getcomics.py`, delete this block from `downloadit`:

```python
        if mylar.DDL_LOCK is True:
            logger.fdebug(
                '[DDL] Another item is currently downloading via DDL. Only one item can'
                ' be downloaded at a time using DDL. Patience.'
            )
            return
        else:
            mylar.DDL_LOCK = True

```

Then delete every remaining `mylar.DDL_LOCK = False` line (each is followed by a `return` or other statement, so no block is left empty):

```bash
sed -i '/^[[:space:]]*mylar\.DDL_LOCK = False$/d' mylar/getcomics.py
grep -n "DDL_LOCK" mylar/getcomics.py
```
Expected: the `grep` prints nothing.

In `mylar/__init__.py`, delete the line `DDL_LOCK = False` and remove `DDL_LOCK, ` from the `global` statement (`SEARCHLOCK, DDL_LOCK, LOG_LEVEL` becomes `SEARCHLOCK, LOG_LEVEL`). Check: `grep -rn "DDL_LOCK" mylar/` prints nothing.

- [ ] **Step 4: Record the file path before the first byte**

In `downloadit`, immediately before `                    with open(dst_path, 'ab') as f:` add:

```python
                    myDB.upsert('ddl_info', {'tmp_filename': dst_path}, {'id': id})
```

and immediately before `                    with open(dst_path, 'wb') as f:` (after the block that may rename the file to `.1`) add the same line:

```python
                    myDB.upsert('ddl_info', {'tmp_filename': dst_path}, {'id': id})
```

- [ ] **Step 5: Lock writes to the GetComics cookie files**

In `mylar/getcomics.py`, add `import threading` with the other imports at the top, and after the imports (before `class DownloadCancelled`) add:

```python
# the search queue, the GetComics worker and the failover worker can all refresh the cookie
_COOKIE_LOCK = threading.Lock()
```

In `cookie_receipt`, change

```python
                        with open(self.session_path, 'w') as f:
                            json.dump(gc_cookie, f)
```

to

```python
                        with _COOKIE_LOCK:
                            with open(self.session_path, 'w') as f:
                                json.dump(gc_cookie, f)
```

In `_save_ua`, change

```python
            with open(self.session_path + '.ua', 'w') as f:
                f.write(ua)
```

to

```python
            with _COOKIE_LOCK:
                with open(self.session_path + '.ua', 'w') as f:
                    f.write(ua)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_getcomics_download.py -q -p no:cacheprovider`
Expected: 3 passed.

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 7: Commit**

```bash
git add mylar/getcomics.py mylar/__init__.py tests/test_getcomics_download.py
git commit -m "fix(getcomics): drop the global download lock, record the file path, lock cookie writes"
```

---

### Task 5: File hosts record their path, stop on abort, and time out

**Files:**
- Modify: `mylar/downloaders/mediafire.py` (`mediafire_dl`)
- Modify: `mylar/downloaders/pixeldrain.py` (`pixel_ddl`)
- Modify: `mylar/downloaders/mega.py` (`testing`)
- Modify: `lib/mega/mega.py:705`
- Test: `tests/test_ddl_hosts.py` (new)

**Interfaces:**
- Consumes: `mylar.DDL_CANCEL` (set of str ids), `mylar.getcomics.DownloadCancelled`.
- Produces: MediaFire and Pixeldrain store the full path in `ddl_info.tmp_filename`; all three stop mid-download when their id is in `DDL_CANCEL`, returning a failed result that `ddl_process` then drops through `ddl_cancelled`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ddl_hosts.py`:

```python
import inspect
import types

import pytest

import mylar
from mylar import getcomics
from mylar.downloaders import mediafire, mega, pixeldrain


class FakeResponse:
    def __init__(self, chunks):
        self.chunks = chunks

    def iter_content(self, chunk_size=1):
        for c in self.chunks:
            yield c


class FakeDB:
    def __init__(self):
        self.upserts = []

    def upsert(self, table, vals, ctrl):
        self.upserts.append(vals)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_LOCATION=str(tmp_path)), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    fake_db = FakeDB()
    for module in (mediafire, pixeldrain):
        monkeypatch.setattr(module.db, 'DBConnection', lambda *a, **k: fake_db)
    return fake_db


def pixel(tmp_path, chunks, record_id='344'):
    p = pixeldrain.PixelDrain.__new__(pixeldrain.PixelDrain)
    p.dl_location = str(tmp_path)
    p.headers = {}
    p.id = record_id
    p.session = types.SimpleNamespace(get=lambda *a, **k: FakeResponse(chunks))
    return p


def fire(tmp_path, chunks):
    m = mediafire.MediaFire.__new__(mediafire.MediaFire)
    m.dl_location = str(tmp_path)
    m.headers = {}
    m.session = types.SimpleNamespace(get=lambda *a, **k: FakeResponse(chunks))
    return m


@pytest.mark.unit
def test_pixeldrain_records_the_full_path(env, tmp_path):
    p = pixel(tmp_path, [b'abc'])
    result = p.pixel_ddl('HqyZnRrC', {'filename': 'Kick-Ass 3 02 (2013).cbz', 'filesize': 3}, '420643')
    path = str(tmp_path / 'Kick-Ass 3 02 (2013)[__420643__].cbz')
    assert {'tmp_filename': path} in env.upserts
    assert result['success'] is True


@pytest.mark.unit
def test_pixeldrain_stops_when_aborted(env, tmp_path):
    mylar.DDL_CANCEL.add('344')
    p = pixel(tmp_path, [b'abc', b'def'])
    result = p.pixel_ddl('HqyZnRrC', {'filename': 'Kick-Ass 3 02 (2013).cbz', 'filesize': 6}, '420643')
    assert result['success'] is False
    assert not (tmp_path / 'Kick-Ass 3 02 (2013)[__420643__].cbz').exists()


@pytest.mark.unit
def test_mediafire_records_the_full_path(env, tmp_path):
    m = fire(tmp_path, [b'abc'])
    result = m.mediafire_dl('https://www.mediafire.com/x', '54429', {'filename': 'Age of Ultron 001.cbz', 'filesize': 3}, '390442')
    assert {'tmp_filename': str(tmp_path / 'Age of Ultron 001.cbz')} in env.upserts
    assert result['success'] is True


@pytest.mark.unit
def test_mediafire_stops_when_aborted(env, tmp_path):
    mylar.DDL_CANCEL.add('54429')
    m = fire(tmp_path, [b'abc', b'def'])
    result = m.mediafire_dl('https://www.mediafire.com/x', '54429', {'filename': 'Age of Ultron 001.cbz', 'filesize': 6}, '390442')
    assert result['success'] is False
    assert not (tmp_path / 'Age of Ultron 001.cbz').exists()


@pytest.mark.unit
def test_mega_stops_when_aborted(monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_CANCEL', {'54429'}, raising=False)
    m = mega.MegaNZ.__new__(mega.MegaNZ)
    m.id = '54429'
    m.wrote_tmp = True
    with pytest.raises(getcomics.DownloadCancelled):
        m.testing({'current': 1, 'total': 10, 'tmp_filename': '/tmp/megapy_x', 'name': 'x.zip', 'status': 'downloading'})


@pytest.mark.unit
def test_mega_download_has_a_timeout():
    from mega.mega import Mega
    assert 'requests.get(file_url, stream=True, timeout=(30, 30))' in inspect.getsource(Mega._download_file)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_ddl_hosts.py -q -p no:cacheprovider`
Expected: FAIL. The path tests see a bare file name, the abort tests download the whole file, Mega's hook doesn't raise, and the timeout string is missing.

- [ ] **Step 3: MediaFire**

In `mylar/downloaders/mediafire.py`, `mediafire_dl`: change the upsert value `{'tmp_filename': fileinfo['filename']}` to `{'tmp_filename': filepath}`. Change the write loop and its `except` to:

```python
            logger.fdebug('[MediaFire] now writing....')
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=4096):
                    if str(id) in mylar.DDL_CANCEL:
                        raise mylar.getcomics.DownloadCancelled()
                    if chunk:
                        f.write(chunk)
                        f.flush()

        except Exception as e:
            if str(id) in mylar.DDL_CANCEL:
                logger.info('[MediaFire] Stopped downloading %s - it was aborted or removed from the queue.' % fileinfo['filename'])
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            else:
                logger.fdebug('[MediaFire][ERROR] %s' % e)
            if 'EBLOCKED' in str(e):
                logger.fdebug('[MediaFire] Content has been removed - we should move on to the next one at this point.')
            return {"success": False, "filename": None, "path": None, "link_type_failure": 'GC-Media'}
```

- [ ] **Step 4: Pixeldrain**

In `mylar/downloaders/pixeldrain.py`, `pixel_ddl`: change the upsert value `{'tmp_filename': filename}` to `{'tmp_filename': filepath}`. Change the write loop and its `except` to:

```python
            logger.fdebug('[PixelDrain] now writing....')
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if str(self.id) in mylar.DDL_CANCEL:
                        raise mylar.getcomics.DownloadCancelled()
                    if chunk:
                        f.write(chunk)
                        f.flush()

        except Exception as e:
            if str(self.id) in mylar.DDL_CANCEL:
                logger.info('[PixelDrain] Stopped downloading %s - it was aborted or removed from the queue.' % filename)
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            else:
                logger.warn('[PixelDrain][ERROR] %s' % e)
            if 'EBLOCKED' in str(e):
                logger.warn('[PixelDrain] Content has been removed - we should move on to the next one at this point.')
            return {"success": False, "filename": filename, "path": None, "link_type_failure": 'GC-Pixel'}
```

If `os` isn't imported in `pixeldrain.py`, add `import os` to its imports (check with `grep -n "^import os" mylar/downloaders/pixeldrain.py`).

- [ ] **Step 5: Mega**

In `mylar/downloaders/mega.py`, make these the first lines of `def testing(self, data):`:

```python
    def testing(self, data):
        # the Mega library calls this after every chunk - raising here stops the download
        if str(self.id) in mylar.DDL_CANCEL:
            raise mylar.getcomics.DownloadCancelled()
```

In `lib/mega/mega.py:705`, change

```python
        input_file = requests.get(file_url, stream=True).raw
```

to

```python
        input_file = requests.get(file_url, stream=True, timeout=(30, 30)).raw
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_ddl_hosts.py -q -p no:cacheprovider`
Expected: 6 passed.

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 7: Commit**

```bash
git add mylar/downloaders/mediafire.py mylar/downloaders/pixeldrain.py mylar/downloaders/mega.py lib/mega/mega.py tests/test_ddl_hosts.py
git commit -m "fix(ddl): file hosts record their path, stop on abort, and Mega times out"
```

---

### Task 6: Progress for every active download

**Files:**
- Modify: `mylar/downloadqueue.py` (`import os`; new `ddl_progress`, `download_rate`; `ddl_queue_rows`; `build`)
- Modify: `mylar/webserve.py` (remove `_DL_SAMPLE`, `_human_bytes`, `_download_rate`; `_active_ddl`; `check_ActiveDDL`; `downloadQueue`)
- Modify: `mylar/queues/utils.py` (`queue_info`)
- Test: `tests/test_download_queue.py` (add tests), `tests/test_queues.py` (add test)

**Interfaces:**
- Consumes: `ddl.waiting_count()` (Tasks 1-2); `ddl_info.tmp_filename` full paths (Tasks 4-5).
- Produces (in `mylar.downloadqueue`): `ddl_progress(row) -> {'done': int, 'total': int | None, 'percent': int | None} | None` (row is a `sqlite3.Row` or dict); `download_rate(did, done, total) -> dict` with `a_progress`, optional `a_speed` and `a_eta`; `build(myDB, active=None, rate=None)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_download_queue.py`:

```python
@pytest.mark.unit
def test_every_active_direct_download_shows_progress(myDB, tmp_path):
    myDB.action('ALTER TABLE ddl_info ADD COLUMN tmp_filename TEXT')
    myDB.action('ALTER TABLE ddl_info ADD COLUMN remote_filesize TEXT')
    for did, done in (('d1', 25), ('d2', 50)):
        f = tmp_path / ('%s.cbz' % did)
        f.write_bytes(b'x' * done)
        myDB.action("INSERT INTO ddl_info (ID, series, status, site, link_type, tmp_filename, remote_filesize, updated_date) "
                    "VALUES (?, 'Alpha', 'Downloading', 'DDL(GetComics)', 'GC-Pixel', ?, '100', '2026-10-11 12:18')",
                    [did, str(f)])
    rates = []

    def rate(did, done, total):
        rates.append(did)
        return {'a_speed': '1.0 MB/s', 'a_progress': '%s of %s' % (done, total)}

    rows = {r['queueid']: r for r in downloadqueue.build(myDB, rate=rate) if r['kind'] == 'ddl'}
    assert rows['d1']['percent'] == 25
    assert rows['d2']['percent'] == 50
    assert rows['d1']['speed'] == '1.0 MB/s'
    assert sorted(rates) == ['d1', 'd2']


@pytest.mark.unit
def test_progress_finds_files_recorded_by_name_only(myDB, tmp_path):
    mylar.CONFIG.DDL_LOCATION = str(tmp_path)
    (tmp_path / 'Kick-Ass 3.zip').write_bytes(b'x' * 40)
    row = {'tmp_filename': 'Kick-Ass 3.zip', 'remote_filesize': '80', 'filename': None, 'size': '80 B'}
    assert downloadqueue.ddl_progress(row) == {'done': 40, 'total': 80, 'percent': 50}


@pytest.mark.unit
def test_progress_is_none_before_the_file_exists(myDB, tmp_path):
    mylar.CONFIG.DDL_LOCATION = str(tmp_path)
    assert downloadqueue.ddl_progress({'tmp_filename': None, 'filename': 'missing.cbz', 'remote_filesize': '80'}) is None


@pytest.mark.unit
def test_download_speed_is_tracked_per_download(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(downloadqueue.time, 'time', lambda: now[0])
    downloadqueue._DL_SAMPLE.clear()
    downloadqueue.download_rate('a', 0, 10 * 1048576)
    downloadqueue.download_rate('b', 0, 10 * 1048576)
    now[0] += 4
    a = downloadqueue.download_rate('a', 4 * 1048576, 10 * 1048576)
    b = downloadqueue.download_rate('b', 1048576, 10 * 1048576)
    assert a['a_speed'] == '1.0 MB/s'
    assert b['a_speed'] == '256 KB/s'
```

Add to `tests/test_queues.py`:

```python
@pytest.mark.unit
def test_queue_info_counts_every_waiting_direct_download(monkeypatch):
    from mylar.queues import ddl, queue_info
    monkeypatch.setattr(ddl, 'waiting_count', lambda: 7)
    info = {q.name: q for q in queue_info()}
    assert info['DDL-QUEUE'].size == 7
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_download_queue.py tests/test_queues.py -q -p no:cacheprovider`
Expected: FAIL. `build()` has no `rate` argument, `ddl_progress`, `download_rate` and `_DL_SAMPLE` don't exist in `downloadqueue`, and `queue_info` reports `DDL_QUEUE.qsize()`.

- [ ] **Step 3: Progress and speed in `mylar/downloadqueue.py`**

Add `import os` to the imports. Add after `ddl_queue_rows`:

```python
def _field(row, key):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def ddl_progress(row):
    """How far a direct download has got, read from the file it's writing.

    Returns {'done', 'total', 'percent'}, or None until the file exists. Rows saved before
    downloaders recorded full paths hold a bare file name, found in the download folder.
    """
    location = getattr(mylar.CONFIG, 'DDL_LOCATION', None) or ''
    path = _field(row, 'tmp_filename')
    if path and not os.path.isabs(path):
        path = os.path.join(location, path)
    if not path and _field(row, 'filename'):
        path = os.path.join(location, _field(row, 'filename'))
    if not path:
        return None
    try:
        done = os.stat(path).st_size
    except OSError:
        return None
    try:
        total = int(_field(row, 'remote_filesize') or 0)
    except (TypeError, ValueError):
        total = 0
    if (not total or done > total * 1.02) and _field(row, 'size'):
        try:
            total = int(helpers.human2bytes(re.sub('/s', '', str(_field(row, 'size'))[:-1]).strip()))
        except Exception:
            total = 0
    if not total:
        return {'done': done, 'total': None, 'percent': None}
    return {'done': done, 'total': total, 'percent': min(100, int(done * 100 / total))}


_DL_SAMPLE = {}


def download_rate(did, done, total):
    """Progress text, speed and time left for one download, smoothed between polls."""
    did = str(did)
    now = time.time()
    for k in [k for k, v in _DL_SAMPLE.items() if now - v[1] > 3600]:
        _DL_SAMPLE.pop(k, None)
    prev = _DL_SAMPLE.get(did)
    speed = prev[2] if prev else None
    if prev and done >= prev[0] and now - prev[1] >= 2:
        inst = (done - prev[0]) / (now - prev[1])
        speed = inst if speed is None else speed * 0.6 + inst * 0.4
        _DL_SAMPLE[did] = (done, now, speed)
    elif not prev or done < prev[0]:
        _DL_SAMPLE[did] = (done, now, None)
    out = {'a_progress': '%s of %s' % (_human(done), _human(total))}
    if speed:
        out['a_speed'] = '%s/s' % _human(speed)
        left = max(total - done, 0) / speed
        if left < 90:
            out['a_eta'] = 'under 2 min left'
        elif left < 5400:
            out['a_eta'] = 'about %d min left' % round(left / 60)
        else:
            out['a_eta'] = 'about %.1f h left' % (left / 3600)
    return out
```

In `ddl_queue_rows`, add these keys to the dict appended to `resultlist` (after `'jd2': ...`):

```python
                           'filename':     r['filename'] if 'filename' in r.keys() else None,
                           'tmp_filename': r['tmp_filename'] if 'tmp_filename' in r.keys() else None,
                           'remote_filesize': r['remote_filesize'] if 'remote_filesize' in r.keys() else None,
```

Change `def build(myDB, active=None):` and its docstring to:

```python
def build(myDB, active=None, rate=None):
    """One list of every download: direct ones and the ones at a download client.

    `active` is one DDL item's progress from check_ActiveDDL ({'a_id', 'percent', ...}); every other
    direct download that's running gets its progress from its file, and `rate(id, done, total)`,
    when given, adds speed and time left.
    """
```

In the DDL loop of `build`, after the existing `if active and status == 'Downloading' and ...:` block and before `rows.append(row)`, add:

```python
        elif status == 'Downloading':
            p = ddl_progress(d)
            if p and p['percent'] is not None:
                row['percent'] = p['percent']
                if rate:
                    r = rate(d['queueid'], p['done'], p['total'])
                    row['speed'], row['eta'], row['progress'] = r.get('a_speed'), r.get('a_eta'), r.get('a_progress')
```

- [ ] **Step 4: `mylar/webserve.py`**

Delete `_DL_SAMPLE = {}`, `def _human_bytes(n):` and `def _download_rate(did, done, total):` (the block from `_DL_SAMPLE = {}` to the `return out` that ends `_download_rate`). Add `from mylar.queues import ddl as ddl_queue` next to `from mylar.queues import queue_info`.

Replace `def downloadQueue(self):` with:

```python
    def downloadQueue(self):
        # Everything on its way: direct downloads plus grabs at SABnzbd, NZBGet or a torrent client.
        myDB = db.DBConnection()
        return json.dumps({'items': downloadqueue.build(myDB, rate=downloadqueue.download_rate),
                           'waiting': ddl_queue.waiting_count()})
    downloadQueue.exposed = True
```

In `check_ActiveDDL`, change `out['waiting'] = mylar.DDL_QUEUE.qsize()` to `out['waiting'] = ddl_queue.waiting_count()` and `out.update(_download_rate(out['a_id'], out['a_done'], out['a_total']))` to `out.update(downloadqueue.download_rate(out['a_id'], out['a_done'], out['a_total']))`.

Replace the whole `def _active_ddl(self):` method with:

```python
    def _active_ddl(self):
         myDB = db.DBConnection()
         # several downloads can run at once - report the one that started last
         active = myDB.selectone("SELECT * FROM DDL_INFO WHERE STATUS = 'Downloading' ORDER BY updated_date DESC").fetchone()
         if active is None:
             return json.dumps({'status':   'There are no active downloads currently being attended to',
                                'percent':   0,
                                'a_series':  None,
                                'a_year':  None,
                                'a_filename':  None,
                                'a_size':  None,
                                'a_id':  None,
                                'a_issueid': None})
         progress = downloadqueue.ddl_progress(active)
         if progress and progress['total']:
             return json.dumps({'status':      'Downloading',
                                'percent':     '%s%%' % progress['percent'],
                                'a_series':    active['series'],
                                'a_year':      active['year'],
                                'a_filename':  active['filename'],
                                'a_size':      active['size'],
                                'a_done':      progress['done'],
                                'a_total':     progress['total'],
                                'a_id':        active['id']})
         if active['filename'] is None and not active['tmp_filename']:
             statline = 'No filename assigned for %s (%s).</br> This was probably never started successfully - you should restart the download (use the option in the GUI)' % (active['series'], active['year'])
         else:
             statline = 'No download file yet for %s (%s).</br> If this doesn\'t change, restart the download.' % (active['series'], active['year'])
         return json.dumps({'a_id': active['id'], 'status': statline, 'percent': 0})
```

Check: `grep -n "_download_rate\|_human_bytes\|_DL_SAMPLE\|DDL_QUEUE.qsize" mylar/webserve.py` prints nothing.

- [ ] **Step 5: `mylar/queues/utils.py`**

Replace `queue_info` with:

```python
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_download_queue.py tests/test_queues.py -q -p no:cacheprovider`
Expected: all pass.

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 7: Commit**

```bash
git add mylar/downloadqueue.py mylar/webserve.py mylar/queues/utils.py tests/test_download_queue.py tests/test_queues.py
git commit -m "feat(queue): progress and speed for every active direct download"
```

---

### Task 7: Final check

**Files:** none new.

- [ ] **Step 1: Full suite**

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: 0 failed, 498 passed (453 existing, counting the test fixed in Task 1, plus 45 new).

- [ ] **Step 2: No undefined names in the changed files**

Run: `python -m pyflakes mylar/queues/ddl.py mylar/queues/jd2.py mylar/queues/utils.py mylar/downloadqueue.py mylar/downloaders/mediafire.py mylar/downloaders/pixeldrain.py mylar/downloaders/mega.py 2>&1 | grep -i "undefined name"`
Expected: no output. (`pip install pyflakes` first if needed. `webserve.py` and `getcomics.py` have older undefined names; check that none of them is in code this plan touched: `python -m pyflakes mylar/webserve.py mylar/getcomics.py | grep -i "undefined name"` and compare with the list before Task 1.)

- [ ] **Step 3: Nothing still uses the removed names**

Run: `grep -rn "DDL_LOCK\|jd2_fallback\|LINK_TYPE_FAILURE\|_download_rate\|ACTIVE\[0\]" mylar/ tests/`
Expected: no output.

- [ ] **Step 4: Spec coverage**

Walk the spec's Testing list against the tests: 1-5, 9 and 11 in `test_ddl_parallel.py` (9 also in `test_ddl_failover.py`); 6 and 7 in `test_ddl_parallel.py` and `test_ddl_failover.py`; 8 in `test_ddl_failover.py` (JD2 skipped, failed links kept) with `test_jd2_giveup.py` (JD2 give-up reaches failover; without JD2, links go to the built-in downloaders) and the existing big-file ordering tests in `test_getcomics_single.py`; 10 in `test_download_queue.py`.

- [ ] **Step 5: Open the pull request**

Push the branch and open a draft PR describing the change. It links the spec and lists the server check from the spec: after deploying, the log shows two file-host downloads at once (`DDL-HOST-…` threads) and never two `DDL-GETCOMICS` downloads at once.
