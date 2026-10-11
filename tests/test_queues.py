import os

import pytest
from mockito import verify

import mylar
from mylar.queues import ddl_cleanup


@pytest.mark.unit
def test_ddl_cleanup(when, monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "CACHE_DIR", os.getcwd(), raising=False)
    when(os).remove(...)
    ddl_cleanup('1234')
    verify(os, times=1).remove(os.path.join(os.getcwd(), "html_cache", "getcomics-1234.html"))


@pytest.mark.unit
def test_ddl_cleanup_keep_cache(when, monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "CACHE_DIR", os.getcwd(), raising=False)
    monkeypatch.setattr(mylar.CONFIG, "KEEP_HTML_CACHE", True, raising=False)
    when(os).remove(...)
    ddl_cleanup('1234')
    verify(os, times=0).remove(os.path.join(os.getcwd(), "html_cache", "getcomics-1234.html"))

## Queue Functions to mock
# postprocess_main
# search_queue
# worker_main
# nzb_monitor
# cdh_monitor
# queue_inf


@pytest.mark.unit
def test_queue_info_counts_every_waiting_direct_download(monkeypatch):
    from mylar.queues import ddl, queue_info
    monkeypatch.setattr(ddl, 'waiting_count', lambda: 7)
    info = {q.name: q for q in queue_info()}
    assert info['DDL-QUEUE'].size == 7
