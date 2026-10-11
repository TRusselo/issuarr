import os
from types import SimpleNamespace

import cherrypy
import pytest

import mylar
from mylar import ui


@pytest.mark.parametrize('value,expected', [
    ('dark', 'dark'), ('light', 'light'), ('system', 'system'), ('LIGHT', 'light'),
    (None, 'dark'), ('', 'dark'), ('purple', 'dark'),
])
def test_theme_falls_back_to_dark(monkeypatch, value, expected):
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(UI_THEME=value))
    assert ui.theme() == expected


def test_custom_css_round_trip(tmp_path):
    assert ui.read_custom_css(str(tmp_path)) == ''
    assert ui.custom_css_version(str(tmp_path)) == 0
    ui.write_custom_css(':root {\r\n  --ink: #000;\r\n}\r\n', str(tmp_path))
    assert ui.read_custom_css(str(tmp_path)) == ':root {\n  --ink: #000;\n}\n'
    assert ui.custom_css_version(str(tmp_path)) > 0
    assert [p.name for p in tmp_path.iterdir()] == [ui.CUSTOM_CSS_FILE]


def test_blank_custom_css_removes_the_file(tmp_path):
    ui.write_custom_css('body { color: red; }', str(tmp_path))
    ui.write_custom_css('   \n', str(tmp_path))
    assert not os.path.exists(ui.custom_css_path(str(tmp_path)))
    ui.write_custom_css('', str(tmp_path))


def test_oversized_custom_css_is_refused(tmp_path):
    ui.write_custom_css('a { color: red; }', str(tmp_path))
    with pytest.raises(ValueError):
        ui.write_custom_css('x' * (ui.CUSTOM_CSS_MAX_BYTES + 1), str(tmp_path))
    assert ui.read_custom_css(str(tmp_path)) == 'a { color: red; }'


@pytest.mark.parametrize('url,expected', [
    ('https://example.com/theme.css', 'https://example.com/theme.css'),
    ('  http://nas.local:8080/t.css ', 'http://nas.local:8080/t.css'),
    ('/themes/issuarr.css', '/themes/issuarr.css'),
    ('//evil.example/x.css', None),
    ('javascript:alert(1)', None),
    ('data:text/css,body{}', None),
    ('https://example.com/a.css" onload="x', None),
    ('theme.css', None),
    ('None', None),
    ('', None),
    (None, None),
])
def test_safe_stylesheet_url(url, expected):
    assert ui.safe_stylesheet_url(url) == expected


@pytest.mark.parametrize('params,flag', [
    ({'nocss': '1', 'ComicID': '42'}, True),
    ({'nocss': 'true'}, True),
    ({'nocss': ['0', '1']}, True),
    ({'nocss': '0'}, False),
    ({'ComicID': '42'}, False),
])
def test_nocss_param_is_taken_off_the_request(params, flag):
    req = cherrypy.serving.request
    saved = req.params
    try:
        req.params = dict(params)
        ui.strip_nocss_param()
        assert 'nocss' not in req.params
        assert ui.nocss_requested() is flag
        if 'ComicID' in params:
            assert req.params['ComicID'] == '42'
    finally:
        req.params = saved
        req.issuarr_nocss = False
