"""Card search widget builds valid widget JSON for result lists."""
import unittest

from app.card_search_widget import build_card_search_widget


class CardSearchWidgetTests(unittest.TestCase):
    def test_builds_with_results(self):
        widget = build_card_search_widget("trait:Imperial Imperial units", [
            {"name": "Death Trooper", "id": "u1", "image": "https://example.com/a.webp"},
            {"name": "Admiral Piett", "id": "u2", "image": None},
        ], 2)
        self.assertIsNotNone(widget)

    def test_builds_with_empty_results(self):
        widget = build_card_search_widget("no such card xyz", [], 0)
        self.assertIsNotNone(widget)

    def test_builds_with_quotes_in_name(self):
        widget = build_card_search_widget("hero", [
            {"name": 'Say "Hello" Trooper', "id": "u3", "image": None},
        ], 1)
        self.assertIsNotNone(widget)


if __name__ == "__main__":
    unittest.main()
