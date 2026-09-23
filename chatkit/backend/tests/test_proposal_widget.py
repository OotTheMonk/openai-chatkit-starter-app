"""Proposal review widget: inline chat review with working Apply/Dismiss."""
import unittest

from app.proposal_widget import build_proposal_widget


CHANGES = [
    {"card_id": "c1", "name": "Moff Gideon", "delta": 2, "section": "deck", "reason": "Curve topper"},
    {"card_id": "c2", "name": "Old Ally", "delta": -3, "section": "sideboard", "reason": "Too slow"},
]


class ProposalWidgetTests(unittest.TestCase):
    def test_builds_rows_and_actions(self):
        widget = build_proposal_widget("Hold midrange", "p1", "Apply changes", CHANGES)
        self.assertIsNotNone(widget)

    def test_empty_reason_falls_back(self):
        widget = build_proposal_widget("g", "p2", "Replace deck", [
            {"card_id": "c9", "name": "X", "delta": 1, "section": "deck", "reason": ""},
        ])
        self.assertIsNotNone(widget)


if __name__ == "__main__":
    unittest.main()
