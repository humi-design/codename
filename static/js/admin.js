/* Admin helpers. */
(function () {
  "use strict";
  const CL = (window.CodenamesLive = window.CodenamesLive || {});

  CL.adminHealth = function (url) {
    const el = document.getElementById("health-status");
    const btn = document.getElementById("health-refresh");
    function load() {
      if (!el) return;
      el.textContent = "checking\u2026";
      fetch(url, { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          el.textContent = "database: " + data.database +
            " \u00b7 active sessions: " + data.active_sessions +
            " \u00b7 server time: " + data.server_time;
        })
        .catch(function () { el.textContent = "unavailable"; });
    }
    if (btn) btn.addEventListener("click", load);
    load();
  };

  /* Live import progress. Polls the status endpoint and updates the counters
     and progress bar in place, then reloads once the run finishes so the
     statistics refresh. */
  CL.adminVocabulary = function (url) {
    const bar = document.getElementById("imp-bar");
    const section = document.getElementById("import-progress");
    if (!section) return;

    function num(value) {
      return (value || 0).toLocaleString();
    }

    function apply(payload) {
      const imp = payload.import;
      if (!imp) return;
      const set = function (id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
      };
      set("imp-source", imp.source);
      set("imp-status", imp.status);
      set("imp-processed", num(imp.processed));
      set("imp-imported", num(imp.imported));
      set("imp-updated", num(imp.updated));
      set("imp-duplicates", num(imp.duplicates));
      set("imp-rejected", num(imp.rejected));
      set("imp-errors", num(imp.errors));
      if (bar) {
        // We do not know the dataset size up-front, so animate within a band
        // that never claims completion; the page reload shows the real end.
        const base = Math.min(95, 5 + Math.log10((imp.processed || 0) + 1) * 12);
        bar.style.width = base.toFixed(1) + "%";
      }
    }

    let ticks = 0;
    const timer = setInterval(function () {
      ticks += 1;
      fetch(url, { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          apply(data);
          const imp = data.import;
          const terminal = imp && ["COMPLETED", "FAILED", "CANCELLED"].indexOf(imp.status) !== -1;
          if (terminal || !imp) {
            clearInterval(timer);
            if (bar) bar.style.width = "100%";
            setTimeout(function () { window.location.reload(); }, 800);
          }
        })
        .catch(function () {
          if (ticks > 20) clearInterval(timer);
        });
    }, 3000);
  };
})();
