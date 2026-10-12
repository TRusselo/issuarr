"""On the Ledger only an issue's Snatched status is yellow; trades get their own collection colour."""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return re.sub(r'/\*.*?\*/', '', f.read(), flags=re.S)


CSS = _read('data', 'css', 'issuarr.css')
LEDGER_CSS = _read('data', 'css', 'ledger.css')
JS = _read('data', 'js', 'ledger.js')


def _lg(prop):
    body = re.search(r'(?:^|\})\s*\.lg\s*\{([^}]*)\}', LEDGER_CSS, flags=re.M).group(1)
    m = re.search(r'(?:^|;)\s*' + re.escape(prop) + r'\s*:\s*([^;]+)', body)
    return m.group(1).strip() if m else None


@pytest.mark.unit
def test_ledger_stylesheet_never_uses_the_snatched_yellow():
    assert '--snatched' not in LEDGER_CSS
    assert '--t-snatch' not in LEDGER_CSS


@pytest.mark.unit
def test_focus_rings_on_the_ledger_are_not_yellow():
    # The global focus ring is var(--snatched); on the Ledger yellow means Snatched only.
    assert _lg('--focus') == 'var(--text)'


@pytest.mark.unit
def test_trade_chips_use_the_collection_colour_not_a_status_colour():
    status = ('--wanted', '--snatched', '--have', '--failed', '--ignored', '--lg-done')
    fills, dupe = _lg('--lg-c-fills'), _lg('--lg-c-dupe')
    assert fills == 'var(--collection)'
    assert '--collection' in dupe and dupe != fills
    for v in (fills, dupe):
        assert not any(s + ')' in v or s + ',' in v for s in status), v
    # A trade you own that collects a missing issue is the same colour as Fills gaps, not On disk.
    assert "style=\"--c:var(--lg-done)\" href=\"comicDetails" not in JS
    assert "'<a class=\"lg-trade\" style=\"--c:var(--lg-c-fills)\"" in JS


@pytest.mark.unit
def test_collection_colour_is_defined_for_every_theme():
    blocks = re.findall(r':where\(:root(?:\[data-theme="light"\]|:not\(\[data-theme\]\))?\)\s*\{([^}]*)\}', CSS)
    themed = [b for b in blocks if '--snatched:' in b]
    assert len(themed) == 3
    for b in themed:
        assert re.search(r'--collection:\s*#[0-9A-Fa-f]{6};', b)


@pytest.mark.unit
def test_only_the_snatched_status_maps_to_yellow_in_ledger_js():
    assert re.findall(r'(\w+)\s*:\s*\'is-snatched\'', JS) == ['Snatched']
    assert re.findall(r'\[\'(\w+)\', \'seg-snatched\'', JS) == ['s']
    assert re.findall(r'(\w+): \[\'seg-snatched\'', JS) == ['s']
    # The 's' bucket counts Snatched issues and nothing else.
    assert "else if (r[7] === 'Snatched') c.s++;" in JS


@pytest.mark.unit
def test_snatched_segments_say_what_yellow_means():
    assert "['s', 'seg-snatched', 'Snatched', 'Grabbed, not filed yet']" in JS
    assert "s: ['seg-snatched', 'snatched', 'grabbed, not filed yet']" in JS
    # Each summary segment and legend entry carries the meaning on hover.
    assert "x[3].toLowerCase()" in JS
    assert '\'<span title="\' + esc(x[3]) + \'"><i class="\'' in JS
    assert "k[1] + (k[2] ? ' - ' + k[2] : '')" in JS
