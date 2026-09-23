"""Candidate payloads must stay small enough for low TPM tiers.

Regression test: get_build_candidates once returned 70 full card dicts
(~11k tokens), blowing a 30k TPM budget on the very next model call and
killing the run with a rate-limit error. Candidates stay a capped sample
of slim rows; full rules text is fetched on demand via search_deck_cards.
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents import RunContextWrapper

from app.deck_state import DeckStateManager
from app.discovery import DiscoveryRequest, create_draft
from app.drafts import get_build_candidates

TODAY = date(2026, 9, 19)


def card(id, name, cost=2):
    return {
        "id": id,
        "name": name,
        "type": "Unit",
        "aspects": ["Vigilance"],
        "traits": [],
        "text": "Draw a card. " * 40,
        "cost": cost,
        "printings": [{"set": "ASH", "number": "001"}],
    }


class CandidateSizeTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_sample_is_capped_and_slim(self):
        units = [card(f"u{i:03d}", f"Unit {i:03d}") for i in range(60)]
        cards = {"l": card("l", "Leader", cost=5), "b": card("b", "Base", cost=0)}
        cards["l"]["type"] = "Leader"
        cards["b"]["type"] = "Base"
        for u in units:
            cards[u["id"]] = u
        with tempfile.TemporaryDirectory() as temp:
            manager = DeckStateManager(Path(temp) / "state.json")
            with patch("app.discovery.catalog", AsyncMock(return_value=cards)), patch(
                "app.drafts.catalog", AsyncMock(return_value=cards)
            ), patch("app.drafts.enrich", AsyncMock(side_effect=lambda x: x)), patch(
                "app.deck_research.research", AsyncMock(return_value={})
            ), patch("app.swustats_stats.evidence", AsyncMock(return_value={})) as stats:
                await create_draft(manager, "t", "l", "b", DiscoveryRequest())
                context = RunContextWrapper(
                    context=SimpleNamespace(
                        request_context={"deck_manager": manager},
                        thread=SimpleNamespace(id="t"),
                    )
                )
                raw = await get_build_candidates.on_invoke_tool(context, "{}")
                result = json.loads(raw)
                self.assertLessEqual(len(result["cards"]), 35)
                for entry in result["cards"]:
                    self.assertEqual(
                        set(entry.keys()),
                        {"id", "name", "cost", "type", "aspects", "role_signals"},
                    )
                self.assertLess(len(raw), 15000)
                self.assertLessEqual(len(stats.call_args[0][2]), 35)


if __name__ == "__main__":
    unittest.main()
