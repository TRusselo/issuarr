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


def _lg(prop, sel='.lg'):
    body = re.search(r'(?:^|\})\s*' + re.escape(sel) + r'\s*\{([^}]*)\}', LEDGER_CSS, flags=re.M).group(1)
    m = re.search(r'(?:^|;)\s*' + re.escape(prop) + r'\s*:\s*([^;]+)', body)
    return m.group(1).strip() if m else None


@pytest.mark.unit
def test_ledger_stylesheet_never_uses_the_snatched_yellow():
    assert '--snatched' not in LEDGER_CSS
    assert '--t-snatch' not in LEDGER_CSS


@pytest.mark.unit
def test_focus_rings_on_the_ledger_are_not_yellow():
    # The global focus ring is var(--snatched); on the Ledger yellow means Snatched only.
    assert _lg('--focus', '.lg-ledger') == 'var(--text)'
    assert '<div class="lg lg-ledger">' in _read('data', 'interfaces', 'default', 'ledger.html')


@pytest.mark.unit
def test_the_ledger_focus_change_stays_off_the_webp_page():
    # WebP conversion reuses .lg and ledger.css; its focus rings are not the Ledger's to change.
    assert _lg('--focus') is None
    assert 'lg-ledger' not in _read('data', 'interfaces', 'default', 'webp.html')


@pytest.mark.unit
def test_trade_chips_use_the_collection_colour_not_a_status_colour():
    status = ('--wanted', '--snatched', '--have', '--failed', '--ignored', '--lg-done')
    fills, dupe = _lg('--lg-c-fills'), _lg('--lg-c-dupe')
    assert fills == 'var(--collection)'
    assert '--collection' in dupe and dupe != fills
    # Fills gaps, Duplicates singles and Not in library are three different colours, and Duplicates singles
    # isn't toned toward the grey of Not in library.
    out = _lg('--lg-c-out')
    assert len({fills, dupe, out}) == 3
    assert '--muted' not in dupe
    for v in (fills, dupe):
        assert not any(s + ')' in v or s + ',' in v for s in status), v
    # A trade you own that collects a missing issue is the same colour as Fills gaps, not On disk.
    assert "style=\"--c:var(--lg-done)\" href=\"comicDetails" not in JS
    assert "'<a class=\"lg-trade\" style=\"--c:var(--lg-c-fills)\"" in JS


@pytest.mark.unit
def test_duplicates_singles_chip_is_outlined_not_filled():
    rule = re.search(r'\.lg \.lg-trade-dupe\s*\{([^}]*)\}', LEDGER_CSS)
    assert rule and 'background: none' in rule.group(1) and 'box-shadow' in rule.group(1)
    assert re.search(r"CC\[k\] === '--lg-c-dupe' \? ' lg-trade-dupe'", JS)


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
    assert re.search(r"\['s',\s*'seg-snatched',\s*'Snatched',\s*'Grabbed, not filed yet'\]", JS)
    assert re.search(r"s:\s*\['seg-snatched',\s*'snatched',\s*'grabbed, not filed yet'\]", JS)
    # Each summary segment, legend entry and runs segment carries the meaning on hover.
    for fn in ('bar', 'runsBar'):
        body = re.search(r'function ' + fn + r'\(.*?\n  \}', JS, flags=re.S).group(0)
        assert re.search(r"class=\"' \+ \w+\[\d\][^;]*title=", body), fn
    assert re.search(r"'<div class=\"legend\">'[^;]*<span title=", JS)
