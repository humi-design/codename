/* Player view: board, guess submission, timer and live sync. */
(function () {
  "use strict";
  const CL = window.CodenamesLive;
  const cfg = window.PLAYER;
  if (!cfg) return;

  let state = cfg.initialState;
  let selectedCard = null;
  const timer = CL.Timer(document.getElementById("timer"));
  const boardEl = document.getElementById("board");
  const overlay = document.getElementById("guess-overlay");
  const guessWordEl = document.getElementById("guess-word");
  const winnerOverlay = document.getElementById("winner-overlay");

  function canGuess() {
    return state && state.round && state.round.status === "ACTIVE";
  }

  function render() {
    if (!state || !state.round) return;
    CL.renderBoard(boardEl, state.round.board, {
      interactive: canGuess(),
      onSelect: function (card) {
        selectedCard = card;
        guessWordEl.textContent = card.word;
        overlay.hidden = false;
      },
    });
    CL.renderScores(state);
    timer.sync(state.round.timer);
    renderTeams(state.round.players);
    document.getElementById("board-hint").textContent = canGuess()
      ? "Tap a word to submit a guess."
      : "Waiting for the host\u2026";
  }

  function renderTeams(players) {
    ["red", "blue"].forEach(function (team) {
      const el = document.getElementById("team-" + team);
      if (!el) return;
      el.innerHTML = (players[team] || []).map(function (p) {
        return '<li><span class="' + (p.connected ? "dot-on" : "dot-off") + '">&#9679;</span>' +
          '<span class="pname">' + CL.escapeHtml(p.name) + '</span>' +
          (p.role === "CAPTAIN" ? '<span class="tag captain">CAPT</span>' : '') +
          '</li>';
      }).join("");
    });
  }

  function showWinner() {
    if (!state.round || state.round.status !== "ENDED") return;
    const winner = state.round.winner;
    const text = winner ? winner + " WINS" : "ROUND ENDED";
    document.getElementById("winner-text").textContent = text;
    document.getElementById("winner-summary-link").href = "/round/" + state.round.id + "/summary";
    winnerOverlay.hidden = false;
  }

  /* --------------------------------------------------------- guess flow */
  document.getElementById("guess-cancel").addEventListener("click", function () {
    overlay.hidden = true;
    selectedCard = null;
  });

  document.getElementById("guess-confirm").addEventListener("click", async function () {
    if (!selectedCard) return;
    const word = selectedCard.word;
    overlay.hidden = true;
    const sent = conn.send("submit_guess", {
      session_code: cfg.sessionCode,
      player_token: cfg.playerToken,
      word: word,
    });
    if (!sent) {
      // Socket fallback: HTTP endpoint.
      try {
        await CL.postJSON(cfg.guessUrl, { word: word }, null, cfg.playerToken);
      } catch (e) {
        CL.toast(e.message, "error");
        return;
      }
    }
    CL.toast("Guess submitted. Waiting for host\u2026", "success");
    selectedCard = null;
  });

  /* ------------------------------------------------------------ socket */
  const conn = CL.connect({
    join: { session_code: cfg.sessionCode, player_token: cfg.playerToken },
    pollUrl: cfg.pollUrl,
  });

  conn.on("state", function (newState) {
    state = newState;
    if (state.round && state.round.status === "ENDED") {
      render();
      showWinner();
    } else {
      winnerOverlay.hidden = true;
      render();
    }
  });

  conn.on("notify", function () {});

  // Re-sync when the tab becomes visible again.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) conn.send("request_state", {
      session_code: cfg.sessionCode, player_token: cfg.playerToken,
    });
  });

  render();
})();
