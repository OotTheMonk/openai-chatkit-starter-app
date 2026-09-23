"""
Widget for reviewing deck proposals inline in chat.
"""

from __future__ import annotations

from typing import Any

from chatkit.widgets import WidgetRoot, WidgetTemplate


proposal_widget_template = WidgetTemplate.from_file("proposal_widget.widget")


def build_proposal_widget(
    goal: str,
    proposal_id: str,
    apply_label: str,
    changes: list[dict[str, Any]],
) -> WidgetRoot:
    """Render a proposal review widget: change rows plus Apply/Dismiss buttons."""
    rows = []
    for change in changes:
        delta = change.get("delta", 0) or 0
        verb = "Add" if delta > 0 else "Remove"
        title = f"{verb} {abs(delta)}x {change.get('name') or change.get('card_id') or 'Unknown card'}"
        if change.get("section") == "sideboard":
            title += " (sideboard)"
        rows.append({"title": title, "reason": change.get("reason") or "No reason given."})
    def button(label: str, action_type: str, variant: str | None = None) -> dict[str, Any]:
        node: dict[str, Any] = {
            "type": "Button",
            "label": label,
            "onClickAction": {"type": action_type, "payload": {"proposal_id": proposal_id}},
        }
        if variant:
            node["variant"] = variant
        return node

    payload = {
        "goal": goal,
        "apply_label": apply_label,
        "count": len(rows),
        "changes": rows,
        "apply_button": button(apply_label, "apply_proposal"),
        "dismiss_button": button("Dismiss", "dismiss_proposal", variant="outline"),
    }
    return proposal_widget_template.build(payload)
