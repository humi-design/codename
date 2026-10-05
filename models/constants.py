"""Shared constants and small helpers used across the models."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return a naive UTC timestamp.

    MySQL ``DATETIME`` columns are timezone-naive, so we consistently store
    UTC without tzinfo to avoid comparison surprises.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SessionStatus:
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"

    ALL = (ACTIVE, ENDED)


class RoundStatus:
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"

    ALL = (SETUP, ACTIVE, PAUSED, ENDED)


class Team:
    RED = "RED"
    BLUE = "BLUE"

    ALL = (RED, BLUE)

    @classmethod
    def opponent(cls, team: str) -> str:
        return cls.BLUE if team == cls.RED else cls.RED


class Role:
    PLAYER = "PLAYER"
    CAPTAIN = "CAPTAIN"

    ALL = (PLAYER, CAPTAIN)


class CardType:
    RED = "RED"
    BLUE = "BLUE"
    NEUTRAL = "NEUTRAL"
    ASSASSIN = "ASSASSIN"

    ALL = (RED, BLUE, NEUTRAL, ASSASSIN)


class GuessStatus:
    PENDING = "PENDING"
    REVEALED = "REVEALED"
    REJECTED = "REJECTED"

    ALL = (PENDING, REVEALED, REJECTED)


class EventType:
    PLAYER_JOINED = "PLAYER_JOINED"
    PLAYER_LEFT = "PLAYER_LEFT"
    ROUND_STARTED = "ROUND_STARTED"
    CAPTAIN_CHANGED = "CAPTAIN_CHANGED"
    TEAM_CHANGED = "TEAM_CHANGED"
    GUESS_SUBMITTED = "GUESS_SUBMITTED"
    GUESS_REJECTED = "GUESS_REJECTED"
    CARD_REVEALED = "CARD_REVEALED"
    TURN_CHANGED = "TURN_CHANGED"
    ROUND_ENDED = "ROUND_ENDED"
    SESSION_ENDED = "SESSION_ENDED"
    TIMER_STARTED = "TIMER_STARTED"
    TIMER_PAUSED = "TIMER_PAUSED"
    TIMER_RESUMED = "TIMER_RESUMED"
    TIMER_RESET = "TIMER_RESET"


class WordMode:
    EASY = "EASY"
    NORMAL = "NORMAL"
    HARD = "HARD"
    CHAOS = "CHAOS"
    CUSTOM = "CUSTOM"

    ALL = (EASY, NORMAL, HARD, CHAOS, CUSTOM)


class UserRole:
    SUPER_ADMIN = "super_admin"

    ALL = (SUPER_ADMIN,)


# Default board distribution per board size.  Values sum to size*size.
# Keyed by board edge length.
BOARD_DISTRIBUTIONS = {
    5: {CardType.RED: 9, CardType.BLUE: 8, CardType.NEUTRAL: 7, CardType.ASSASSIN: 1},
    6: {CardType.RED: 11, CardType.BLUE: 10, CardType.NEUTRAL: 13, CardType.ASSASSIN: 2},
}
