"""Real-time Socket.IO check: state pushes, role filtering, isolation.

Requires a running server (BASE_URL, default http://127.0.0.1:5000) and the
``python-socketio`` + ``websocket-client`` client packages.
Run with:  python tests/e2e_socketio.py
"""

from __future__ import annotations

import os
import re
import time

import requests
import socketio

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:5000")


def ok(label, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        raise SystemExit(f"Socket.IO test failed: {label}")


def make_browser():
    return requests.Session()


def csrf(session, path):
    r = session.get(BASE + path)
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    return m.group(1) if m else None


def create_session(host_name="Host"):
    s = make_browser()
    token = csrf(s, "/create")
    r = s.post(BASE + "/create",
               data={"host_name": host_name, "csrf_token": token},
               allow_redirects=False)
    code = r.headers["Location"].rstrip("/").split("/")[-1]
    page = s.get(BASE + f"/host/{code}")
    host_token = re.search(r'\bhostToken:\s*"([^"]+)"', page.text).group(1)
    return s, code, host_token


def join(code, name):
    s = make_browser()
    token = csrf(s, f"/join/{code}")
    s.post(BASE + f"/join/{code}",
           data={"display_name": name, "csrf_token": token},
           allow_redirects=False)
    page = s.get(BASE + f"/player/{code}")
    m = re.search(r'\bplayerToken:\s*"([^"]+)"', page.text)
    return s, (m.group(1) if m else None)


def main():
    host, code, host_token = create_session()
    players = {}
    for name in ["Somil", "Priya", "Rahul", "Aman"]:
        s, tok = join(code, name)
        players[name] = {"session": s, "token": tok}
    print(f"    session {code}")

    # Connect host + a player over websockets.
    host_events = []
    player_events = []

    host_sio = socketio.Client()
    host_sio.connect(BASE, transports=["websocket"])
    host_sio.emit("join_session", {"session_code": code, "host_token": host_token})

    player_sio = socketio.Client()
    player_sio.connect(BASE, transports=["websocket"])
    player_sio.emit("join_session",
                    {"session_code": code, "player_token": players["Aman"]["token"]})

    host_sio.on("host_state", lambda d: host_events.append(d))
    player_sio.on("session_state", lambda d: player_events.append(d))
    time.sleep(0.8)

    # Start a round.
    state = host.get(BASE + f"/api/host/{code}/state",
                     headers={"X-Host-Token": host_token}).json()
    ids = {p["name"]: p["id"] for p in state["players"]}
    cfg = {
        "red_player_ids": [ids["Somil"], ids["Priya"]],
        "blue_player_ids": [ids["Rahul"], ids["Aman"]],
        "captain_player_id": ids["Priya"],
        "board_size": 5, "timer_duration": 120, "word_mode": "NORMAL",
    }
    r = host.post(BASE + f"/api/host/{code}/rounds", json=cfg,
                  headers={"X-Host-Token": host_token})
    ok("round created over http", r.status_code == 200)
    rid = r.json()["round_id"]
    host.post(BASE + f"/api/host/{code}/rounds/{rid}/start", json={},
              headers={"X-Host-Token": host_token})
    time.sleep(1.2)

    ok("host received state over socket", len(host_events) > 0)
    ok("player received state over socket", len(player_events) > 0)
    if player_events:
        blob = str(player_events[-1])
        ok("player socket state hides hidden key", "card_type" not in blob)
        ok("player socket state has board",
           player_events[-1].get("round", {}).get("board"))
    if host_events:
        ok("host socket state includes hidden key",
           "card_type" in str(host_events[-1]))

    # Isolation: a second session must not receive this session's events.
    other, other_code, other_token = create_session("OtherHost")
    other_events = []
    other_sio = socketio.Client()
    other_sio.connect(BASE, transports=["websocket"])
    other_sio.emit("join_session",
                   {"session_code": other_code, "host_token": other_token})
    other_sio.on("host_state", lambda d: other_events.append(d))
    time.sleep(0.6)

    before = len(other_events)
    # Trigger activity in the first session.
    card = next(c for c in host.get(
        BASE + f"/api/host/{code}/state",
        headers={"X-Host-Token": host_token}).json()["round"]["board"])
    host.post(BASE + f"/api/host/{code}/rounds/{rid}/reveal",
              json={"card_id": card["id"]}, headers={"X-Host-Token": host_token})
    time.sleep(1.2)

    ok("event did not leak to other session",
       len(other_events) == before)

    host_sio.disconnect()
    player_sio.disconnect()
    other_sio.disconnect()
    print("\nALL SOCKET.IO CHECKS PASSED")


if __name__ == "__main__":
    main()
