"""End-to-end acceptance test driving the real HTTP + Socket.IO server.

Runs the exact scenario from the specification:
  create session -> 5 players join -> start round 1 -> captain sees key but
  players do not -> guess submitted -> host reveals -> score/turn update ->
  refresh restores state -> round ends -> round 2 with new teams/captain ->
  end session -> old invite is dead.

Requires a running server on BASE_URL (default http://127.0.0.1:5000).
Run with:  python tests/e2e_acceptance.py
"""

from __future__ import annotations

import os
import re

import requests

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:5000")


def ok(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Acceptance test failed: {label}")


class Browser:
    """A single browser (cookie jar) - one host or one player."""

    def __init__(self):
        self.s = requests.Session()

    def post(self, path, **kw):
        return self.s.post(f"{BASE}{path}", allow_redirects=False, **kw)

    def get(self, path, **kw):
        return self.s.get(f"{BASE}{path}", **kw)

    def token_from(self, path, key):
        r = self.get(path)
        m = re.search(r'\b%s:\s*"([^"]+)"' % key, r.text)
        return m.group(1) if m else None

    def csrf(self, path):
        r = self.get(path)
        m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
        return m.group(1) if m else None

    def form_post(self, path, form_path, data):
        token = self.csrf(form_path)
        data = dict(data)
        if token:
            data["csrf_token"] = token
        return self.post(path, data=data)


def main():
    host = Browser()
    # 1. Create the session.
    r = host.form_post("/create", "/create", {"host_name": "Host"})
    ok("create session redirects", r.status_code == 302)
    code = r.headers["Location"].rstrip("/").split("/")[-1]
    ok("session code looks valid", bool(re.fullmatch(r"[A-Z0-9]{5}", code)))
    print(f"    session code: {code}")

    host_token = host.token_from(f"/host/{code}", "hostToken")
    ok("host token available", bool(host_token))

    # 2. Five players join, each in its own browser.
    names = ["Somil", "Priya", "Rahul", "Aman", "Neha"]
    players = {}
    for name in names:
        b = Browser()
        resp = b.form_post(f"/join/{code}", f"/join/{code}",
                           {"display_name": name})
        ok(f"{name} joined", resp.status_code == 302)
        token = b.token_from(f"/player/{code}", "playerToken")
        ok(f"{name} has a player token", bool(token))
        players[name] = {"browser": b, "token": token}

    # 3. Start round 1 (teams + captain as in the spec).
    r = host.get(f"/api/host/{code}/state",
                 headers={"X-Host-Token": host_token})
    ok("host state reachable", r.status_code == 200)
    ids = {p["name"]: p["id"] for p in r.json()["players"]}
    red = [ids["Somil"], ids["Priya"]]
    blue = [ids["Rahul"], ids["Aman"], ids["Neha"]]
    cfg = {
        "red_player_ids": red,
        "blue_player_ids": blue,
        "captain_player_id": ids["Priya"],
        "board_size": 5,
        "timer_duration": 180,
        "word_mode": "NORMAL",
    }
    r = host.post(f"/api/host/{code}/rounds", json=cfg,
                  headers={"X-Host-Token": host_token})
    ok("round created", r.status_code == 200)
    round_id = r.json()["round_id"]
    r = host.post(f"/api/host/{code}/rounds/{round_id}/start", json={},
                  headers={"X-Host-Token": host_token})
    ok("round started", r.status_code == 200)

    # 4. Captain sees the key; normal players do not.
    cap = players["Priya"]["browser"]
    r = cap.get(f"/captain/{code}")
    ok("captain page reachable", r.status_code == 200)
    ok("captain payload includes hidden key", '"card_type"' in r.text)

    somil = players["Somil"]["browser"]
    r = somil.get(f"/player/{code}")
    ok("player page reachable", r.status_code == 200)
    ok("player page hides hidden key", '"card_type"' not in r.text)

    r = somil.get(f"/api/session/{code}/state",
                  headers={"X-Player-Token": players["Somil"]["token"]})
    ok("player state api hides key", "card_type" not in r.text)

    # 5. Host sees the full board.
    r = host.get(f"/api/host/{code}/state",
                 headers={"X-Host-Token": host_token})
    host_state = r.json()
    board = host_state["round"]["board"]
    ok("host sees hidden card types", all("card_type" in c for c in board))
    ok("board has 25 cards", len(board) == 25)

    # 6. Player Somil submits a guess.
    red_card = next(c for c in board if c["card_type"] == "RED")
    r = somil.post(f"/api/session/{code}/guess", json={"word": red_card["word"]},
                   headers={"X-Player-Token": players["Somil"]["token"]})
    ok("guess submitted", r.status_code == 200)

    r = host.get(f"/api/host/{code}/state",
                 headers={"X-Host-Token": host_token})
    pending = r.json()["round"]["pending_guesses"]
    ok("host sees pending guess", any(g["word"] == red_card["word"] for g in pending))
    ok("pending guess shows submitter",
       any(s["name"] == "Somil" for g in pending for s in g["submitters"]))

    # 7. Host reveals it; server decides the type.
    r = host.post(f"/api/host/{code}/rounds/{round_id}/guess/resolve",
                  json={"normalized_word": red_card["word"].upper(), "accept": True},
                  headers={"X-Host-Token": host_token})
    ok("host accepted guess", r.status_code == 200)

    r = host.get(f"/api/host/{code}/state",
                 headers={"X-Host-Token": host_token})
    after = r.json()["round"]
    revealed = next(c for c in after["board"] if c["id"] == red_card["id"])
    ok("card revealed", revealed["revealed"] is True)
    ok("score updated", after["scores"]["red"] == 8)
    ok("turn stays RED after RED reveal", after["current_team"] == "RED")

    # 8. Refresh restores state.
    r = somil.get(f"/player/{code}")
    ok("player page reloads with state",
       r.status_code == 200 and "ROUND" in r.text.upper())

    # 9. End round 1.
    r = host.post(f"/api/host/{code}/rounds/{round_id}/end",
                  json={"winner": "RED"}, headers={"X-Host-Token": host_token})
    ok("round 1 ended", r.status_code == 200)

    # 10. Round 2 with new teams, captain, board and scores.
    cfg2 = {
        "red_player_ids": blue,
        "blue_player_ids": red,
        "captain_player_id": ids["Rahul"],
        "board_size": 5,
        "timer_duration": 120,
        "word_mode": "CHAOS",
    }
    r = host.post(f"/api/host/{code}/rounds", json=cfg2,
                  headers={"X-Host-Token": host_token})
    ok("round 2 created", r.status_code == 200)
    round2 = r.json()["round_id"]
    r = host.post(f"/api/host/{code}/rounds/{round2}/start", json={},
                  headers={"X-Host-Token": host_token})
    ok("round 2 started", r.status_code == 200)

    r = host.get(f"/api/host/{code}/state",
                 headers={"X-Host-Token": host_token})
    r2 = r.json()["round"]
    ok("round 2 number is 2", r2["round_number"] == 2)
    ok("round 2 scores reset",
       r2["scores"]["red"] == 9 and r2["scores"]["blue"] == 8)
    ok("round 2 board is new",
       {c["word"] for c in r2["board"]} != {c["word"] for c in board})

    # 11. Players are still in the same session - no new invite.
    r = somil.get(f"/api/session/{code}/state",
                  headers={"X-Player-Token": players["Somil"]["token"]})
    ok("player still valid in session after new round", r.status_code == 200)

    # 12. End the session.
    r = host.post(f"/api/host/{code}/end", json={},
                  headers={"X-Host-Token": host_token})
    ok("session ended", r.status_code == 200)

    r = requests.get(f"{BASE}/join/{code}")
    ok("old invite is dead", r.status_code == 410)
    ok("ended message shown", "ended" in r.text.lower())

    print("\nALL ACCEPTANCE CHECKS PASSED")


if __name__ == "__main__":
    main()
