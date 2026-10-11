(function () {
  var el = document.getElementById('pd_usage');
  if (!el || !window.jQuery) return;
  function gb(n) { return (n / 1e9).toFixed(n < 1e9 ? 2 : 1); }
  function load() {
    jQuery.getJSON('pixeldrain_status', function (r) {
      if (!r || !r.ok) { el.textContent = 'Pixeldrain: unavailable'; return; }
      var left = r.limit - r.used;
      el.textContent = 'Pixeldrain ' + gb(r.used) + ' / ' + gb(r.limit) + ' GB' + (r.user ? ' (' + r.user + ')' : '');
      el.style.color = left < 0.5e9 ? 'var(--t-fail, #c0392b)' : left < 1.5e9 ? 'var(--t-snatch, #b98200)' : '';
    });
  }
  load();
  setInterval(load, 300000);
})();
