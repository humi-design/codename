"""Model package - imports every model so SQLAlchemy sees them."""

from models.app_setting import AppSetting
from models.constants import (
    BOARD_DISTRIBUTIONS,
    CardType,
    Category,
    EventType,
    GuessStatus,
    ImportStatus,
    Role,
    RoundStatus,
    SessionStatus,
    Team,
    UserRole,
    VocabularyStatus,
    WordMode,
)
from models.game_session import GameSession
from models.guess import Guess
from models.round import Round
from models.round_card import RoundCard
from models.round_player import RoundPlayer
from models.session_event import SessionEvent
from models.session_player import SessionPlayer
from models.user import User
from models.vocabulary_import import VocabularyImport
from models.vocabulary_source import VocabularySource
from models.word import Word

__all__ = [
    "AppSetting",
    "GameSession",
    "Guess",
    "Round",
    "RoundCard",
    "RoundPlayer",
    "SessionEvent",
    "SessionPlayer",
    "User",
    "VocabularyImport",
    "VocabularySource",
    "Word",
    "BOARD_DISTRIBUTIONS",
    "CardType",
    "Category",
    "EventType",
    "GuessStatus",
    "ImportStatus",
    "Role",
    "RoundStatus",
    "SessionStatus",
    "Team",
    "UserRole",
    "VocabularyStatus",
    "WordMode",
]
