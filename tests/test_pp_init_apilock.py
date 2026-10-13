import queue

import pytest

import mylar
from mylar import PostProcessor


@pytest.mark.unit
def test_a_run_can_be_set_up_while_another_holds_the_api_lock(monkeypatch):
    # live 12 Oct: File as on Needs attention failed with "__init__() should return None, not 'dict'"
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'FILE_OPTS', 'move', raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'IGNORE_SEARCH_WORDS', [], raising=False)
    monkeypatch.setattr(mylar, 'APILOCK', True, raising=False)
    pp = PostProcessor.PostProcessor('Manual Run', '/downloads/mylar-review', queue=queue.Queue())
    assert pp.nzb_folder == '/downloads/mylar-review'
    assert mylar.APILOCK is True   # still the other run's
