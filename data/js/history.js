/* Downloads > History: everything grabbed and what happened to it. */
(function () {
  'use strict';

  // Row: [DateAdded, ComicName, Issue_Number, Status, IssueID, ComicID, Provider, StoryArc, IssueArcID, StoryArcID, Oneoff]
  var CLASS = { Snatched: 'is-snatched', 'Post-Processed': 'is-have', Processed: 'is-have', Downloaded: 'is-have',
                Archived: 'is-have', Failed: 'is-failed', Unprocessed: 'is-idle' };
  var st = { status: '', q: '', start: 0, len: 50, total: 0, counts: {}, rows: [], sel: {} };

  function $id(id) { return document.getElementById(id); }
  function I() { return window.Issuarr; }
  function esc(t) { return I().esc(t); }

  function seriesCell(r) {
    var name = esc(r[1]);
    var iid = r[4] || '';
    if (iid.indexOf('_') > -1 || r[8] !== null) {
      if (iid.indexOf('_') > -1 && r[7] !== null) {
        return '<a href="detailStoryArc?StoryArcID=' + encodeURIComponent(iid.split('_')[0]) + '">' + name + '</a> <span class="muted">' + esc(r[7]) + '</span>';
      }
      if (r[8] !== null) {
        return '<a href="comicDetails?ComicID=' + encodeURIComponent(r[5]) + '">' + name + '</a> <a class="muted" href="detailStoryArc?StoryArcID=' +
          encodeURIComponent(r[9]) + '">' + esc(r[7]) + '</a>';
      }
      return '<a href="detailStoryArc?StoryArcID=' + encodeURIComponent(r[5]) + '">' + name + '</a>';
    }
    if (r[10] !== null) {
      var wk = String(r[10]).split('-');
      return '<a href="pullist?week=' + encodeURIComponent(wk[0]) + '&amp;year=' + encodeURIComponent(wk[1]) + '">' + name + '</a> <span class="muted">one-off</span>';
    }
    return '<a href="comicDetails?ComicID=' + encodeURIComponent(r[5]) + '">' + name + '</a>';
  }

  function renderTabs() {
    var c = st.counts;
    var names = Object.keys(c).sort(function (a, b) { return c[b] - c[a]; });
    var all = names.reduce(function (n, k) { return n + c[k]; }, 0);
    if (st.status && names.indexOf(st.status) < 0) names.push(st.status);
    $id('h-tabs').innerHTML = [['', 'All', all]].concat(names.map(function (k) { return [k, k, c[k] || 0]; })).map(function (t) {
      return '<button type="button" data-ui data-status="' + esc(t[0]) + '" aria-pressed="' + (st.status === t[0]) + '">' +
        esc(t[1]) + '<span class="count">' + t[2] + '</span></button>';
    }).join('');
  }

  function renderRows() {
    var tb = $id('h-table').tBodies[0];
    if (!st.rows.length) {
      tb.innerHTML = '<tr><td colspan="7" class="empty-state">' + (st.q || st.status ? 'Nothing matches.' : 'Nothing has been grabbed yet.') + '</td></tr>';
      $id('h-all').checked = false;
      return;
    }
    tb.innerHTML = st.rows.map(function (r, i) {
      var status = r[3] || 'Unknown';
      return '<tr><td class="check"><input type="checkbox" data-i="' + i + '" aria-label="Select ' + esc(r[1]) + ' #' + esc(r[2]) + '"' + (st.sel[r[4]] ? ' checked' : '') + '></td>' +
        '<td class="mono muted nowrap">' + esc((r[0] || '').slice(0, 16)) + '</td>' +
        '<td>' + seriesCell(r) + '</td>' +
        '<td class="mono nowrap">' + (r[2] != null ? '#' + esc(r[2]) : '') + '</td>' +
        '<td><span class="status ' + (CLASS[status] || '') + '">' + esc(status) + '</span></td>' +
        '<td class="nowrap">' + esc(r[6] || '-') + '</td>' +
        '<td class="actions"><button type="button" class="btn btn-sm" data-retry="' + i + '">Search again</button></td></tr>';
    }).join('');
    $id('h-all').checked = st.rows.every(function (r) { return st.sel[r[4]]; });
  }

  function renderRange() {
    var from = st.total ? st.start + 1 : 0, to = Math.min(st.start + st.len, st.total);
    $id('h-range').textContent = st.total ? 'Showing ' + from + '–' + to + ' of ' + st.total : '';
    $id('h-prev').disabled = st.start === 0;
    $id('h-next').disabled = st.start + st.len >= st.total;
  }

  function renderBulk() {
    var n = Object.keys(st.sel).length;
    $id('h-bulk').hidden = !n;
    $id('h-bulk-count').textContent = n + (n === 1 ? ' issue selected' : ' issues selected');
  }

  function load() {
    var p = new URLSearchParams({ iDisplayStart: st.start, iDisplayLength: st.len, iSortCol_0: '1', sSortDir_0: 'asc', sSearch: st.q });
    if (st.status) p.set('status', st.status);
    return fetch('loadhistory?' + p.toString(), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        st.total = d.iTotalDisplayRecords || 0;
        st.rows = d.aaData || [];
        st.counts = d.statusCounts || {};
        renderTabs(); renderRows(); renderRange();
      })
      .catch(function () {
        $id('h-table').tBodies[0].innerHTML = '<tr><td colspan="7" class="empty-state">Couldn\'t load history. Check the log.</td></tr>';
      });
  }

  function get(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); });
  }

  /* ---- events ---- */
  document.addEventListener('click', function (e) {
    var tab = e.target.closest('#h-tabs [data-status]');
    if (tab) { st.status = tab.getAttribute('data-status'); st.start = 0; load(); return; }

    var retry = e.target.closest('[data-retry]');
    if (retry) {
      var r = st.rows[+retry.getAttribute('data-retry')];
      retry.disabled = true;
      var q = new URLSearchParams({ ComicName: r[1], ComicID: r[5], IssueID: r[4], IssueNumber: r[2], redirect: 'history' });
      get('retryissue?' + q.toString())
        .then(function (t) { var o = {}; try { o = JSON.parse(t); } catch (x) {} I().toast(o.message || 'Search started', o.status !== 'failure'); })
        .catch(function () { I().toast('That didn\'t work. Check the log.', false); })
        .then(function () { retry.disabled = false; load(); });
      return;
    }

    var clear = e.target.closest('[data-clear]');
    if (clear) {
      var kind = clear.getAttribute('data-clear');
      var what = kind === 'all' ? 'all history' : 'every ' + kind.toLowerCase() + ' entry';
      $id('h-clear-menu').open = false;
      if (!window.confirm('Clear ' + what + '? Issue statuses in your library don\'t change.')) return;
      get('clearhistory?status_type=' + encodeURIComponent(kind))
        .then(function () { I().toast('History cleared'); st.sel = {}; renderBulk(); st.start = 0; load(); })
        .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
      return;
    }

    if (e.target.closest('[data-wipe-nzblog]')) {
      $id('h-clear-menu').open = false;
      if (!window.confirm('Clear the download log? Issuarr forgets which issue each grabbed download belongs to. Downloads that haven\'t been filed yet are then matched by file name only, and failed-download handling can\'t link them back to their issue. Don\'t do this while anything is downloading.')) return;
      get('wipenzblog').then(function () { I().toast('Download log cleared.'); }).catch(function () { I().toast('That didn\'t work. Check the log.', false); });
      return;
    }

    var bulk = e.target.closest('[data-bulk]');
    if (bulk) {
      var action = bulk.getAttribute('data-bulk');
      var ids = Object.keys(st.sel);
      if (action === 'Clear' && !window.confirm('Clear ' + ids.length + ' entries from history?')) return;
      var body = new URLSearchParams();
      body.append('action', action);
      ids.forEach(function (id) { body.append('issueids[]', id); });
      fetch('markissues', { method: 'POST', credentials: 'same-origin', body: body })
        .then(function (r) { if (!r.ok) throw new Error(r.status); I().toast(action === 'Retry' ? 'Searching again for ' + ids.length + ' issues' : 'Cleared ' + ids.length + ' entries'); })
        .catch(function () { I().toast('That didn\'t work. Check the log.', false); })
        .then(function () { st.sel = {}; renderBulk(); load(); });
    }
  });

  $id('h-bulk-none').addEventListener('click', function () { st.sel = {}; renderBulk(); renderRows(); });
  $id('h-table').addEventListener('change', function (e) {
    var cb = e.target;
    if (cb.id === 'h-all') {
      st.rows.forEach(function (r) { if (cb.checked) st.sel[r[4]] = true; else delete st.sel[r[4]]; });
      renderRows();
    } else if (cb.hasAttribute('data-i')) {
      var id = st.rows[+cb.getAttribute('data-i')][4];
      if (cb.checked) st.sel[id] = true; else delete st.sel[id];
      $id('h-all').checked = st.rows.every(function (r) { return st.sel[r[4]]; });
    }
    renderBulk();
  });
  $id('h-prev').addEventListener('click', function () { st.start = Math.max(0, st.start - st.len); load(); });
  $id('h-next').addEventListener('click', function () { st.start += st.len; load(); });
  $id('h-len').addEventListener('change', function (e) { st.len = +e.target.value; st.start = 0; load(); });
  var t = null;
  $id('h-search').addEventListener('input', function (e) {
    clearTimeout(t);
    t = setTimeout(function () { st.q = e.target.value.trim(); st.start = 0; load(); }, 250);
  });
  document.addEventListener('click', function (e) {
    var m = $id('h-clear-menu');
    if (m.open && !m.contains(e.target)) m.open = false;
  });

  document.addEventListener('issuarr:refresh', function () { load(); });
  if (window.jQuery) window.jQuery(load); else document.addEventListener('DOMContentLoaded', load);
})();
