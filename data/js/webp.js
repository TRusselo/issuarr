(function () {
  var $id = function (id) { return document.getElementById(id); };
  var form = $id('wp-form'), st = {}, timer = null, dirty = false;

  function gb(n) {
    if (n == null) return '?';
    if (n >= 1e12) return (n / 1e12).toFixed(2) + ' TB';
    if (n >= 1e9) return (n / 1e9).toFixed(1) + ' GB';
    return (n / 1e6).toFixed(0) + ' MB';
  }
  function num(n) { return (n || 0).toLocaleString(); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function dur(s) {
    s = Math.max(0, Math.round(s));
    var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
    return h ? h + ' h ' + m + ' min' : m ? m + ' min' : s + ' s';
  }
  function tile(n, label, sub, colour) {
    return '<div class="lg-tile" aria-pressed="true" style="--c:' + (colour || 'var(--t-fg)') + ';cursor:default"><b>' + n + '</b><span>' + label + '</span>' + (sub ? '<small>' + sub + '</small>' : '') + '</div>';
  }
  function post(url, data) {
    return fetch(url, { method: 'POST', body: new URLSearchParams(data || {}), credentials: 'same-origin' }).then(function (r) { return r.json(); });
  }
  function showError(msg) {
    var box = $id('wp-error');
    box.textContent = msg || '';
    box.hidden = !msg;
  }
  function lockForm(on) {
    Array.prototype.forEach.call(form.elements, function (el) { el.disabled = on; });
    if (!on) form.elements.backup_dir.disabled = form.elements.no_backup.checked;
  }
  function formData() {
    var d = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name) return;
      if (el.type === 'checkbox') { if (el.checked) d[el.name] = '1'; }
      else d[el.name] = el.value;
    });
    return d;
  }

  function render() {
    var busy = st.state === 'previewing' || st.state === 'running';
    lockForm(busy);
    $id('wp-preview').disabled = busy;
    $id('wp-preview').textContent = st.state === 'previewing' ? 'Scanning…' : 'Preview';
    if (st.available === false) showError('This install of Pillow can\'t write WebP, so nothing can be converted.');
    else if (st.error && st.state === 'idle') showError(st.error);

    if (st.state === 'previewing') {
      $id('wp-hint').textContent = 'Reading ' + num(st.scanned) + ' files… ' + (st.current ? st.current.split('/').slice(-1)[0] : '');
    } else if (!busy) {
      $id('wp-hint').textContent = 'Preview first: it only reads your files. Your choices are kept for next time when you start converting.';
    }

    renderMemory();
    renderGradual();
    var res = $id('wp-result');
    res.hidden = st.state !== 'previewed';
    if (st.state === 'previewed') renderPreview();

    var run = $id('wp-run');
    run.hidden = ['running', 'finished', 'stopped'].indexOf(st.state) < 0;
    if (!run.hidden) renderRun();
    form.hidden = !run.hidden;
  }

  function renderMemory() {
    var m = st.memory || {}, parts = [];
    if (m.converted) parts.push(num(m.converted) + ' converted (' + gb(m.saved) + ' saved)');
    if (m['nothing to gain']) parts.push(num(m['nothing to gain']) + ' with nothing to gain');
    if (m['already webp']) parts.push(num(m['already webp']) + ' already WebP');
    if (m.failed) parts.push(num(m.failed) + ' that failed a check');
    if (m.damaged) parts.push(num(m.damaged) + ' damaged (listed in <a href="needsAttention">Needs attention</a>)');
    $id('wp-memory-text').innerHTML = (parts.length ? 'Files looked at so far: ' + parts.join(', ') + '. ' : '') +
      'Each file is remembered and isn\'t opened again until it changes. The largest files go first.';
    var re = $id('wp-recheck');
    re.hidden = !m['nothing to gain'];
    re.disabled = st.state === 'previewing' || st.state === 'running';
  }

  var STOPPED = {
    'done for tonight': 'Did the whole night\'s share.',
    'the window closed': 'Stopped at the end of the window.',
    'nothing left to convert': 'Nothing left to convert.',
    'turned off': 'Stopped when it was turned off.'
  };
  function nightLine(n) {
    return num(n.done) + ' of ' + num(n.quota) + ' issues looked at: ' + num(n.converted) + ' converted (' + gb(n.saved) + ' saved), ' +
      num(n.skipped) + ' skipped' + (n.failed ? ', ' + num(n.failed) + ' failed a check' : '') +
      (n.damaged ? ', <a href="needsAttention">' + num(n.damaged) + ' damaged</a>' : ', none damaged') + '.';
  }
  function renderGradual() {
    var g = st.gradual || {}, lines = [];
    if (g.state === 'running') lines.push('<b>Converting now</b>' + (g.current ? ': ' + esc(g.current) : '') + '.');
    else if (g.state === 'waiting' && g.why) lines.push('<b>Waiting while ' + esc(g.why) + '.</b> It carries on once they finish.');
    if (g.tonight) lines.push('Tonight so far, ' + nightLine(g.tonight));
    if (g.last) {
      var day = new Date(g.last.night + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' });
      lines.push('Night of ' + esc(day) + ': ' + nightLine(g.last) + (g.last.note ? ' ' + esc(STOPPED[g.last.note] || 'Stopped: ' + g.last.note + '.') : ''));
    }
    if (!lines.length && g.settings && g.settings.enabled) lines.push('Nothing converted yet. It starts at ' + esc(g.settings.start) + '.');
    $id('wp-g-night').innerHTML = lines.map(function (l) { return '<span>' + l + '</span>'; }).join('<br>');
  }

  function renderPreview() {
    var o = st.opts || {};
    var room = st.backup_free == null ? '' : gb(st.backup_free) + ' free in the holding folder';
    $id('wp-tiles').innerHTML =
      tile(num(st.count), 'files to convert', gb(st.bytes) + ' now', 'var(--lg-after)') +
      tile('~' + gb(st.est_saving), 'estimated saving', st.bytes ? Math.round(100 * st.est_saving / st.bytes) + '% from a sample of page quality' : '', 'var(--lg-done)') +
      tile(num(st.too_old), 'dated before ' + esc(o.since || '-'), 'left alone', 'var(--lg-before)') +
      tile(num(st.no_date), 'with no date', o.unknown ? 'included' : 'left alone', 'var(--lg-before)') +
      tile(num(st.already), 'already WebP', 'skipped', 'var(--lg-before)') +
      tile(num(st.remembered), 'looked at before', 'not opened again', 'var(--lg-before)') +
      tile(num(st.other), '.cbr / .cb7 / .pdf', 'not converted', 'var(--lg-before)');
    var lines = [];
    lines.push('<p>Folder <code>' + esc(o.root) + '</code> &middot; WebP quality ' + o.quality + ' &middot; JPEG pages below quality ' + o.min_q + ' left as they are &middot; ' + o.threads + ' CPU threads, ' + o.files + ' files at once' + (o.limit ? ' &middot; <b>stops after ' + num(o.limit) + ' files</b>' : '') + '</p>');
    if (o.limit && st.count >= o.limit) lines.push('<p>Found the ' + num(st.count) + ' largest of ' + num(st.scanned) + ' files that match, then stopped. The counts above only cover the files looked at; set "Stop after" to 0 to see the whole library.</p>');
    if (o.no_backup) lines.push('<p class="wp-danger"><b>Originals will not be kept.</b> The conversion can\'t be undone.</p>');
    else lines.push('<p>Originals go to <code>' + esc(o.backup_dir) + '</code>' + (room ? ' (' + room + ', needs about ' + gb(st.bytes) + ')' : '') + '.</p>');
    if (st.examples && st.examples.length) lines.push('<details><summary>First files</summary><ul>' + st.examples.map(function (e) { return '<li><code>' + esc(e) + '</code></li>'; }).join('') + '</ul></details>');
    $id('wp-detail').innerHTML = lines.join('');
    var go = $id('wp-go');
    go.disabled = !st.count || dirty;
    go.textContent = 'Convert ' + num(st.count) + ' files…';
    $id('wp-go-text').textContent = dirty ? 'You changed the options - preview again.' : (st.count ? 'Nothing has been changed yet.' : 'Nothing matches these options.');
  }

  function renderRun() {
    var pct = st.total ? Math.round(100 * st.done / st.total) : 0;
    $id('wp-bar-fill').style.width = pct + '%';
    var elapsed = ((st.finished || Date.now() / 1000) - st.started), left = st.done ? elapsed / st.done * (st.total - st.done) : null;
    $id('wp-run-tiles').innerHTML =
      tile(num(st.done) + ' / ' + num(st.total), 'files done', pct + '%', 'var(--lg-after)') +
      tile(num(st.converted), 'converted', '', 'var(--lg-done)') +
      tile(gb(st.saved), 'saved', st.before ? Math.round(100 * st.saved / st.before) + '% of the converted files' : '', 'var(--lg-done)') +
      tile(num(st.skipped), 'skipped', 'nothing to gain', 'var(--lg-before)') +
      tile(num((st.failed || 0) + (st.damaged || 0)), 'left unchanged', st.damaged ? num(st.damaged) + ' damaged, listed in Needs attention' : 'a check failed',
           st.failed || st.damaged ? 'var(--lg-gap)' : 'var(--lg-before)');
    $id('wp-current').textContent = st.state === 'running' && st.current ? 'Converting ' + st.current : '';
    $id('wp-errors').innerHTML = (st.errors || []).map(function (e) { return '<li>' + esc(e) + '</li>'; }).join('');
    var running = st.state === 'running';
    $id('wp-stop').hidden = !running;
    $id('wp-stop').disabled = !!st.stopping;
    $id('wp-done').hidden = running;
    $id('wp-run-text').textContent = running
      ? (st.stopping ? 'Stopping after this file…' : 'Running for ' + dur(elapsed) + (left != null ? ', about ' + dur(left) + ' left' : ''))
      : (st.state === 'stopped' ? 'Stopped' : 'Finished') + ' after ' + dur(elapsed) + '. Details are in the Mylar log ([WEBP]).';
  }

  // Show the form's current "how" choices in the preview, in place of the ones it ran with.
  function syncHow() {
    var d = formData(), o = st.opts = Object.assign({}, st.opts);
    ['quality', 'min_q', 'threads', 'files'].forEach(function (k) { if (d[k] !== '' && !isNaN(d[k])) o[k] = +d[k]; });
    o.no_backup = !!d.no_backup;
    var dir = o.no_backup ? '' : (d.backup_dir || '').trim();
    if (dir !== o.backup_dir) st.backup_free = null;
    o.backup_dir = dir;
  }

  function poll() {
    clearTimeout(timer);
    if (document.hidden) return;
    fetch('webp_status', { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (s) {
      st = s;
      if (st.state === 'previewed') syncHow();
      render();
      if (s.state === 'previewing' || s.state === 'running') timer = setTimeout(poll, 2000);
      else if (s.gradual && (s.gradual.state === 'running' || s.gradual.state === 'waiting')) timer = setTimeout(poll, 10000);
    }).catch(function () { timer = setTimeout(poll, 5000); });
  }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    showError('');
    var d = formData();
    if (!d.no_backup && !d.backup_dir.trim()) { showError('Choose a holding folder for the originals, or tick the box to not keep them.'); return; }
    dirty = false;
    post('webp_preview', d).then(function (r) {
      if (r.error) { showError(r.error); return; }
      st = r.status; render(); poll();
    });
  });
  // Only the choices about which files to convert need a new preview. The others (quality, threads,
  // originals) just update this one, and go with the Convert request.
  var WHICH = { root: 1, since: 1, unknown: 1, limit: 1 };
  function edited(e) {
    if (st.state !== 'previewed' || !e.target.name) return;
    if (WHICH[e.target.name]) dirty = true;
    else syncHow();
    renderPreview();
  }
  form.addEventListener('input', edited);
  form.addEventListener('change', edited);
  form.elements.no_backup.addEventListener('change', function () { form.elements.backup_dir.disabled = this.checked; });

  function reset() {
    post('webp_reset').then(function (r) { st = r.status; dirty = false; showError(''); render(); });
  }
  $id('wp-reset').addEventListener('click', reset);
  $id('wp-recheck').addEventListener('click', function () {
    var n = (st.memory || {})['nothing to gain'] || 0;
    if (!confirm('Look again at the ' + num(n) + ' files that had nothing to gain? Nothing is changed until you run a conversion.')) return;
    post('webp_recheck').then(function (r) {
      st = r.status; render();
      window.Issuarr.toast(num(r.reopened) + ' files will be looked at again.', true);
    });
  });
  $id('wp-done').addEventListener('click', reset);
  $id('wp-stop').addEventListener('click', function () {
    post('webp_stop').then(function (r) { st = r.status; st.stopping = true; render(); });
  });

  $id('wp-g-save').addEventListener('click', function () {
    var d = formData(), btn = this;
    d.enabled = $id('wp-g-on').checked ? '1' : '';
    d.per_night = $id('wp-g-per').value;
    d.start = $id('wp-g-start').value;
    d.end = $id('wp-g-end').value;
    var hint = $id('wp-g-hint');
    function say(msg, bad) { hint.textContent = msg; hint.classList.toggle('wp-danger', !!bad); }
    if (d.enabled && !d.no_backup && !(d.backup_dir || '').trim()) {
      say('Choose a holding folder for the originals above, or tick the box to not keep them.', true);
      return;
    }
    btn.disabled = true;
    post('webp_gradual', d).then(function (r) {
      btn.disabled = false;
      if (r.error) { say(r.error, true); return; }
      st = r.status; render(); poll();
      say(d.enabled ? 'Saved. It runs each night between ' + d.start + ' and ' + d.end + '.' : 'Saved. It\'s turned off.');
    }).catch(function () { btn.disabled = false; say('That didn\'t save. Check the log.', true); });
  });

  var c1 = $id('wp-confirm1'), c2 = $id('wp-confirm2'), input = $id('wp-c2-input');
  [c1, c2].forEach(function (d) {
    d.querySelectorAll('[data-close]').forEach(function (b) { b.addEventListener('click', function () { d.close(); }); });
  });
  $id('wp-go').addEventListener('click', function () {
    var o = st.opts || {};
    if (!o.no_backup && !o.backup_dir) { showError('Choose a holding folder for the originals, or tick the box to not keep them.'); return; }
    showError('');
    $id('wp-c1-body').innerHTML =
      '<p><b>' + num(st.count) + ' files</b> (' + gb(st.bytes) + ') under <code>' + esc(o.root) + '</code> will have their pages re-encoded as WebP quality ' + o.quality + ' and be replaced in place.</p>' +
      (o.no_backup ? '<p class="wp-danger"><b>The originals will be deleted as each file is replaced. This can\'t be undone.</b></p>'
                   : '<p>Each original is copied to <code>' + esc(o.backup_dir) + '</code> first. Delete that folder yourself once you\'re happy with the results.</p>') +
      '<p>Pause Kavita\'s folder watching first. You can stop at any time; files already converted stay converted.</p>';
    c1.showModal();
  });
  $id('wp-c1-next').addEventListener('click', function () {
    c1.close();
    $id('wp-c2-count').textContent = String(st.count);
    $id('wp-c2-body').textContent = (st.opts && st.opts.no_backup ? 'Without a copy of the originals, ' : '') + 'This changes ' + num(st.count) + ' files in your library.';
    input.value = '';
    $id('wp-c2-start').disabled = true;
    c2.showModal();
    input.focus();
  });
  input.addEventListener('input', function () { $id('wp-c2-start').disabled = input.value.trim() !== String(st.count); });
  $id('wp-c2-start').addEventListener('click', function () {
    var btn = this;
    btn.disabled = true;
    var d = formData(), body = { token: st.token, confirm: input.value.trim() };
    ['quality', 'min_q', 'threads', 'files', 'backup_dir', 'no_backup'].forEach(function (k) { if (d[k] != null) body[k] = d[k]; });
    post('webp_start', body).then(function (r) {
      c2.close();
      if (r.error) { showError(r.error); poll(); return; }
      showError('');
      st = r.status; render(); poll();
    });
  });

  poll();
})();
