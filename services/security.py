"""Security helpers: tokens, hashing, session codes and rate limiting.

The session code *identifies* a session; the host/player token *authenticates*
the actor.  Tokens are only ever stored as hashes.
"""

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from werkzeug.security import check_password_hash, generate_password_hash

# Ambiguous characters (0/O/1/I) are intentionally excluded from codes.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 5
TOKEN_BYTES = 32


def generate_session_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def generate_token() -> str:
    """Return a URL-safe, high-entropy token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Hash a token for storage.

    Uses Werkzeug's password hashing (PBKDF2) so a leaked database row cannot
    be turned back into a usable token.
    """
    return generate_password_hash(token)


def verify_token(token: str, token_hash: str) -> bool:
    if not token or not token_hash:
        return False
    try:
        return check_password_hash(token_hash, token)
    except (ValueError, TypeError):
        return False


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")


def normalize_word(value: str) -> str:
    """Normalise a guess/word for duplicate detection."""
    if not value:
        return ""
    return " ".join(value.strip().upper().split())


class RateLimiter:
    """Small in-memory sliding-window limiter.

    Shared-hosting friendly: no Redis required.  It is intentionally
    best-effort - the authoritative checks live in the game services.
    """

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_events:
                return False
            bucket.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


# Pre-configured limiters used by routes and sockets.
login_limiter = RateLimiter(max_events=10, window_seconds=300)
join_limiter = RateLimiter(max_events=30, window_seconds=60)
guess_limiter = RateLimiter(max_events=30, window_seconds=60)
create_limiter = RateLimiter(max_events=20, window_seconds=300)
