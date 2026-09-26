import json
import unittest

from app.stats_widget import build_stats_widget, tier, format_pct


class StatsWidgetTests(unittest.TestCase):
    def test_builds_rows_with_tiers(self):
        cards = [
            {"id": "a", "name": "Alpha", "image": "https://example.com/a.webp",
             "play_rate": 38, "win_rate_when_played": 67.79, "sample_label": "Observed usage"},
            {"id": "b", "name": 'Say "Hi" Beta', "image": None,
             "play_rate": None, "win_rate_when_played": None, "sample_label": "No observations"},
        ]
        widget = build_stats_widget("Card performance", "Premier · 2 cards", cards)
        self.assertIsNotNone(widget)
        model = widget.model_dump(mode="json")
        grid = model["children"][1]["children"][0]
        self.assertEqual(grid["wrap"], "wrap")
        self.assertEqual([tile["background"] for tile in grid["children"]],
                         ["#edf7ef", "#f2f3f1"])
        self.assertEqual(len(model["children"][0]["children"]), 1)
        thumbnail = grid["children"][0]["children"][0]["children"][0]
        self.assertEqual(thumbnail["id"], "a")
        self.assertEqual(thumbnail["src"], "https://www.swustats.net/TCGEngine/SWUDeck/concat/a.webp")
        self.assertEqual((thumbnail["aspectRatio"], thumbnail["fit"]), (1, "contain"))
        dump = json.dumps(model, ensure_ascii=False)
        self.assertIn("Win 67.79%", dump)
        self.assertIn('"success"', dump)
        self.assertIn("Win —", dump)
        self.assertIn("No observations", dump)

    def test_truncates_with_footer(self):
        cards = [{"id": str(i), "name": f"C{i}", "play_rate": 10 + i,
                  "win_rate_when_played": 50, "sample_label": "Observed usage"} for i in range(12)]
        widget = build_stats_widget("t", "s", cards)
        dump = json.dumps(widget.model_dump(mode="json"), ensure_ascii=False)
        self.assertIn("+2 more", dump)

    def test_tiers_and_format(self):
        self.assertEqual([tier(None), tier(67.8), tier(50), tier(30)],
                         ["secondary", "success", "warning", "danger"])
        self.assertEqual([format_pct(None), format_pct(38), format_pct(67.79)],
                         ["—", "38%", "67.79%"])


if __name__ == "__main__":
    unittest.main()
