"""Compact performance widget with color-coded card tiles."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from chatkit.widgets import WidgetRoot, WidgetTemplate


stats_widget_template = WidgetTemplate.from_file("stats_widget.widget")

MAX_ROWS = 10


def format_pct(value):
    return "—" if value is None else f"{value:g}%"


def tier(win):
    if win is None:
        return "secondary"
    if win >= 55:
        return "success"
    if win >= 45:
        return "warning"
    return "danger"


def heat(win):
    return {
        "success": "#edf7ef",
        "warning": "#fff6e8",
        "danger": "#fceeea",
        "secondary": "#f2f3f1",
    }[tier(win)]


def _row(card: dict[str, Any]) -> dict[str, Any]:
    sample = card.get("sample_label") or ""
    card_id = card.get("id")
    thumbnail = (f"https://www.swustats.net/TCGEngine/SWUDeck/concat/{quote(str(card_id), safe='')}.webp"
                 if card_id is not None and str(card_id) else card.get("image"))
    return {
        "id": str(card_id) if card_id is not None else "",
        "name": card.get("name") or "Unknown",
        "image": thumbnail or None,
        "heat": heat(card.get("win_rate_when_played")),
        "play": {"label": f"Play {format_pct(card.get('play_rate'))}", "color": "secondary"},
        "win": {"label": f"Win {format_pct(card.get('win_rate_when_played'))}", "color": tier(card.get("win_rate_when_played"))},
        "sample": sample if sample and sample != "Observed usage" else None,
    }


def build_stats_widget(title: str, subtitle: str, cards: list[dict[str, Any]]) -> WidgetRoot:
    """Render up to MAX_ROWS card tiles; the rest collapse into a footer."""
    rows = [_row(c) for c in cards[:MAX_ROWS]]
    more = max(0, len(cards) - MAX_ROWS)
    return stats_widget_template.build({"title": title, "subtitle": subtitle, "cards": rows, "more": more})
