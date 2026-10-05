/* Host dashboard: reveal, guesses, timer, turn and session control. */
(function () {
  "use strict";
  const CL = window.CodenamesLive;
  const cfg = window.HOST;
  if (!cfg) return;

  let state = cfg.initialState;
  const timer = CL.Timer(document.getElementById("timer"));
  const boardEl = document.getElementById("board");
  const pendingEl = document.getElementById("pending-guesses");

  function activeRoundId() {
    return state && state.round ? state.round.id : cfg.roundId;
  }

  function api(path) {
    return cfg.apiBase + path;
  }

  /* --------------------------------------------------------- rendering */
  function render() {
    if (!state || !state.round) {
      boardEl.innerHTML = '<p class="muted small">No round yet. Set one up in the lobby.</p>';
      return;
    }
    CL.renderBoard(boardEl, state.round.board, {
      showKey: true,
      interactive: state.round.status === "ACTIVE",
      onSelect: function (card) {
        if (card.revealed) return;
        confirmAction(
          "Reveal card?",
          "Reveal \"" + card.word + "\" and apply the result?",
          "REVEAL",
          async function () {
            await CL.postJSON(api("/rounds/" + activeRoundId() + "/reveal"),
              { card_id: card.id }, cfg.hostToken);
            CL.toast("Card revealed.", "success");
          });
      },
    });
    CL.renderScores(state);
    timer.sync(state.round.timer);
    renderPending(state.round.pending_guesses || []);
  }

  function renderPending(guesses) {
    if (!guesses.length) {
      pendingEl.innerHTML = '<p class="muted small">No pending guesses.</p>';
      return;
    }
    pendingEl.innerHTML = guesses.map(function (g) {
      const submitters = g.submitters.map(function (s) {
        return CL.escapeHtml(s.name);
      }).join(", ");
      return '<div class="guess-item">' +
        '<div><div class="gword">' + CL.escapeHtml(g.word) + '</div>' +
        '<div class="gby">Submitted by: ' + submitters + '</div></div>' +
        '<div class="gbtns">' +
        '<button class="btn btn-sm btn-success" data-accept="' + CL.escapeHtml(g.normalized_word) + '">REVEAL</button>' +
        '<button class="btn btn-sm btn-danger" data-reject="' + CL.escapeHtml(g.normalized_word) + '">REJECT</button>' +
        '</div></div>';
    }).join("");
  }

  pendingEl.addEventListener("click", async function (ev) {
    const acceptBtn = ev.target.closest("[data-accept]");
    const rejectBtn = ev.target.closest("[data-reject]");
    if (acceptBtn) {
      try {
        await CL.postJSON(api("/rounds/" + activeRoundId() + "/guess/resolve"),
          { normalized_word: acceptBtn.getAttribute("data-accept"), accept: true },
          cfg.hostToken);
      } catch (e) { CL.toast(e.message, "error"); }
    } else if (rejectBtn) {
      try {
        await CL.postJSON(api("/rounds/" + activeRoundId() + "/guess/resolve"),
          { normalized_word: rejectBtn.getAttribute("data-reject"), accept: false },
          cfg.hostToken);
        CL.toast("Guess rejected.", "info");
      } catch (e) { CL.toast(e.message, "error"); }
    }
  });

  /* ------------------------------------------------------------- timer */
  function timerAction(action, extra) {
    if (!activeRoundId()) return;
    return CL.postJSON(api("/rounds/" + activeRoundId() + "/timer"),
      Object.assign({ action: action }, extra || {}), cfg.hostToken);
  }
  document.getElementById("timer-start").addEventListener("click", function () {
    timerAction("start").catch(function (e) { CL.toast(e.message, "error"); });
  });
  document.getElementById("timer-pause").addEventListener("click", function () {
    timerAction("pause").catch(function (e) { CL.toast(e.message, "error"); });
  });
  document.getElementById("timer-resume").addEventListener("click", function () {
    timerAction("resume").catch(function (e) { CL.toast(e.message, "error"); });
  });
  document.getElementById("timer-reset").addEventListener("click", function () {
    timerAction("reset").catch(function (e) { CL.toast(e.message, "error"); });
  });

  /* -------------------------------------------------------------- turn */
  document.getElementById("switch-turn").addEventListener("click", function () {
    if (!activeRoundId()) return;
    CL.postJSON(api("/rounds/" + activeRoundId() + "/turn"), {}, cfg.hostToken)
      .catch(function (e) { CL.toast(e.message, "error"); });
  });

  /* --------------------------------------------------------- end round */
  document.getElementById("end-round").addEventListener("click", function () {
    if (!activeRoundId()) return;
    confirmAction("End this round?", "Choose the winner or leave it undecided.",
      "END ROUND", async function () {
        await CL.postJSON(api("/rounds/" + activeRoundId() + "/end"),
          { winner: null }, cfg.hostToken);
        CL.toast("Round ended.", "success");
      });
  });

  /* --------------------------------------------------------- end session */
  document.getElementById("end-session-btn").addEventListener("click", function () {
    confirmAction(
      "End the session?",
      "This stops future rounds, disables the invite for everyone, prevents new " +
      "players from joining, and keeps the history. This cannot be undone.",
      "END SESSION", async function () {
        const data = await CL.postJSON(api("/end"), {}, cfg.hostToken);
        window.location.href = data.redirect || cfg.summaryUrl;
      });
  });

  /* ----------------------------------------------------------- confirm */
  const confirmOverlay = document.getElementById("confirm-overlay");
  let confirmCallback = null;
  function confirmAction(title, body, yesLabel, cb) {
    document.getElementById("confirm-title").textContent = title;
    document.getElementById("confirm-body").textContent = body;
    document.getElementById("confirm-yes").textContent = yesLabel;
    confirmCallback = cb;
    confirmOverlay.hidden = false;
  }
  document.getElementById("confirm-no").addEventListener("click", function () {
    confirmOverlay.hidden = true;
    confirmCallback = null;
  });
  document.getElementById("confirm-yes").addEventListener("click", async function () {
    const cb = confirmCallback;
    confirmOverlay.hidden = true;
    confirmCallback = null;
    if (cb) {
      try { await cb(); } catch (e) { CL.toast(e.message, "error"); }
    }
  });

  /* ------------------------------------------------------------- socket */
  const conn = CL.connect({
    join: { session_code: cfg.sessionCode, host_token: cfg.hostToken },
    pollUrl: null,
  });

  conn.on("state", function (newState) {
    state = newState;
    render();
    if (state.round && state.round.status === "ENDED") {
      CL.toast("Round ended" + (state.round.winner ? ": " + state.round.winner + " wins!" : "."),
        "info");
    }
  });

  conn.on("session_ended", function () {
    window.location.href = cfg.summaryUrl;
  });

  // Host-side timer expiry detection: when our local countdown hits zero and
  // the server agrees, tell the server to switch turns.
  setInterval(function () {
    if (timer.isExpired() && state && state.round && state.round.status === "ACTIVE") {
      conn.send("notify_timer_expired", {
        session_code: cfg.sessionCode,
        host_token: cfg.hostToken,
      });
    }
  }, 2000);

  render();
})();
