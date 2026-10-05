/* Captain view: board with the secret key, plus guess submission. */
(function () {
  "use strict";
  const CL = window.CodenamesLive;
  const cfg = window.CAPTAIN;
  if (!cfg) return;

  let state = cfg.initialState;
  let showKey = true;
  let selectedCard = null;
  const timer = CL.Timer(document.getElementById("timer"));
  const boardEl = document.getElementById("board");
  const overlay = document.getElementById("guess-overlay");
  const winnerOverlay = document.getElementById("winner-overlay");

  function canGuess() {
    return state && state.round && state.round.status === "ACTIVE";
  }

  function render() {
    if (!state || !state.round) return;
    CL.renderBoard(boardEl, state.round.board, {
      showKey: showKey,
      interactive: canGuess(),
      onSelect: function (card) {
        selectedCard = card;
        document.getElementById("guess-word").textContent = card.word;
        overlay.hidden = false;
      },
    });
    CL.renderScores(state);
    timer.sync(state.round.timer);
  }

  document.getElementById("toggle-key").addEventListener("click", function (e) {
    showKey = !showKey;
    e.target.textContent = showKey ? "HIDE KEY" : "SHOW KEY";
    render();
  });

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

  const conn = CL.connect({
    join: { session_code: cfg.sessionCode, player_token: cfg.playerToken },
    pollUrl: cfg.pollUrl,
  });

  conn.on("state", function (newState) {
    state = newState;
    render();
    if (state.round && state.round.status === "ENDED") {
      document.getElementById("winner-text").textContent =
        (state.round.winner ? state.round.winner + " WINS" : "ROUND ENDED");
      document.getElementById("winner-summary-link").href =
        "/round/" + state.round.id + "/summary";
      winnerOverlay.hidden = false;
    } else {
      winnerOverlay.hidden = true;
    }
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) conn.send("request_state", {
      session_code: cfg.sessionCode, player_token: cfg.playerToken,
    });
  });

  render();
})();
