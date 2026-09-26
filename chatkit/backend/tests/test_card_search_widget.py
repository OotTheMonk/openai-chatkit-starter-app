"""Card search widget builds valid widget JSON for result lists."""
import json
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

    def test_rows_with_ids_render_card_images(self):
        widget = build_card_search_widget("q", [
            {"name": "With Art", "id": "u1", "image": "https://example.com/a.webp"},
            {"name": "Art By Id", "id": "u2", "image": None},
        ], 2)
        dump = json.dumps(widget.model_dump(mode="json"), ensure_ascii=False)
        self.assertIn("CardImage", dump)
        self.assertNotIn('"value": "With Art"', dump)
        self.assertNotIn('"value": "Art By Id"', dump)

    def test_row_without_id_falls_back_to_text(self):
        widget = build_card_search_widget("q", [
            {"name": "Mystery", "id": None, "image": None},
        ], 1)
        dump = json.dumps(widget.model_dump(mode="json"), ensure_ascii=False)
        self.assertIn('"value": "Mystery"', dump)


if __name__ == "__main__":
    unittest.main()
