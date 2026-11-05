"""Small deployment configuration helpers (no Discord imports needed)."""

import math


def session_duration_seconds(raw: str) -> float:
    """Zero disables the timer; otherwise accept at most a 24-hour session."""
    try:
        hours = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("AUTO_SHUTDOWN_HOURS 必須是 0 到 24 的數字。") from exc
    if not math.isfinite(hours) or not 0 <= hours <= 24:
        raise ValueError("AUTO_SHUTDOWN_HOURS 必須介於 0 到 24。")
    return hours * 3600
