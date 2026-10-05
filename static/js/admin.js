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
})();
