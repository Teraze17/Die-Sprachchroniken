"""LeetCode-inspired, privacy-safe study activity calendar.

All dates use the user's Asia/Taipei calendar day. The chart only reads events;
opening it never creates a new learning event or changes a streak.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont


WINDOW_DAYS = 365
COLORS = ("#EDEFF0", "#B9EDB5", "#79D879", "#41B957", "#208A42")


@dataclass(frozen=True)
class StreakStats:
    start: date
    today: date
    counts: dict[date, int]
    active_days: int
    current_streak: int
    max_streak: int
    total_actions: int


def summarize_streaks(day_counts: Mapping[date, int], today: date) -> StreakStats:
    """Compute annual activity plus longest *all-time* and current streak.

    Today's streak remains valid through the end of the day even if the latest
    action was yesterday. Future-dated and zero/negative events do not count.
    """
    valid = {day: int(count) for day, count in day_counts.items()
             if day <= today and int(count) > 0}
    start = today - timedelta(days=WINDOW_DAYS - 1)
    visible = {day: n for day, n in valid.items() if day >= start}

    max_streak = 0
    run = 0
    previous = None
    for day in sorted(valid):
        if previous is not None and day == previous + timedelta(days=1):
            run += 1
        else:
            run = 1
        max_streak = max(max_streak, run)
        previous = day

    anchor = today if today in valid else today - timedelta(days=1)
    current = 0
    while anchor in valid:
        current += 1
        anchor -= timedelta(days=1)

    return StreakStats(
        start=start, today=today, counts=visible,
        active_days=len(visible), current_streak=current,
        max_streak=max_streak, total_actions=sum(visible.values()),
    )


def _font(size: int, bold: bool = False):
    candidates = (
        ("DejaVuSans-Bold.ttf", "C:/Windows/Fonts/segoeuib.ttf")
        if bold else ("DejaVuSans.ttf", "C:/Windows/Fonts/segoeui.ttf")
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _color(count: int) -> str:
    if count <= 0:
        return COLORS[0]
    if count == 1:
        return COLORS[1]
    if count <= 3:
        return COLORS[2]
    if count <= 6:
        return COLORS[3]
    return COLORS[4]


def render_streak_png(stats: StreakStats) -> bytes:
    """Render a full-year Monday–Sunday heatmap as a PNG for Discord embeds."""
    image = Image.new("RGB", (1120, 310), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    title = _font(25, bold=True)
    normal = _font(14)
    small = _font(12)
    metric = _font(22, bold=True)

    draw.text((36, 21), "DIE SPRACHCHRONIKEN", fill="#264434", font=title)
    draw.text((37, 59), "Learning streak  /  Last 365 days", fill="#738078", font=normal)

    for x, label, value in (
        (565, "ACTIVE DAYS", stats.active_days),
        (755, "CURRENT STREAK", stats.current_streak),
        (958, "BEST STREAK", stats.max_streak),
    ):
        draw.text((x, 20), label, fill="#7E8882", font=small)
        draw.text((x, 41), str(value), fill="#245D35", font=metric)

    x0 = 70
    y0 = 100
    step = 18
    square = 13
    grid_start = stats.start - timedelta(days=stats.start.weekday())

    for weekday, label in ((0, "Mon"), (2, "Wed"), (4, "Fri")):
        draw.text((30, y0 + weekday * step - 1), label, fill="#9AA5A0", font=small)

    current = stats.start
    while current <= stats.today:
        offset = (current - grid_start).days
        col, row = divmod(offset, 7)
        x, y = x0 + col * step, y0 + row * step
        draw.rounded_rectangle((x, y, x + square, y + square), radius=3,
                               fill=_color(stats.counts.get(current, 0)))
        if current == stats.today:
            draw.rounded_rectangle((x - 2, y - 2, x + square + 2, y + square + 2),
                                   radius=4, outline="#638B72", width=1)
        current += timedelta(days=1)

    month = stats.start.replace(day=1)
    if month < stats.start:
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    while month <= stats.today:
        col = (month - grid_start).days // 7
        draw.text((x0 + col * step, 241), month.strftime("%b"), fill="#A4ADA6", font=small)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)

    draw.text((35, 282), "Each square = 1 day with saved study activity · Asia/Taipei",
              fill="#8A968D", font=small)
    draw.text((876, 282), "Less", fill="#7E8882", font=small)
    for i, color in enumerate(COLORS):
        x = 918 + i * 21
        draw.rounded_rectangle((x, 283, x + 13, 296), radius=3, fill=color)
    draw.text((1029, 282), "More", fill="#7E8882", font=small)

    result = io.BytesIO()
    image.save(result, format="PNG", optimize=True)
    return result.getvalue()
