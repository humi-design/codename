# Codenames Live

A lightweight, mobile-first, real-time Codenames-style board game controller.

Players talk in a Starmaker voice room. This site is only the board: it holds
the session, teams, secret key, guesses, timer, score and history. It has no
audio, video or chat.

* Backend: Python Flask + Flask-SocketIO
* Database: MySQL / MariaDB (via SQLAlchemy + PyMySQL)
* Frontend: HTML5, CSS3, vanilla JavaScript, Jinja2 templates
* No React, no Node backend, no heavy framework

The server is the source of truth. Hidden card colours are never sent to a
normal player before the card is revealed.

---

## 1. Core idea: one session, many rounds

A **session** is the whole Starmaker evening. A **round** is one Codenames
game.

```
Create session  ->  share one code  ->  players join once
      ->  round 1  ->  round 2  ->  round 3  ->  ...
      ->  host ends the session  ->  invite stops working
```

Teams and the captain are chosen fresh for every round. Players stay in the
same session the whole time and never need a new invite.

---

## 2. Requirements

* Python 3.10 or newer
* MySQL 8+ or MariaDB 10.5+ (shared hosting is fine)
* pip

---

## 3. Local development

```bash
git clone https://github.com/humi-design/codename.git
cd codename

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

Create your environment file:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```
SECRET_KEY=<a long random string>
DATABASE_URL=mysql+pymysql://USER:PASSWORD@127.0.0.1/codenames_live?charset=utf8mb4
SUPER_ADMIN_USERNAME=admin
SUPER_ADMIN_PASSWORD_HASH=<see below>
```

Generate a secret key and an admin password hash:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
python -c "from werkzeug.security import generate_password_hash as g; print(g('your-admin-password'))"
```

Create the database (example for a local MySQL):

```sql
CREATE DATABASE codenames_live CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'cnuser'@'localhost' IDENTIFIED BY 'cnpass123';
GRANT ALL PRIVILEGES ON codenames_live.* TO 'cnuser'@'localhost';
FLUSH PRIVILEGES;
```

Initialise the schema and seed defaults:

```bash
python scripts/init_db.py
```

Load the sample vocabulary (259 words for development):

```bash
python scripts/import_words.py data/sample_words.csv --source seed
```

Run the app:

```bash
python app.py
```

Open <http://127.0.0.1:5000>.

---

## 4. Database migrations

The project ships with Alembic migrations (Flask-Migrate). Apply them with:

```bash
export FLASK_APP=app.py
flask db upgrade
```

Create a new migration after changing a model:

```bash
flask db migrate -m "describe change"
flask db upgrade
```

If your host will not let you run Flask commands, the alternative is:

```bash
python scripts/init_db.py
```

`init_db.py` calls `db.create_all()`, which is safe to run on a fresh
database and creates every table.

---

## 5. Large-scale vocabulary engine

The game reads words from the MySQL `words` table. The table is the single
source of vocabulary; no external API is ever called at game time. Populate it
once (and refresh it periodically) from large public datasets.

### Ingestion pipeline

```
providers -> cleaner -> classifier -> importer -> words table
```

* `services/vocabulary/cleaner.py` - normalises Unicode/whitespace/case and
  rejects URLs, HTML, templates, sentences and metadata fragments. It keeps
  scientific, technical, medical, historical, place, brand and rare words.
* `services/vocabulary/classifier.py` - infers category, difficulty and
  frequency score, and detects proper nouns.
* `services/vocabulary/importer.py` - streams entries one line at a time and
  upserts them in batches. Nothing is loaded wholesale into memory.
* `services/word_engine.py` - the only gameplay reader. It samples random
  primary keys, so selection stays fast on tables with millions of rows and
  never uses `ORDER BY RAND()`.

### Supported sources

| Source | Provider | License |
|--------|----------|---------|
| Wiktionary / Wiktextract (Kaikki) | `kaikki_provider.py` | CC BY-SA 4.0 |
| Wikidata entities | `wikidata_provider.py` | CC0 1.0 |
| Frequency lists | `frequency_provider.py` | dataset-specific |
| Custom CSV / TXT | `custom_file_provider.py` | operator-provided |

Downloadable dataset files go in `data/datasets/` (see
`data/datasets/README.md`). Import them from the Super Admin **Vocabulary**
page or with the CLI.

### CLI

```bash
# Bundled sample (first run / development)
python scripts/import_words.py --source seed

# A downloaded dataset, auto-detected in data/datasets/
python scripts/import_words.py --source kaikki
python scripts/import_words.py --source wikidata
python scripts/import_words.py --source frequency

# An explicit file
python scripts/import_words.py data/sample_words.csv --source custom

# Rebuild one source from scratch
python scripts/import_words.py --source custom --file words.csv --mode replace

# Resume an interrupted large import from its byte offset
python scripts/import_words.py --source kaikki --resume-offset 12345678

# Download then import (explicit, one-off)
python scripts/import_words.py --source kaikki --download
```

Imports are resumable and cancellable. A failed import never deletes existing
vocabulary.

### Super Admin vocabulary page

`/admin/vocabulary` provides: live database statistics, one-click imports per
source, CSV/TXT/JSONL upload, import history with cancel/retry, and
word-quality filters (max characters, max words, minimum frequency, allow
proper nouns, allow multi-word entries).

### Word modes

`EASY`, `NORMAL`, `HARD`, `CHAOS`. CHAOS spans every difficulty bucket so it
mixes common, technical, proper-noun and rare vocabulary. The host picks the
mode when starting a round.

The bundled `data/sample_words.csv` (259 words) keeps a fresh install playable.
Real deployments import a Wiktionary/Wikidata dump for tens of thousands to
millions of words.

---

## 6. How a game runs

1. Host opens the site and clicks **Create game**, then shares the code
   (for example `X7K9P`) or the invite link `https://your-domain/join/X7K9P`.
2. Players open the link, type a name and join. No account is needed.
3. In the lobby the host assigns teams, picks a captain, board size
   (5x5 or 6x6), difficulty and timer, then clicks **Start round**.
4. Captains see the secret key. Normal players only see the words.
5. Any player can tap a word and submit a guess.
6. The host sees pending guesses and taps **Reveal** or **Reject**. The
   server decides the real card colour, updates the score and turn, and
   checks the win condition.
7. When the round ends the host configures the next round in the lobby.
8. When the evening is over the host clicks **End session**. The invite
   stops working and history stays in the database.

Reveal rules (server side):

| Card     | Result                                                      |
|----------|-------------------------------------------------------------|
| RED      | Red score +1. Red turn continues, otherwise turn changes.   |
| BLUE     | Blue score +1. Blue turn continues, otherwise turn changes. |
| NEUTRAL  | Turn changes.                                               |
| ASSASSIN | Round ends immediately, the opposing team wins.             |

A round also ends when a team finds all of its cards, or when the timer runs
out (the turn changes).

---

## 7. Pages

| Path                    | Purpose                        |
|-------------------------|--------------------------------|
| `/`                     | Landing page                   |
| `/create`               | Create a session               |
| `/join/<code>`          | Join a session                 |
| `/session/<code>`       | Lobby                          |
| `/player/<code>`        | Player game view               |
| `/captain/<code>`       | Captain view (with secret key) |
| `/host/<code>`          | Host dashboard                 |
| `/round/<id>/summary`   | Round summary                  |
| `/session/<code>/summary`| Session summary               |
| `/admin/login`          | Super-admin sign in            |
| `/admin/dashboard`      | Super-admin dashboard          |
| `/admin/sessions`       | All sessions                   |
| `/admin/settings`       | Global settings and flags      |
| `/admin/adsense`        | AdSense configuration          |

---

## 8. Security model

* **Role-based state serialization** - `services/serializers.py` builds three
  different payloads. A player never receives `card_type` for an unrevealed
  card. A captain and the host do.
* **Host token** - the session code identifies the session; a separate random
  host token authorises host actions. Only a hash of the token is stored.
* **Player token** - each player gets a random token, stored as a hash.
* **CSRF** - HTML forms use Flask-WTF CSRF tokens. The JSON action APIs are
  exempt because they require a custom header (`X-Host-Token` /
  `X-Player-Token`) that a cross-site form cannot set.
* **Rate limiting** - lightweight in-process limiters guard joins, guesses
  and admin logins.
* **Server authority** - score, turn, reveals, timer and win conditions are
  all computed on the server. The client only sends an intent.
* **Multi-session isolation** - every query is scoped by `session_id`,
  `round_id` or `player_id`. Socket.IO rooms are named `session:<code>`.

---

## 9. Tests

Unit and integration tests run against a real MySQL/MariaDB test database:

```bash
export TEST_DATABASE_URL="mysql+pymysql://USER:PASSWORD@127.0.0.1/codenames_test?charset=utf8mb4"
python -m pytest tests/ -q
```

The suite covers session lifecycle, round and board generation, game rules,
the timer, security (hidden cards, authorization, session isolation), and the
vocabulary engine (cleaning, classification, providers, dedupe, import
management, admin pages).

Two end-to-end scripts drive a running server:

```bash
python app.py &                      # in one terminal
python tests/e2e_acceptance.py       # full session -> rounds -> end
python tests/e2e_socketio.py         # real-time push + isolation
```

---

## 10. cPanel deployment (Namecheap + Passenger + MySQL)

This is the intended target. Steps assume cPanel with **Setup Python App**.

1. **Create the MySQL database.** In cPanel open *MySQL Databases*. Create a
   database (for example `youracct_codenames`). Create a database user and
   note the password. Add the user to the database with **All Privileges**.

2. **Upload the project.** Put the code in a folder such as
   `/home/youracct/codename`. You can upload a zip in *File Manager* and
   extract it, or clone it over SSH.

3. **Create the Python application.** Open *Setup Python App* and click
   *Create Application*.
   * Python version: 3.10 or newer.
   * Application root: `codename`
   * Application URL: your domain or subdomain.
   * Application startup file: `passenger_wsgi.py`
   * Application entry point: `application`

4. **Install requirements.** cPanel creates a virtualenv for the app. Use the
   command shown on the Python App page, for example:

   ```bash
   source /home/youracct/virtualenv/codename/3.11/bin/activate
   cd /home/youracct/codename
   pip install -r requirements.txt
   ```

5. **Configure environment variables.** Create `.env` in the project root
   (copy `.env.example`). Set `SECRET_KEY`, `DATABASE_URL`,
   `SUPER_ADMIN_USERNAME`, `SUPER_ADMIN_PASSWORD_HASH`,
   `SESSION_COOKIE_SECURE=1`, and `PROXY_FIX=1`. Keep
   `SOCKETIO_ASYNC_MODE=threading` unless your host supports eventlet.

6. **Initialise the database.** From the activated virtualenv:

   ```bash
   python scripts/init_db.py
   flask db upgrade          # optional; init_db.py already created tables
   python scripts/import_words.py data/sample_words.csv --source seed
   ```

7. **Restart the application.** Click *Restart* on the Python App page.

8. **Check the site.** Open your domain. The landing page should load. Create
   a game to confirm the database connection works.

9. **Test Socket.IO.** Open the host dashboard on a desktop and the player
   page on a phone. Start a round. If websockets are blocked by the host, the
   page falls back to long-polling and then to REST polling, so play still
   works. The connection indicator in the header shows the state.

10. **Verify the MySQL connection.** Open `/admin/login`, sign in, and check
    the health card on `/admin/dashboard` (`database: ok`).

### Shared-hosting notes

* Passenger runs a single process by default. `threading` async mode is used
  for Socket.IO so no extra worker is needed.
* If you later run multiple processes and want cross-process Socket.IO, set
  `SOCKETIO_MESSAGE_QUEUE` to a Redis URL.
* Set `SESSION_COOKIE_SECURE=1` once HTTPS is active so cookies are only sent
  over TLS.

---

## 11. Super admin and AdSense

The super admin is separate from a game host. Sign in at `/admin/login` with
the credentials from your environment (or a row in the `users` table).

From the admin panel you can:

* See active and total sessions, players and rounds.
* Search sessions, view details, and terminate a problem session.
* Change global defaults (board size, timer, difficulty) and feature flags.
* Configure AdSense: enable/disable, publisher ID, and one ad slot per page
  area (home, join, player top, player bottom, session summary).

When AdSense is disabled the script is not loaded and no ad boxes are shown.
Ads are only placed in reserved areas and never cover the board, timer,
guesses or host controls.

---

## 12. Project layout

```
codename/
├── app.py                 # application factory
├── wsgi.py                # generic WSGI entry point
├── passenger_wsgi.py      # cPanel / Passenger entry point
├── config.py              # configuration classes
├── extensions.py          # db, migrate, csrf, socketio
├── models/                # SQLAlchemy models
├── routes/                # HTTP blueprints (main, session, player, captain, host, admin)
├── sockets/               # Socket.IO handlers
├── services/              # game logic (board, game manager, timer, serializers, ...)
│   └── vocabulary/        # ingestion engine (cleaner, classifier, providers, importer)
├── templates/             # Jinja2 templates
├── static/                # CSS and vanilla JS
├── scripts/               # init_db.py, import_words.py
├── migrations/            # Alembic migrations
├── data/                  # sample_words.csv, datasets/ (large dumps, git-ignored)
└── tests/                 # pytest suite + e2e scripts
```

---

## 13. License

Provided as-is for private use. Add a license file if you plan to publish it.
