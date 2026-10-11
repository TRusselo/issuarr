#  This file is part of Issuarr.
#
#  Issuarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Issuarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Issuarr.  If not, see <http://www.gnu.org/licenses/>.

"""Publisher -> imprint listing (data/imprints.json).

The listing ships with Issuarr. A copy is also fetched from the repository
once a day into the cache folder, so fixes to the list reach installs that
haven't updated yet. Whichever copy has the higher version is used.
"""

import json
import os
import time

import requests

from mylar import logger

IMPRINTS_URL = 'https://raw.githubusercontent.com/issuarr/issuarr/main/data/imprints.json'
MAX_AGE_HOURS = 24


def _version(data):
    try:
        return tuple(int(x) for x in str(data.get('version', '0')).split('.'))
    except (ValueError, AttributeError):
        return (0,)


def _valid(data):
    return isinstance(data, dict) and isinstance(data.get('publishers'), list)


def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.warn('[IMPRINT_LOADS] Unable to read %s: %s' % (path, e))
        return None
    return data if _valid(data) else None


def _is_stale(path):
    try:
        return (time.time() - os.path.getmtime(path)) / 3600 > MAX_AGE_HOURS
    except OSError:
        return True


def _download(path):
    try:
        r = requests.get(IMPRINTS_URL, timeout=30)
        r.raise_for_status()
        data = r.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warn('[IMPRINT_LOADS] Unable to retrieve the publisher imprints listing: %s' % e)
        return
    if not _valid(data):
        logger.warn('[IMPRINT_LOADS] Downloaded publisher imprints listing is not in the expected format. Ignoring it.')
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        logger.warn('[IMPRINT_LOADS] Unable to write %s: %s' % (path, e))


def load(cache_dir, prog_dir, download=True):
    """Return the imprint listing, or None if no usable copy exists."""
    bundled = os.path.join(prog_dir, 'data', 'imprints.json')
    cached = os.path.join(cache_dir, 'imprints.json') if cache_dir else None

    if download and cached and _is_stale(cached):
        _download(cached)

    best = None
    for path in (bundled, cached):
        if not path:
            continue
        data = _read(path)
        if data is not None and (best is None or _version(data) > _version(best)):
            best = data
    return best
