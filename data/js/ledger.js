(function () {
  var MK = ['--lg-gap', '--lg-unrec', '--lg-after', '--lg-before', '--lg-cut', '--lg-done'];
  var ML = ['Gap', 'Files not recognised', 'After last owned', 'Before first owned', 'After collection ended', 'Complete'];
  var MH = ['Owned issues on both sides', 'Series has files Mylar can\'t match', 'Past your last owned issue', 'Before your first owned issue', 'Released after your cutoff date', 'Series where you have every issue'];
  var COMPLETE = 5;
  var CK = ['fills_gaps', 'covered', 'partly', 'not_in_library', 'unknown'];
  var CC = ['--lg-c-fills', '--lg-c-dupe', '--lg-c-part', '--lg-c-out', '--lg-c-unknown'];
  var CL = ['Fills gaps', 'Duplicates singles', 'Partly covered', 'Not in library', 'No contents info'];
  var CH = ['Collects issues you don\'t have as singles', 'You own every tracked issue it collects', 'Its own series has issues Mylar doesn\'t track', 'Collects series you don\'t track', 'No source lists what it collects'];
  var BOOK = '<svg class="lg-ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 4.2C6.6 3 4.4 2.6 1.5 2.8v9.6c2.9-.2 5.1.2 6.5 1.4 1.4-1.2 3.6-1.6 6.5-1.4V2.8c-2.9-.2-5.1.2-6.5 1.4zM8 4.2v9.6"/></svg>';

  var st = {
    tab: 'missing', by: 'issue', kinds: { missing: [0], collected: [0, 1] }, q: '', pub: '', dec: '',
    sort: null, limit: 300, sel: {}, open: {}, status: ''
  };
  try { var saved = JSON.parse(localStorage.getItem('mylar-ledger') || 'null'); if (saved) { st.tab = saved.tab || st.tab; st.kinds = saved.kinds || st.kinds; st.by = saved.by || st.by; } } catch (e) {}
  function save() { try { localStorage.setItem('mylar-ledger', JSON.stringify({ tab: st.tab, kinds: st.kinds, by: st.by })); } catch (e) {} }

  var M = null, C = null, $id = function (i) { return document.getElementById(i); };
  var fmt = function (n) { return Number(n).toLocaleString(); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  var isOwned = function (t) { return t.tstatus === 'Downloaded' || t.tstatus === 'Archived'; };
  var cmp = function (a, b) { return a < b ? -1 : a > b ? 1 : 0; };

  function load(view, cb) {
    $id('lg-count').textContent = 'Loading…';
    $.getJSON('ledger_data', { view: view }, function (d) { if (view === 'missing') prep(d); cb(d); });
  }

  // Per series, how its missing issues split by status (all kinds, before any filter).
  function prep(d) {
    d.sc = {};
    d.rows.forEach(function (r) {
      var c = d.sc[r[1]] || (d.sc[r[1]] = { w: 0, s: 0, f: 0, m: 0 });
      if (r[7] === 'Wanted') c.w++; else if (r[7] === 'Snatched') c.s++; else if (r[7] === 'Failed') c.f++; else c.m++;
    });
    return d;
  }

  // One bar per series, by status: on disk, wanted, snatched, failed, missing and not wanted, and the rest
  // (Ignored issues aren't listed as missing, so they make up most of it). The last item is what the colour means, on hover.
  var SEGS = [['have', 'seg-have', 'On disk', 'Downloaded or archived'], ['w', 'seg-wanted', 'Wanted', 'Mylar searches for these'],
              ['s', 'seg-snatched', 'Snatched', 'Grabbed, not filed yet'], ['f', 'seg-failed', 'Failed', 'The download or filing failed'],
              ['m', 'seg-missing', 'Missing, not wanted', 'Not on disk and not searched for'], ['rest', 'seg-ignored', 'Ignored or not listed', 'Ignored, or not counted as missing']];
  function counts(si) {
    var S = M.series[si], c = M.sc[si] || { w: 0, s: 0, f: 0, m: 0 }, tot = S[3] || 0, have = tot ? Math.min(S[2], tot) : S[2];
    return { have: have, w: c.w, s: c.s, f: c.f, m: c.m, rest: Math.max(tot - have - c.w - c.s - c.f - c.m, 0) };
  }
  function bar(c) {
    var title = SEGS.filter(function (x) { return c[x[0]]; }).map(function (x) { return x[2] + ': ' + fmt(c[x[0]]); }).join(' · ');
    return '<div class="collection-bar" title="' + esc(title) + '">' + SEGS.map(function (x) {
      return c[x[0]] ? '<span class="' + x[1] + '" style="flex: ' + c[x[0]] + ' 1 0" title="' + esc(x[2] + ' - ' + x[3].toLowerCase() + ': ' + fmt(c[x[0]])) + '"></span>' : '';
    }).join('') + '</div>';
  }
  // A series' issues in number order as runs: on disk, wanted, missing and so on, so each gap shows where it is.
  var RUN = { h: ['seg-have', 'on disk'], w: ['seg-wanted', 'wanted'], s: ['seg-snatched', 'snatched', 'grabbed, not filed yet'], f: ['seg-failed', 'failed'],
              i: ['seg-ignored', 'ignored'], m: ['seg-missing', 'missing'] };
  function runsBar(runs) {
    if (!runs || !runs.length) return '<div class="collection-bar"></div>';
    var tot = {}, n = 0;
    var spans = runs.map(function (r) {
      var k = RUN[r[0]] || RUN.m;
      tot[k[1]] = (tot[k[1]] || 0) + r[1]; n += r[1];
      var which = r[1] === 1 ? '#' + r[2] : '#' + r[2] + '–#' + r[3];
      return '<span class="' + k[0] + '" style="flex: ' + r[1] + ' 1 0" title="' + esc(which + ' ' + k[1] + (k[2] ? ' - ' + k[2] : '')) + '"></span>';
    }).join('');
    var label = n + ' issues: ' + Object.keys(tot).map(function (k) { return tot[k] + ' ' + k; }).join(', ');
    return '<div class="collection-bar is-runs" role="img" aria-label="' + esc(label) + '">' + spans + '</div>';
  }

  function renderSum() {
    var box = $id('lg-sum');
    box.hidden = st.tab !== 'missing' || !M;
    if (box.hidden) return;
    var seen = {}, t = { have: 0, w: 0, s: 0, f: 0, m: 0, rest: 0 }, tracked = 0;
    M.rows.forEach(function (r) { seen[r[1]] = 1; });
    var ids = Object.keys(seen);
    ids.forEach(function (si) { var c = counts(si); Object.keys(t).forEach(function (k) { t[k] += c[k]; }); tracked += M.series[si][3] || 0; });
    var missing = t.w + t.s + t.f + t.m;
    box.innerHTML = '<div class="lg-sum-line"><span><b>' + fmt(ids.length) + '</b> series with missing issues · <b>' + fmt(missing) + '</b> missing of <b>' + fmt(tracked) + '</b> tracked</span>' +
      '<span class="is-wanted"><b>' + fmt(t.w) + '</b> wanted</span></div>' + bar(t) +
      '<div class="legend">' + SEGS.map(function (x) { return '<span title="' + esc(x[3]) + '"><i class="' + x[1].replace('seg-', 'is-') + '"></i>' + x[2] + ' <b>' + fmt(t[x[0]]) + '</b></span>'; }).join('') + '</div>';
  }

  var PILL = { Wanted: 'is-wanted', Snatched: 'is-snatched', Failed: 'is-failed', Downloaded: 'is-have', Archived: 'is-have', Ignored: 'is-ignored', Skipped: 'is-idle' };
  function statusPill(v) { return '<span class="status ' + (PILL[v] || 'is-idle') + '">' + esc(v) + '</span>'; }

  function tiles() {
    var counts, L, H, K, keys = st.kinds[st.tab];
    var wanted = [0, 0, 0, 0, 0, 0];
    if (st.tab === 'missing') {
      counts = [0, 0, 0, 0, 0, M.complete.length]; M.rows.forEach(function (r) { counts[r[0]]++; if (r[7] === 'Wanted') wanted[r[0]]++; }); L = ML; H = MH; K = MK;
    } else {
      counts = [0, 0, 0, 0, 0]; C.trades.forEach(function (t) { counts[CK.indexOf(t.coverage)]++; }); L = CL; H = CH; K = CC;
    }
    $id('lg-tiles').innerHTML = L.map(function (l, i) {
      if (st.tab === 'missing' && i === 4 && !M.cutoff) return '';
      return '<button type="button" class="lg-tile" style="--c:var(' + K[i] + ')" data-k="' + i + '" aria-pressed="' + (keys.indexOf(i) >= 0) + '" title="' + esc(H[i]) + '"><b>' + fmt(counts[i]) + '</b><span>' + l + '</span><small>' + H[i] + '</small>' + (wanted[i] ? '<em>' + fmt(wanted[i]) + ' wanted</em>' : '') + '</button>';
    }).join('');
  }

  $('#lg-tiles').on('click', '.lg-tile', function () {
    var k = +this.getAttribute('data-k'), a = st.kinds[st.tab], p = a.indexOf(k);
    if (p >= 0) a.splice(p, 1); else a.push(k);
    this.setAttribute('aria-pressed', p < 0); st.limit = 300; save();
    if (st.tab === 'missing' && k === COMPLETE && p < 0 && st.by === 'issue') { setBy('series'); return; }
    render();
  });

  function filters() {
    var pubs = {}, decs = {};
    if (st.tab === 'missing') {
      M.rows.forEach(function (r) { var p = M.pubs[M.series[r[1]][4]]; pubs[p] = (pubs[p] || 0) + 1; if (r[5]) decs[r[5].slice(0, 3) + '0'] = 1; });
    } else {
      C.trades.forEach(function (t) { pubs[t.pub || '?'] = (pubs[t.pub || '?'] || 0) + 1; });
    }
    var list = Object.keys(pubs).sort(function (a, b) { return pubs[b] - pubs[a]; });
    $id('lg-pub').innerHTML = '<option value="">All publishers</option>' + list.map(function (p) { return '<option value="' + esc(p) + '">' + esc(p) + ' (' + fmt(pubs[p]) + ')</option>'; }).join('');
    $id('lg-pub').value = st.pub;
    var dl = Object.keys(decs).sort();
    $id('lg-dec').innerHTML = '<option value="">All decades</option>' + dl.map(function (d) { return '<option value="' + d + '">' + d + 's</option>'; }).join('');
    $id('lg-dec').value = st.dec;
    $id('lg-dec').hidden = st.tab !== 'missing';
    $id('lg-stat').hidden = st.tab !== 'missing';
    $id('lg-cutoff-wrap').hidden = st.tab !== 'missing';
    $id('lg-cutoff').value = (M && M.cutoff) || '';
    $('.lg-seg').toggle(st.tab === 'missing');
  }

  $('#lg-q').on('input', function () { st.q = this.value.trim().toLowerCase(); st.limit = 300; render(); });
  $('#lg-pub').on('change', function () { st.pub = this.value; st.limit = 300; render(); });
  $('#lg-dec').on('change', function () { st.dec = this.value; st.limit = 300; render(); });
  $('#lg-stat').on('change', function () { st.status = this.value; st.limit = 300; render(); });
  $('#lg-more').on('click', function () { st.limit += 300; render(); });
  $('#lg-cutoff').on('change', function () {
    $.getJSON('ledger_cutoff', { cutoff: this.value }, function (r) {
      if (!r.ok) { alert(r.error); return; }
      load('missing', function (d) { M = d; st.sel = {}; tiles(); filters(); render(); });
    });
  });

  // The sidebar opens this page as Ledger (no hash) or Library > Trades (#trades).
  function tabFromHash() { return location.hash === '#trades' ? 'collected' : 'missing'; }
  function setTab(t) {
    st.tab = t; st.sel = {}; st.limit = 300; st.sort = null; save();
    $id('lg-tab-missing').setAttribute('aria-selected', t === 'missing');
    $id('lg-tab-collected').setAttribute('aria-selected', t === 'collected');
    if (tabFromHash() !== t) history.replaceState(null, '', t === 'collected' ? '#trades' : location.pathname + location.search);
    if (window.issuarrMarkNav) window.issuarrMarkNav();
    $('.lg-title').html(t === 'collected' ? '<span class="page-crumb">Library › </span>Trades' : 'Ledger');
    document.title = document.title.replace(/ - [^-]*$/, ' - ' + (t === 'collected' ? 'Trades' : 'Ledger'));
    $id('lg-sub').textContent = t === 'collected'
      ? 'Trade paperbacks in your library, and how they overlap the single issues you own.'
      : 'Issues missing from the series you follow, where they sit in each run, and which ones you\'ve asked for.';
    $id('lg-tiles-label').textContent = t === 'collected' ? 'What each trade covers' : 'Where the missing issues sit';
    var go = function () { tiles(); filters(); render(); buildBar(); };
    if (t === 'missing') { if (M) go(); else load('missing', function (d) { M = d; go(); }); }
    else { if (C) go(); else load('collected', function (d) { C = d; go(); }); }
  }
  $('#lg-tab-missing').on('click', function () { setTab('missing'); });
  $('#lg-tab-collected').on('click', function () { setTab('collected'); });
  function setBy(b) { st.by = b; st.sort = null; st.limit = 300; save(); $id('lg-by-issue').setAttribute('aria-pressed', b === 'issue'); $id('lg-by-series').setAttribute('aria-pressed', b === 'series'); render(); }
  $('#lg-by-issue').on('click', function () { setBy('issue'); });
  $('#lg-by-series').on('click', function () { setBy('series'); });

  function head(cols, check) {
    var s = st.sort || {};
    $('#lg-table thead').html('<tr>' + (check ? '<th class="lg-chk"><input type="checkbox" id="lg-all" aria-label="Select all shown"></th>' : '') + cols.map(function (c) {
      return '<th data-key="' + c[0] + '" class="' + (c[2] || '') + '" aria-sort="' + (s.key === c[0] ? (s.dir > 0 ? 'ascending' : 'descending') : 'none') + '" tabindex="0">' + c[1] + '</th>';
    }).join('') + '</tr>');
  }
  $('#lg-table').on('click', 'th[data-key]', function () {
    var k = this.getAttribute('data-key'); if (k === 'mix' || k === 'lack') return;
    st.sort = st.sort && st.sort.key === k ? { key: k, dir: -st.sort.dir } : { key: k, dir: ['miss', 'own', 'w', 'found', 'lacking'].indexOf(k) >= 0 ? -1 : 1 };
    render();
  });
  $('#lg-table').on('keydown', 'th[data-key]', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $(this).click(); } });

  function tradeName(T) { return T[0] + ' (' + T[1] + ') #' + T[2]; }
  function tradeCell(list) {
    if (!list || !list.length) return '<span class="lg-dim">—</span>';
    var mine = list.filter(function (i) { return M.trades[i][4]; }), other = list.filter(function (i) { return !M.trades[i][4]; });
    var html = mine.map(function (i) {
      var T = M.trades[i];
      return '<a class="lg-trade" style="--c:var(--lg-c-fills)" href="comicDetails?ComicID=' + T[3] + '" title="You own this in ' + esc(tradeName(T)) + '">' + BOOK + '<span>' + esc(tradeName(T)) + '</span></a>';
    }).join('');
    if (other.length) html += '<span class="lg-trade lg-trade-out" title="Collected in ' + esc(other.map(function (i) { return tradeName(M.trades[i]); }).join(', ')) + ' (not owned)">' + BOOK + '<span>' + (other.length === 1 ? esc(tradeName(M.trades[other[0]])) : other.length + ' trades') + '</span></span>';
    return html;
  }
  function seriesTrades(list) {
    if (!list || !list.length) return '<span class="lg-dim">—</span>';
    var g = {};
    list.forEach(function (i) { var T = M.trades[i]; if (!T[4]) return; (g[T[5]] = g[T[5]] || []).push(tradeName(T)); });
    var keys = Object.keys(g).map(Number).sort();
    if (!keys.length) return '<span class="lg-trade lg-trade-out" title="Collected in trades you don\'t own">' + BOOK + '<span>' + list.length + ' not owned</span></span>';
    return keys.map(function (k) {
      return '<span class="lg-trade" style="--c:var(' + CC[k] + ')" title="' + esc(CL[k] + ': ' + g[k].join(', ')) + '">' + BOOK + '<span>' + CL[k] + (g[k].length > 1 ? ' ×' + g[k].length : '') + '</span></span>';
    }).join('');
  }

  var STATS = ['Wanted', 'Skipped', 'Ignored', 'Snatched', 'Failed'];
  function statusFilter(base) {
    var c = {};
    base.forEach(function (r) { c[r[7]] = (c[r[7]] || 0) + 1; });
    var list = STATS.filter(function (k) { return c[k]; }).concat(Object.keys(c).filter(function (k) { return STATS.indexOf(k) < 0; }).sort());
    if (st.status && !c[st.status]) list.push(st.status);
    $id('lg-stat').innerHTML = '<option value="">Any status</option>' + list.map(function (k) { return '<option value="' + esc(k) + '">' + esc(k) + ' (' + fmt(c[k] || 0) + ')</option>'; }).join('');
    $id('lg-stat').value = st.status;
    return { rows: st.status ? base.filter(function (r) { return r[7] === st.status; }) : base, wanted: c.Wanted || 0 };
  }
  function countLine(shown, total, noun, wanted) {
    $id('lg-count').textContent = fmt(shown) + ' of ' + fmt(total) + ' ' + noun + (wanted && st.status !== 'Wanted' ? ' · ' + fmt(wanted) + ' already Wanted' : '');
  }

  function missingRows() {
    var keys = st.kinds.missing;
    return M.rows.filter(function (r) {
      if (keys.indexOf(r[0]) < 0) return false;
      var S = M.series[r[1]];
      if (st.pub && M.pubs[S[4]] !== st.pub) return false;
      if (st.dec && (!r[5] || r[5].slice(0, 3) + '0' !== st.dec)) return false;
      if (st.q && S[0].toLowerCase().indexOf(st.q) < 0 && r[4].toLowerCase().indexOf(st.q) < 0) return false;
      return true;
    });
  }

  function render() {
    if (st.tab === 'missing') { if (st.by === 'issue') renderIssues(); else renderSeries(); }
    else renderTrades();
    renderSum();
    selBar();
    syncAll();
  }

  function syncAll() {
    var all = $id('lg-all');
    if (!all) return;
    var boxes = $('#lg-table tbody td.lg-chk input'), on = boxes.filter(':checked').length;
    all.checked = boxes.length > 0 && on === boxes.length;
    all.indeterminate = on > 0 && on < boxes.length;
  }

  function renderIssues() {
    var sf = statusFilter(missingRows()), f = sf.rows, s = st.sort || { key: 'k', dir: 1 };
    head([['k', 'Kind'], ['series', 'Series'], ['n', '#', 'num'], ['t', 'Title'], ['d', 'Released'], ['st', 'Status'], ['tr', 'Trades'], ['own', 'Series owned', 'num']], true);
    var tv = function (r) { var l = r[8] || []; return l.some(function (i) { return M.trades[i][4]; }) ? 2 : l.length ? 1 : 0; };
    var v = function (r) { var S = M.series[r[1]]; return s.key === 'series' ? S[0].toLowerCase() : s.key === 'own' ? S[2] / (S[3] || 1) : s.key === 'k' ? r[0] : s.key === 'n' ? r[3] : s.key === 't' ? r[4] : s.key === 'd' ? r[5] : s.key === 'tr' ? -tv(r) : r[7]; };
    f.sort(function (a, b) { return s.dir * cmp(v(a), v(b)) || cmp(M.series[a[1]][0], M.series[b[1]][0]) || cmp(a[3], b[3]); });
    var page = f.slice(0, st.limit);
    $('#lg-table tbody').html(page.length ? page.map(function (r) {
      var S = M.series[r[1]];
      return '<tr class="' + (st.sel[r[6]] ? 'lg-on' : '') + '"><td class="lg-chk"><input type="checkbox" data-id="' + r[6] + '"' + (st.sel[r[6]] ? ' checked' : '') + ' aria-label="Select issue"></td>' +
        '<td><span class="lg-pill" style="--c:var(' + MK[r[0]] + ')">' + ML[r[0]] + '</span></td>' +
        '<td><a href="comicDetails?ComicID=' + S[5] + '">' + esc(S[0]) + '</a> <span class="lg-dim">(' + esc(S[1]) + ')</span><br><small class="lg-dim">' + esc(M.pubs[S[4]]) + '</small></td>' +
        '<td class="num lg-mono"><a href="https://comicvine.gamespot.com/issue/4000-' + r[6] + '/" target="_blank" rel="noopener">' + esc(r[2]) + '</a></td>' +
        '<td class="lg-dim lg-title-cell">' + (esc(r[4]) || '—') + '</td><td class="lg-mono">' + (r[5] || '—') + '</td>' +
        '<td>' + statusPill(r[7]) + '</td><td class="lg-trades">' + tradeCell(r[8]) + '</td><td class="num lg-mono">' + S[2] + ' / ' + S[3] + '</td></tr>';
    }).join('') : '<tr><td class="lg-empty" colspan="9">' + (st.kinds.missing.length === 1 && st.kinds.missing[0] === COMPLETE ? 'Complete series are listed in the By series view.' : 'No issues match. Turn on more kinds above or clear the search.') + '</td></tr>');
    countLine(Math.min(st.limit, f.length), f.length, 'issues', sf.wanted);
    $id('lg-more').hidden = f.length <= st.limit;
    $id('lg-note').textContent = KEYS + ' Trades: a filled book means a trade you own collects the issue; an outlined one means a trade you don\'t own collects it. Wanted starts a search for those issues. Ignored stops Mylar from ever searching for them. Series lost completely aren\'t in Mylar, so they can\'t show here.';
  }

  function renderSeries() {
    var sf = statusFilter(missingRows()), f = sf.rows, g = {};
    f.forEach(function (r) {
      var x = g[r[1]] || (g[r[1]] = { s: r[1], p: [0, 0, 0], none: 0, ids: [], w: 0 });
      if (r[9] < 0) x.none++; else x.p[r[9]]++;
      x.ids.push(r[6]); if (r[7] === 'Wanted') x.w++;
    });
    var s = st.sort || { key: 'miss', dir: -1 };
    if (st.kinds.missing.indexOf(COMPLETE) >= 0) M.complete.forEach(function (si) {
      var S = M.series[si];
      if (g[si] || (st.pub && M.pubs[S[4]] !== st.pub) || (st.q && S[0].toLowerCase().indexOf(st.q) < 0)) return;
      g[si] = { s: si, p: [0, 0, 0], none: 0, ids: [], w: 0, done: true };
    });
    var list = Object.keys(g).map(function (k) { var x = g[k], S = M.series[x.s]; x.series = S[0].toLowerCase(); x.pub = M.pubs[S[4]]; x.own = S[2] / (S[3] || 1); x.total = x.p[0] + x.p[1] + x.p[2] + x.none; x.miss = x.p[1] * 1e6 + x.total; x.tr = -(S[6] || []).length; return x; });
    list.sort(function (a, b) { return s.dir * cmp(a[s.key], b[s.key]) || cmp(a.series, b.series); });
    head([['series', 'Series'], ['mix', 'Collection'], ['own', 'Owned', 'num'], ['miss', 'Missing <small class="lg-dim">before / gap / after</small>', 'num'], ['w', 'Wanted', 'num'], ['tr', 'Trades']], true);
    var page = list.slice(0, st.limit);
    $('#lg-table tbody').html(page.length ? page.map(function (x) {
      var S = M.series[x.s], all = x.ids.every(function (i) { return st.sel[i]; });
      if (x.done) all = false;
      return '<tr class="' + (all ? 'lg-on' : '') + (x.done ? ' lg-complete' : '') + '"><td class="lg-chk">' + (x.done ? '' : '<input type="checkbox" data-ids="' + x.ids.join(',') + '"' + (all ? ' checked' : '') + ' aria-label="Select all missing issues in this series">') + '</td>' +
        '<td><a href="comicDetails?ComicID=' + S[5] + '">' + esc(S[0]) + '</a> <span class="lg-dim">(' + esc(S[1]) + ')</span><br><small class="lg-dim">' + esc(M.pubs[S[4]]) + '</small></td>' +
        '<td class="lg-cbar-cell">' + runsBar(S[7]) + '</td>' +
        '<td class="num lg-mono">' + S[2] + ' / ' + S[3] + '</td><td class="num lg-mono">' + missCell(x) + '</td>' +
        '<td class="num lg-mono is-wanted">' + (x.w || '') + '</td>' +
        '<td class="lg-trades">' + seriesTrades(S[6]) + '</td></tr>';
    }).join('') : '<tr><td class="lg-empty" colspan="9">No series match these filters.</td></tr>');
    countLine(Math.min(st.limit, list.length), list.length, 'series', sf.wanted);
    $id('lg-more').hidden = list.length <= st.limit;
    $id('lg-note').textContent = KEYS + ' Selecting a series selects all of its missing issues that match the filters.';
  }

  function missCell(x) {
    if (x.done) return '<span class="lg-pill" style="--c:var(--lg-done)">Complete</span>';
    if (x.none && !x.total) return '';
    if (x.none === x.total) return M.series[x.s][2] > 0
      ? '<span class="lg-dim" title="This series has files, but none are matched to an issue, so gaps can\'t be placed">files not matched</span> ' + x.none
      : '<span class="lg-dim" title="No issues of this series are on disk">none on disk</span> ' + x.none;
    var v = function (n, cls, t) { return '<span class="' + cls + '" title="' + t + '">' + (n || '—') + '</span>'; };
    return '<span class="lg-miss">' + v(x.p[0], '', 'Before your first owned issue') + '<i>/</i>' + v(x.p[1], 'lg-strong', 'In gaps between issues you own') +
      '<i>/</i>' + v(x.p[2], '', 'After your last owned issue') + '</span>';
  }

  function renderTrades() {
    var keys = st.kinds.collected, s = st.sort || { key: 'cov', dir: 1 };
    var f = C.trades.filter(function (t) {
      if (keys.indexOf(CK.indexOf(t.coverage)) < 0) return false;
      if (st.pub && (t.pub || '?') !== st.pub) return false;
      if (st.q && (t.name + ' ' + t.collects).toLowerCase().indexOf(st.q) < 0) return false;
      return true;
    });
    var v = function (t) { return s.key === 'cov' ? CK.indexOf(t.coverage) : s.key === 'name' ? t.name.toLowerCase() : s.key === 'lacking' ? t.lacking.length : s.key === 'found' ? t.own / (t.found || 1) : s.key === 'tstatus' ? t.tstatus : t.collects; };
    f.sort(function (a, b) { return s.dir * cmp(v(a), v(b)) || cmp(a.name, b.name); });
    head([['cov', 'Coverage'], ['name', 'Trade'], ['collects', 'Collects'], ['found', 'Singles owned', 'num'], ['lacking', 'Covers missing', 'num'], ['tstatus', 'Trade status']], true);
    var page = f.slice(0, st.limit);
    $('#lg-table tbody').html(page.length ? page.map(function (t) {
      var i = CK.indexOf(t.coverage), open = st.open[t.iid];
      var row = '<tr class="' + (st.sel[t.iid] ? 'lg-on' : '') + '"><td class="lg-chk"><input type="checkbox" data-id="' + t.iid + '"' + (st.sel[t.iid] ? ' checked' : '') + ' aria-label="Select trade"></td>' +
        '<td><span class="lg-pill" style="--c:var(' + CC[i] + ')">' + CL[i] + '</span></td>' +
        '<td><a href="comicDetails?ComicID=' + t.cid + '">' + esc(t.name) + '</a> <span class="lg-dim">(' + esc(t.year) + ') #' + esc(t.num) + '</span><br><small class="lg-dim">' + esc(t.type) + ' · ' + esc(t.pub) + '</small></td>' +
        '<td class="lg-dim lg-title-cell">' + (esc(t.collects) || '—') + (t.extras && t.extras.length ? '<br><small>Tie-ins not tracked: ' + esc(t.extras.join(', ')) + '</small>' : '') + '</td>' +
        '<td class="num lg-mono">' + (t.found ? t.own + ' / ' + t.found : '—') + (t.unresolved ? '<br><small class="lg-dim">+' + t.unresolved + ' not tracked</small>' : '') + '</td>' +
        '<td class="num lg-mono">' + (t.lacking.length ? '<button class="lg-link" data-open="' + t.iid + '" aria-expanded="' + !!open + '">' + t.lacking.length + '</button>' : '') + '</td>' +
        '<td>' + statusPill(t.tstatus) + '</td></tr>';
      if (open) row += '<tr class="lg-sub-row"><td></td><td colspan="6">' + t.lacking.map(function (l) { return '<span class="lg-chip">' + esc(l[1]) + ' (' + esc(l[2]) + ') #' + esc(l[3]) + ' <em>' + esc(l[4]) + '</em></span>'; }).join('') + '</td></tr>';
      return row;
    }).join('') : '<tr><td class="lg-empty" colspan="7">' + (C.trades.length ? 'No trades match these filters.' : 'Trade contents haven\'t been read yet. Use the button above.') + '</td></tr>');
    $id('lg-count').textContent = fmt(Math.min(st.limit, f.length)) + ' of ' + fmt(f.length) + ' trades';
    $id('lg-more').hidden = f.length <= st.limit;
    $id('lg-note').textContent = KEYS + ' Contents come from each trade\'s ComicVine description and the summary saved in the trade file. Trades neither describes can\'t be checked. Select trades to want or skip the trade itself, want or ignore the singles it collects that you\'re missing, or move the singles it duplicates out of your library.';
  }

  $('#lg-table').on('click', '[data-open]', function () { var k = this.getAttribute('data-open'); st.open[k] = !st.open[k]; render(); });
  $('#lg-table').on('change', 'input[type=checkbox]', function () {
    if (this.id === 'lg-all') {
      var on = this.checked;
      $('#lg-table tbody input[type=checkbox]').each(function () { ids(this).forEach(function (i) { if (on) st.sel[i] = 1; else delete st.sel[i]; }); });
      render(); return;
    }
    st.confirm = null;
    var on2 = this.checked; ids(this).forEach(function (i) { if (on2) st.sel[i] = 1; else delete st.sel[i]; });
    $(this).closest('tr').toggleClass('lg-on', on2); selBar(); syncAll();
  });
  var KEYS = 'Keys: ↑/↓ move through the list, Space ticks a row, Shift+↑/↓ ticks as you go.';
  function boxRows() { return $('#lg-table tbody tr').filter(function () { return $(this).find('td.lg-chk input').length > 0; }); }
  function tick(box) { if (box && !box.checked) { box.checked = true; $(box).trigger('change'); } }
  $(document).on('keydown', function (e) {
    if ((e.key !== 'ArrowDown' && e.key !== 'ArrowUp') || e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target, tag = t.tagName, inTable = $(t).closest('#lg-table tbody').length > 0;
    if (tag === 'SELECT' || tag === 'TEXTAREA' || t.isContentEditable || (tag === 'INPUT' && t.type !== 'checkbox')) return;
    var rows = boxRows(); if (!rows.length) return;
    var cur = inTable ? $(t).closest('tr') : $(), i = cur.length ? rows.index(cur) : -1;
    var j = i < 0 ? 0 : Math.max(0, Math.min(rows.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)));
    e.preventDefault();
    var box = rows.eq(j).find('td.lg-chk input')[0];
    if (e.shiftKey) { if (i >= 0) tick(rows.eq(i).find('td.lg-chk input')[0]); tick(box); }
    box.focus({ preventScroll: true });
    rows[j].scrollIntoView({ block: 'nearest' });
  });
  function ids(el) { var a = el.getAttribute('data-ids'); return a ? a.split(',') : [el.getAttribute('data-id')]; }

  function btn(id, label, n, why) {
    return '<button type="button" class="btn btn-sm" data-do="' + id + '"' + (n ? '' : ' disabled title="' + esc(why) + '"') + '>' + label + (n ? ' <span class="lg-n">' + fmt(n) + '</span>' : '') + '</button>';
  }
  function selTrades() { return C ? C.trades.filter(function (t) { return st.sel[t.iid]; }) : []; }
  function lackingIds(list) { var o = {}; list.forEach(function (t) { t.lacking.forEach(function (l) { o[l[0]] = 1; }); }); return Object.keys(o); }

  function selBar() {
    var n = Object.keys(st.sel).length, bar = $id('lg-actions');
    bar.hidden = n === 0;
    if (!n) { st.confirm = null; return; }
    var html;
    if (st.tab === 'missing') {
      var already = M.rows.reduce(function (a, r) { return a + (st.sel[r[6]] && r[7] === 'Wanted' ? 1 : 0); }, 0);
      html = '<span id="lg-selcount">' + fmt(n) + ' missing issues selected' + (already ? ' <small class="lg-dim">(' + fmt(already) + ' already Wanted)</small>' : '') + '</span>' +
        btn('issues:Wanted', 'Mark Wanted', n) + btn('issues:Skipped', 'Mark Skipped', n) + btn('issues:Ignored', 'Mark Ignored', n);
    } else {
      var sel = selTrades(), notOwned = sel.filter(function (t) { return !isOwned(t); }), owned = sel.filter(isOwned);
      var lack = lackingIds(sel), dupes = owned.reduce(function (a, t) { return a + (t.ondisk || 0); }, 0);
      html = '<span id="lg-selcount">' + fmt(n) + ' trades selected</span>' +
        '<span class="lg-grp"><small>The trade</small>' +
        btn('trade:Wanted', 'Want it', notOwned.length, 'You already have every selected trade') +
        btn('trade:Skipped', 'Skip it', notOwned.length, 'You already have every selected trade') + '</span>' +
        '<span class="lg-grp"><small>Singles it collects that you\'re missing</small>' +
        btn('lack:Wanted', 'Want them', lack.length, 'You have every single these trades collect') +
        btn('lack:Ignored', 'Ignore them', lack.length, 'You have every single these trades collect') + '</span>' +
        '<span class="lg-grp"><small>Singles it duplicates</small>' +
        btn('remove', 'Remove them…', dupes, owned.length ? 'No single issue files of these trades are left in your library' : 'Only trades you have can replace singles') + '</span>';
    }
    html += '<button type="button" class="btn btn-sm btn-ghost" data-do="clear">Clear selection</button>';
    if (st.confirm) html += '<div class="lg-confirm">' + st.confirm + '</div>';
    bar.innerHTML = html;
    try { document.documentElement.style.setProperty('--lg-bar-h', bar.offsetHeight + 'px'); } catch (e) {}
  }

  function mark(action, list, done) {
    if (!list.length) return;
    $('.lg-actions button').prop('disabled', true);
    $.ajax({ url: 'markissues', type: 'POST', traditional: true, data: { action: action, 'issueids[]': list } })
      .done(function () { done(); })
      .fail(function () { $('.lg-actions button').prop('disabled', false); $id('lg-selcount').textContent = 'Mylar didn\'t accept the change. Check the log.'; });
  }
  function reload() {
    st.sel = {}; st.confirm = null;
    if (st.tab === 'missing') load('missing', function (d) { M = d; tiles(); render(); });
    else load('collected', function (d) { C = d; M = null; tiles(); render(); });
  }
  function size(b) { return b > 1e9 ? (b / 1e9).toFixed(1) + ' GB' : Math.round(b / 1e6) + ' MB'; }
  $('#lg-actions').on('click', '[data-do]', function () {
    var d = this.getAttribute('data-do'), p = d.split(':');
    if (d === 'clear') { st.sel = {}; st.confirm = null; render(); return; }
    if (p[0] === 'issues') return mark(p[1], Object.keys(st.sel), reload);
    if (p[0] === 'trade') return mark(p[1], selTrades().filter(function (t) { return !isOwned(t); }).map(function (t) { return t.iid; }), reload);
    if (p[0] === 'lack') return mark(p[1], lackingIds(selTrades()), reload);
    if (d === 'cancel') { st.confirm = null; selBar(); return; }
    var ids = selTrades().filter(isOwned).map(function (t) { return t.iid; }).join(',');
    if (d === 'remove') {
      $('.lg-actions button').prop('disabled', true);
      $.post('ledger_remove', { ids: ids, confirm: 0 }, function (r) {
        st.confirm = r.count
          ? 'Move <b>' + fmt(r.count) + ' single issue files</b> (' + size(r.bytes) + ') to <code>' + esc(r.dest) + '</code>? They stay counted as owned (Archived), and an undo list is saved in that folder. ' +
            (r.skipped.length ? '<br><small>Skipped: ' + esc(r.skipped.join('; ')) + '</small> ' : '') +
            '<button type="button" class="btn btn-sm btn-danger" data-do="move">Move ' + fmt(r.count) + ' files</button><button type="button" class="btn btn-sm btn-ghost" data-do="cancel">Cancel</button>'
          : 'No single issue files to move.' + (r.skipped.length ? ' <small>' + esc(r.skipped.join('; ')) + '</small>' : '') + ' <button type="button" class="btn btn-sm btn-ghost" data-do="cancel">OK</button>';
        selBar();
      }, 'json');
      return;
    }
    if (d === 'move') {
      $('.lg-actions button').prop('disabled', true);
      $.post('ledger_remove', { ids: ids, confirm: 1 }, function (r) {
        reload();
        var msg = 'Moved ' + fmt(r.moved) + ' files to ' + r.dest + '. Undo list: ' + r.undo + (r.failed && r.failed.length ? '. Failed: ' + r.failed.join('; ') : '');
        $id('lg-note').textContent = r.moved ? msg : 'Nothing was moved.';
      }, 'json');
    }
  });

  var poll = null;
  function buildBar(s) {
    if (st.tab !== 'collected') { $id('lg-build').hidden = true; return; }
    s = s || (C && C.build) || {};
    $id('lg-build').hidden = false;
    var t;
    if (s.running) t = (s.phase || 'Working') + ': ' + fmt(s.done) + ' of ' + fmt(s.total) + ' trades';
    else if (s.error) t = 'Last read failed: ' + s.error;
    else if (s.stored) t = fmt(s.stored) + ' trades read, last on ' + s.updated + '. Sources: ComicVine and the summaries in your trade files (' + fmt(s.comicinfo_found || 0) + ').';
    else t = 'Trade contents haven\'t been read yet.';
    if (!s.running && s.note) t += ' ' + s.note;
    $id('lg-build-text').textContent = t;
    $('#lg-build-btn, #lg-rebuild-btn').prop('disabled', !!s.running);
    $id('lg-build-btn').textContent = s.stored ? 'Read new trades' : 'Read trade contents';
    if (s.running && !poll) poll = setInterval(function () {
      $.getJSON('ledger_status', function (x) {
        buildBar(x);
        if (!x.running) { clearInterval(poll); poll = null; load('collected', function (d) { C = d; tiles(); filters(); render(); buildBar(); }); }
      });
    }, 4000);
  }
  $('#lg-build-btn').on('click', function () { $.getJSON('ledger_build', { force: 0 }, function (r) { buildBar(r.status); }); });
  $('#lg-rebuild-btn').on('click', function () { $.getJSON('ledger_build', { force: 1 }, function (r) { buildBar(r.status); }); });

  $id('lg-by-issue').setAttribute('aria-pressed', st.by === 'issue');
  $id('lg-by-series').setAttribute('aria-pressed', st.by === 'series');
  setTab(tabFromHash());
  window.addEventListener('hashchange', function () { if (tabFromHash() !== st.tab) setTab(tabFromHash()); });
})();
