import configparser

import pytest

import mylar
from mylar import config as mconfig


@pytest.fixture(autouse=True)
def quiet_log(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)


def _upgrade(git_user, git_branch):
    cp = configparser.ConfigParser()
    cp.add_section('Git')
    cp.add_section('Release Provider')
    old = mconfig.config
    mconfig.config = cp
    try:
        c = mconfig.Config.__new__(mconfig.Config)
        c.CONFIG_VERSION = 19
        c.newconfig = 20
        c.GIT_USER = git_user
        c.GIT_BRANCH = git_branch
        c.config_update()
    finally:
        mconfig.config = old
    return c, cp


@pytest.mark.parametrize('user', ['MylarComics', 'mylar3', None])
def test_update_checks_move_to_trusselo(user):
    c, cp = _upgrade(user, 'stable')
    assert c.GIT_USER == 'TRusselo'
    assert c.GIT_BRANCH == 'trusselo'
    assert cp.get('Git', 'GIT_USER') == 'TRusselo'
    assert cp.get('Git', 'GIT_BRANCH') == 'trusselo'


def test_own_fork_and_branch_are_kept():
    c, cp = _upgrade('someone', 'my-branch')
    assert c.GIT_USER == 'someone'
    assert c.GIT_BRANCH == 'my-branch'
    assert not cp.has_option('Git', 'GIT_USER')


def test_default_user_is_trusselo():
    assert mconfig._CONFIG_DEFINITIONS['GIT_USER'][2] == 'TRusselo'
