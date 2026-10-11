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
        c.newconfig = 21
        c.GIT_USER = git_user
        c.GIT_BRANCH = git_branch
        c.GIT_REPO = 'Issuarr'
        c.config_update()
    finally:
        mconfig.config = old
    return c, cp


@pytest.mark.parametrize('user', ['MylarComics', 'mylar3', None])
def test_update_checks_move_to_issuarr(user):
    c, cp = _upgrade(user, 'stable')
    assert c.GIT_USER == 'TRusselo'
    assert c.GIT_BRANCH == 'main'
    assert c.GIT_REPO == 'Issuarr'
    assert cp.get('Git', 'GIT_USER') == 'TRusselo'
    assert cp.get('Git', 'GIT_BRANCH') == 'main'


def test_own_fork_and_branch_are_kept():
    c, cp = _upgrade('someone', 'my-branch')
    assert c.GIT_USER == 'someone'
    assert c.GIT_BRANCH == 'my-branch'
    assert c.GIT_REPO == 'mylar3'
    assert not cp.has_option('Git', 'GIT_USER')


def test_old_main_branch_name_moves_to_main():
    c, cp = _upgrade('TRusselo', 'trusselo')
    assert c.GIT_BRANCH == 'main'
    assert cp.get('Git', 'GIT_BRANCH') == 'main'


def test_defaults_point_at_issuarr():
    assert mconfig._CONFIG_DEFINITIONS['GIT_USER'][2] == 'TRusselo'
    assert mconfig._CONFIG_DEFINITIONS['GIT_REPO'][2] == 'Issuarr'
