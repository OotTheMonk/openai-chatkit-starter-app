"""
Widget for displaying deck lists.
"""

from __future__ import annotations

from typing import Any

from chatkit.widgets import WidgetRoot, WidgetTemplate


deck_list_widget_template = WidgetTemplate.from_file("deck_list.widget")


def build_deck_list_widget(decks: list[dict[str, Any]], count: int) -> WidgetRoot:
    """Render a deck list widget using the .widget template."""
    payload = {
        "decks": [_serialize_deck(deck) for deck in decks],
        "count": count
    }
    return deck_list_widget_template.build(payload)


def _serialize_deck(deck: dict[str, Any]) -> dict[str, Any]:
    """Serialize deck data for the widget."""
    deck_id = deck.get("id", 0)
    name = deck.get("name")
    if not name:
        name = f"Unnamed Deck #{deck_id}"
    
    return {
        "id": deck_id,
        "name": name,
        "is_favorite": deck.get("is_favorite", False)
    }
