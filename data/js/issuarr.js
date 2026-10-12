/* Issuarr interface: sidebar state, Ctrl K jump menu, the "Running now" box,
   pages whose sections moved into the sidebar, and the custom CSS editor. */
(function () {
  'use strict';

  var doc = document;
  var $ = window.jQuery;
  var path = (location.pathname.split('/').pop() || 'home').toLowerCase();

  function $id(id) { return doc.getElementById(id); }
  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function toast(message, ok) {
    if (!$) return;
    var box = $('#ajaxMsg');
    box.removeClass().addClass('ajaxMsg ' + (ok === false ? 'error' : 'success'));
    box.html('<div class="msg"></div>').find('.msg').text(message);
    box.stop(true, true).fadeIn().delay(3000).fadeOut();
  }
  function mark() { return window.issuarrMarkNav ? window.issuarrMarkNav() : null; }

  // Helpers shared by the rebuilt pages.
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function span(secs) {
    secs = Math.abs(secs);
    if (secs < 60) return 'under a minute';
    var m = Math.round(secs / 60);
    if (m < 60) return m + ' min';
    var h = Math.round(m / 60);
    if (h < 48) return h + ' h';
    return Math.round(h / 24) + ' days';
  }
  function relTime(epoch) {
    if (!epoch) return '';
    var d = epoch - Date.now() / 1000;
    if (Math.abs(d) < 45) return 'now';
    return d > 0 ? 'in ' + span(d) : span(d) + ' ago';
  }
  function clock(epoch) {
    if (!epoch) return '';
    var t = new Date(epoch * 1000);
    var today = new Date();
    var time = t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return t.toDateString() === today.toDateString() ? time : t.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + time;
  }
  window.Issuarr = { esc: esc, toast: toast, relTime: relTime, clock: clock };

  /* ---------- Pages whose tab strip moved into the sidebar ---------- */

  var TABBED = { manage: true, config: true };

  function tabsWidget() {
    if (!$) return null;
    var t = $('#tabs');
    return t.length && t.data('tabs') ? t : null;
  }

  function selectTab(hash) {
    var t = tabsWidget();
    if (!t || !hash) return false;
    var anchors = t.find('> ul a');
    var idx = -1;
    anchors.each(function (i) { if (this.getAttribute('href') === hash) idx = i; });
    if (idx < 0) return false;
    t.tabs('select', idx);
    return true;
  }

  // The browser jumps to #tabs-N on load; keep the page title in view instead.
  function toTop() {
    setTimeout(function () { window.scrollTo(0, 0); }, 0);
    window.addEventListener('load', function () { window.scrollTo(0, 0); }, { once: true });
  }

  // On pages split across the sidebar, the title names the section shown.
  function syncTitle() {
    if (!doc.body.classList.contains('tabs-in-sidebar') || !TABBED[path]) return;
    var cur = doc.querySelector('#sidebar [aria-current="page"]');
    var h1 = doc.querySelector('#main h1');
    if (!cur || !h1) return;
    var label = cur.getAttribute('data-label') || cur.textContent.trim();
    var parentLink = cur.classList.contains('nav-child') ? cur.closest('.nav-item').querySelector('.nav-link') : null;
    var parent = parentLink ? parentLink.getAttribute('data-label') : '';
    h1.textContent = '';
    if (parent) h1.appendChild(el('span', 'page-crumb', parent + ' › '));
    h1.appendChild(doc.createTextNode(label));
    doc.title = doc.title.replace(/ - [^-]*$/, ' - ' + (parent ? parent + ' › ' : '') + label);
  }

  function setupTabbedPage(tries) {
    if (path === 'ledger') doc.body.classList.add('tabs-in-sidebar');
    if (!TABBED[path] || !$id('tabs')) return;
    doc.body.classList.add('tabs-in-sidebar');
    var t = tabsWidget();
    if (!t) {
      // Some pages build their tabs in a late ready handler; wait for them.
      tries = tries || 0;
      if (tries < 60) setTimeout(function () { setupTabbedPage(tries + 1); }, 50);
      return;
    }
    t.bind('tabsselect', function (e, ui) {
      if (ui && ui.panel && ui.panel.id && location.hash !== '#' + ui.panel.id) {
        history.replaceState(null, '', '#' + ui.panel.id);
        mark();
        syncTitle();
      }
    });
    if (location.hash) {
      selectTab(location.hash);
      toTop();
    } else {
      var current = mark();
      var href = current && current.getAttribute('href');
      if (href && href.indexOf('#') > 0) {
        var hash = href.slice(href.indexOf('#'));
        if (selectTab(hash)) history.replaceState(null, '', hash);
      }
    }
    window.addEventListener('hashchange', function () {
      if (selectTab(location.hash)) window.scrollTo(0, 0);
      mark();  // the title reads the highlighted sidebar entry, so update that first
      syncTitle();
    });
    syncTitle();
  }

  /* ---------- Title + actions in one row ---------- */

  function setupPageHead() {
    var main = $id('main');
    var menu = $id('subhead_menu');
    if (!main || !menu || !menu.querySelector('a')) return;
    var title = main.querySelector('h1');
    if (!title || title.closest('.page-head') || title.closest('.lg-head')) return;
    var head = el('div', 'page-head');
    title.parentNode.insertBefore(head, title);
    head.appendChild(title);
    menu.classList.add('page-actions');
    head.appendChild(menu);
    var sub = $id('subhead');
    if (sub && !sub.textContent.trim() && !sub.querySelector('img, input, a, select')) sub.style.display = 'none';
  }

  /* ---------- Small screens ---------- */

  function setupMobileNav() {
    var app = doc.querySelector('.app');
    var toggle = $id('nav-toggle');
    var scrim = $id('nav-scrim');
    if (!app || !toggle) return;
    function set(open) {
      app.classList.toggle('nav-open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (scrim) scrim.hidden = !open;
    }
    toggle.addEventListener('click', function () { set(!app.classList.contains('nav-open')); });
    if (scrim) scrim.addEventListener('click', function () { set(false); });
    doc.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && app.classList.contains('nav-open')) set(false);
    });
    $id('sidebar').addEventListener('click', function (e) {
      if (e.target.closest('a[href]') && window.matchMedia('(max-width: 900px)').matches) set(false);
    });
  }

  /* ---------- Running now ---------- */

  function setupDock() {
    var dock = $id('dock');
    if (!dock) return;
    var rows = { pp: $id('dock-pp'), search: $id('dock-search'), dl: $id('dock-dl'), mon: $id('dock-monitor'), idle: $id('dock-idle') };
    var importRow = $id('import_indicator');
    var timer = null;

    function show(row, text) {
      if (!row) return;
      row.hidden = !text;
      if (text) row.querySelector('.dock-text').textContent = text;
    }
    function refreshIdle() {
      var busy = ['pp', 'search', 'dl'].some(function (k) { return rows[k] && !rows[k].hidden; });
      if (importRow && importRow.style.display !== 'none') busy = true;
      if (rows.idle) rows.idle.hidden = busy;
    }
    function searchText(s) {
      if (!s) return '';
      var n = (s.waiting || []).length;
      var waiting = n ? ' (' + n + ' waiting)' : '';
      if (s.current) return 'Searching ' + (s.current.name || '') + ' #' + (s.current.number == null ? '?' : s.current.number) + waiting;
      if (s.busy) return 'Checking RSS feeds' + waiting;
      return n ? n + ' queued for search' : '';
    }
    function poll() {
      if (doc.hidden) return;
      fetch('pp_activity', { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          show(rows.pp, d.state === 'Working' ? 'Post-processing' + (d.detail ? ': ' + d.detail : '') : '');
          show(rows.search, searchText(d.search));
          var queued = (d.download_counts || {}).Queued || 0;
          var dl = d.download ? 'Downloading ' + d.download : '';
          if (queued) dl = dl ? dl + ' (' + queued + ' queued)' : queued + ' queued for download';
          show(rows.dl, dl);
          show(rows.mon, d.monitor_enabled ? 'Folder Monitor: ' + (d.monitor_status || 'on') : '');
          refreshIdle();
        })
        .catch(function () { if (timer) { clearInterval(timer); timer = null; } });
    }
    poll();
    timer = setInterval(poll, 20000);
    doc.addEventListener('visibilitychange', function () { if (!doc.hidden && timer) poll(); });
    // Pages with the flow line poll more often: keep the search row in step with it.
    doc.addEventListener('issuarr:flow', function (e) {
      var s = e.detail.now.search;
      show(rows.search, searchText({ current: s.current, busy: s.busy, waiting: new Array(s.waiting) }));
      refreshIdle();
    });
    if (importRow && window.MutationObserver) {
      new MutationObserver(refreshIdle).observe(importRow, { attributes: true, attributeFilter: ['style'] });
    }
  }

  /* ---------- Ctrl K jump menu ---------- */

  var ACTIONS = [
    { label: 'Search for wanted issues now', job: 'search', done: 'Search started' },
    { label: 'Check RSS feeds now', job: 'rss', done: 'RSS check started' },
    { label: 'Run Folder Monitor now', job: 'monitor', done: 'Folder Monitor started' },
    { label: 'Update all series from ComicVine', job: 'updater', done: 'Series update started' },
    { label: 'Refresh this week\'s pull list', job: 'weekly', done: 'Pull list refresh started' },
    { label: 'Check for a new version', job: 'version', done: 'Version check started' },
    { label: 'Restart Issuarr', href: 'restart', confirm: 'Restart Issuarr now?' },
    { label: 'Shut down Issuarr', href: 'shutdown', confirm: 'Shut down Issuarr? It stays off until you start it again.' }
  ];

  function setupJump() {
    var backdrop = $id('jump');
    var input = $id('jump-input');
    var list = $id('jump-list');
    if (!backdrop || !input || !list) return;

    var pages = [];
    doc.querySelectorAll('#sidebar .nav-item').forEach(function (item) {
      var link = item.querySelector(':scope > .nav-link');
      if (!link) return;
      var parent = link.getAttribute('data-label') || link.textContent.trim();
      if (link.getAttribute('href') && link.getAttribute('href') !== '#' && !link.hasAttribute('data-action')) {
        pages.push({ label: parent, href: link.getAttribute('href') });
      }
      item.querySelectorAll('.nav-child').forEach(function (c) {
        pages.push({ label: parent + ' › ' + (c.getAttribute('data-label') || c.textContent.trim()), href: c.getAttribute('href') });
      });
    });

    var options = [];
    var active = 0;
    var series = [];
    var seriesFor = '';
    var seriesTimer = null;
    var lastFocus = null;

    // Every word has to appear; words that start a word in the label rank higher.
    function score(label, q) {
      var l = label.toLowerCase(), total = 0;
      var words = q.split(/\s+/).filter(Boolean);
      for (var k = 0; k < words.length; k++) {
        var i = l.indexOf(words[k]);
        if (i < 0) return 0;
        total += i === 0 || /[\s›(]/.test(l.charAt(i - 1)) ? 2 : 1;
      }
      return total;
    }
    function pick(items, q) {
      if (!q) return items.slice();
      return items.map(function (x) { return { x: x, s: score(x.label, q) }; })
        .filter(function (r) { return r.s; })
        .sort(function (a, b) { return b.s - a.s; })
        .map(function (r) { return r.x; });
    }

    function render() {
      var q = input.value.trim();
      var lq = q.toLowerCase();
      var groups = [];
      if (q && series.length && seriesFor === lq) {
        groups.push({ title: 'In your library', items: series.map(function (s) {
          return { label: s.name + (s.year ? ' (' + s.year + ')' : ''), hint: s.publisher || '', href: 'comicDetails?ComicID=' + encodeURIComponent(s.id) };
        }) });
      }
      var p = pick(pages, lq);
      if (p.length) groups.push({ title: 'Pages', items: p.slice(0, q ? 8 : 40) });
      var a = pick(ACTIONS, lq);
      if (a.length) groups.push({ title: 'Actions', items: a });

      list.textContent = '';
      options = [];
      groups.forEach(function (g, gi) {
        var head = el('li', 'jump-group', g.title);
        head.setAttribute('role', 'presentation');
        head.id = 'jump-g' + gi;
        list.appendChild(head);
        g.items.forEach(function (item) {
          var li = el('li', 'jump-opt');
          li.setAttribute('role', 'option');
          li.id = 'jump-o' + options.length;
          li.appendChild(el('span', null, item.label));
          if (item.hint) li.appendChild(el('span', 'jump-hint', item.hint));
          li.addEventListener('mousemove', function () { setActive(options.indexOf(item)); });
          li.addEventListener('click', function () { run(item); });
          item.node = li;
          options.push(item);
          list.appendChild(li);
        });
      });
      if (!options.length) list.appendChild(el('li', 'jump-empty', 'Nothing in your library or menus matches. To add a new series, use Add series.'));
      setActive(Math.min(active, options.length - 1));
    }

    function setActive(i) {
      active = Math.max(0, i);
      options.forEach(function (o, j) { o.node.setAttribute('aria-selected', j === active ? 'true' : 'false'); });
      var cur = options[active];
      if (cur) {
        input.setAttribute('aria-activedescendant', cur.node.id);
        cur.node.scrollIntoView({ block: 'nearest' });
      } else {
        input.removeAttribute('aria-activedescendant');
      }
    }

    function run(item) {
      if (item.job) {
        close();
        fetch('schedulerForceCheck?jobid=' + encodeURIComponent(item.job), { credentials: 'same-origin' })
          .then(function (r) { toast(r.ok ? item.done : 'That didn\'t work. Check the log.', r.ok); })
          .catch(function () { toast('That didn\'t work. Check the log.', false); });
        return;
      }
      if (item.confirm && !window.confirm(item.confirm)) return;
      location.href = item.href;
    }

    function fetchSeries() {
      var q = input.value.trim().toLowerCase();
      if (q.length < 2) { series = []; seriesFor = ''; return; }
      fetch('jump_series?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (rows) {
          if (input.value.trim().toLowerCase() !== q) return;
          series = rows || [];
          seriesFor = q;
          active = 0;
          render();
        })
        .catch(function () {});
    }

    function open(prefill) {
      lastFocus = doc.activeElement;
      backdrop.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      input.value = prefill || '';
      active = 0;
      series = [];
      render();
      input.focus();
    }
    function close() {
      backdrop.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    input.addEventListener('input', function () {
      active = 0;
      render();
      clearTimeout(seriesTimer);
      seriesTimer = setTimeout(fetchSeries, 160);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setActive((active + 1) % Math.max(options.length, 1)); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((active - 1 + options.length) % Math.max(options.length, 1)); }
      else if (e.key === 'Enter') { e.preventDefault(); if (options[active]) run(options[active]); }
      else if (e.key === 'Escape') { e.preventDefault(); close(); }
      else if (e.key === 'Tab') { e.preventDefault(); }
    });
    backdrop.addEventListener('mousedown', function (e) { if (e.target === backdrop) close(); });
    doc.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        if (backdrop.hidden) open(); else close();
      }
    });
    doc.querySelectorAll('[data-action="jump"]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); open(); });
    });
  }

  /* ---------- Settings › Appearance ---------- */

  var CSS_VARS = [
    ['--ink', 'Page background'], ['--surface', 'Panels and tables'], ['--raised', 'Buttons, hover'],
    ['--line', 'Borders, empty bar'], ['--text', 'Text and main buttons'], ['--muted', 'Secondary text'],
    ['--have', 'Downloaded'], ['--wanted', 'Wanted'], ['--snatched', 'Snatched, in progress'],
    ['--failed', 'Failed'], ['--ignored', 'Ignored'], ['--radius', 'Corner rounding'],
    ['--font-display', 'Titles'], ['--font-body', 'Everything else'], ['--font-mono', 'Numbers and paths']
  ];

  function setupAppearance() {
    var area = $id('custom_css');
    if (!area) return;
    var check = $id('css-check');
    var preview = $id('css-preview');
    var varsBody = $id('css-vars-body');
    var saved = $id('custom-css');
    var timer = null;

    doc.querySelectorAll('input[name="ui_theme"]').forEach(function (r) {
      r.addEventListener('change', function () {
        if (r.value === 'system') doc.documentElement.removeAttribute('data-theme');
        else doc.documentElement.setAttribute('data-theme', r.value);
        drawVars();
      });
    });

    function drawVars() {
      if (!varsBody) return;
      var style = getComputedStyle(doc.documentElement);
      var text = area.value;
      varsBody.textContent = '';
      CSS_VARS.forEach(function (v) {
        var value = style.getPropertyValue(v[0]).trim();
        if (v[0].indexOf('--font') === 0) value = value.split(',')[0].replace(/["']/g, '');
        var tr = el('tr');
        if (new RegExp(v[0].replace(/-/g, '\\-') + '\\s*:').test(text)) tr.className = 'is-set';
        var sw = el('td', 'swatch');
        var chip = el('span');
        if (/^(#|rgb|hsl|color-mix)/i.test(value)) chip.style.background = value;
        else chip.style.borderStyle = 'dashed';
        sw.appendChild(chip);
        var name = el('td');
        name.appendChild(el('code', null, v[0]));
        tr.appendChild(sw);
        tr.appendChild(name);
        tr.appendChild(el('td', null, v[1]));
        tr.appendChild(el('td', 'value', value.length > 28 ? value.slice(0, 26) + '…' : value));
        varsBody.appendChild(tr);
      });
    }

    function applyPreview() {
      var live = $id('css-live');
      if (preview && preview.checked) {
        if (!live) {
          live = el('style');
          live.id = 'css-live';
          doc.head.appendChild(live);
        }
        live.textContent = area.value;
        if (saved) saved.disabled = true;
      } else {
        if (live) live.remove();
        if (saved) saved.disabled = false;
      }
    }

    function update() {
      var text = area.value;
      var opens = (text.match(/{/g) || []).length;
      var closes = (text.match(/}/g) || []).length;
      var lines = text ? text.split('\n').length : 0;
      var set = CSS_VARS.filter(function (v) { return new RegExp(v[0].replace(/-/g, '\\-') + '\\s*:').test(text); }).length;
      var ok = opens === closes;
      area.classList.toggle('is-bad', !ok);
      if (check) {
        check.className = 'css-check' + (!text.trim() ? '' : ok ? ' is-ok' : ' is-bad');
        check.textContent = !text.trim() ? 'Empty' : ok
          ? 'Looks valid · ' + lines + (lines === 1 ? ' line' : ' lines') + ' · ' + set + ' of ' + CSS_VARS.length + ' variables set'
          : 'Check your braces: ' + opens + ' { and ' + closes + ' }';
      }
      applyPreview();
      drawVars();
    }

    area.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(update, 150); });
    area.addEventListener('keydown', function (e) {
      if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
        e.preventDefault();
        var s = area.selectionStart;
        area.setRangeText('  ', s, area.selectionEnd, 'end');
        clearTimeout(timer); timer = setTimeout(update, 150);
      }
    });
    if (preview) preview.addEventListener('change', update);

    var file = $id('css-file');
    var importBtn = $id('css-import');
    if (file && importBtn) {
      importBtn.addEventListener('click', function () { file.click(); });
      file.addEventListener('change', function () {
        var f = file.files && file.files[0];
        if (!f) return;
        var reader = new FileReader();
        reader.onload = function () { area.value = String(reader.result || ''); update(); toast('Loaded ' + f.name + '. Save to keep it.'); };
        reader.readAsText(f);
        file.value = '';
      });
    }
    var exportBtn = $id('css-export');
    if (exportBtn) exportBtn.addEventListener('click', function () {
      var url = URL.createObjectURL(new Blob([area.value], { type: 'text/css' }));
      var a = el('a');
      a.href = url;
      a.download = 'issuarr-custom.css';
      doc.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    });
    var resetBtn = $id('css-reset');
    if (resetBtn) resetBtn.addEventListener('click', function () {
      if (area.value.trim() && !window.confirm('Clear the editor? Nothing changes until you save.')) return;
      area.value = '/* Loaded after the built-in theme, on every page. */\n:root {\n  \n}\n';
      update();
      area.focus();
    });
    update();
  }

  /* ---------- Add series: searches ComicVine, never the library ---------- */

  function setupAddSeries() {
    var box = $id('add-series');
    var input = $id('add-series-input');
    if (!box || !input) return;
    var last = null;
    function open() {
      last = doc.activeElement;
      box.hidden = false;
      input.value = '';
      input.focus();
    }
    function close() {
      box.hidden = true;
      if (last && last.focus) last.focus();
    }
    doc.querySelectorAll('[data-action="add"]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); open(); });
    });
    box.addEventListener('mousedown', function (e) { if (e.target === box) close(); });
    box.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); close(); } });
  }

  // "More" menus (details.menu) close on an outside click, on Escape, and after a choice.
  function setupMenus() {
    function closeAll(except) {
      doc.querySelectorAll('details.menu[open]').forEach(function (m) { if (m !== except) m.open = false; });
    }
    doc.addEventListener('click', function (e) {
      var inMenu = e.target.closest && e.target.closest('details.menu');
      closeAll(inMenu);
      if (inMenu && e.target.closest('.menu-list .btn')) inMenu.open = false;
    });
    doc.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      var open = doc.querySelector('details.menu[open]');
      if (!open) return;
      open.open = false;
      var s = open.querySelector('summary');
      if (s) s.focus();
    });
  }

  function start() {
    setupMenus();
    setupTabbedPage();
    setupPageHead();
    setupMobileNav();
    setupDock();
    setupJump();
    setupAddSeries();
    setupAppearance();
    window.addEventListener('hashchange', mark);
  }

  if ($) $(start);
  else doc.addEventListener('DOMContentLoaded', start);
})();
