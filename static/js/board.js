/* Shared board renderer used by player, captain and host views. */
(function () {
  "use strict";
  const CL = window.CodenamesLive;

  CL.renderBoard = function (container, cards, options) {
    options = options || {};
    if (!container) return;
    const size = Math.round(Math.sqrt(cards.length)) || 5;
    container.setAttribute("data-size", String(size));
    container.innerHTML = "";

    cards.forEach(function (card) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tile";
      btn.setAttribute("data-card-id", card.id);
      btn.setAttribute("data-word", card.word);

      let colorClass = "";
      if (card.revealed) {
        colorClass = CL.colorClass(card.revealed_type);
        btn.classList.add(colorClass, "readonly");
        btn.disabled = true;
      } else if (options.showKey && card.card_type) {
        // Captain / host: show the hidden colour directly.
        colorClass = CL.colorClass(card.card_type);
        btn.classList.add(colorClass);
        btn.disabled = !options.interactive;
      } else if (options.showKeyDot && card.card_type) {
        btn.disabled = !options.interactive;
      } else {
        btn.disabled = !options.interactive;
      }

      btn.textContent = card.word;

      if (!card.revealed && options.showKeyDot && card.card_type) {
        const dot = document.createElement("span");
        dot.className = "keydot k-" + card.card_type.toLowerCase();
        btn.appendChild(dot);
      }

      if (options.interactive && !card.revealed) {
        btn.addEventListener("click", function () {
          options.onSelect && options.onSelect(card, btn);
        });
      }
      container.appendChild(btn);
    });
  };

  /* --------------------------------------------------- score / status */
  CL.renderScores = function (state) {
    const round = state && state.round;
    if (!round) return;
    const redEl = document.getElementById("score-red");
    const blueEl = document.getElementById("score-blue");
    if (redEl) redEl.textContent = round.scores.red;
    if (blueEl) blueEl.textContent = round.scores.blue;
    if (redEl) redEl.closest(".score").classList.toggle("turn", round.current_team === "RED");
    if (blueEl) blueEl.closest(".score").classList.toggle("turn", round.current_team === "BLUE");

    const turn = document.getElementById("turn-indicator");
    if (turn) {
      turn.textContent = round.current_team + " TEAM'S TURN";
      turn.className = "turn-indicator " + round.current_team.toLowerCase();
    }
    const roundLabel = document.getElementById("round-label");
    if (roundLabel) roundLabel.textContent = "ROUND " + round.round_number;
  };

  CL.escapeHtml = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
})();
