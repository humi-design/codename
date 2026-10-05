/* Common client helpers shared by every page. */
(function () {
  "use strict";

  const CL = (window.CodenamesLive = window.CodenamesLive || {});

  /* --------------------------------------------------------- toasts */
  CL.toast = function (message, level) {
    const area = document.getElementById("toast-area");
    if (!area) return;
    const el = document.createElement("div");
    el.className = "toast " + (level || "info");
    el.textContent = message;
    area.appendChild(el);
    setTimeout(function () {
      el.style.opacity = "0";
      el.style.transition = "opacity .3s";
      setTimeout(function () { el.remove(); }, 320);
    }, 3200);
  };

  /* ------------------------------------------------- connection status */
  CL.setConnected = function (connected) {
    const box = document.getElementById("conn-status");
    const text = document.getElementById("conn-text");
    if (!box || !text) return;
    box.classList.toggle("offline", !connected);
    text.textContent = connected ? "Connected" : "Reconnecting\u2026";
  };

  /* -------------------------------------------------------- clipboard */
  CL.copy = async function (value) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const ta = document.createElement("textarea");
        ta.value = value;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      CL.toast("Copied!", "success");
      return true;
    } catch (e) {
      CL.toast("Could not copy. Please copy manually.", "error");
      return false;
    }
  };

  document.addEventListener("click", function (ev) {
    const target = ev.target.closest("[data-copy]");
    if (target) {
      ev.preventDefault();
      CL.copy(target.getAttribute("data-copy"));
    }
  });

  /* --------------------------------------------------------- confirm */
  CL.confirm = function (message) {
    return window.confirm(message);
  };

  /* --------------------------------------------------------- fetch JSON */
  CL.postJSON = async function (url, body, token, playerToken) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["X-Host-Token"] = token;
    if (playerToken) headers["X-Player-Token"] = playerToken;
    const resp = await fetch(url, {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await resp.json(); } catch (e) { data = {}; }
    if (!resp.ok) {
      throw new Error(data.error || "Something went wrong. Please try again.");
    }
    return data;
  };

  /* -------------------------------------------------- socket connection
     Falls back to REST polling when socket.io is unavailable (some shared
     hosts block websockets).  Pages register a `onState` handler. */
  CL.connect = function (options) {
    options = options || {};
    const state = {
      socket: null,
      connected: false,
      fallbackTimer: null,
      handlers: {},
    };

    function emitLocal(name, payload) {
      (state.handlers[name] || []).forEach(function (fn) {
        try { fn(payload); } catch (e) { console.error(e); }
      });
    }

    state.on = function (name, fn) {
      (state.handlers[name] = state.handlers[name] || []).push(fn);
      return state;
    };

    state.send = function (name, payload) {
      if (state.socket && state.connected) {
        state.socket.emit(name, payload || {});
        return true;
      }
      return false;
    };

    function startFallback() {
      if (state.fallbackTimer) return;
      state.fallbackTimer = setInterval(function () {
        if (options.pollUrl) {
          fetch(options.pollUrl, { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) { if (data) emitLocal("state", data); })
            .catch(function () {});
        }
      }, 4000);
    }
    function stopFallback() {
      if (state.fallbackTimer) {
        clearInterval(state.fallbackTimer);
        state.fallbackTimer = null;
      }
    }

    if (typeof window.io === "undefined") {
      CL.setConnected(false);
      startFallback();
      return state;
    }

    const socket = window.io({
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionDelay: 800,
      reconnectionDelayMax: 5000,
    });
    state.socket = socket;

    socket.on("connect", function () {
      state.connected = true;
      CL.setConnected(true);
      stopFallback();
      socket.emit("join_session", options.join || {});
    });

    socket.on("disconnect", function () {
      state.connected = false;
      CL.setConnected(false);
      startFallback();
    });

    socket.on("connect_error", function () {
      state.connected = false;
      CL.setConnected(false);
      startFallback();
    });

    // Generic error from the server.
    socket.on("error_message", function (data) {
      CL.toast((data && data.message) || "Something went wrong.", "error");
    });

    // Forward every state/event payload to local handlers.
    [
      "session_state", "captain_state", "host_state",
      "player_joined", "player_left", "notify",
      "round_started", "round_ended", "card_revealed", "turn_changed",
      "guess_rejected", "timer_started", "timer_paused", "timer_resumed",
      "timer_reset", "session_ended", "joined",
    ].forEach(function (name) {
      socket.on(name, function (payload) {
        emitLocal(name, payload);
        if (name === "session_state" || name === "captain_state" || name === "host_state") {
          emitLocal("state", payload);
        }
        if (name === "notify" && payload && payload.message) {
          CL.toast(payload.message, payload.level || "info");
        }
      });
    });

    return state;
  };

  /* -------------------------------------------------------- timer view */
  CL.Timer = function (element) {
    let remaining = null;
    let running = false;
    let tick = null;

    function render() {
      if (!element) return;
      if (remaining === null) {
        element.textContent = "--:--";
        element.classList.remove("warning", "danger");
        return;
      }
      const m = Math.floor(remaining / 60);
      const s = remaining % 60;
      element.textContent = String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
      element.classList.toggle("warning", remaining <= 30 && remaining > 10);
      element.classList.toggle("danger", remaining <= 10);
      element.classList.toggle("paused", !running);
    }

    function loop() {
      if (running && remaining !== null && remaining > 0) {
        remaining -= 1;
        render();
      }
    }

    return {
      sync: function (timerState) {
        if (!timerState) { remaining = null; running = false; render(); return; }
        remaining = timerState.remaining;
        running = !!timerState.running;
        render();
        if (!tick) tick = setInterval(loop, 1000);
      },
      get remaining() { return remaining; },
      isExpired: function () { return remaining !== null && remaining <= 0; },
    };
  };

  /* -------------------------------------------------- team/colour helpers */
  CL.colorClass = function (type) {
    switch (type) {
      case "RED": return "t-red";
      case "BLUE": return "t-blue";
      case "NEUTRAL": return "t-neutral";
      case "ASSASSIN": return "t-assassin";
      default: return "";
    }
  };
})();
