"""
Widget for displaying card search results.
"""

from __future__ import annotations

from typing import Any

from chatkit.widgets import WidgetRoot, WidgetTemplate


card_search_widget_template = WidgetTemplate.from_file("cards_widget.widget")


def build_card_search_widget(query: str, cards: list[dict[str, Any]], count: int) -> WidgetRoot:
    """Render a card search results widget using the .widget template."""
    payload = {
        "query": query,
        "cards": [_serialize_card(card) for card in cards],
        "count": count
    }
    return card_search_widget_template.build(payload)


def _serialize_card(card: dict[str, Any]) -> dict[str, Any]:
    """Serialize card data for the widget."""
    return {
        "ability": card.get("name", "Unknown")
    }
