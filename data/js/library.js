/* Library: every series as covers or a list, with filters and bulk edit.
   The filter box searches your library only; Add series searches ComicVine. */
(function () {
  'use strict';

  var STORE = 'issuarr-library';
  var CHUNK = 120;
  var TABS = [
    ['all', 'All', function () { return true; }],
    ['continuing', 'Continuing', function (s) { return s.recent === 'Continuing'; }],
    ['ended', 'Ended', function (s) { return s.recent === 'Ended'; }],
    ['paused', 'Paused', function (s) { return s.status === 'Paused'; }],
    ['gaps', 'Has gaps', function (s) { return s.total > 0 && s.have < s.total; }],
    ['loading', 'Loading', function (s) { return s.status === 'Loading' || s.recent === 'Loading'; }],
    ['problems', 'Problems', function (s) { return isError(s) || s.cv_removed === 1; }]
  ];
  var BULK = {
    refresh: { done: 'Refreshing', confirm: null },
    pause: { done: 'Paused', confirm: null },
    resume: { done: 'Resumed', confirm: null },
    recheck: { done: 'Rechecking files for', confirm: null },
    metatag: { done: 'Writing metadata for', confirm: 'Write ComicInfo metadata into the files of {n}? This changes the files on disk.' },
    rename: { done: 'Renaming files for', confirm: 'Rename the files of {n} to match your naming settings? This changes the files on disk.' },
    delete: { done: 'Removed', confirm: 'Remove {n} from Issuarr? The series, its issue list and statuses are removed. Files on disk stay where they are.' }
  };

  var st = { all: [], tab: 'all', q: '', pub: '', sort: 'title', view: 'covers', limit: CHUNK, selecting: /[?&]select=1\b/.test(location.search), sel: {}, loaded: false, noArt: {} };
  try {
    var saved = JSON.parse(localStorage.getItem(STORE) || 'null');
    if (saved) { st.view = saved.view || st.view; st.sort = saved.sort || st.sort; }
  } catch (e) {}

  function save() { try { localStorage.setItem(STORE, JSON.stringify({ view: st.view, sort: st.sort })); } catch (e) {} }
  function $id(id) { return document.getElementById(id); }
  function I() { return window.Issuarr; }
  function esc(t) { return I().esc(t); }
  function isError(s) { return ['Active', 'Paused', 'Loading'].indexOf(s.status) < 0; }
  function fmt(n) { return Number(n).toLocaleString(); }

  function tint(name) {
    var h = 0;
    for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
    return 'hsl(' + h + ' 28% 30%)';
  }

  function statusOf(s) {
    if (s.status === 'Paused') return ['Paused', 'is-ignored'];
    if (s.status === 'Loading' || s.recent === 'Loading') return ['Loading', 'is-snatched is-running'];
    if (isError(s)) return ['Error', 'is-failed'];
    if (s.recent === 'Ended') return ['Ended', 'is-ignored'];
    return [s.recent || 'Unknown', ''];
  }

  function bar(s) {
    if (!s.total) return '<div class="collection-bar" title="No issue count yet"></div>';
    var have = Math.min(s.have, s.total);
    var wanted = Math.min(s.wanted, Math.max(s.total - have, 0));
    var rest = Math.max(s.total - have - wanted, 0);
    var title = have + ' of ' + s.total + ' on disk' + (wanted ? ', ' + wanted + ' wanted' : '');
    return '<div class="collection-bar" title="' + esc(title) + '">' +
      (have ? '<span class="seg-have" style="flex: ' + have + ' 1 0"></span>' : '') +
      (wanted ? '<span class="seg-wanted" style="flex: ' + wanted + ' 1 0"></span>' : '') +
      (rest ? '<span class="seg-missing" style="flex: ' + rest + ' 1 0"></span>' : '') + '</div>';
  }

  function counts(s) {
    var t = s.total ? s.have + '/' + s.total : String(s.have);
    return '<span class="card-count">' + esc(t) + (s.wanted ? ' <b class="is-wanted">' + s.wanted + ' wanted</b>' : '') + '</span>';
  }

  function link(s) { return 'comicDetails?ComicID=' + encodeURIComponent(s.id); }

  // Covers that failed once aren't asked for again until the page reloads.
  function img(s, cls) {
    if (!s.image || st.noArt[s.id]) return '';
    return '<img class="' + cls + '" loading="lazy" decoding="async" src="' + esc(s.image) + '" alt="" data-art="' + esc(s.id) + '">';
  }
  document.addEventListener('error', function (e) {
    var t = e.target;
    if (!t || !t.getAttribute || !t.hasAttribute('data-art')) return;
    st.noArt[t.getAttribute('data-art')] = true;
    t.remove();
  }, true);

  function card(s) {
    var stt = statusOf(s);
    var badges = '';
    if (s.status === 'Paused') badges += '<span class="cover-badge is-dim">Paused</span>';
    if (stt[0] === 'Loading') badges += '<span class="cover-badge is-dim">Loading</span>';
    if (stt[0] === 'Error') badges += '<span class="cover-badge is-bad">Error</span>';
    if (s.cv_removed === 1) badges += '<span class="cover-badge is-bad">Not on ComicVine</span>';
    if (s.latest) badges += '<span class="cover-badge">#' + esc(s.latest) + '</span>';
    var meta = [s.publisher, s.year, stt[0]].filter(Boolean).map(esc).join(' · ');
    var picked = !!st.sel[s.id];
    return '<article class="cover-card' + (picked ? ' is-picked' : '') + '" data-id="' + esc(s.id) + '">' +
      '<input type="checkbox" class="card-check" data-pick="' + esc(s.id) + '" aria-label="Select ' + esc(s.name) + '"' + (picked ? ' checked' : '') + '>' +
      '<a class="cover" href="' + link(s) + '" tabindex="-1" aria-hidden="true">' + img(s, 'cover-art') +
      '<span class="cover-fallback" style="--tint: ' + tint(s.name || '') + '">' + esc(s.name) + '</span>' +
      '<span class="cover-badges">' + badges + '</span></a>' +
      '<div class="card-text"><a class="card-title" href="' + link(s) + '" title="' + esc(s.name) + '">' + esc(s.name) +
      (s.volume && s.volume !== 'v1' ? ' <span class="muted">' + esc(s.volume) + '</span>' : '') + '</a>' +
      bar(s) + '<div class="card-nums"><span>' + esc(s.total ? fmt(s.have) + ' / ' + fmt(s.total) : fmt(s.have)) + '</span>' +
      (s.wanted ? '<span class="is-wanted">' + fmt(s.wanted) + ' wanted</span>' : '') + '</div>' +
      '<div class="card-meta">' + meta + '</div></div></article>';
  }

  function row(s) {
    var stt = statusOf(s);
    var picked = !!st.sel[s.id];
    return '<tr data-id="' + esc(s.id) + '"' + (picked ? ' class="is-picked"' : '') + '>' +
      '<td class="check lib-check"><input type="checkbox" data-pick="' + esc(s.id) + '" aria-label="Select ' + esc(s.name) + '"' + (picked ? ' checked' : '') + '></td>' +
      '<td><span class="lib-name"><span class="thumb-wrap">' + img(s, 'thumb') + '</span><a href="' + link(s) + '">' + esc(s.name) + '</a>' +
      (s.cv_removed === 1 ? ' <span class="status is-failed">Not on ComicVine</span>' : '') + '</span></td>' +
      '<td class="nowrap">' + esc(s.publisher || '-') + '</td>' +
      '<td class="mono">' + esc(s.year || '-') + '</td>' +
      '<td class="mono nowrap">' + (s.latest ? '#' + esc(s.latest) : '-') + '</td>' +
      '<td><span class="status ' + stt[1] + '">' + esc(stt[0]) + '</span></td>' +
      '<td><div class="lib-issues">' + bar(s) + counts(s) + '</div></td></tr>';
  }

  function filtered() {
    var test = (TABS.filter(function (t) { return t[0] === st.tab; })[0] || TABS[0])[2];
    // Every word has to match the name, publisher or year: "batman dc", "saga 2012".
    var words = st.q.toLowerCase().split(/\s+/).filter(Boolean);
    var list = st.all.filter(function (s) {
      if (!test(s) || (st.pub && s.publisher !== st.pub)) return false;
      if (!words.length) return true;
      var hay = [s.name, s.publisher, s.year].join(' ').toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) > -1; });
    });
    var byTitle = function (a, b) { return String(a.sort || a.name).localeCompare(String(b.sort || b.name), undefined, { sensitivity: 'base' }); };
    var sorts = {
      title: byTitle,
      updated: function (a, b) { return String(b.updated || '').localeCompare(String(a.updated || '')) || byTitle(a, b); },
      year: function (a, b) { return (parseInt(a.year, 10) || 9999) - (parseInt(b.year, 10) || 9999) || byTitle(a, b); },
      missing: function (a, b) { return (b.total - b.have) - (a.total - a.have) || byTitle(a, b); },
      publisher: function (a, b) { return String(a.publisher || '').localeCompare(String(b.publisher || '')) || byTitle(a, b); }
    };
    return list.sort(sorts[st.sort] || byTitle);
  }

  function renderTabs() {
    $id('lib-tabs').innerHTML = TABS.map(function (t) {
      var n = st.all.filter(t[2]).length;
      if (!n && t[0] !== 'all' && (t[0] === 'loading' || t[0] === 'problems') && st.tab !== t[0]) return '';
      return '<button type="button" data-ui data-tab="' + t[0] + '" aria-pressed="' + (st.tab === t[0]) + '">' + t[1] + '<span class="count">' + fmt(n) + '</span></button>';
    }).join('');
  }

  function renderStats() {
    var issues = 0, have = 0;
    st.all.forEach(function (s) { issues += s.total || 0; have += Math.min(s.have, s.total || s.have); });
    var pct = issues ? Math.floor(have / issues * 100) : 0;
    $id('lib-stats').textContent = fmt(st.all.length) + ' series · ' + fmt(issues) + ' issues · ' + pct + '% on disk';
  }

  function renderPublishers() {
    var sel = $id('lib-pub');
    var pubs = {};
    st.all.forEach(function (s) { if (s.publisher) pubs[s.publisher] = (pubs[s.publisher] || 0) + 1; });
    var names = Object.keys(pubs).sort(function (a, b) { return a.localeCompare(b); });
    if (st.pub && !pubs[st.pub]) st.pub = '';
    sel.innerHTML = '<option value="">All</option>' + names.map(function (p) {
      return '<option value="' + esc(p) + '"' + (p === st.pub ? ' selected' : '') + '>' + esc(p) + ' (' + pubs[p] + ')</option>';
    }).join('');
  }

  function render() {
    var list = filtered();
    var shown = list.slice(0, st.limit);
    var covers = st.view === 'covers';
    $id('lib-grid').hidden = !covers || !shown.length;
    $id('lib-list').hidden = covers || !shown.length;
    if (covers) $id('lib-grid').innerHTML = shown.map(card).join('');
    else $id('lib-list').querySelector('tbody').innerHTML = shown.map(row).join('');
    var empty = $id('lib-empty');
    empty.hidden = !!shown.length || !st.loaded;
    if (!shown.length && st.loaded) {
      empty.innerHTML = st.all.length
        ? 'No series match. <button type="button" class="btn btn-sm" id="lib-clear-filters">Clear filters</button>'
        : 'Your library is empty. <button type="button" class="btn btn-sm btn-primary" data-action-add>Add a series</button> ' +
          '<a class="btn btn-sm" href="manage#tabs-1">Scan a folder you already have</a>';
    }
    var more = $id('lib-more-rows');
    more.hidden = list.length <= st.limit;
    more.textContent = 'Show more (' + fmt(Math.max(list.length - st.limit, 0)) + ' left)';
    document.querySelectorAll('.library [data-view]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-view') === st.view)); });
    $id('lib-sort').value = st.sort;
    renderBulk();
  }

  function renderBulk() {
    var n = Object.keys(st.sel).length;
    $id('lib-bulk').hidden = !st.selecting;
    $id('lib-bulk-count').textContent = n ? n + (n === 1 ? ' series selected' : ' series selected') : 'Select series below';
    document.querySelectorAll('#lib-bulk [data-bulk]').forEach(function (b) { b.disabled = !n; });
    document.querySelector('.library').classList.toggle('is-selecting', st.selecting);
    $id('lib-select').setAttribute('aria-pressed', String(st.selecting));
    $id('lib-select').textContent = st.selecting ? 'Done' : 'Select';
  }

  function load() {
    return fetch('library_data', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        st.all = d.series || [];
        st.loaded = true;
        var ids = {};
        st.all.forEach(function (s) { ids[s.id] = true; });
        Object.keys(st.sel).forEach(function (k) { if (!ids[k]) delete st.sel[k]; });
        renderStats(); renderTabs(); renderPublishers(); render();
      })
      .catch(function () {
        st.loaded = true;
        $id('lib-empty').hidden = false;
        $id('lib-empty').textContent = 'Couldn\'t load your library. Check the log.';
      });
  }

  function bulk(action) {
    var picked = st.all.filter(function (s) { return st.sel[s.id]; });
    if (!picked.length) return;
    var what = picked.length === 1 ? '"' + picked[0].name + '"' : picked.length + ' series';
    var cfg = BULK[action];
    if (cfg.confirm && !window.confirm(cfg.confirm.replace('{n}', what))) return;
    var body = new URLSearchParams();
    body.append('action', action);
    picked.forEach(function (s) { body.append(s.name + '[' + s.year + ']', s.id); });
    fetch('markComics', { method: 'POST', credentials: 'same-origin', body: body })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        var bg = ['refresh', 'recheck', 'metatag', 'rename'].indexOf(action) > -1;
        I().toast(cfg.done + ' ' + what + (bg ? '. Follow it in Tasks › Jobs or the log.' : '.'));
        if (action === 'delete') st.sel = {};
        return load();
      })
      .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
  }

  /* ---- events ---- */
  document.addEventListener('click', function (e) {
    var t = e.target;
    var tab = t.closest('#lib-tabs [data-tab]');
    if (tab) { st.tab = tab.getAttribute('data-tab'); st.limit = CHUNK; renderTabs(); render(); return; }
    var view = t.closest('.library [data-view]');
    if (view) { st.view = view.getAttribute('data-view'); save(); render(); return; }
    var b = t.closest('#lib-bulk [data-bulk]');
    if (b) { bulk(b.getAttribute('data-bulk')); return; }
    if (t.closest('#lib-clear-filters')) {
      st.tab = 'all'; st.q = ''; st.pub = ''; $id('lib-q').value = ''; $id('lib-pub').value = '';
      renderTabs(); render(); return;
    }
    if (t.closest('[data-action-add]')) { var add = document.querySelector('[data-action="add"]'); if (add) add.click(); return; }
    var exp = t.closest('[data-export]');
    if (exp) {
      $id('lib-more').open = false;
      var mode = exp.getAttribute('data-export');
      fetch('wanted_Export?mode=' + encodeURIComponent(mode), { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); I().toast('Saved ' + mode + '_list.csv in the data folder.'); })
        .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
      return;
    }
    if (t.closest('#lib-update-all')) {
      $id('lib-more').open = false;
      if (!window.confirm('Update every series from ComicVine? On a big library this takes a while and uses ComicVine requests.')) return;
      fetch('forceUpdate', { credentials: 'same-origin' })
        .then(function () { I().toast('Updating every series. Follow it in Tasks › Jobs or the log.'); })
        .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
      return;
    }
  });

  document.addEventListener('change', function (e) {
    var pick = e.target.closest('[data-pick]');
    if (!pick) return;
    var id = pick.getAttribute('data-pick');
    if (pick.checked) st.sel[id] = true; else delete st.sel[id];
    var holder = pick.closest('.cover-card, tr');
    if (holder) holder.classList.toggle('is-picked', pick.checked);
    renderBulk();
  });

  // In select mode a click anywhere on a card picks it instead of opening the series.
  $id('lib-grid').addEventListener('click', function (e) {
    if (!st.selecting || e.target.closest('[data-pick]')) return;
    var cardEl = e.target.closest('.cover-card');
    if (!cardEl) return;
    e.preventDefault();
    var cb = cardEl.querySelector('[data-pick]');
    cb.checked = !cb.checked;
    cb.dispatchEvent(new Event('change', { bubbles: true }));
  });

  $id('lib-select').addEventListener('click', function () {
    st.selecting = !st.selecting;
    if (!st.selecting) st.sel = {};
    render();
  });
  $id('lib-select-all').addEventListener('click', function () {
    filtered().slice(0, st.limit).forEach(function (s) { st.sel[s.id] = true; });
    render();
  });
  var qTimer = null;
  $id('lib-q').addEventListener('input', function (e) {
    clearTimeout(qTimer);
    qTimer = setTimeout(function () { st.q = e.target.value.trim(); st.limit = CHUNK; render(); }, 120);
  });
  $id('lib-pub').addEventListener('change', function (e) { st.pub = e.target.value; st.limit = CHUNK; render(); });
  $id('lib-sort').addEventListener('change', function (e) { st.sort = e.target.value; save(); render(); });
  $id('lib-more-rows').addEventListener('click', function () { st.limit += CHUNK; render(); });
  if (window.IntersectionObserver) {
    new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting && !$id('lib-more-rows').hidden) { st.limit += CHUNK; render(); }
    }, { rootMargin: '600px' }).observe($id('lib-more-rows'));
  }
  var refreshTimer = null;
  document.addEventListener('issuarr:refresh', function () { clearTimeout(refreshTimer); refreshTimer = setTimeout(load, 800); });

  render();
  if (window.jQuery) window.jQuery(load); else document.addEventListener('DOMContentLoaded', load);
})();
