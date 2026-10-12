/* Downloads > Queue: one list of everything on its way, from every source.
   Direct downloads (GetComics, JDownloader 2) and grabs at SABnzbd, NZBGet or a torrent client
   all come from downloadQueue, with live progress where the client can be reached. */
(function () {
  'use strict';

  // Tab order. "Active" is everything not finished; Completed only applies to direct downloads.
  var TABS = [['active', 'Active'], ['Downloading', 'Downloading'], ['Queued', 'Queued'], ['Processing', 'Processing'],
              ['Sent', 'Sent'], ['Paused', 'Paused'], ['Incomplete', 'Incomplete'], ['Failed', 'Failed'], ['Completed', 'Finished'], ['', 'All']];
  var CLASS = { Completed: 'is-have', Downloading: 'is-snatched is-running', Processing: 'is-snatched is-running',
                Checking: 'is-snatched', Queued: 'is-idle', Sent: 'is-idle', Paused: 'is-idle',
                Incomplete: 'is-snatched', Failed: 'is-failed' };
  var LABEL = { Completed: 'Finished', Sent: 'Waiting on client', Processing: 'Processing' };
  var HELP = { Sent: 'Sent to the download client. Its progress shows here when the client can be reached.',
               Processing: 'Downloaded. Waiting for the client to unpack it or for Issuarr to file it.' };
  var st = { tab: 'active', q: '', start: 0, len: 50, items: [], stalled: 0, loaded: false };

  function $id(id) { return document.getElementById(id); }
  function I() { return window.Issuarr; }
  function esc(t) { return I().esc(t); }

  function call(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }).then(function (t) { try { return JSON.parse(t); } catch (e) { return {}; } });
  }

  function post(url, data) {
    return fetch(url, { method: 'POST', body: new URLSearchParams(data || {}), credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  }

  // Clears finished or failed direct downloads from the list (ddl_clear), not from the library.
  function clearStatus(status, confirmText) {
    if (!window.confirm(confirmText)) return;
    post('ddl_clear', { status: status })
      .then(function (r) { I().toast(r.message || 'Done', r.status !== false); document.dispatchEvent(new CustomEvent('issuarr:flow-poke')); })
      .catch(function () { I().toast('That didn\'t work. Check the log.', false); })
      .then(function () { load(true); });
  }

  function requeue(mode, id, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    call('ddl_requeue?mode=' + encodeURIComponent(mode) + (id != null ? '&id=' + encodeURIComponent(id) : ''))
      .then(function (r) { I().toast(r.message || 'Done'); document.dispatchEvent(new CustomEvent('issuarr:flow-poke')); })
      .catch(function () { I().toast('That didn\'t work. Check the log.', false); })
      .then(function () { load(true); });
  }

  function inTab(it, tab) {
    if (tab === '') return true;
    if (tab === 'active') return it.status !== 'Completed';
    if (tab === 'Downloading') return it.status === 'Downloading' || it.status === 'Checking';
    return it.status === tab;
  }

  /* ---- filter tabs ---- */
  function renderTabs() {
    var tabs = TABS.filter(function (t) {
      return t[0] === 'active' || t[0] === '' || t[0] === st.tab || st.items.some(function (it) { return inTab(it, t[0]); });
    });
    $id('q-tabs').innerHTML = tabs.map(function (t) {
      var n = st.items.filter(function (it) { return inTab(it, t[0]); }).length;
      return '<button type="button" data-ui data-tab="' + esc(t[0]) + '" aria-pressed="' + (st.tab === t[0]) + '">' +
        esc(t[1]) + '<span class="count">' + n + '</span></button>';
    }).join('');
  }

  /* ---- rows ---- */
  function actionsFor(it) {
    if (it.kind !== 'ddl') return '';
    var id = it.queueid, out = [];
    var label = { Queued: 'Start', Downloading: 'Restart', Incomplete: 'Restart', Failed: 'Retry', Completed: 'Download again' }[it.status];
    if (it.status === 'Incomplete' || it.status === 'Downloading') out.push('<button type="button" class="btn btn-sm" data-act="resume" data-id="' + esc(id) + '">Resume</button>');
    if (label) out.push('<button type="button" class="btn btn-sm" data-act="restart" data-id="' + esc(id) + '">' + label + '</button>');
    if (it.status === 'Downloading') {
      out.push('<button type="button" class="btn btn-sm btn-danger" data-act="abort" data-id="' + esc(id) + '" data-name="' + esc(it.title) + '" title="Stop the download and mark it Failed">Stop</button>');
    } else {
      out.push('<button type="button" class="btn btn-sm btn-ghost" data-act="remove" data-id="' + esc(id) + '" data-name="' + esc(it.title) + '">Remove</button>');
    }
    return out.join('');
  }

  function progressCell(it) {
    if (it.percent == null) {
      return it.size ? '<span class="muted">' + esc(it.size) + '</span>' : '<span class="muted">-</span>';
    }
    var left = it.progress || (it.size ? it.size : '');
    var right = [it.speed, it.eta].filter(Boolean).join(' · ');
    return '<div class="progress' + (it.percent >= 100 ? ' is-done' : '') + '" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + esc(it.percent) + '">' +
      '<span style="width: ' + esc(it.percent) + '%"></span></div>' +
      '<div class="q-meta"><span>' + esc(it.percent) + '%' + (left ? ' · ' + esc(left) : '') + '</span><span>' + esc(right) + '</span></div>';
  }

  function sourceCell(it) {
    return '<span class="q-src"><b>' + esc(it.source || '-') + '</b>' + (it.via && it.via !== it.source ? esc(it.via) : '') + '</span>';
  }

  function renderRows() {
    var tb = $id('q-table').tBodies[0];
    var q = st.q.toLowerCase();
    var rows = st.items.filter(function (it) { return inTab(it, st.tab) && (!q || String(it.title || '').toLowerCase().indexOf(q) > -1); });
    st.total = rows.length;
    if (st.start >= rows.length) st.start = Math.max(0, Math.floor((rows.length - 1) / st.len) * st.len);
    renderRange();
    if (!rows.length) {
      var msg = q ? 'Nothing matches.' : st.tab === 'active' ? idleMessage() : 'Nothing here.';
      tb.innerHTML = '<tr><td colspan="6" class="empty-state">' + msg + '</td></tr>';
      return;
    }
    tb.innerHTML = rows.slice(st.start, st.start + st.len).map(function (it) {
      var title = it.comicid ? '<a href="comicDetails?ComicID=' + encodeURIComponent(it.comicid) + '">' + esc(it.title) + '</a>' : esc(it.title);
      var detail = it.message || (it.detail && it.detail !== it.title ? it.detail : '');
      var status = it.status || 'Unknown';
      return '<tr data-row="' + esc(it.key) + '"><td class="q-title"><b>' + title + '</b>' + (detail ? '<p>' + esc(detail) + '</p>' : '') + '</td>' +
        '<td class="q-prog">' + progressCell(it) + '</td>' +
        '<td>' + sourceCell(it) + '</td>' +
        '<td><span class="status ' + (CLASS[status] || 'is-idle') + '"' + (HELP[status] ? ' title="' + esc(HELP[status]) + '"' : '') + '>' + esc(LABEL[status] || status) + '</span></td>' +
        '<td class="mono muted nowrap">' + esc((it.updated || '').slice(0, 16)) + '</td>' +
        '<td class="actions">' + actionsFor(it) + '</td></tr>';
    }).join('');
  }

  // An empty queue says what's coming from the search side, from the flow line's data.
  function idleMessage() {
    var f = window.IssuarrFlow;
    var msg = 'Nothing is downloading. Grabs from every source show here until they\'re filed.';
    if (!f) return msg;
    var n = (f.search.current ? 1 : 0) + f.search.waiting;
    if (n) return 'Nothing is downloading yet. ' + n + (n === 1 ? ' issue is' : ' issues are') + ' being searched; anything found shows up here.';
    var t1 = f.wanted.tier1;
    if (t1) return msg + ' <a href="wanted">' + t1.toLocaleString() + (t1 === 1 ? ' Tier 1 issue is' : ' Tier 1 issues are') + '</a> searched on the next scheduled search.';
    return msg;
  }

  function renderRange() {
    var from = st.total ? st.start + 1 : 0;
    var to = Math.min(st.start + st.len, st.total);
    $id('q-range').textContent = st.total > st.len ? 'Showing ' + from + '–' + to + ' of ' + st.total : '';
    $id('q-prev').disabled = st.start === 0;
    $id('q-next').disabled = st.start + st.len >= st.total;
  }

  // The server decides what's stalled (rows JD2 is holding stay Queued but aren't stuck).
  function renderStalled() {
    $id('q-stalled').hidden = !st.stalled;
    if (st.stalled) $id('q-stalled-text').textContent = 'Nothing is downloading or about to pick up ' +
      (st.stalled === 1 ? '1 queued item.' : st.stalled + ' queued items.');
  }

  // Only direct downloads can be cleared; a failed grab at the client stays until the client drops it.
  function ddlCount(status) {
    return st.items.filter(function (it) { return it.kind === 'ddl' && it.status === status; }).length;
  }

  function renderClear() {
    $id('q-clear-finished').hidden = !ddlCount('Completed');
    $id('q-clear-failed').hidden = !ddlCount('Failed');
  }

  /* ---- loading ---- */
  var loading = false;
  function load(force) {
    if ((document.hidden && force !== true) || loading) return;
    loading = true;
    fetch('downloadQueue', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        st.items = d.items || [];
        st.stalled = d.stalled || 0;
        st.loaded = true;
        renderTabs();
        renderRows();
        renderStalled();
        renderClear();
      })
      .catch(function () {
        if (!st.loaded) $id('q-table').tBodies[0].innerHTML = '<tr><td colspan="6" class="empty-state">Couldn\'t load the queue. Check the log.</td></tr>';
      })
      .then(function () { loading = false; });
  }

  function pixeldrain() {
    if (!window.queueShowPixeldrain) return;
    fetch('pixeldrain_status', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (r) {
        if (!r || !r.ok || !r.limit) return;
        var gb = function (n) { return (n / 1e9).toFixed(n < 1e10 ? 1 : 0); };
        var el = $id('q-pixeldrain');
        el.textContent = 'Pixeldrain: ' + gb(r.used) + ' of ' + gb(r.limit) + ' GB used in the last day' + (r.user ? ' (' + r.user + ')' : '') + '.';
        el.hidden = false;
      })
      .catch(function () {});
  }

  /* ---- events ---- */
  document.addEventListener('click', function (e) {
    var tab = e.target.closest('#q-tabs [data-tab]');
    if (tab) { st.tab = tab.getAttribute('data-tab'); st.start = 0; renderTabs(); renderRows(); return; }
    var b = e.target.closest('#main [data-act]');
    if (!b) return;
    var act = b.getAttribute('data-act'), id = b.getAttribute('data-id'), name = b.getAttribute('data-name');
    if (act === 'remove') requeue('remove', id, 'Remove ' + name + ' from the queue? Any file already downloaded stays where it is.');
    else if (act === 'abort') requeue('abort', id, 'Stop downloading ' + name + '? It will be marked Failed.');
    else requeue(act, id);
  });
  $id('q-restart-queue').addEventListener('click', function () { requeue('restart_queue'); });
  document.addEventListener('click', function (e) { if (e.target.closest('[data-queue-restart]')) requeue('restart_queue'); });
  $id('q-clear-queue').addEventListener('click', function () {
    requeue('clear_queue', null, 'Remove every queued direct download? Anything downloading now, finished downloads and grabs at your download client stay.');
  });
  $id('q-clear-finished').addEventListener('click', function () {
    var n = ddlCount('Completed');
    clearStatus('Completed', 'Remove ' + n + ' finished ' + (n === 1 ? 'download' : 'downloads') + ' from this list? ' +
      'The comics and their status in your library stay; only the list entries go, so you won\'t be able to download them again from this page or from the issue\'s history.');
  });
  $id('q-clear-failed').addEventListener('click', function () {
    var n = ddlCount('Failed');
    clearStatus('Failed', 'Remove ' + n + ' failed ' + (n === 1 ? 'download' : 'downloads') + ' from this list? ' +
      'The comics and their status in your library stay. The failures also leave the activity history, and you can\'t retry them from here or from the issue\'s history.');
  });
  $id('q-prev').addEventListener('click', function () { st.start = Math.max(0, st.start - st.len); renderRows(); });
  $id('q-next').addEventListener('click', function () { st.start += st.len; renderRows(); });
  var searchTimer = null;
  $id('q-search').addEventListener('input', function (e) {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { st.q = e.target.value.trim(); st.start = 0; renderRows(); }, 200);
  });

  function start() {
    renderTabs();
    load(true);
    pixeldrain();
    setInterval(load, 5000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) load(true); });
    document.addEventListener('issuarr:refresh', function () { load(true); });
    document.addEventListener('issuarr:flow', function () { if (st.loaded && !st.items.some(function (it) { return inTab(it, st.tab); })) renderRows(); });
  }
  if (window.jQuery) window.jQuery(start); else document.addEventListener('DOMContentLoaded', start);
})();
