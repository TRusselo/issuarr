/* Calendar › This week: the pull list, filtered to what you follow. */
(function () {
  'use strict';

  var STORE = 'issuarr-calendar';
  var list = document.getElementById('cal-list');
  if (!list) return;
  var rows = Array.prototype.slice.call(list.querySelectorAll('.release'));
  var heads = Array.prototype.slice.call(list.querySelectorAll('[data-pub-head]'));
  var st = { scope: list.getAttribute('data-default') || 'following', q: '' };
  try {
    var saved = localStorage.getItem(STORE);
    if (saved) st.scope = saved;
  } catch (e) {}

  function I() { return window.Issuarr; }

  function apply() {
    var q = st.q.toLowerCase();
    var shown = 0;
    var perPub = {};
    rows.forEach(function (r) {
      var ok = (st.scope === 'all' || (st.scope === 'following' && r.getAttribute('data-follow') === '1') ||
                (st.scope === 'wanted' && r.getAttribute('data-wanted') === '1')) &&
               (!q || r.getAttribute('data-text').indexOf(q) > -1);
      r.hidden = !ok;
      if (ok) { shown++; perPub[r.getAttribute('data-pub')] = true; }
    });
    heads.forEach(function (h) { h.hidden = !perPub[h.getAttribute('data-pub-head')]; });
    document.querySelectorAll('#cal-tabs [data-scope]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-scope') === st.scope));
    });
    var empty = document.getElementById('cal-empty');
    empty.hidden = shown > 0;
    if (!shown) {
      if (!rows.length) empty.textContent = 'There is no pull list for this week yet. Try Recreate pull list in the ⋯ menu.';
      else if (q) empty.textContent = 'Nothing matches.';
      else if (st.scope === 'following') empty.textContent = 'Nothing from series you follow this week. Switch to Everything to see the whole list.';
      else empty.textContent = 'Nothing wanted from this week.';
    }
  }

  function run(btn) {
    var url = btn.getAttribute('data-act');
    var row = btn.closest('.release');
    btn.disabled = true;
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        I().toast(btn.getAttribute('data-done') || 'Done.');
        var menu = btn.closest('details.menu');
        if (menu) menu.open = false;
        if (btn.hasAttribute('data-reload')) { setTimeout(function () { location.reload(); }, 900); return; }
        if (row) {
          var pill = row.querySelector('[data-pill]');
          if (pill && btn.getAttribute('data-after')) {
            pill.textContent = btn.getAttribute('data-after');
            pill.className = 'status ' + (btn.getAttribute('data-after-class') || '');
          }
          row.querySelectorAll('.release-actions .btn').forEach(function (b) { b.disabled = true; });
        } else {
          btn.disabled = false;
        }
      })
      .catch(function () {
        btn.disabled = false;
        I().toast('That didn\'t work. Check the log.', false);
      });
  }

  document.addEventListener('click', function (e) {
    var tab = e.target.closest('#cal-tabs [data-scope]');
    if (tab) {
      st.scope = tab.getAttribute('data-scope');
      try { localStorage.setItem(STORE, st.scope); } catch (err) {}
      apply();
      return;
    }
    var act = e.target.closest('[data-act]');
    if (act && !act.disabled) { run(act); return; }
  });

  var qTimer = null;
  document.getElementById('cal-q').addEventListener('input', function (e) {
    clearTimeout(qTimer);
    qTimer = setTimeout(function () { st.q = e.target.value.trim(); apply(); }, 120);
  });

  // The weekly folder is a setting that only lives here.
  var wf = document.getElementById('cal-weekfolder');
  if (wf) {
    wf.addEventListener('change', function () {
      fetch('MassWeeklyDownload?weekfolder=' + (wf.checked ? 1 : 0), { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          I().toast(wf.checked ? 'Downloads from the pull list will also go to a weekly folder.' : 'Weekly folder turned off.');
          setTimeout(function () { location.reload(); }, 900);
        })
        .catch(function () { wf.checked = !wf.checked; I().toast('That didn\'t work. Check the log.', false); });
    });
  }

  /* ---- Add every series this week (mass add) ---- */
  var pubsReady = false;
  function setupPublishers() {
    if (pubsReady || !window.jQuery || !jQuery.fn.selectize) return;
    pubsReady = true;
    var weeknumber = document.getElementById('weeknumber').value;
    var year = document.getElementById('year').value;
    jQuery.getJSON('get_the_pubs').always(function (saved) {
      var options = Array.isArray(saved) ? saved : [];
      jQuery('#publishers').selectize({
        valueField: 'name', labelField: 'name', searchField: ['name'], create: false, preload: true,
        options: options, items: options.map(function (o) { return o.name; }),
        render: { option: function (item, escape) { return '<div>' + escape(item.name) + '</div>'; } },
        load: function (query, callback) {
          jQuery.ajax({ type: 'GET', url: 'weekly_publisherlisting', data: { weeknumber: weeknumber, year: year }, dataType: 'json',
                        error: function () { callback(); }, success: function (res) { callback(res); } });
        }
      });
    });
  }

  var massBtn = document.getElementById('cal-mass-add');
  if (massBtn) {
    massBtn.addEventListener('click', function () {
      var menu = massBtn.closest('details.menu');
      if (menu) menu.open = false;
      setupPublishers();
      jQuery('#publisher_dialog').dialog({ modal: true, width: Math.min(560, window.innerWidth - 32) });
    });
  }
  var pubBtn = document.getElementById('pub_button');
  if (pubBtn) {
    pubBtn.addEventListener('click', function () {
      // The server reads the selectize state off the serialized select element.
      var publishers = window.CircularJSON ? CircularJSON.stringify(document.getElementsByName('publishers[]')) : '[]';
      var body = new URLSearchParams({ publishers: publishers, weeknumber: document.getElementById('weeknumber').value,
                                       year: document.getElementById('year').value, mass_auto: document.getElementById('auto_mass_add').checked });
      pubBtn.disabled = true;
      fetch('dump_that_shizzle', { method: 'POST', credentials: 'same-origin', body: body })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          I().toast('Adding ' + d.series_count + ' series from ' + d.publisher_count + ' publishers.');
          jQuery('#publisher_dialog').dialog('close');
        })
        .catch(function () { I().toast('That didn\'t work. Check the log.', false); })
        .then(function () { pubBtn.disabled = false; });
    });
  }

  // Links from Upcoming land on a release by its anchor; show everything so it's visible.
  if (location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)))) st.scope = 'all';
  apply();
})();
