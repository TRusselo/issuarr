import os
from types import SimpleNamespace

import pytest

import mylar
from mylar import versioncheck


@pytest.fixture(autouse=True)
def quiet_log(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)


def _version(monkeypatch, tmp_path, built_from, config_branch):
    (tmp_path / '.LAST_RELEASE').write_text(' (%s)\nabc123def\n' % built_from)
    monkeypatch.setattr(mylar, 'PROG_DIR', str(tmp_path))
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(GIT_BRANCH=config_branch, GIT_REPO='issuarr', GIT_TOKEN=None, DESTINATION_DIR='/comics'), raising=False)
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, 'exists', lambda p: p == '/.dockerenv' or real_exists(p))
    ptv = {'git_branch': config_branch, 'git_user': 'issuarr', 'git_token': None, 'check_github_on_startup': False, 'git_path': None}
    return versioncheck.getVersion(ptv)


@pytest.mark.parametrize('built_from,config_branch', [('dev', 'main'), ('main', 'dev'), ('main', 'main'), ('dev', None)])
def test_docker_follows_the_branch_the_image_was_built_from(monkeypatch, tmp_path, built_from, config_branch):
    info = _version(monkeypatch, tmp_path, built_from, config_branch)
    assert mylar.INSTALL_TYPE == 'docker'
    assert info['branch'] == built_from
    assert info['current_version'] == 'abc123def'


def test_docker_feature_branch_image_keeps_the_configured_branch(monkeypatch, tmp_path):
    info = _version(monkeypatch, tmp_path, 'claude/some-feature', 'main')
    assert info['branch'] == 'main'
