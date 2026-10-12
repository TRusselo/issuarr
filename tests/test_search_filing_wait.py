"""Searching waits for filing only when filing could be handling the same series.

2026-10-11: every search waited for all post-processing to finish, and with downloads finishing
one after another the search queue moved one issue every 35-60 seconds.
"""
import queue

import pytest

import mylar
from mylar import archives, autoadd
from mylar.queues import search as worker


@pytest.fixture
def filing(monkeypatch):
    monkeypatch.setattr(mylar, 'PP_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(archives, 'JOBS', [])
    monkeypatch.setattr(autoadd, 'running', lambda: False)
    monkeypatch.setattr(worker, 'HELD', {})
    for name in ('info', 'fdebug'):
        monkeypatch.setattr(worker.logger, name, lambda *a, **k: None)


def item(comicid='100', issueid='1'):
    return {'comicid': comicid, 'issueid': issueid, 'comicname': 'Iron Man', 'issuenumber': '4'}


@pytest.mark.unit
def test_filing_another_series_doesnt_hold_a_search(filing):
    archives.JOBS.append('200')
    mylar.PP_QUEUE.put({'comicid': '300'})
    assert not worker.held(item())


@pytest.mark.unit
def test_filing_the_same_series_holds_it(filing):
    archives.JOBS.append('100')
    assert worker.held(item())
    archives.JOBS.clear()
    mylar.PP_QUEUE.put({'comicid': '100'})
    assert worker.held(item())


@pytest.mark.unit
@pytest.mark.parametrize('how', ['monitored folder', 'auto-add'])
def test_filing_that_could_be_anything_holds_every_search(filing, monkeypatch, how):
    if how == 'auto-add':
        monkeypatch.setattr(autoadd, 'running', lambda: True)
    else:
        archives.JOBS.append(None)
    assert worker.held(item())


@pytest.mark.unit
def test_a_held_search_goes_ahead_after_the_limit(filing, monkeypatch):
    archives.JOBS.append('100')
    worker.HELD['1'] = 0     # held since the epoch
    assert not worker.held(item())
    assert '1' not in worker.HELD


@pytest.mark.unit
def test_post_processing_registers_its_series_while_it_runs(filing, monkeypatch):
    from mylar import PostProcessor
    seen = []
    monkeypatch.setattr(PostProcessor.PostProcessor, '_locked_process', lambda self: seen.append(list(archives.JOBS)))
    for name, comicid, expected in (('Iron Man #4', '100', ['100']), ('Manual Run', None, [None])):
        pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
        pp.nzb_name, pp.comicid, pp.apicall = name, comicid, False
        pp.Process()
        assert seen.pop() == expected and archives.JOBS == []
