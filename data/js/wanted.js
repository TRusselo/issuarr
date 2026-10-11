/* Wanted: every issue Issuarr is looking for, split by search tier. */
(function () {
  'use strict';

  // loadupcoming row: [ComicName, Issue_Number, ReleaseDate, IssueID, tier, ComicID, Status,
  //                    StoryArc, StoryArcID, IssueArcID, watcharc ("both" | "oneoff" | null), Int_IssueNumber]
  var CHUNK = 100;
  var TABS = [
    ['all', 'All', function () { return true; }],
    ['tier1', 'Tier 1', function (r) { return r.tier === 1; }],
    ['tier2', 'Tier 2', function (r) { return r.tier === 2; }],
    ['snatched', 'Snatched', function (r) { return r.status === 'Snatched'; }],
    ['failed', 'Failed', function (r) { return r.status === 'Failed'; }],
    ['arcs', 'Story arcs', function (r) { return !!r.arc; }]
  ];
  var MARK = { Wanted: 'Marked {n} as wanted', Skipped: 'Skipped {n}', Ignored: 'Ignored {n}', Downloaded: 'Marked {n} as downloaded',
               Archived: 'Marked {n} as archived', OppositeTier: 'Switched the tier of {n}' };
  var STATUS = { Wanted: 'is-wanted', Snatched: 'is-snatched', Failed: 'is-failed' };

  var st = { rows: [], tab: 'all', q: '', sort: 'release-desc', limit: CHUNK, sel: {}, loaded: false };

  function $id(id) { return document.getElementById(id); }
  function I() { return window.Issuarr; }
  function esc(t) { return I().esc(t); }
  function fmt(n) { return Number(n).toLocaleString(); }
  function plural(n) { return n === 1 ? '1 issue' : fmt(n) + ' issues'; }

  function parse(r) {
    var tierText = r[4] || '';
    var tier = 0, added = '';
    if (r[6] === 'Wanted') {
      if (tierText.indexOf('2nd') === 0) tier = 2;
      else { tier = 1; var m = /\[(.*)\]/.exec(tierText); added = m ? m[1] : ''; }
    }
    return { name: r[0] || '', issue: r[1] == null ? '' : String(r[1]), release: r[2] || '', id: String(r[3]), tier: tier, added: added,
             comicid: r[5], status: r[6] || '', arc: r[7], arcid: r[8], watch: r[10], num: Number(r[11]) || 0 };
  }

  function seriesCell(r) {
    var name = esc(r.name);
    if (r.watch === 'oneoff') {
      return '<a href="detailStoryArc?StoryArcID=' + encodeURIComponent(r.arcid) + '">' + name + '</a> <span class="muted">' + esc(r.arc) + '</span>';
    }
    var link = '<a href="comicDetails?ComicID=' + encodeURIComponent(r.comicid) + '">' + name + '</a>';
    if (r.arc) link += ' <a class="muted" href="detailStoryArc?StoryArcID=' + encodeURIComponent(r.arcid) + '">' + esc(r.arc) + '</a>';
    return link;
  }

  function tierCell(r) {
    if (r.tier === 1) return 'Tier 1' + (r.added ? ' <span class="muted mono">since ' + esc(r.added) + '</span>' : '');
    if (r.tier === 2) return '<span class="muted">Tier 2</span>';
    return '';
  }

  function filtered() {
    var test = (TABS.filter(function (t) { return t[0] === st.tab; })[0] || TABS[0])[2];
    var q = st.q.toLowerCase();
    var list = st.rows.filter(function (r) {
      return test(r) && (!q || r.name.toLowerCase().indexOf(q) > -1 || r.issue.toLowerCase() === q.replace(/^#/, '') ||
        (r.arc && String(r.arc).toLowerCase().indexOf(q) > -1));
    });
    var bySeries = function (a, b) { return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.num - b.num; };
    var sorts = {
      'release-desc': function (a, b) { return b.release.localeCompare(a.release) || bySeries(a, b); },
      'release-asc': function (a, b) { return (a.release || '9999').localeCompare(b.release || '9999') || bySeries(a, b); },
      'added-desc': function (a, b) { return b.added.localeCompare(a.added) || b.release.localeCompare(a.release); },
      series: bySeries
    };
    return list.sort(sorts[st.sort] || sorts['release-desc']);
  }

  function renderTabs() {
    $id('w-tabs').innerHTML = TABS.map(function (t) {
      var n = st.rows.filter(t[2]).length;
      if (!n && t[0] !== 'all' && st.tab !== t[0]) return '';
      return '<button type="button" data-ui data-tab="' + t[0] + '" aria-pressed="' + (st.tab === t[0]) + '">' + t[1] +
        '<span class="count">' + fmt(n) + '</span></button>';
    }).join('');
  }

  function render() {
    var list = filtered();
    var shown = list.slice(0, st.limit);
    var tb = $id('w-table').tBodies[0];
    if (!shown.length) {
      tb.innerHTML = '<tr><td colspan="7" class="empty-state">' + (!st.loaded ? 'Loading…' : st.rows.length ? 'Nothing matches.' :
        'Nothing is wanted right now. Mark issues as wanted from a series page, or let the Calendar add new releases of series you follow.') + '</td></tr>';
    } else {
      tb.innerHTML = shown.map(function (r) {
        var picked = !!st.sel[r.id];
        var canSearch = r.watch !== 'oneoff';
        return '<tr' + (picked ? ' class="is-picked"' : '') + '><td class="check"><input type="checkbox" data-pick="' + esc(r.id) + '" aria-label="Select ' +
          esc(r.name) + ' #' + esc(r.issue) + '"' + (picked ? ' checked' : '') + '></td>' +
          '<td>' + seriesCell(r) + '</td>' +
          '<td class="mono nowrap">#' + esc(r.issue) + '</td>' +
          '<td class="mono nowrap">' + esc(r.release || '-') + '</td>' +
          '<td><span class="status ' + (STATUS[r.status] || '') + '">' + esc(r.status) + '</span></td>' +
          '<td class="nowrap">' + tierCell(r) + '</td>' +
          '<td class="actions">' + (canSearch ? '<button type="button" class="btn btn-sm" data-search="' + esc(r.id) + '">Search now</button>' : '') + '</td></tr>';
      }).join('');
    }
    $id('w-all').checked = shown.length > 0 && shown.every(function (r) { return st.sel[r.id]; });
    $id('w-range').textContent = list.length ? 'Showing ' + fmt(shown.length) + ' of ' + plural(list.length) : '';
    var more = $id('w-more-rows');
    more.hidden = list.length <= st.limit;
    more.textContent = 'Show more (' + fmt(list.length - st.limit) + ' left)';
    renderBulk();
  }

  function renderBulk() {
    var n = Object.keys(st.sel).length;
    $id('w-bulk').hidden = !n;
    $id('w-bulk-count').textContent = plural(n) + ' selected';
  }

  function load() {
    var p = new URLSearchParams({ iDisplayStart: 0, iDisplayLength: -1, iSortCol_0: '3', sSortDir_0: 'desc', sSearch: '', filters: '[]' });
    return fetch('loadupcoming?' + p.toString(), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        st.rows = (d.aaData || []).map(parse);
        st.loaded = true;
        var ids = {};
        st.rows.forEach(function (r) { ids[r.id] = true; });
        Object.keys(st.sel).forEach(function (k) { if (!ids[k]) delete st.sel[k]; });
        renderTabs(); render();
      })
      .catch(function () {
        st.loaded = true;
        $id('w-table').tBodies[0].innerHTML = '<tr><td colspan="7" class="empty-state">Couldn\'t load the wanted list. Check the log.</td></tr>';
      });
  }

  function search(ids) {
    var p = new URLSearchParams();
    ids.forEach(function (id) { p.append('issueIds', id); });
    return fetch('forceSearch?' + p.toString(), { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        I().toast('Searching for ' + plural(ids.length) + '. Anything found shows up in Downloads.');
      })
      .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
  }

  function mark(action) {
    var ids = Object.keys(st.sel);
    if (!ids.length) return;
    if (action === 'Downloaded' && !window.confirm('Mark ' + plural(ids.length) + ' as downloaded? Issuarr stops looking for them, even if the files are not on disk.')) return;
    var p = new URLSearchParams({ action: action });
    ids.forEach(function (id) { p.append('issueids[]', id); });
    fetch('markissues?' + p.toString(), { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        I().toast(MARK[action].replace('{n}', plural(ids.length)) + '.');
        st.sel = {};
        return load();
      })
      .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
  }

  /* ---- events ---- */
  document.addEventListener('click', function (e) {
    var t = e.target;
    var tab = t.closest('#w-tabs [data-tab]');
    if (tab) { st.tab = tab.getAttribute('data-tab'); st.limit = CHUNK; renderTabs(); render(); return; }
    var s = t.closest('[data-search]');
    if (s) { search([s.getAttribute('data-search')]); return; }
    var m = t.closest('#w-bulk [data-mark]');
    if (m) { mark(m.getAttribute('data-mark')); return; }
    if (t.closest('#w-bulk [data-bulk="search"]')) {
      // Story-arc-only issues can't be searched from here.
      var ids = st.rows.filter(function (r) { return st.sel[r.id] && r.watch !== 'oneoff'; }).map(function (r) { return r.id; });
      if (ids.length) search(ids); else I().toast('Story-arc-only issues are searched from their arc page.', false);
      return;
    }
  });

  document.addEventListener('change', function (e) {
    var pick = e.target.closest('[data-pick]');
    if (!pick) return;
    var id = pick.getAttribute('data-pick');
    if (pick.checked) st.sel[id] = true; else delete st.sel[id];
    pick.closest('tr').classList.toggle('is-picked', pick.checked);
    renderBulk();
  });

  $id('w-all').addEventListener('change', function (e) {
    filtered().slice(0, st.limit).forEach(function (r) { if (e.target.checked) st.sel[r.id] = true; else delete st.sel[r.id]; });
    render();
  });
  $id('w-bulk-none').addEventListener('click', function () { st.sel = {}; render(); });
  $id('w-search-tier1').addEventListener('click', function () {
    fetch('forceSearch', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); I().toast('Searching every Tier 1 issue. Anything found shows up in Downloads.'); })
      .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
  });
  $id('w-export').addEventListener('click', function () {
    fetch('wanted_Export?mode=Wanted', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); I().toast('Saved Wanted_list.csv in the data folder.'); })
      .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
  });
  var qTimer = null;
  $id('w-q').addEventListener('input', function (e) {
    clearTimeout(qTimer);
    qTimer = setTimeout(function () { st.q = e.target.value.trim(); st.limit = CHUNK; render(); }, 120);
  });
  $id('w-sort').addEventListener('change', function (e) { st.sort = e.target.value; render(); });
  $id('w-more-rows').addEventListener('click', function () { st.limit += CHUNK; render(); });
  var refreshTimer = null;
  document.addEventListener('issuarr:refresh', function () { clearTimeout(refreshTimer); refreshTimer = setTimeout(load, 800); });

  if (window.jQuery) window.jQuery(load); else document.addEventListener('DOMContentLoaded', load);
})();
