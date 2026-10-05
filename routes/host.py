"""Host dashboard, host-only action APIs, and round summary."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from models.constants import RoundStatus
from routes.helpers import (
    host_action,
    load_session_or_404,
    require_host_page,
    resolve_host_header,
    resolve_host_token,
)
from services.broadcaster import Broadcaster
from services.game_manager import GameError, GameManager
from services.serializers import VIEWER_HOST, build_state
from services.session_manager import SessionManager
from services.timer import TimerService

host_bp = Blueprint("host", __name__)


def _get_round_or_404(session, round_id: int):
    rnd = next((r for r in session.rounds if r.id == round_id), None)
    if rnd is None:
        abort(404)
    return rnd


# ------------------------------------------------------------------- pages
@host_bp.route("/host/<session_code>")
def dashboard(session_code: str):
    code = session_code.strip().upper()
    game_session, host_token = require_host_page(code)
    round_obj = game_session.live_round() or game_session.current_round()
    state = build_state(game_session, VIEWER_HOST)
    return render_template(
        "host.html",
        game_session=game_session,
        host_token=host_token,
        state=state,
        round_obj=round_obj,
    )


@host_bp.route("/round/<int:round_id>/summary")
def round_summary(round_id: int):
    from models.round import Round

    round_obj = Round.query.get(round_id)
    if round_obj is None:
        abort(404)
    code = round_obj.session.session_code
    host_token = resolve_host_token(code)
    is_host = bool(host_token and SessionManager.is_host(round_obj.session, host_token))
    if not is_host:
        # Players may view a finished round summary.
        from routes.helpers import resolve_player_token

        token = resolve_player_token(code)
        player = SessionManager.authenticate_player(round_obj.session, token) if token else None
        if player is None or round_obj.status != RoundStatus.ENDED:
            abort(403)

    summary = {
        "round_number": round_obj.round_number,
        "winner": round_obj.winner,
        "red_total": round_obj.total_for("RED"),
        "blue_total": round_obj.total_for("BLUE"),
        "red_found": round_obj.total_for("RED") - round_obj.remaining("RED"),
        "blue_found": round_obj.total_for("BLUE") - round_obj.remaining("BLUE"),
        "captain_name": round_obj.captain.display_name if round_obj.captain else None,
        "started_at": round_obj.started_at,
        "ended_at": round_obj.ended_at,
    }
    return render_template(
        "round_summary.html",
        game_session=round_obj.session,
        round_obj=round_obj,
        summary=summary,
        is_host=is_host,
        next_round_number=GameManager.next_round_number(round_obj.session),
    )


@host_bp.route("/api/host/<session_code>/state")
def state_api(session_code: str):
    code = session_code.strip().upper()
    game_session = load_session_or_404(code)
    token = resolve_host_header(code)
    if not token or not SessionManager.is_host(game_session, token):
        return jsonify(error="You are not authorized to perform this action."), 403
    return jsonify(build_state(game_session, VIEWER_HOST))


# ----------------------------------------------------------- round control
@host_bp.route("/api/host/<session_code>/rounds", methods=["POST"])
@host_action
def create_round(game_session):
    data = request.get_json(silent=True) or {}
    round_obj = GameManager.create_round(
        game_session,
        captain_player_id=_int_or_none(data.get("captain_player_id")),
        red_player_ids=_int_list(data.get("red_player_ids")),
        blue_player_ids=_int_list(data.get("blue_player_ids")),
        board_size=int(data.get("board_size") or 5),
        timer_duration=int(data.get("timer_duration") or 180),
        word_mode=(data.get("word_mode") or "NORMAL").upper(),
    )
    Broadcaster.push_state(game_session)
    current_app.logger.info("Round %s created in %s", round_obj.round_number,
                            game_session.session_code)
    return jsonify(ok=True, round_id=round_obj.id)


@host_bp.route("/api/host/<session_code>/rounds/<int:round_id>/config", methods=["POST"])
@host_action
def configure_round(game_session, round_id: int):
    round_obj = _get_round_or_404(game_session, round_id)
    data = request.get_json(silent=True) or {}
    GameManager.update_round_config(
        game_session,
        round_obj,
        captain_player_id=_int_or_none(data.get("captain_player_id")),
        red_player_ids=_int_list(data.get("red_player_ids")),
        blue_player_ids=_int_list(data.get("blue_player_ids")),
        timer_duration=_int_or_none(data.get("timer_duration")),
        board_size=_int_or_none(data.get("board_size")),
        word_mode=(data.get("word_mode") or None),
    )
    Broadcaster.push_state(game_session)
    return jsonify(ok=True)


@host_bp.route("/api/host/<session_code>/rounds/<int:round_id>/start", methods=["POST"])
@host_action
def start_round(game_session, round_id: int):
    round_obj = _get_round_or_404(game_session, round_id)
    GameManager.start_round(game_session, round_obj)
    Broadcaster.push_state(game_session)
    Broadcaster.event(game_session, "round_started", {"round_id": round_obj.id})
    current_app.logger.info("Round %s started in %s", round_obj.round_number,
                            game_session.session_code)
    return jsonify(ok=True)


@host_bp.route("/api/host/<session_code>/rounds/<int:round_id>/end", methods=["POST"])
@host_action
def end_round(game_session, round_id: int):
    round_obj = _get_round_or_404(game_session, round_id)
    data = request.get_json(silent=True) or {}
    winner = data.get("winner") or round_obj.winner
    GameManager.end_round(game_session, round_obj, winner=winner, reason="MANUAL")
    Broadcaster.push_state(game_session)
    Broadcaster.event(game_session, "round_ended", {"winner": winner})
    return jsonify(ok=True, winner=winner)


@host_bp.route("/api/host/<session_code>/rounds/<int:round_id>/turn", methods=["POST"])
@host_action
def switch_turn(game_session, round_id: int):
    round_obj = _get_round_or_404(game_session, round_id)
    GameManager.switch_turn(game_session, round_obj)
    from extensions import db

    db.session.commit()
    Broadcaster.push_state(game_session)
    Broadcaster.event(game_session, "turn_changed",
                      {"current_team": round_obj.current_team})
    return jsonify(ok=True, current_team=round_obj.current_team)


@host_bp.route("/api/host/<session_code>/rounds/<int:round_id>/timer", methods=["POST"])
@host_action
def timer_action(game_session, round_id: int):
    round_obj = _get_round_or_404(game_session, round_id)
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()

    if action == "start":
        TimerService.start(round_obj)
        event = "timer_started"
    elif action == "pause":
        TimerService.pause(round_obj)
        event = "timer_paused"
    elif action == "resume":
        TimerService.resume(round_obj)
        event = "timer_resumed"
    elif action == "reset":
        TimerService.reset(round_obj, _int_or_none(data.get("duration")))
        event = "timer_reset"
    else:
        raise GameError("Unknown timer action.")

    from extensions import db

    db.session.commit()
    Broadcaster.push_state(game_session)
    Broadcaster.event(game_session, event, TimerService.state(round_obj))
    return jsonify(ok=True, timer=TimerService.state(round_obj))


# --------------------------------------------------------------- reveal
@host_bp.route("/api/host/<session_code>/rounds/<int:round_id>/reveal", methods=["POST"])
@host_action
def reveal(game_session, round_id: int):
    round_obj = _get_round_or_404(game_session, round_id)
    data = request.get_json(silent=True) or {}
    card_id = _int_or_none(data.get("card_id"))
    if card_id is None:
        raise GameError("No card specified.")
    host_player = next((p for p in game_session.players if p.is_host), None)
    result = GameManager.reveal_card(
        game_session, round_obj, card_id,
        host_player.id if host_player else None,
    )
    Broadcaster.push_state(game_session)
    Broadcaster.event(game_session, "card_revealed",
                      {"word": result["word"], "type": result["card_type"]})
    if result.get("round_ended"):
        Broadcaster.event(game_session, "round_ended",
                          {"winner": result.get("winner")})
    return jsonify(ok=True, **{k: v for k, v in result.items() if k != "card_type"})


@host_bp.route("/api/host/<session_code>/rounds/<int:round_id>/guess/resolve",
               methods=["POST"])
@host_action
def resolve_guess(game_session, round_id: int):
    round_obj = _get_round_or_404(game_session, round_id)
    data = request.get_json(silent=True) or {}
    normalized = data.get("normalized_word")
    accept = bool(data.get("accept"))
    if not normalized:
        raise GameError("No guess specified.")
    host_player = next((p for p in game_session.players if p.is_host), None)
    result = GameManager.resolve_guess(
        game_session, round_obj, normalized,
        host_player.id if host_player else None, accept=accept,
    )
    Broadcaster.push_state(game_session)
    if result.get("accepted"):
        Broadcaster.event(game_session, "card_revealed",
                          {"word": result["word"], "type": result["card_type"]})
    else:
        Broadcaster.event(game_session, "guess_rejected", {"word": result["word"]})
    if result.get("round_ended"):
        Broadcaster.event(game_session, "round_ended",
                          {"winner": result.get("winner")})
    return jsonify(ok=True, accepted=result.get("accepted"),
                   winner=result.get("winner"), round_ended=result.get("round_ended", False))


# ----------------------------------------------------------- session end
@host_bp.route("/api/host/<session_code>/end", methods=["POST"])
@host_action
def end_session(game_session):
    SessionManager.end_session(game_session)
    Broadcaster.push_state(game_session)
    Broadcaster.event(game_session, "session_ended", {"code": game_session.session_code})
    current_app.logger.info("Session %s ended", game_session.session_code)
    return jsonify(ok=True, redirect=url_for("main.session_summary",
                                             session_code=game_session.session_code))


# ---------------------------------------------------------------- helpers
def _int_or_none(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_list(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = [v for v in value.split(",") if v.strip()]
    result = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result
