import unittest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx

from app.simulation import _aggregate, _aggregate_full_games, _card_id, _check_engine_card_data, _store_replay, available_opponents, deck_to_fixture, import_replay, opponent_deck, run_local


def deck(base="JTL_019", count=50):
    return {
        "leader": {"id": "ASH_009"}, "base": {"id": base},
        "deck": [{"id": "SEC_046", "count": count}],
    }


class SimulationTest(unittest.TestCase):
    def test_working_deck_serializes_to_swu_fixture(self):
        text = deck_to_fixture(deck())
        self.assertEqual(text, "Leader\n1 ASH_009\n\nBase\n1 JTL_019\n\nDeck\n50 SEC_046\n")

    def test_base_specific_deck_minimum_is_checked(self):
        with self.assertRaisesRegex(ValueError, "at least 60"):
            deck_to_fixture(deck("JTL_024", 50))
        self.assertIn("45 SEC_046", deck_to_fixture(deck("JTL_025", 45)))

    def test_invalid_card_ids_are_rejected(self):
        bad = deck()
        bad["deck"][0]["id"] = "not-mapped"
        with self.assertRaisesRegex(ValueError, "usable SWUSim printing"):
            deck_to_fixture(bad)

    def test_numeric_swustats_ids_use_verified_printings(self):
        self.assertEqual(_card_id({"id": "3621912835", "printings": [{"set": "ASH", "number": "008"}]}), "ASH_008")
        self.assertEqual(_card_id({"id": "0036920495", "printings": [{"set": "TWI", "number": "181"}]}), "TWI_181")
        self.assertEqual(_card_id({"id": "123", "printings": [{"set": "TS26", "number": "034"}]}), "TS26_34")

    def test_opponent_options_include_leader_and_base_image_ids(self):
        with TemporaryDirectory() as temporary:
            fixtures = Path(temporary) / "SWUSim/Tests/BotFixtures/meta"
            fixtures.mkdir(parents=True)
            (fixtures / "sample.txt").write_text(
                "# Sample opponent\n\nLeader\n1 ASH_009\n\nBase\n1 JTL_019\n\nDeck\n3 SEC_046\n", encoding="utf-8")
            cards = {"10": {"printings": [{"set": "ASH", "number": "009"}]},
                     "20": {"printings": [{"set": "JTL", "number": "019"}]}}
            with patch("app.simulation.ENGINE_ROOT", Path(temporary)), patch("app.simulation.FIXTURE_DIRS", ("meta",)):
                self.assertEqual(available_opponents(cards), [{"id": "sample", "label": "Sample opponent",
                    "group": "meta", "leaderId": "10", "baseId": "20"}])

    def test_opponent_deck_lists_exact_fixture_with_card_names(self):
        with TemporaryDirectory() as temporary:
            fixtures = Path(temporary) / "SWUSim/Tests/BotFixtures/meta"
            fixtures.mkdir(parents=True)
            (fixtures / "sample.txt").write_text(
                "# Sample opponent\nLeader\n1 ASH_009\nBase\n1 JTL_019\nDeck\n3 SEC_046\n2 LOF_093\n",
                encoding="utf-8")
            cards = {"10": {"id": "10", "name": "Ahsoka", "printings": [{"set": "ASH", "number": "009"}]},
                     "20": {"id": "20", "name": "City", "printings": [{"set": "JTL", "number": "019"}]},
                     "30": {"id": "30", "name": "Trooper", "cost": 2, "type": "Unit", "arenas": ["Ground"],
                            "printings": [{"set": "SEC", "number": "046"}]}}
            with patch("app.simulation.ENGINE_ROOT", Path(temporary)), patch("app.simulation.FIXTURE_DIRS", ("meta",)):
                result = opponent_deck("sample", cards)
            self.assertEqual(result["total"], 5)
            self.assertEqual(result["leader"]["name"], "Ahsoka")
            self.assertEqual(result["deck"][0]["name"], "Trooper")
            self.assertEqual(result["deck"][0]["arenas"], ["Ground"])
            self.assertEqual(result["deck"][1]["name"], "LOF_093")

    def test_failed_samples_are_not_scored_as_losses(self):
        samples = [
            {"status": "resolved_attack", "summary": {"unitCount": {"1": {"Ground": 0, "Space": 0}, "2": {"Ground": 1, "Space": 0}}, "remainingUnitHealth": {"1": {"Ground": 0, "Space": 0}, "2": {"Ground": 2, "Space": 0}}}, "afterAttack": {"baseHealth": {"1": 30, "2": 30}}},
            {"status": "no_unit_attack", "summary": {"unitCount": {"1": {"Ground": 1, "Space": 0}, "2": {"Ground": 0, "Space": 1}}, "remainingUnitHealth": {"1": {"Ground": 3, "Space": 0}, "2": {"Ground": 0, "Space": 4}}}, "afterAttack": {"baseHealth": {"1": 30, "2": 29}}},
            {"status": "engine_error"},
        ]
        result = _aggregate(samples)
        self.assertEqual(result["counts"], {"ahead": 1, "equal": 1, "behind": 0, "no_unit_attack": 1, "failed": 1})
        self.assertEqual(result["scoredSamples"], 2)

    def test_full_game_aggregate_excludes_incomplete_games(self):
        result = _aggregate_full_games([
            {"status": "completed", "winner": 2, "rounds": 5, "appliedSteps": 70,
             "afterAttack": {"baseHealth": {"1": 0, "2": 8}}},
            {"status": "completed", "winner": 1, "rounds": 7, "appliedSteps": 90,
             "afterAttack": {"baseHealth": {"1": 12, "2": 0}}},
            {"status": "timeout"},
        ])
        self.assertEqual(result["counts"], {"ours": 1, "opponent": 1, "incomplete": 1})
        self.assertEqual(result["ourWinRate"], 0.5)
        self.assertEqual(result["meanRounds"], 6)
        self.assertEqual(result["meanActions"], 80)
        self.assertEqual(result["meanOurBaseHealthInWins"], 8)
        self.assertEqual(result["meanOpponentBaseHealthInLosses"], 12)

    def test_unsupported_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "supported simulation mode"):
            run_local(deck(), 1, 1, "ahsoka_blue", "seed", 1, "unknown")

    def test_missing_generated_card_data_stops_before_batch(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = root / "SWUSim/GeneratedCode"
            generated.mkdir(parents=True)
            (generated / "cardArrayCache.json").write_text(
                '{"cardArray":[{"id":"JTL_019"},{"id":"ASH_009"}]}', encoding="utf-8")
            fixture = root / "opponent.txt"
            fixture.write_text("Leader\n1 ASH_009\n", encoding="utf-8")
            with patch("app.simulation.ENGINE_ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "ASH_021"):
                    _check_engine_card_data(fixture, "Base\n1 ASH_021\n")

    def test_completed_replay_import_returns_petranaki_playback_link(self):
        with TemporaryDirectory() as temporary, patch("app.simulation.REPLAY_DIR", Path(temporary)):
            token = _store_replay({"format": "tcgengine-match-replay-v1", "rootName": "SWUSim",
                                   "initialGamestate": "state", "actions": []})
            transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
                "success": True, "gameName": "123456", "authKey": "a" * 32}))
            client = httpx.AsyncClient(transport=transport)
            with patch("app.simulation.httpx.AsyncClient", return_value=client):
                url = asyncio.run(import_replay(token))
            self.assertEqual(url, "https://petranaki.net/TCGEngine/NextTurn.php?"
                             "gameName=123456&playerID=1&folderPath=SWUSim&authKey=" + "a" * 32 + "&replay=1")

    def test_replay_link_rejects_unknown_token(self):
        with self.assertRaisesRegex(ValueError, "Invalid replay link"):
            asyncio.run(import_replay("../other"))


if __name__ == "__main__":
    unittest.main()
