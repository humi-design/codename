"""Game manager - server-authoritative game rules.

All authoritative decisions live here: reveal, score, turn changes, win
conditions, assassin handling, round end and timer expiry.  Routes and socket
handlers only validate input / authorize the caller and then delegate here, so
the rules exist in exactly one place.

Client input is never trusted: the browser may say "reveal QUASAR" but only the
server reads the card type from the database and computes the consequences.
"""

from __future__ import annotations

from extensions import db
from models.constants import (
    CardType,
    EventType,
    GuessStatus,
    Role,
    RoundStatus,
    Team,
    utcnow,
)
from models.guess import Guess
from models.round import Round
from models.round_card import RoundCard
from models.round_player import RoundPlayer
from services.board_generator import BoardGenerator, BoardConfigError
from services.event_logger import EventLogger
from services.security import normalize_word
from services.timer import TimerService


class GameError(Exception):
    """User-facing game error (safe to show to the user)."""


class GameManager:
    # ------------------------------------------------------------- rounds
    @staticmethod
    def next_round_number(session) -> int:
        return (max((r.round_number for r in session.rounds), default=0)) + 1

    @staticmethod
    def create_round(
        session,
        *,
        captain_player_id: int | None = None,
        red_player_ids: list[int] | None = None,
        blue_player_ids: list[int] | None = None,
        board_size: int = 5,
        timer_duration: int = 180,
        word_mode: str = "NORMAL",
    ) -> Round:
        """Create a round in SETUP state with team / captain configuration."""
        try:
            BoardGenerator.distribution_for(board_size)
        except BoardConfigError as exc:
            raise GameError(str(exc)) from exc

        red_ids = list(red_player_ids or [])
        blue_ids = list(blue_player_ids or [])
        overlap = set(red_ids) & set(blue_ids)
        if overlap:
            raise GameError("A player cannot be on both teams.")
        if not red_ids or not blue_ids:
            raise GameError("Both teams need at least one player.")

        valid_ids = {p.id for p in session.players}
        if not (set(red_ids) | set(blue_ids)).issubset(valid_ids):
            raise GameError("One or more selected players are not in this session.")

        round_obj = Round(
            session_id=session.id,
            round_number=GameManager.next_round_number(session),
            status=RoundStatus.SETUP,
            board_size=board_size,
            timer_duration=int(timer_duration),
            word_mode=word_mode,
            current_team=Team.RED,
            captain_player_id=captain_player_id,
        )
        db.session.add(round_obj)
        db.session.flush()

        captain_id = captain_player_id
        # Captain must belong to the team they lead; if the id is invalid the
        # captain defaults to the first player of the RED team.
        if captain_id not in red_ids and captain_id not in blue_ids:
            captain_id = red_ids[0]
            round_obj.captain_player_id = captain_id
        captain_team = Team.RED if captain_id in red_ids else Team.BLUE

        for pid in red_ids:
            db.session.add(
                RoundPlayer(
                    round_id=round_obj.id,
                    player_id=pid,
                    team=Team.RED,
                    role=Role.CAPTAIN if pid == captain_id else Role.PLAYER,
                )
            )
        for pid in blue_ids:
            db.session.add(
                RoundPlayer(
                    round_id=round_obj.id,
                    player_id=pid,
                    team=Team.BLUE,
                    role=Role.CAPTAIN if pid == captain_id else Role.PLAYER,
                )
            )

        # Generate the board now so the host can preview, but it stays hidden
        # from players until the round starts (status SETUP).
        BoardGenerator.generate_board(
            round_obj.id, board_size=board_size, mode=word_mode
        )
        round_obj.current_team = captain_team
        session.touch()
        db.session.commit()
        return round_obj

    @staticmethod
    def start_round(session, round_obj: Round) -> Round:
        if round_obj.status == RoundStatus.ENDED:
            raise GameError("This round has ended.")
        if not round_obj.cards:
            BoardGenerator.generate_board(
                round_obj.id, board_size=round_obj.board_size, mode=round_obj.word_mode
            )
        round_obj.status = RoundStatus.ACTIVE
        round_obj.started_at = utcnow()
        TimerService.start(round_obj)
        session.touch()
        EventLogger.log(
            session.id,
            EventType.ROUND_STARTED,
            round_id=round_obj.id,
            data={"round_number": round_obj.round_number,
                  "current_team": round_obj.current_team},
        )
        db.session.commit()
        return round_obj

    @staticmethod
    def end_round(session, round_obj: Round, *, winner: str | None = None,
                  reason: str = "MANUAL") -> Round:
        if round_obj.status == RoundStatus.ENDED:
            return round_obj
        round_obj.status = RoundStatus.ENDED
        round_obj.ended_at = utcnow()
        round_obj.winner = winner
        # Freeze the timer.
        TimerService.pause(round_obj)
        # Reject any still-pending guesses.
        for guess in round_obj.guesses:
            if guess.status == GuessStatus.PENDING:
                guess.status = GuessStatus.REJECTED
                guess.resolved_at = utcnow()
        session.touch()
        EventLogger.log(
            session.id,
            EventType.ROUND_ENDED,
            round_id=round_obj.id,
            data={"winner": winner, "reason": reason},
        )
        db.session.commit()
        return round_obj

    # ---------------------------------------------------------- team setup
    @staticmethod
    def update_round_config(session, round_obj: Round, *,
                            captain_player_id: int | None = None,
                            red_player_ids: list[int] | None = None,
                            blue_player_ids: list[int] | None = None,
                            timer_duration: int | None = None,
                            board_size: int | None = None,
                            word_mode: str | None = None) -> Round:
        """Change teams / captain / settings before the round starts."""
        if round_obj.status != RoundStatus.SETUP:
            raise GameError("Teams can only be changed before the round starts.")

        if red_player_ids is not None or blue_player_ids is not None:
            red_ids = list(red_player_ids if red_player_ids is not None
                           else [rp.player_id for rp in round_obj.players_for(Team.RED)])
            blue_ids = list(blue_player_ids if blue_player_ids is not None
                            else [rp.player_id for rp in round_obj.players_for(Team.BLUE)])
            if set(red_ids) & set(blue_ids):
                raise GameError("A player cannot be on both teams.")
            if not red_ids or not blue_ids:
                raise GameError("Both teams need at least one player.")
            valid_ids = {p.id for p in session.players}
            if not (set(red_ids) | set(blue_ids)).issubset(valid_ids):
                raise GameError("One or more selected players are not in this session.")

            RoundPlayer.query.filter_by(round_id=round_obj.id).delete()
            for pid in red_ids:
                db.session.add(RoundPlayer(round_id=round_obj.id, player_id=pid,
                                           team=Team.RED, role=Role.PLAYER))
            for pid in blue_ids:
                db.session.add(RoundPlayer(round_id=round_obj.id, player_id=pid,
                                           team=Team.BLUE, role=Role.PLAYER))
            db.session.flush()

        if captain_player_id is not None:
            rp = RoundPlayer.query.filter_by(
                round_id=round_obj.id, player_id=captain_player_id
            ).first()
            if rp is None:
                raise GameError("The chosen captain is not part of this round.")
            RoundPlayer.query.filter_by(round_id=round_obj.id).update(
                {RoundPlayer.role: Role.PLAYER}
            )
            rp.role = Role.CAPTAIN
            round_obj.captain_player_id = captain_player_id
            round_obj.current_team = rp.team
            EventLogger.log(session.id, EventType.CAPTAIN_CHANGED, round_id=round_obj.id,
                            player_id=captain_player_id, data={"team": rp.team})

        if timer_duration is not None:
            if not (10 <= int(timer_duration) <= 3600):
                raise GameError("Timer must be between 10 and 3600 seconds.")
            round_obj.timer_duration = int(timer_duration)

        if board_size is not None and int(board_size) != round_obj.board_size:
            try:
                BoardGenerator.distribution_for(int(board_size))
            except BoardConfigError as exc:
                raise GameError(str(exc)) from exc
            # Board has not started yet -> safe to regenerate.
            RoundCard.query.filter_by(round_id=round_obj.id).delete()
            round_obj.board_size = int(board_size)
            BoardGenerator.generate_board(round_obj.id, board_size=int(board_size),
                                          mode=round_obj.word_mode)

        if word_mode is not None:
            round_obj.word_mode = word_mode

        session.touch()
        db.session.commit()
        return round_obj

    # --------------------------------------------------------------- turns
    @staticmethod
    def switch_turn(session, round_obj: Round, *, reason: str = "MANUAL") -> None:
        if round_obj.status == RoundStatus.ENDED:
            raise GameError("This round has ended.")
        round_obj.current_team = Team.opponent(round_obj.current_team)
        EventLogger.log(session.id, EventType.TURN_CHANGED, round_id=round_obj.id,
                        data={"current_team": round_obj.current_team, "reason": reason})
        session.touch()

    # -------------------------------------------------------------- reveal
    @staticmethod
    def _apply_card_reveal(session, round_obj: Round, card: RoundCard,
                           actor_player_id: int | None) -> dict:
        """Apply the consequences of revealing ``card``. Returns a result dict."""
        card.is_revealed = True
        card.revealed_at = utcnow()
        card.revealed_by = actor_player_id

        result = {"card_type": card.card_type, "word": card.word, "winner": None}

        if card.card_type == CardType.ASSASSIN:
            winner = Team.opponent(round_obj.current_team)
            result["winner"] = winner
            result["round_ended"] = True
            GameManager._sync_scores(round_obj)
            EventLogger.log(session.id, EventType.CARD_REVEALED, round_id=round_obj.id,
                            player_id=actor_player_id,
                            data={"word": card.word, "type": card.card_type})
            GameManager.end_round(session, round_obj, winner=winner, reason="ASSASSIN")
            return result

        # Colour reveal -> that colour takes/continues the turn.
        if card.card_type == CardType.NEUTRAL:
            round_obj.current_team = Team.opponent(round_obj.current_team)
            result["turn_changed"] = True
        elif card.card_type in (CardType.RED, CardType.BLUE):
            round_obj.current_team = card.card_type

        GameManager._sync_scores(round_obj)
        EventLogger.log(session.id, EventType.CARD_REVEALED, round_id=round_obj.id,
                        player_id=actor_player_id,
                        data={"word": card.word, "type": card.card_type,
                              "current_team": round_obj.current_team})

        # Win condition: all cards of a colour revealed.
        for team in (CardType.RED, CardType.BLUE):
            if round_obj.remaining(team) == 0:
                result["winner"] = team
                result["round_ended"] = True
                GameManager.end_round(session, round_obj, winner=team, reason="ALL_FOUND")
                return result

        return result

    @staticmethod
    def _sync_scores(round_obj: Round) -> None:
        """Store revealed counts (display uses remaining)."""
        round_obj.red_score = sum(
            1 for c in round_obj.cards if c.card_type == CardType.RED and c.is_revealed
        )
        round_obj.blue_score = sum(
            1 for c in round_obj.cards if c.card_type == CardType.BLUE and c.is_revealed
        )

    @staticmethod
    def reveal_card(session, round_obj: Round, card_id: int,
                    actor_player_id: int | None) -> dict:
        if round_obj.status == RoundStatus.ENDED:
            raise GameError("This round has ended.")
        card = next((c for c in round_obj.cards if c.id == card_id), None)
        if card is None:
            raise GameError("That card does not exist on this board.")
        if card.is_revealed:
            raise GameError("That card has already been revealed.")
        return GameManager._apply_card_reveal(session, round_obj, card, actor_player_id)

    # -------------------------------------------------------------- guesses
    @staticmethod
    def submit_guess(session, round_obj: Round, player, word: str) -> Guess:
        if round_obj.status != RoundStatus.ACTIVE:
            raise GameError("You can only guess while the round is active.")
        normalized = normalize_word(word)
        if not normalized:
            raise GameError("Please choose a word to guess.")
        card = next(
            (c for c in round_obj.cards if normalize_word(c.word) == normalized), None
        )
        if card is None:
            raise GameError("That word is not on the board.")
        if card.is_revealed:
            raise GameError("That card has already been revealed.")

        # Consolidate: if the same word already has a pending guess, do not
        # create a duplicate row - just record who else submitted it.
        existing = next(
            (g for g in round_obj.guesses
             if g.status == GuessStatus.PENDING and g.normalized_word == normalized),
            None,
        )
        if existing is not None and existing.player_id == player.id:
            raise GameError("This guess has already been submitted.")
        if existing is not None:
            # Another player already guessed it; still log the submission.
            EventLogger.log(session.id, EventType.GUESS_SUBMITTED, round_id=round_obj.id,
                            player_id=player.id, data={"word": normalized, "duplicate": True})
            session.touch()
            db.session.commit()
            return existing

        guess = Guess(
            round_id=round_obj.id,
            player_id=player.id,
            card_id=card.id,
            word=card.word,
            normalized_word=normalized,
            status=GuessStatus.PENDING,
        )
        db.session.add(guess)
        EventLogger.log(session.id, EventType.GUESS_SUBMITTED, round_id=round_obj.id,
                        player_id=player.id, data={"word": normalized})
        session.touch()
        db.session.commit()
        return guess

    @staticmethod
    def resolve_guess(session, round_obj: Round, normalized_word: str,
                      host_player_id: int | None, *, accept: bool) -> dict:
        """Reveal (accept) or reject all pending guesses for a word."""
        if round_obj.status == RoundStatus.ENDED:
            raise GameError("This round has ended.")
        normalized = normalize_word(normalized_word)
        pending = [
            g for g in round_obj.guesses
            if g.status == GuessStatus.PENDING and g.normalized_word == normalized
        ]
        if not pending:
            raise GameError("This guess has already been resolved.")

        now = utcnow()
        if not accept:
            for guess in pending:
                guess.status = GuessStatus.REJECTED
                guess.resolved_at = now
                guess.resolved_by = host_player_id
            EventLogger.log(session.id, EventType.GUESS_REJECTED, round_id=round_obj.id,
                            player_id=host_player_id, data={"word": normalized})
            session.touch()
            db.session.commit()
            return {"accepted": False, "word": normalized}

        card = next(
            (c for c in round_obj.cards if normalize_word(c.word) == normalized), None
        )
        if card is None:
            raise GameError("That word is not on the board.")
        if card.is_revealed:
            raise GameError("That card has already been revealed.")

        for guess in pending:
            guess.status = GuessStatus.REVEALED
            guess.resolved_at = now
            guess.resolved_by = host_player_id

        result = GameManager._apply_card_reveal(
            session, round_obj, card, host_player_id
        )
        db.session.commit()
        result["accepted"] = True
        return result

    # -------------------------------------------------------------- timer
    @staticmethod
    def handle_timer_expiry(session, round_obj: Round) -> dict:
        """Time's up: end the current turn and restart the timer."""
        if round_obj.status != RoundStatus.ACTIVE:
            return {"ignored": True}
        if not TimerService.is_expired(round_obj):
            return {"ignored": True}
        GameManager.switch_turn(session, round_obj, reason="TIMER_EXPIRED")
        TimerService.reset(round_obj, round_obj.timer_duration)
        TimerService.start(round_obj)
        db.session.commit()
        return {"turn_changed": True, "current_team": round_obj.current_team}
