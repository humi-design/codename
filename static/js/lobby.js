/* Lobby: team assignment, round setup and presence. */
(function () {
  "use strict";
  const CL = window.CodenamesLive;
  const cfg = window.LOBBY;
  if (!cfg) return;

  const assignments = {}; // playerId -> "RED" | "BLUE"
  const assignList = document.getElementById("assign-list");
  const captainSelect = document.getElementById("captain-select");
  const startBtn = document.getElementById("start-round-btn");

  /* ---------------------------------------------------- team assignment */
  function refreshCaptainOptions() {
    if (!captainSelect) return;
    const previous = captainSelect.value;
    captainSelect.innerHTML = "";
    Object.keys(assignments).forEach(function (pid) {
      const li = assignList.querySelector('[data-player-id="' + pid + '"]');
      const name = li ? li.getAttribute("data-player-name") : pid;
      const opt = document.createElement("option");
      opt.value = pid;
      opt.textContent = name + " (" + assignments[pid] + ")";
      captainSelect.appendChild(opt);
    });
    if (previous) captainSelect.value = previous;
  }

  function assignTeam(pid, team, button) {
    // Toggle: tapping the same team again removes the assignment.
    if (assignments[pid] === team) {
      delete assignments[pid];
    } else {
      assignments[pid] = team;
    }
    const li = assignList.querySelector('[data-player-id="' + pid + '"]');
    li.querySelectorAll(".team-btn").forEach(function (b) {
      const t = b.getAttribute("data-team");
      b.classList.toggle("btn-red", assignments[pid] === "RED" && t === "RED");
      b.classList.toggle("btn-blue", assignments[pid] === "BLUE" && t === "BLUE");
      b.classList.toggle("btn-ghost", assignments[pid] !== t);
    });
    refreshCaptainOptions();
  }

  if (assignList) {
    assignList.addEventListener("click", function (ev) {
      const btn = ev.target.closest(".team-btn");
      if (!btn) return;
      const li = btn.closest("li");
      assignTeam(li.getAttribute("data-player-id"), btn.getAttribute("data-team"), btn);
    });
    // Default split: first half red, second half blue (host can change).
    const items = Array.prototype.slice.call(assignList.querySelectorAll("li"));
    items.forEach(function (li, idx) {
      const team = idx < Math.ceil(items.length / 2) ? "RED" : "BLUE";
      const btn = li.querySelector('.team-btn[data-team="' + team + '"]');
      assignTeam(li.getAttribute("data-player-id"), team, btn);
    });
  }

  /* ------------------------------------------------------- timer select */
  const timerSelect = document.getElementById("timer-duration");
  const customField = document.getElementById("custom-timer-field");
  if (timerSelect) {
    timerSelect.addEventListener("change", function () {
      customField.classList.toggle("hidden", timerSelect.value !== "custom");
    });
  }
  function currentTimer() {
    if (timerSelect.value === "custom") {
      return parseInt(document.getElementById("custom-timer").value, 10) || 180;
    }
    return parseInt(timerSelect.value, 10);
  }

  /* ---------------------------------------------------------- start round */
  function collectPayload() {
    const red = [], blue = [];
    Object.keys(assignments).forEach(function (pid) {
      const id = parseInt(pid, 10);
      if (assignments[pid] === "RED") red.push(id); else blue.push(id);
    });
    return {
      red_player_ids: red,
      blue_player_ids: blue,
      captain_player_id: captainSelect && captainSelect.value ? parseInt(captainSelect.value, 10) : null,
      board_size: parseInt(document.getElementById("board-size").value, 10),
      timer_duration: currentTimer(),
      word_mode: document.getElementById("word-mode").value,
    };
  }

  if (startBtn) {
    startBtn.addEventListener("click", async function () {
      const payload = collectPayload();
      if (!payload.red_player_ids.length || !payload.blue_player_ids.length) {
        CL.toast("Both teams need at least one player.", "error");
        return;
      }
      startBtn.disabled = true;
      startBtn.textContent = "STARTING\u2026";
      try {
        // Reuse the existing SETUP round if present, else create one.
        let roundId = cfg.roundId;
        if (!roundId) {
          const created = await CL.postJSON(
            "/api/host/" + cfg.sessionCode + "/rounds", payload, cfg.hostToken);
          roundId = created.round_id;
        } else {
          await CL.postJSON(
            "/api/host/" + cfg.sessionCode + "/rounds/" + roundId + "/config",
            payload, cfg.hostToken);
        }
        await CL.postJSON(
          "/api/host/" + cfg.sessionCode + "/rounds/" + roundId + "/start",
          {}, cfg.hostToken);
        CL.toast("Round started!", "success");
        window.location.href = cfg.hostDashboardUrl;
      } catch (e) {
        CL.toast(e.message, "error");
        startBtn.disabled = false;
        startBtn.textContent = "START ROUND";
      }
    });
  }

  /* ------------------------------------------------------------ end session */
  const endBtn = document.getElementById("end-session-btn");
  if (endBtn) {
    endBtn.addEventListener("click", async function () {
      const ok = CL.confirm(
        "End this session?\n\n" +
        "- Stops future rounds\n" +
        "- Disables the invite\n" +
        "- Prevents new players from joining\n" +
        "- Keeps session history\n\n" +
        "This cannot be undone.");
      if (!ok) return;
      try {
        const data = await CL.postJSON(
          "/api/host/" + cfg.sessionCode + "/end", {}, cfg.hostToken);
        window.location.href = data.redirect || cfg.summaryUrl;
      } catch (e) {
        CL.toast(e.message, "error");
      }
    });
  }

  /* ---------------------------------------------------------- presence */
  const conn = CL.connect({
    join: cfg.isHost
      ? { session_code: cfg.sessionCode, host_token: cfg.hostToken }
      : { session_code: cfg.sessionCode, player_token: cfg.playerToken },
    pollUrl: cfg.pollUrl || null,
  });

  conn.on("state", function (state) {
    if (!state || !state.players) return;
    const list = document.getElementById("player-list");
    if (!list) return;
    list.innerHTML = state.players.map(function (p) {
      return '<li data-player-id="' + p.id + '">' +
        '<span class="' + (p.connected ? "dot-on" : "dot-off") + '">&#9679;</span>' +
        '<span class="pname">' + escapeHtml(p.name) + '</span>' +
        (p.is_host ? '<span class="tag host">HOST</span>' : '') +
        '</li>';
    }).join("");
  });

  conn.on("session_ended", function () {
    CL.toast("The host ended the session.", "info");
    window.location.href = cfg.summaryUrl;
  });

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
})();
