/* Tasks > Jobs: schedule, workers and post-processing status. */
(function () {
  'use strict';

  var data = window.tasksInitial || { jobs: [], queues: [] };
  var timer = null;

  function $id(id) { return document.getElementById(id); }
  function I() { return window.Issuarr; }

  function statusClass(s) {
    if (s === 'Running') return 'is-snatched is-running';
    if (s === 'Paused') return 'is-ignored';
    return 'is-idle';
  }

  function renderJobs() {
    var tb = $id('jobs-table').tBodies[0];
    var esc = I().esc;
    if (tb.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return;
    if (!data.jobs.length) {
      tb.innerHTML = '<tr><td colspan="6" class="empty-state">No scheduled jobs yet. They appear after the first start-up.</td></tr>';
      return;
    }
    tb.innerHTML = data.jobs.map(function (j) {
      var paused = j.status === 'Paused';
      var every = j.minutes != null
        ? '<label class="nowrap"><input type="number" class="inline-num" min="' + esc(j.min_minutes) + '" value="' + esc(j.minutes) +
          '" data-job="' + esc(j.jobname) + '" aria-label="' + esc(j.jobname) + ' runs every, in minutes"> min</label>'
        : esc(String(j.interval || '-').replace(/ mins$/, ' min'));
      var next = paused || !j.next_ts ? '<span class="muted">-</span>'
        : esc(I().relTime(j.next_ts)) + ' <span class="muted">· ' + esc(I().clock(j.next_ts)) + '</span>';
      var last = j.prev_ts ? '<span title="' + esc(I().clock(j.prev_ts)) + '">' + esc(I().relTime(j.prev_ts)) + '</span>' : '<span class="muted">never</span>';
      var actions = (j.force ? '<button type="button" class="btn btn-sm" data-run="' + esc(j.force) + '" data-name="' + esc(j.jobname) + '">Run now</button>' : '') +
        '<button type="button" class="btn btn-sm btn-ghost" data-toggle="' + esc(j.jobname) + '" data-mode="' + (paused ? 'resume' : 'pause') + '">' + (paused ? 'Resume' : 'Pause') + '</button>';
      return '<tr><td><b>' + esc(j.jobname) + '</b></td>' +
        '<td><span class="status ' + statusClass(j.status) + '">' + esc(j.status || 'Unknown') + '</span></td>' +
        '<td>' + every + '</td><td class="nowrap">' + next + '</td><td class="nowrap">' + last + '</td>' +
        '<td class="actions">' + actions + '</td></tr>';
    }).join('');
  }

  function renderWorkers() {
    var tb = $id('workers-table').tBodies[0];
    var esc = I().esc;
    if (!data.queues.length) {
      tb.innerHTML = '<tr><td colspan="3" class="empty-state">No workers reported.</td></tr>';
      return;
    }
    tb.innerHTML = data.queues.map(function (q) {
      var cls = q.state === 'Up' ? 'is-have' : q.state === 'Down' ? 'is-failed' : 'is-idle';
      return '<tr><td class="mono">' + esc(q.name) + '</td><td class="num mono">' + esc(q.size) + '</td>' +
        '<td><span class="status ' + cls + '">' + esc(q.state) + '</span></td></tr>';
    }).join('');
  }

  function render() { renderJobs(); renderWorkers(); }

  function refresh() {
    return fetch('tasks_data', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { data = d; render(); })
      .catch(function () {});
  }

  function get(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    });
  }

  $id('jobs-table').addEventListener('click', function (e) {
    var run = e.target.closest('[data-run]');
    var tog = e.target.closest('[data-toggle]');
    if (run) {
      run.disabled = true;
      get('schedulerForceCheck?jobid=' + encodeURIComponent(run.getAttribute('data-run')))
        .then(function () { I().toast(run.getAttribute('data-name') + ' started'); })
        .catch(function () { I().toast('Couldn\'t start ' + run.getAttribute('data-name') + '. Check the log.', false); })
        .then(function () { setTimeout(refresh, 1500); });
    } else if (tog) {
      var job = tog.getAttribute('data-toggle');
      var mode = tog.getAttribute('data-mode');
      tog.disabled = true;
      get('jobmanage?job=' + encodeURIComponent(job) + '&mode=' + mode)
        .then(function () { I().toast(job + (mode === 'pause' ? ' paused' : ' resumed')); })
        .catch(function () { I().toast('Couldn\'t ' + mode + ' ' + job + '. Check the log.', false); })
        .then(refresh);
    }
  });

  $id('jobs-table').addEventListener('change', function (e) {
    var input = e.target.closest('input[data-job]');
    if (!input) return;
    var job = input.getAttribute('data-job');
    fetch('job_interval?job=' + encodeURIComponent(job) + '&minutes=' + encodeURIComponent(input.value), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (r) {
        I().toast(r.ok ? (r.note || job + ' now runs every ' + r.minutes + ' minutes') : r.error, !!r.ok);
        input.blur();
        refresh();
      })
      .catch(function () { I().toast('Couldn\'t change ' + job + '. Check the log.', false); });
  });

  function ppRefresh() {
    if (document.hidden) return;
    fetch('pp_activity', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        var working = d.state === 'Working';
        var state = $id('pp-state');
        state.className = 'status ' + (working ? 'is-snatched is-running' : 'is-idle');
        state.textContent = d.state || 'Idle';
        $id('pp-detail').textContent = working ? (d.detail || 'Working') + (d.since ? ' (started ' + I().relTime(d.since) + ')' : '') : 'Nothing';
        var dl = $id('pp-download');
        var queued = (d.download_counts || {}).Queued;
        dl.textContent = '';
        if (d.download) {
          var a = document.createElement('a');
          a.href = 'queueManage';
          a.textContent = d.download + (queued ? ' (' + queued + ' queued)' : '');
          dl.appendChild(a);
        } else {
          dl.textContent = 'Nothing' + (queued ? ' (' + queued + ' queued)' : '');
        }
        var mon = $id('pp-monitor');
        if (d.monitor_enabled) {
          mon.textContent = (d.monitor_status || 'On') + ' - checks ' + (d.monitor_folder || 'the folder') + ' every ' + d.interval + ' min';
        } else {
          mon.innerHTML = 'Off. Turn it on in <a href="config#tabs-5">Settings › Files &amp; post-processing</a>.';
        }
        $id('pp-last').textContent = d.last_at ? I().relTime(d.last_at) + (d.last ? ' - ' + d.last : '') : '-';
        $id('pp-review').textContent = d.review_dir || '-';
      })
      .catch(function () {});
  }

  function start() {
    render();
    ppRefresh();
    setInterval(ppRefresh, 5000);
    timer = setInterval(function () { if (!document.hidden) refresh(); }, 15000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { refresh(); ppRefresh(); } });
  }

  if (window.jQuery) window.jQuery(start); else document.addEventListener('DOMContentLoaded', start);
})();
