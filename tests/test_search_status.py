import queue

import pytest

import mylar
from mylar import search


@pytest.fixture
def idle(monkeypatch):
    monkeypatch.setattr(mylar, 'SEARCH_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_CURRENT', None, raising=False)
    monkeypatch.setattr(mylar, 'SEARCHLOCK', False, raising=False)


def item(issueid, name='Alpha', number='1'):
    return {'issueid': issueid, 'comicname': name, 'issuenumber': number, 'comicid': '1', 'booktype': 'Print'}


@pytest.mark.unit
def test_nothing_to_report_when_idle(idle):
    assert search.search_status() == {'current': None, 'waiting': [], 'busy': False}


@pytest.mark.unit
def test_reports_the_issue_being_searched_and_the_queue_in_order(idle):
    mylar.SEARCH_CURRENT = item('617854', 'Star Wars: Mace Windu', '1')
    mylar.SEARCHLOCK = True
    mylar.SEARCH_QUEUE.put(item('a', 'Ant-Man', '2'))
    mylar.SEARCH_QUEUE.put('exit')
    mylar.SEARCH_QUEUE.put(item('b', 'Batman', '3'))
    status = search.search_status()
    assert status['current'] == {'issueid': '617854', 'name': 'Star Wars: Mace Windu', 'number': '1'}
    assert [w['issueid'] for w in status['waiting']] == ['a', 'b']
    assert status['busy'] is True
