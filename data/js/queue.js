/* Downloads > Queue: the direct-download queue and the active download. */
(function () {
  'use strict';

  var STATUSES = ['Downloading', 'Queued', 'Incomplete', 'Failed', 'Completed'];
  var HOSTS = { 'GC-Main': 'GetComics', 'GC-Mirror': 'GetComics mirror', 'GC-Pixel': 'Pixeldrain',
                'GC-Mega': 'Mega', 'GC-Media': 'Mediafire', 'DDL-Ext': 'External' };
  var CLASS = { Completed: 'is-have', Downloading: 'is-snatched is-running', Queued: 'is-idle',
                Incomplete: 'is-snatched', Failed: 'is-failed' };
  var st = { status: '', q: '', start: 0, len: 50, total: 0, counts: {}, active: null, key: '' };

  function $id(id) { return document.getElementById(id); }
  function I() { return window.Issuarr; }
  function esc(t) { return I().esc(t); }

  function call(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }).then(function (t) { try { return JSON.parse(t); } catch (e) { return {}; } });
  }

  function requeue(mode, id, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    call('ddl_requeue?mode=' + encodeURIComponent(mode) + (id != null ? '&id=' + encodeURIComponent(id) : ''))
      .then(function (r) { I().toast(r.message || 'Done'); })
      .catch(function () { I().toast('That didn\'t work. Check the log.', false); })
      .then(function () { pollActive(true); loadTable(); });
  }

  /* ---- filter tabs ---- */
  function renderTabs() {
    var c = st.counts;
    var all = STATUSES.reduce(function (n, s) { return n + (c[s] || 0); }, 0);
    var tabs = [['', 'All', all]].concat(STATUSES.filter(function (s) { return c[s] || st.status === s; })
      .map(function (s) { return [s, s, c[s] || 0]; }));
    $id('q-tabs').innerHTML = tabs.map(function (t) {
      return '<button type="button" data-ui data-status="' + esc(t[0]) + '" aria-pressed="' + (st.status === t[0]) + '">' +
        esc(t[1]) + '<span class="count">' + t[2] + '</span></button>';
    }).join('');
  }

  /* ---- table ---- */
  function actionsFor(row) {
    var id = row[5], status = row[3], name = row[0], out = [];
    var label = { Queued: 'Start', Downloading: 'Restart', Incomplete: 'Restart', Failed: 'Retry', Completed: 'Download again' }[status];
    if (status === 'Incomplete') out.push('<button type="button" class="btn btn-sm" data-act="resume" data-id="' + esc(id) + '">Resume</button>');
    if (label) out.push('<button type="button" class="btn btn-sm" data-act="restart" data-id="' + esc(id) + '">' + label + '</button>');
    out.push('<button type="button" class="btn btn-sm btn-ghost" data-act="remove" data-id="' + esc(id) + '" data-name="' + esc(name) + '">Remove</button>');
    return out.join('');
  }

  function renderRows(rows) {
    var tb = $id('q-table').tBodies[0];
    if (!rows.length) {
      var msg = st.q || st.status ? 'Nothing matches.' : 'Nothing has been sent to the download queue yet.';
      tb.innerHTML = '<tr><td colspan="6" class="empty-state">' + msg + '</td></tr>';
      return;
    }
    tb.innerHTML = rows.map(function (r) {
      var series = r[7] ? '<a href="comicDetails?ComicID=' + encodeURIComponent(r[7]) + '">' + esc(r[0]) + '</a>' : esc(r[0]);
      var status = r[3] || 'Unknown';
      var pct = status === 'Downloading' && st.active && String(st.active.a_id) === String(r[5]) ? ' ' + esc(st.active.percent) : '';
      return '<tr data-row="' + esc(r[5]) + '"><td>' + series + '</td>' +
        '<td class="num mono nowrap">' + esc(r[1] || '-') + '</td>' +
        '<td class="nowrap">' + esc(HOSTS[r[8]] || r[8] || '-') + '</td>' +
        '<td><span class="status ' + (CLASS[status] || 'is-idle') + '">' + esc(status) + pct + '</span></td>' +
        '<td class="mono muted nowrap">' + esc((r[4] || '').slice(0, 16)) + '</td>' +
        '<td class="actions">' + actionsFor(r) + '</td></tr>';
    }).join('');
  }

  function renderRange() {
    var from = st.total ? st.start + 1 : 0;
    var to = Math.min(st.start + st.len, st.total);
    $id('q-range').textContent = st.total ? 'Showing ' + from + '–' + to + ' of ' + st.total : '';
    $id('q-prev').disabled = st.start === 0;
    $id('q-next').disabled = st.start + st.len >= st.total;
  }

  function loadTable() {
    var p = new URLSearchParams({ iDisplayStart: st.start, iDisplayLength: st.len, iSortCol_0: '5', sSortDir_0: 'desc', sSearch: st.q });
    if (st.status) p.set('status', st.status);
    fetch('queueManageIt?' + p.toString(), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { st.total = d.iTotalDisplayRecords || 0; renderRows(d.aaData || []); renderRange(); })
      .catch(function () {
        $id('q-table').tBodies[0].innerHTML = '<tr><td colspan="6" class="empty-state">Couldn\'t load the queue. Check the log.</td></tr>';
      });
  }

  /* ---- active download ---- */
  function renderActive(d) {
    var body = $id('q-active-body');
    var id = d.a_id;
    if (d.status === 'Downloading') {
      var detail = [d.a_progress || d.a_size, d.a_speed, d.a_eta].filter(Boolean).map(esc).join(' · ');
      body.className = '';
      body.innerHTML =
        '<div style="display: flex; flex-direction: column; gap: 8px">' +
        '<div class="btn-row" style="justify-content: space-between"><b>' + esc(d.a_series || '') + (d.a_year ? ' (' + esc(d.a_year) + ')' : '') + '</b>' +
        '<span class="mono">' + esc(d.percent) + '</span></div>' +
        '<div class="progress"><span style="width: ' + esc(d.percent) + '"></span></div>' +
        '<div class="btn-row" style="justify-content: space-between"><span class="mono muted" style="overflow-wrap: anywhere">' + esc(d.a_filename || '') + '</span>' +
        '<span class="muted">' + detail + '</span></div>' +
        '<div class="btn-row"><button type="button" class="btn btn-sm" data-act="resume" data-id="' + esc(id) + '">Resume</button>' +
        '<button type="button" class="btn btn-sm" data-act="restart" data-id="' + esc(id) + '" title="Try this download again">Retry</button>' +
        '<button type="button" class="btn btn-sm btn-danger" data-act="abort" data-id="' + esc(id) + '" data-name="' + esc(d.a_series || 'this download') + '" title="Stop the download and mark it Failed">Stop</button></div></div>';
    } else if (id != null) {
      body.className = '';
      body.innerHTML = '<p style="margin: 0 0 10px">' + esc(String(d.status || '').replace(/<\/?br\s*\/?>/gi, ' ')) + '</p>' +
        '<div class="btn-row"><button type="button" class="btn btn-sm" data-act="restart" data-id="' + esc(id) + '" title="Try this download again">Retry</button>' +
        '<button type="button" class="btn btn-sm btn-danger" data-act="abort" data-id="' + esc(id) + '" data-name="this download" title="Stop the download and mark it Failed">Stop</button></div>';
    } else {
      body.className = 'muted';
      body.textContent = 'Nothing is downloading right now.';
    }
  }

  function pollActive(force) {
    if (document.hidden && force !== true) return;
    fetch('check_ActiveDDL', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        st.active = d.status === 'Downloading' ? d : null;
        st.counts = d.counts || {};
        renderTabs();
        renderActive(d);
        var queued = st.counts.Queued || 0;
        var stalled = queued && !d.waiting && d.status !== 'Downloading';
        $id('q-stalled').hidden = !stalled;
        if (stalled) $id('q-stalled-text').textContent = queued + ' queued and nothing downloading.';
        var key = JSON.stringify(st.counts) + '|' + d.a_id;
        if (key !== st.key) { st.key = key; loadTable(); }
        else if (st.active) {
          var cell = document.querySelector('#q-table tr[data-row="' + CSS.escape(String(st.active.a_id)) + '"] .status');
          if (cell) cell.textContent = 'Downloading ' + st.active.percent;
        }
      })
      .catch(function () {});
  }

  function pixeldrain() {
    if (!window.queueShowPixeldrain) return;
    fetch('pixeldrain_status', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (r) {
        if (!r || !r.ok || !r.limit) return;
        var gb = function (n) { return (n / 1e9).toFixed(n < 1e10 ? 1 : 0); };
        var el = $id('q-pixeldrain');
        el.textContent = 'Pixeldrain: ' + gb(r.used) + ' of ' + gb(r.limit) + ' GB used in the last day' + (r.user ? ' (' + r.user + ')' : '');
        el.hidden = false;
      })
      .catch(function () {});
  }

  /* ---- events ---- */
  document.addEventListener('click', function (e) {
    var tab = e.target.closest('#q-tabs [data-status]');
    if (tab) { st.status = tab.getAttribute('data-status'); st.start = 0; renderTabs(); loadTable(); return; }
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
    requeue('clear_queue', null, 'Remove every queued download? Anything downloading now, and finished downloads, stay.');
  });
  $id('q-prev').addEventListener('click', function () { st.start = Math.max(0, st.start - st.len); loadTable(); });
  $id('q-next').addEventListener('click', function () { st.start += st.len; loadTable(); });
  var searchTimer = null;
  $id('q-search').addEventListener('input', function (e) {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { st.q = e.target.value.trim(); st.start = 0; loadTable(); }, 250);
  });

  function start() {
    renderTabs();
    pollActive(true);
    pixeldrain();
    setInterval(pollActive, 5000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) pollActive(true); });
    document.addEventListener('issuarr:refresh', function () { pollActive(true); loadTable(); });
  }
  if (window.jQuery) window.jQuery(start); else document.addEventListener('DOMContentLoaded', start);
})();
