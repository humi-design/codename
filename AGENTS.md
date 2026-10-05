# AGENTS.md

Repository knowledge for the Codenames Live app (Flask + Socket.IO + MySQL).

## Project

A real-time Codenames-style board-game controller. Voice happens on Starmaker;
this app only holds the board/session/round state. No audio, video or chat.

## Architecture

* `app.py` - application factory, blueprint registration, error handlers.
  `wsgi.py` and `passenger_wsgi.py` are deployment entry points.
* `models/` - SQLAlchemy models. Core split: **session != round**.
  A session is the whole evening; a round is one game inside it.
* `routes/` - HTTP blueprints: `main`, `session`, `player`, `captain`,
  `host`, `admin`.
* `sockets/` - Socket.IO handlers. Rooms are named `session:<CODE>`,
  `captain:<CODE>`, `host:<CODE>`, `player:<id>`.
* `services/` - all game logic. Routes and sockets both call these; never
  duplicate rules.
  * `game_manager.py` - reveal, score, turn, win conditions, guesses.
  * `board_generator.py` - word selection + card distribution.
  * `serializers.py` - **the security boundary**. `VIEWER_PLAYER` never gets
    `card_type` for an unrevealed card; `VIEWER_CAPTAIN` and `VIEWER_HOST` do.
  * `timer.py` - timestamp-based (no per-second DB writes).
  * `broadcaster.py` - emits role-specific state to the right rooms.

## Commands

```bash
python app.py                      # dev server on 127.0.0.1:5000
python scripts/init_db.py          # create tables + seed settings/admin
python scripts/import_words.py data/sample_words.csv --source seed
python -m pytest tests/ -q         # full suite (needs MySQL test DB)
python tests/e2e_acceptance.py     # HTTP end-to-end (server must be running)
python tests/e2e_socketio.py       # Socket.IO real-time + isolation
```

Migrations (Flask-Migrate): `flask db migrate -m "..."` then `flask db upgrade`.
`init_db.py` (db.create_all) is the fallback when the host blocks Flask CLI.

## Conventions

* Server is authoritative. Never trust client score/team/role/reveal/timer.
* JSON action APIs authenticate with header tokens only (`X-Host-Token`,
  `X-Player-Token`) so they are CSRF-safe and are `csrf.exempt`ed. HTML forms
  keep Flask-WTF CSRF.
* Only token *hashes* are stored (`host_token_hash`, `player_token_hash`).
* Scope every query by `session_id` / `round_id` / `player_id`. No global
  game state.
* Mobile-first: no horizontal scrolling down to 320px. Test 320/375/390/414/
  768/1024/1440.
* Dark theme palette lives in `static/css/style.css` as CSS variables.

## Environment

`.env` (never committed) supplies `SECRET_KEY`, `DATABASE_URL`,
`SUPER_ADMIN_USERNAME`, `SUPER_ADMIN_PASSWORD_HASH`, `SOCKETIO_ASYNC_MODE`
(default `threading` for shared hosting), `PROXY_FIX`, `SESSION_COOKIE_SECURE`.
`TEST_DATABASE_URL` is used by pytest.

## Gotchas

* The host is also a player row. Player names must be unique per session, so
  an e2e host name and player names must differ.
* `live_round()` returns a non-ENDED round; `current_round()` returns the
  latest round of any status.
* Reveal rules: RED/BLUE continue their own turn, otherwise turn flips;
  NEUTRAL flips; ASSASSIN ends the round with the opposing team winning.
