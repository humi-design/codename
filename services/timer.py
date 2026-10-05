"""Server-authoritative timer.

Timestamps are stored, never ticked, so the database is not written every
second.  The client renders the countdown locally and re-syncs on events.
"""

from __future__ import annotations

from datetime import timedelta

from models.constants import utcnow


class TimerService:
    @staticmethod
    def start(round_obj) -> None:
        now = utcnow()
        round_obj.timer_started_at = now
        round_obj.timer_paused_at = None

    @staticmethod
    def pause(round_obj) -> None:
        if round_obj.timer_paused_at is None:
            round_obj.timer_paused_at = utcnow()

    @staticmethod
    def resume(round_obj) -> None:
        """Shift the start timestamp forward by the paused duration."""
        if round_obj.timer_paused_at is None or round_obj.timer_started_at is None:
            round_obj.timer_paused_at = None
            return
        paused_for = utcnow() - round_obj.timer_paused_at
        round_obj.timer_started_at = round_obj.timer_started_at + paused_for
        round_obj.timer_paused_at = None

    @staticmethod
    def reset(round_obj, duration: int | None = None) -> None:
        if duration is not None:
            round_obj.timer_duration = int(duration)
        round_obj.timer_started_at = None
        round_obj.timer_paused_at = None

    @staticmethod
    def seconds_remaining(round_obj) -> int | None:
        """Remaining seconds, or ``None`` when the timer has not started."""
        if round_obj.timer_started_at is None:
            return None
        reference = round_obj.timer_paused_at or utcnow()
        elapsed = (reference - round_obj.timer_started_at).total_seconds()
        remaining = round_obj.timer_duration - elapsed
        return max(0, int(remaining))

    @staticmethod
    def is_expired(round_obj) -> bool:
        remaining = TimerService.seconds_remaining(round_obj)
        return remaining is not None and remaining <= 0

    @staticmethod
    def is_running(round_obj) -> bool:
        return (
            round_obj.timer_started_at is not None
            and round_obj.timer_paused_at is None
            and round_obj.status == "ACTIVE"
        )

    @staticmethod
    def state(round_obj) -> dict:
        return {
            "duration": round_obj.timer_duration,
            "remaining": TimerService.seconds_remaining(round_obj),
            "running": TimerService.is_running(round_obj),
            "paused": round_obj.timer_paused_at is not None,
            "started_at": round_obj.timer_started_at.isoformat()
            if round_obj.timer_started_at
            else None,
            "server_now": utcnow().isoformat(),
        }
