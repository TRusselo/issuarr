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
        self.failed = []
        self.results = {}
        self.raises = set()
        self.gates = collections.defaultdict(threading.Event)
        self.closing = False

    def __call__(self, myDB, item):
        group = 'gc' if threading.current_thread().name == 'DDL-GETCOMICS' else 'host'
        with self.lock:
            self.running[group] += 1
            self.peak[group] = max(self.peak[group], self.running[group])
            self.started.append(item['id'])
        try:
            self.gates[item['id']].wait(0 if self.closing else 5)
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
    monkeypatch.setattr(ddl, 'WORKER_POLL', 0.05)
    monkeypatch.setattr(ddl, 'reload_saved', lambda myDB: None)
    monkeypatch.setattr(ddl.db, 'DBConnection', lambda *a, **k: None)
    fake = FakeDownloads()
    monkeypatch.setattr(ddl, 'ddl_process', fake)
    monkeypatch.setattr(ddl, 'handle_failure',
                        lambda myDB, item, result, jd2_gave_up=False: fake.failed.append((item, result, jd2_gave_up)))
    fake.dispatcher = threading.Thread(target=ddl.ddl_downloader, args=(mylar.DDL_QUEUE,), name='DDL-QUEUE', daemon=True)
    fake.dispatcher.start()
    yield fake
    fake.closing = True
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


@pytest.mark.unit
def test_restarting_the_queue_never_runs_two_getcomics_downloads(lanes):
    # turning direct downloads off and on again starts a new dispatcher while the old GetComics worker is busy
    for i in ('a', 'b', 'c'):
        mylar.DDL_QUEUE.put(gc_item(i))
    assert wait_for(lambda: 'a' in lanes.started)
    mylar.DDL_QUEUE.put('exit')
    assert wait_for(lambda: not lanes.dispatcher.is_alive(), timeout=10)
    lanes.dispatcher = threading.Thread(target=ddl.ddl_downloader, args=(mylar.DDL_QUEUE,), name='DDL-QUEUE', daemon=True)
    lanes.dispatcher.start()
    time.sleep(0.5)
    lanes.release('a', 'b', 'c')
    assert wait_for(lambda: sorted(lanes.done) == ['a', 'b', 'c'], timeout=10)
    assert lanes.peak['gc'] == 1
