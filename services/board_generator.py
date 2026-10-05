"""Board generator.

Responsibilities:
    1. Select unique words.
    2. Validate duplicates.
    3. Select card assignments (distribution).
    4. Randomise positions.
    5. Persist board rows against a ``round_id``.

A board is generated exactly once per round; it is never regenerated on a page
refresh because it is read back from ``round_cards``.
"""

from __future__ import annotations

import random

from extensions import db
from models.constants import BOARD_DISTRIBUTIONS, CardType
from models.round_card import RoundCard
from services.word_engine import WordEngine


class BoardConfigError(ValueError):
    """Raised when a requested board configuration is invalid."""


class BoardGenerator:
    DEFAULT_DISTRIBUTIONS = BOARD_DISTRIBUTIONS

    # ---------------------------------------------------------- validation
    @staticmethod
    def distribution_for(board_size: int) -> dict[str, int]:
        if board_size not in BoardGenerator.DEFAULT_DISTRIBUTIONS:
            raise BoardConfigError(f"Unsupported board size: {board_size}")
        return dict(BoardGenerator.DEFAULT_DISTRIBUTIONS[board_size])

    @staticmethod
    def validate_distribution(board_size: int, distribution: dict[str, int]) -> None:
        total_cards = board_size * board_size
        total_assigned = sum(int(distribution.get(t, 0)) for t in CardType.ALL)
        if total_assigned != total_cards:
            raise BoardConfigError(
                f"Distribution sums to {total_assigned} but board has {total_cards} cards"
            )
        for card_type in CardType.ALL:
            if int(distribution.get(card_type, 0)) < 0:
                raise BoardConfigError(f"Negative count for {card_type}")

    # ------------------------------------------------------------ generate
    @staticmethod
    def build_distribution(board_size: int, distribution: dict[str, int] | None = None):
        """Return a shuffled list of card types (length == board_size**2)."""
        distribution = distribution or BoardGenerator.distribution_for(board_size)
        BoardGenerator.validate_distribution(board_size, distribution)
        deck: list[str] = []
        for card_type in CardType.ALL:
            deck.extend([card_type] * int(distribution.get(card_type, 0)))
        random.shuffle(deck)
        return deck

    @staticmethod
    def generate_board(
        round_id: int,
        board_size: int = 5,
        mode: str = "NORMAL",
        distribution: dict[str, int] | None = None,
    ) -> list[RoundCard]:
        """Create and persist the board for ``round_id``.

        Idempotent: if cards already exist for the round they are returned
        unchanged, so a page refresh can never regenerate the board.
        """
        existing = RoundCard.query.filter_by(round_id=round_id).order_by(
            RoundCard.position
        ).all()
        if existing:
            return existing

        total_cards = board_size * board_size
        words = WordEngine.pick_words(total_cards, mode=mode)

        # Defensive duplicate check.
        if len(set(words)) != len(words):
            raise BoardConfigError("Duplicate words selected for board")

        deck = BoardGenerator.build_distribution(board_size, distribution)

        cards = []
        for position, (word, card_type) in enumerate(zip(words, deck)):
            card = RoundCard(
                round_id=round_id,
                position=position,
                word=word,
                card_type=card_type,
                is_revealed=False,
            )
            db.session.add(card)
            cards.append(card)

        db.session.flush()
        return cards
