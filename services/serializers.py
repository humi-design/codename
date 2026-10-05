"""State serializers.

This module is the single security boundary that decides what each viewer is
allowed to see.  Three viewer roles exist:

    HOST     -> complete board (card types even before reveal) + controls
    CAPTAIN  -> complete board key (spymaster view)
    PLAYER   -> words only; card types are withheld until a card is revealed

The frontend never receives hidden card types for a normal player, so a
malicious player cannot read the answer from the network tab or JS.
"""

from __future__ import annotations

from models.constants import CardType, GuessStatus, Role
from services.timer import TimerService

VIEWER_HOST = "HOST"
VIEWER_CAPTAIN = "CAPTAIN"
VIEWER_PLAYER = "PLAYER"


# ---------------------------------------------------------------- players
def serialize_player(player) -> dict:
    return {
        "id": player.id,
        "name": player.display_name,
        "connected": bool(player.is_connected),
        "is_host": bool(player.is_host),
    }


def serialize_round_player(rp) -> dict:
    return {
        "player_id": rp.player_id,
        "name": rp.player.display_name if rp.player else "",
        "team": rp.team,
        "role": rp.role,
        "connected": bool(rp.player.is_connected) if rp.player else False,
    }


# ------------------------------------------------------------------ cards
def serialize_card(card, viewer_role: str) -> dict:
    """Serialize a single card according to the viewer's role."""
    reveal_type = viewer_role in (VIEWER_HOST, VIEWER_CAPTAIN)
    data = {
        "id": card.id,
        "position": card.position,
        "word": card.word,
        "revealed": bool(card.is_revealed),
        # Once revealed the type is public information for everyone.
        "revealed_type": card.card_type if card.is_revealed else None,
    }
    if reveal_type:
        # Host & captain additionally receive the hidden assignment.
        data["card_type"] = card.card_type
    return data


def serialize_board(round_obj, viewer_role: str) -> list[dict]:
    return [serialize_card(c, viewer_role) for c in round_obj.cards]


# ---------------------------------------------------------------- guesses
def serialize_guess(guess) -> dict:
    return {
        "id": guess.id,
        "word": guess.word,
        "normalized_word": guess.normalized_word,
        "status": guess.status,
        "player_id": guess.player_id,
        "player_name": guess.player.display_name if guess.player else "",
        "submitted_at": guess.submitted_at.isoformat() if guess.submitted_at else None,
    }


def serialize_pending_guesses(round_obj) -> list[dict]:
    """Consolidate duplicate pending guesses into one entry per word."""
    grouped: dict[str, dict] = {}
    for guess in round_obj.guesses:
        if guess.status != GuessStatus.PENDING:
            continue
        key = guess.normalized_word
        entry = grouped.get(key)
        if entry is None:
            entry = {
                "normalized_word": key,
                "word": guess.word,
                "card_id": guess.card_id,
                "guess_ids": [],
                "submitters": [],
                "submitted_at": guess.submitted_at.isoformat()
                if guess.submitted_at
                else None,
            }
            grouped[key] = entry
        entry["guess_ids"].append(guess.id)
        entry["submitters"].append(
            {
                "id": guess.player_id,
                "name": guess.player.display_name if guess.player else "",
            }
        )
    # Oldest first.
    return sorted(grouped.values(), key=lambda e: e["submitted_at"] or "")


# ------------------------------------------------------------------ round
def serialize_round(round_obj, viewer_role: str, viewer_player=None) -> dict:
    if round_obj is None:
        return None

    data = {
        "id": round_obj.id,
        "round_number": round_obj.round_number,
        "status": round_obj.status,
        "board_size": round_obj.board_size,
        "word_mode": round_obj.word_mode,
        "current_team": round_obj.current_team,
        "winner": round_obj.winner,
        "captain_player_id": round_obj.captain_player_id,
        "captain_name": round_obj.captain.display_name if round_obj.captain else None,
        "scores": {
            "red": round_obj.remaining(CardType.RED),
            "blue": round_obj.remaining(CardType.BLUE),
            "red_total": round_obj.total_for(CardType.RED),
            "blue_total": round_obj.total_for(CardType.BLUE),
        },
        "timer": TimerService.state(round_obj),
        "board": serialize_board(round_obj, viewer_role),
        "players": {
            "red": [serialize_round_player(rp) for rp in round_obj.players_for("RED")],
            "blue": [serialize_round_player(rp) for rp in round_obj.players_for("BLUE")],
        },
        "pending_guesses": serialize_pending_guesses(round_obj),
    }

    if viewer_role in (VIEWER_HOST, VIEWER_CAPTAIN):
        data["distribution"] = {
            "red": round_obj.total_for(CardType.RED),
            "blue": round_obj.total_for(CardType.BLUE),
            "neutral": sum(
                1 for c in round_obj.cards if c.card_type == CardType.NEUTRAL
            ),
            "assassin": sum(
                1 for c in round_obj.cards if c.card_type == CardType.ASSASSIN
            ),
        }

    if viewer_player is not None:
        rp = next(
            (x for x in round_obj.round_players if x.player_id == viewer_player.id),
            None,
        )
        data["my_team"] = rp.team if rp else None
        data["my_role"] = rp.role if rp else None
    return data


# ------------------------------------------------------------------- view
def build_state(session, viewer_role: str, viewer_player=None) -> dict:
    """Full serialized state for a viewer."""
    round_obj = session.live_round() or session.current_round()
    return {
        "session": {
            "id": session.id,
            "code": session.session_code,
            "status": session.status,
            "host_name": session.host_name,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        },
        "viewer": {
            "role": viewer_role,
            "player_id": viewer_player.id if viewer_player else None,
            "name": viewer_player.display_name if viewer_player else session.host_name,
        },
        "players": [serialize_player(p) for p in session.players],
        "round": serialize_round(round_obj, viewer_role, viewer_player),
        "server_time": __import__("models.constants", fromlist=["utcnow"]).utcnow().isoformat(),
    }
