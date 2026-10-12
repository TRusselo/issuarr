"""The Running now box, the flow line and Tasks > Schedule use one color per activity."""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


CSS = re.sub(r'/\*.*?\*/', '', _read('data', 'css', 'issuarr.css'), flags=re.S)
BASE = _read('data', 'interfaces', 'default', 'base.html')
TASKS_JS = _read('data', 'js', 'tasks.js')


def _rules(selector):
    """Declaration blocks of every top-level rule whose selector list is exactly `selector`."""
    pat = r'(?:^|\})\s*' + re.escape(selector) + r'\s*\{([^}]*)\}'
    return re.findall(pat, CSS, flags=re.M)


def _decl(selector, prop):
    for body in _rules(selector):
        m = re.search(r'(?:^|;)\s*' + re.escape(prop) + r'\s*:\s*([^;]+)', body)
        if m:
            return m.group(1).strip()
    return None


@pytest.mark.unit
def test_dot_reads_its_color_from_a_custom_property():
    assert _decl('.dot', 'background') == 'var(--dot, var(--snatched))'
    # An idle dot must still draw hollow, so no ID rule may set a dot's background directly.
    assert _decl('.dot.is-idle', 'background') == 'transparent'
    assert not re.search(r'#dock-[\w-]+\s+\.dot[^{]*\{[^}]*background', CSS)


@pytest.mark.unit
def test_every_active_dock_row_has_a_color():
    rows = re.findall(r'id="(dock-[\w-]+)"[^>]*><span class="dot"></span>', BASE)
    assert set(rows) == {'dock-pp', 'dock-search', 'dock-dl'}
    for row in rows:
        assert _decl('#' + row, '--dot'), row


@pytest.mark.unit
@pytest.mark.parametrize('row,stage,token', [
    ('dock-search', '--flow-search', '--wanted'),
    ('dock-dl', '--flow-download', '--snatched'),
    ('dock-pp', '--flow-filing', '--snatched'),
])
def test_dock_rows_match_the_flow_line(row, stage, token):
    assert _decl('#' + row, '--dot') == 'var(%s)' % stage
    assert _decl(':where(:root)', stage) == 'var(%s)' % token
    assert _decl('.flow', stage) is None


@pytest.mark.unit
def test_import_spinner_uses_the_palette():
    assert _decl('#import_indicator .ii-spin', 'border-top-color') == 'var(--snatched)'
    assert _decl('#import_indicator.ii-wait .ii-spin', 'border-top-color') == 'var(--wanted)'


@pytest.mark.unit
def test_running_search_jobs_show_as_wanted():
    jobs = re.search(r'SEARCH_JOBS\s*=\s*\{([^}]*)\}', TASKS_JS).group(1)
    assert re.findall(r"'([^']+)'\s*:", jobs) == ['Auto-Search', 'RSS Feeds']
    # The names must match the scheduler's job names.
    webserve = _read('mylar', 'webserve.py')
    assert "'Auto-Search'" in webserve and "'RSS Feeds'" in webserve
    assert "SEARCH_JOBS[job] ? 'is-wanted' : 'is-snatched'" in TASKS_JS
    assert 'statusClass(j.status, j.jobname)' in TASKS_JS
