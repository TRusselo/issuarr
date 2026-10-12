"""Running now / Folder Monitor: what filing is doing and what its last pass did.

2026-10-12: "folder monitor don't seem to work". It did - four passes overnight filed over 100
issues and auto-add added 84 series - but auto-add ran alongside the passes and both shared one
status. The first pass to finish set it to Idle while auto-add worked for another hour and a half,
its notes were dropped, and the "Last pass" line only ever said how many files were checked.
"""
import threading
import types

import pytest

import mylar
from mylar import archives


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(archives, 'ACTIVE', {})
    monkeypatch.setattr(archives, 'LAST', {'last': '', 'last_at': None})
    monkeypatch.setattr(archives, 'MONITOR', {'skipped_at': None, 'why': ''})


def in_thread(fn):
    t = threading.Thread(target=fn)
    t.start()
    t.join()


@pytest.mark.unit
def test_a_pass_finishing_doesnt_hide_auto_add_still_running(fresh):
    gate, finished = threading.Event(), threading.Event()

    def auto_add():
        archives.busy('Finding series for 110 unclaimed issues')
        gate.wait(5)
        archives.note('added 84 series')
        archives.done('Auto-add finished.')
        finished.set()

    t = threading.Thread(target=auto_add)
    t.start()
    try:
        def monitor_pass():
            archives.busy('Post-processing the monitored folder')
            archives.note('checked 40 files against the watchlist')
            archives.done()
        in_thread(monitor_pass)
        snap = archives.snapshot()
        assert snap['state'] == 'Working'
        assert snap['detail'] == 'Finding series for 110 unclaimed issues'
        assert snap['last'] == 'checked 40 files against the watchlist'
    finally:
        gate.set()
        t.join()
    assert finished.is_set()
    snap = archives.snapshot()
    assert snap['state'] == 'Idle' and snap['last'] == 'added 84 series'


@pytest.mark.unit
def test_last_pass_says_what_was_filed_and_what_needs_attention(fresh):
    def monitor_pass():
        archives.busy('Post-processing the monitored folder')
        archives.note('checked 40 files against the watchlist')
        for _ in range(22):
            archives.tally('filed')
        archives.tally('attention')
        archives.done()
    in_thread(monitor_pass)
    assert archives.snapshot()['last'] == ('checked 40 files against the watchlist; filed 22 issues; '
                                           '1 file left for Downloads > Needs attention')


@pytest.mark.unit
def test_a_crashed_auto_add_doesnt_leave_filing_working(fresh, monkeypatch):
    from mylar import autoadd
    myDB = types.SimpleNamespace(select=lambda *a, **k: [])
    monkeypatch.setattr(autoadd.db, 'DBConnection', lambda: myDB)
    monkeypatch.setattr(autoadd, '_load', lambda: {})

    def save(reg):
        # Fails after _run has said it's busy.
        assert archives.snapshot()['state'] == 'Working'
        raise RuntimeError('disk full')
    monkeypatch.setattr(autoadd, '_save', save)

    def run():
        with pytest.raises(RuntimeError):
            autoadd._run([])
    in_thread(run)
    snap = archives.snapshot()
    assert snap['state'] == 'Idle' and not autoadd.running()
    assert snap['last'] == 'Auto-add stopped early - check the log.'


@pytest.mark.unit
def test_filing_from_a_web_request_doesnt_count_in_another_job(fresh):
    gate = threading.Event()

    def auto_add():
        archives.busy('Finding series')
        archives.note('added 84 series')
        gate.wait(5)
        archives.done()

    t = threading.Thread(target=auto_add)
    t.start()
    try:
        # Re-filing from Needs attention runs in a web thread that never called busy().
        in_thread(lambda: archives.tally('filed'))
    finally:
        gate.set()
        t.join()
    assert archives.snapshot()['last'] == 'added 84 series'


@pytest.mark.unit
def test_a_manual_run_of_the_monitored_folder_clears_the_skip(fresh, monkeypatch):
    from mylar import PostProcessor
    archives.skipped('other post-processing was running')
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(CHECK_FOLDER='/downloads/complete/mylar'), raising=False)
    monkeypatch.setattr(archives, 'sweep', lambda *a, **k: None)
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp.nzb_folder, pp.nzb_name = '/downloads/complete/mylar', 'Manual Run'
    pp._process_main = lambda: None
    in_thread(pp._locked_process)
    assert archives.snapshot()['monitor_skipped_at'] is None


@pytest.mark.unit
def test_folder_monitor_says_when_it_skipped_a_check(fresh, monkeypatch):
    from mylar import PostProcessor
    monkeypatch.setattr(mylar, 'IMPORTLOCK', False, raising=False)
    monkeypatch.setattr(mylar, 'APILOCK', True, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(CHECK_FOLDER='/downloads/complete/mylar'), raising=False)
    monkeypatch.setattr(PostProcessor.logger, 'info', lambda *a, **k: None)
    PostProcessor.FolderCheck().run()
    snap = archives.snapshot()
    assert snap['monitor_skipped_at'] and snap['monitor_skipped_why'] == 'other post-processing was running'


@pytest.mark.unit
def test_pp_activity_passes_the_skip_to_the_page(fresh, monkeypatch):
    import json
    from mylar import webserve
    archives.skipped('other post-processing was running')
    monkeypatch.setattr(webserve.archives, 'review_dir', lambda: '')
    monkeypatch.setattr(webserve.search, 'search_status', lambda: None)
    monkeypatch.setattr(webserve.WebInterface, 'check_ActiveDDL', lambda self: json.dumps({'status': 'Idle'}))
    monkeypatch.setattr(webserve.webp, 'dock_summary', lambda: None)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_CHECK_FOLDER=True, CHECK_FOLDER='/downloads/complete/mylar',
                                                               DOWNLOAD_SCAN_INTERVAL=15), raising=False)
    monkeypatch.setattr(mylar, 'MONITOR_STATUS', 'Waiting', raising=False)
    out = json.loads(webserve.WebInterface.pp_activity(webserve.WebInterface()))
    assert out['monitor_skipped_why'] == 'other post-processing was running' and out['state'] == 'Idle'


@pytest.mark.unit
def test_a_file_left_for_needs_attention_counts_in_the_pass(fresh, monkeypatch, tmp_path):
    from mylar import PostProcessor
    f = tmp_path / 'Witchblade 025 (2026).cbr'
    f.write_bytes(b'x')
    monkeypatch.setattr(PostProcessor.attention, 'record', lambda *a, **k: None)
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp._att = {'path': str(f), 'reasons': {'series'}, 'detail': '', 'comicid': None, 'counts': (0, 0, 0)}

    def monitor_pass():
        archives.busy('Post-processing the monitored folder')
        pp._att_settle((0, 0, 0))
        archives.done()
    in_thread(monitor_pass)
    assert archives.snapshot()['last'] == '1 file left for Downloads > Needs attention'
