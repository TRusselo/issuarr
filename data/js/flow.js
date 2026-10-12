/* The flow line on Wanted and Downloads > Queue: an issue's way from Wanted into the library.
   Wanted -> Searching -> Downloading -> Filing -> Added today, each with what it's doing now,
   plus what happened lately. Polls activity_flow and hands the data to the page as an
   "issuarr:flow" event, so its rows can say where each issue is. */
(function () {
  'use strict';

  var root = document.getElementById('flow');
  if (!root) return;
  var here = root.getAttribute('data-here') || '';
  var last = null;
  var logOpen = false;

  function I() { return window.Issuarr; }
  function esc(t) { return I().esc(t == null ? '' : String(t)); }
  function fmt(n) { return Number(n || 0).toLocaleString(); }
  function issue(x) { return (x.name || 'Unknown') + (x.number != null && x.number !== '' ? ' #' + x.number : ''); }

  function ago(at, now) {
    var s = Math.max(0, Math.round(now - at));
    if (s < 60) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) === 1 ? 'yesterday' : Math.round(s / 86400) + ' days ago';
  }
  function until(at, now) {
    var m = Math.max(0, Math.round((at - now) / 60));
    if (m < 1) return 'in under a minute';
    if (m < 60) return 'in ' + m + ' min';
    var h = Math.floor(m / 60), r = m % 60;
    return 'in ' + h + ' h' + (r ? ' ' + r + ' min' : '');
  }
  function provider(p) { return String(p || '').replace(/^DDL\((.*)\)$/, '$1') || 'a provider'; }

  /* ---- the five stops ---- */
  function stops(d) {
    var s = d.search, dl = d.download, f = d.filing, now = d.now;
    var out = [];

    out.push({ key: 'wanted', name: 'Wanted', href: 'wanted', count: d.wanted.count,
               now: !d.wanted.count ? 'Nothing wanted' : d.wanted.tier1 === d.wanted.count ? 'All in Tier 1' :
                    !d.wanted.tier1 ? 'All in Tier 2, RSS only' : fmt(d.wanted.tier1) + ' in Tier 1',
               state: d.wanted.count ? 'on' : 'idle' });

    var searching = (s.current ? 1 : 0) + s.waiting;
    var sNow, sState = 'idle', sMeta = '';
    if (s.current) {
      sNow = issue(s.current); sState = 'live';
      sMeta = s.waiting ? fmt(s.waiting) + ' waiting' : 'Nothing else waiting';
    } else if (s.blocked === 'filing') {
      sNow = 'Waiting for filing'; sState = 'held';
      sMeta = 'Its series is being filed, searching after';
    } else if (s.busy) {
      sNow = 'Checking RSS feeds'; sState = 'live';
      sMeta = s.waiting ? fmt(s.waiting) + ' waiting' : '';
    } else if (s.waiting) {
      sNow = 'Starting the next search'; sState = 'live';
      sMeta = fmt(s.waiting) + ' waiting';
    } else {
      sNow = 'Idle';
      sMeta = s.next_run ? 'Next search ' + until(s.next_run, now) : '';
    }
    out.push({ key: 'search', name: 'Searching', href: 'wanted', count: searching, now: sNow, meta: sMeta, state: sState });

    var running = dl.now.length, waiting = dl.queued + dl.client;
    var dNow, dState = 'idle', dMeta = '', bar = null;
    if (running) {
      var top = dl.now[0];
      dNow = top.title; dState = 'live';
      if (top.percent != null) bar = top.percent;
      dMeta = (top.via === 'JDownloader 2' ? 'At JDownloader 2' : top.percent != null ? top.percent + '%' : 'Starting') +
              (running > 1 ? ', ' + (running - 1) + ' more running' : '') + (waiting ? ', ' + fmt(waiting) + ' waiting' : '');
    } else if (dl.stalled) {
      dNow = 'Stalled'; dState = 'stuck';
      dMeta = fmt(dl.queued) + ' queued, nothing moving';
    } else if (dl.client) {
      dNow = 'At your download client'; dState = 'live';
      dMeta = fmt(dl.client) + (dl.client === 1 ? ' grab' : ' grabs') + ' sent';
    } else {
      dNow = 'Idle';
      dMeta = dl.incomplete ? fmt(dl.incomplete) + ' incomplete' : '';
    }
    out.push({ key: 'download', name: 'Downloading', href: 'queueManage', count: running + waiting, now: dNow, meta: dMeta, state: dState, bar: bar });

    var filing = (f.working ? 1 : 0) + f.queued;
    out.push({ key: 'filing', name: 'Filing', href: 'tasks', count: filing,
               now: f.working ? (f.detail || 'Filing downloads') : 'Idle',
               meta: f.working ? (f.queued ? fmt(f.queued) + ' waiting' : '') : (f.last_at ? 'Last run ' + ago(f.last_at, now) : ''),
               state: f.working ? 'live' : 'idle' });

    var filed = d.events.filter(function (e) { return e.kind === 'filed'; })[0];
    out.push({ key: 'library', name: 'Added today', href: 'history', count: d.added_today,
               now: filed ? issue(filed) : 'Nothing yet',
               meta: filed ? ago(filed.at, now) : '',
               state: d.added_today ? 'on' : 'idle' });
    return out;
  }

  function stopHtml(st, i, all) {
    var mine = (here === 'wanted' && (st.key === 'wanted' || st.key === 'search')) || (here === 'queue' && st.key === 'download');
    var next = all[i + 1];
    var feeding = next && (next.state === 'live');
    var label = st.name + ': ' + st.count + '. ' + st.now + (st.meta ? '. ' + st.meta : '');
    return '<li class="flow-stop is-' + st.key + ' is-' + st.state + (feeding ? ' is-feeding" style="--feed: var(--flow-' + next.key + ')' : '') + '">' +
      '<a href="' + st.href + '"' + (mine ? ' aria-current="page"' : '') + ' aria-label="' + esc(label) + '">' +
      '<span class="flow-name">' + esc(st.name) + '</span>' +
      '<span class="flow-count">' + fmt(st.count) + '</span>' +
      '<span class="flow-now" title="' + esc(st.now) + '">' + esc(st.now) + '</span>' +
      (st.bar != null ? '<span class="flow-bar" aria-hidden="true"><span style="width:' + Math.max(2, Math.min(100, st.bar)) + '%"></span></span>' : '') +
      '<span class="flow-meta">' + esc(st.meta || '') + '</span>' +
      '</a></li>';
  }

  /* ---- what happened lately ---- */
  function sentence(e) {
    var name = '<b>' + esc(issue(e)) + '</b>' + (e.count > 1 ? ', ' + fmt(e.count) + ' issues,' : '');
    if (e.comicid) name = '<a href="comicDetails?ComicID=' + encodeURIComponent(e.comicid) + '">' + name + '</a>';
    switch (e.kind) {
      case 'found': return 'Found ' + name + ' on ' + esc(provider(e.provider));
      case 'filed': return 'Added ' + name + ' to the library';
      case 'failed': return 'Download failed for ' + name;
      case 'on_disk': return name + ' was already on disk, filing it';
      default: return 'Searched for ' + name + ', nothing found';
    }
  }

  function logHtml(d) {
    if (!d.events.length) return '<p class="flow-quiet">Nothing has happened since Issuarr started. Searches, downloads and new issues show up here.</p>';
    var first = d.events[0];
    var items = d.events.map(function (e) {
      return '<li class="flow-event is-' + e.kind + '"><span>' + sentence(e) + '</span><time>' + esc(ago(e.at, d.now)) + '</time></li>';
    }).join('');
    return '<details class="flow-log"' + (logOpen ? ' open' : '') + '><summary><span class="flow-event is-' + first.kind + '"><span>' +
      sentence(first) + '</span><time>' + esc(ago(first.at, d.now)) + '</time></span>' +
      '<span class="flow-more">' + (logOpen ? 'Show less' : 'Show the last ' + d.events.length) + '</span></summary><ol>' + items + '</ol></details>';
  }

  // Rebuilt only when something changed, so a focused link or an open list isn't lost every poll.
  var shown = '';
  function render(d) {
    var html = '<ol class="flow-line" aria-label="From wanted to your library">' + stops(d).map(stopHtml).join('') + '</ol>' + logHtml(d);
    if (html === shown) return;
    var focused = document.activeElement && root.contains(document.activeElement) ? document.activeElement.getAttribute('href') : null;
    root.innerHTML = shown = html;
    if (focused) {
      var again = root.querySelector('a[href="' + focused + '"]');
      if (again) again.focus();
    }
  }

  root.addEventListener('toggle', function (e) {
    if (!e.target.matches('.flow-log')) return;
    logOpen = e.target.open;
    var more = e.target.querySelector('.flow-more');
    if (more && last) more.textContent = logOpen ? 'Show less' : 'Show the last ' + last.events.length;
    shown = '';
  }, true);

  /* ---- polling ---- */
  var timer = null;
  function poll() {
    clearTimeout(timer);
    return fetch('activity_flow', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        var before = last;
        last = d;
        window.IssuarrFlow = d;
        render(d);
        document.dispatchEvent(new CustomEvent('issuarr:flow', { detail: { now: d, before: before } }));
      })
      .catch(function () {
        if (!last) root.innerHTML = '<p class="flow-quiet">Couldn\'t get what Issuarr is doing. Check the log.</p>';
      })
      .then(function () { timer = setTimeout(poll, document.hidden ? 30000 : 5000); });
  }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });
  // A page action (a search, a restart) changes the flow: show it without waiting for the next poll.
  document.addEventListener('issuarr:flow-poke', function () { clearTimeout(timer); timer = setTimeout(poll, 1200); });

  if (window.jQuery) window.jQuery(poll); else document.addEventListener('DOMContentLoaded', poll);
})();
