#  This file is part of Mylar.
#
#  Mylar is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mylar is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mylar.  If not, see <http://www.gnu.org/licenses/>.

"""Interface helpers: the theme choice and the user's custom CSS.

The custom CSS lives in its own file next to config.ini rather than in the
ini itself, so multi-line stylesheets survive untouched.
"""

import os
import re
import tempfile

import cherrypy

import mylar

CUSTOM_CSS_FILE = 'custom.css'
CUSTOM_CSS_MAX_BYTES = 256 * 1024
THEMES = ('dark', 'light', 'system')

_URL_OK = re.compile(r'^https?://[^\s"\'<>]+$', re.I)
_PATH_OK = re.compile(r'^/(?!/)[^\s"\'<>]*$')


def theme():
    value = str(getattr(mylar.CONFIG, 'UI_THEME', None) or 'dark').strip().lower()
    return value if value in THEMES else 'dark'


def custom_css_path(data_dir=None):
    return os.path.join(data_dir or mylar.DATA_DIR or '', CUSTOM_CSS_FILE)


def read_custom_css(data_dir=None):
    try:
        with open(custom_css_path(data_dir), encoding='utf-8') as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ''


def write_custom_css(text, data_dir=None):
    """Save the stylesheet, or remove the file when it is blank."""
    text = (text or '').replace('\r\n', '\n')
    if len(text.encode('utf-8')) > CUSTOM_CSS_MAX_BYTES:
        raise ValueError('Custom CSS is larger than %d KB' % (CUSTOM_CSS_MAX_BYTES // 1024))
    path = custom_css_path(data_dir)
    if not text.strip():
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    folder = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(prefix='.custom-css-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def custom_css_version(data_dir=None):
    """Changes whenever the file does, so browsers fetch the new copy."""
    try:
        return int(os.path.getmtime(custom_css_path(data_dir)))
    except OSError:
        return 0


def safe_stylesheet_url(url):
    """An http(s) URL or a path on this server, else None."""
    url = str(url or '').strip()
    if url.lower() == 'none':
        return None
    if _URL_OK.match(url) or _PATH_OK.match(url):
        return url
    return None


def _truthy(value):
    if isinstance(value, (list, tuple)):
        value = value[-1] if value else ''
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def strip_nocss_param():
    """before_handler hook: take ?nocss=1 off the request so page handlers never see it."""
    req = cherrypy.request
    value = req.params.pop('nocss', None)
    req.issuarr_nocss = value is not None and _truthy(value)


def nocss_requested():
    return bool(getattr(cherrypy.request, 'issuarr_nocss', False))
