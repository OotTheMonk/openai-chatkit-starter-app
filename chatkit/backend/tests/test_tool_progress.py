"""Progress cards for SWUStats requests and the browser-UA client."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.swu import (
    BROWSER_USER_AGENT,
    FAILED_PREFIX,
    describe_cards,
    describe_deck_contents,
    describe_decks,
    describe_evidence,
    swu_client,
    track_request,
)


class FakeAgentCtx:
    """Stands in for chatkit's AgentContext workflow streaming."""

    def __init__(self):
        self.tasks = []
        self.workflow_item = SimpleNamespace(workflow=SimpleNamespace(tasks=self.tasks))
        self.ended = 0

    async def add_workflow_task(self, task):
        self.tasks.append(task)

    async def update_workflow_task(self, task, index):
        self.tasks[index] = task

    async def end_workflow(self):
        self.ended += 1


class TrackRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_marks_task_complete_with_summary(self):
        ctx = FakeAgentCtx()
        result = await track_request(ctx, "Loading decks", lambda: self._ok({"n": 1}), lambda r: f"got {r['n']}")
        self.assertEqual(result, {"n": 1})
        self.assertEqual(len(ctx.tasks), 1)
        self.assertEqual(ctx.tasks[0].status_indicator, "complete")
        self.assertEqual(ctx.tasks[0].content, "got 1")
        self.assertEqual(ctx.ended, 1)

    async def test_minimal_context_runs_call_with_no_card(self):
        ctx = SimpleNamespace()
        result = await track_request(ctx, "Loading decks", lambda: self._ok(7), lambda r: "unused")
        self.assertEqual(result, 7)

    async def test_loading_state_is_streamed_before_completion(self):
        seen = []

        class RecordingCtx(FakeAgentCtx):
            async def add_workflow_task(self, task):
                seen.append(("added", task.status_indicator))
                await super().add_workflow_task(task)

            async def update_workflow_task(self, task, index):
                seen.append(("updated", task.status_indicator))
                await super().update_workflow_task(task, index)

        await track_request(RecordingCtx(), "T", lambda: self._ok(1), lambda r: "one")
        self.assertEqual(seen, [("added", "loading"), ("updated", "complete")])

    async def test_failure_marks_task_failed_and_reraises(self):
        ctx = FakeAgentCtx()

        async def boom():
            raise ConnectionError("down")

        with self.assertRaises(ConnectionError):
            await track_request(ctx, "Loading decks", boom, lambda r: "unused")
        self.assertTrue(ctx.tasks[0].content.startswith(FAILED_PREFIX))
        self.assertIn("down", ctx.tasks[0].content)
        self.assertEqual(ctx.tasks[0].status_indicator, "complete")
        self.assertEqual(ctx.ended, 1)

    async def _ok(self, value):
        return value

    async def test_parallel_requests_share_one_workflow(self):
        ctx = FakeAgentCtx()
        started = asyncio.Event()

        async def slow():
            started.set()
            await asyncio.sleep(0.05)
            return {"ok": "slow"}

        async def fast():
            await started.wait()
            return {"ok": "fast"}

        fast_result, slow_result = await asyncio.gather(
            track_request(ctx, "A", fast, lambda r: "a-done"),
            track_request(ctx, "B", slow, lambda r: "b-done"),
        )
        self.assertEqual(fast_result, {"ok": "fast"})
        self.assertEqual(slow_result, {"ok": "slow"})
        by_title = {t.title: t for t in ctx.tasks}
        self.assertEqual(by_title["A"].content, "a-done")
        self.assertEqual(by_title["B"].content, "b-done")
        self.assertTrue(all(t.status_indicator == "complete" for t in ctx.tasks))
        self.assertEqual(ctx.ended, 1)

    async def test_update_after_ended_workflow_still_returns_result(self):
        class EndedOnceCtx(FakeAgentCtx):
            """Mimics chatkit raising once when the workflow is already gone."""

            def __init__(self):
                super().__init__()
                self.fail_next_update = True

            async def update_workflow_task(self, task, index):
                if self.fail_next_update:
                    self.fail_next_update = False
                    raise ValueError("Workflow is not set")
                await super().update_workflow_task(task, index)

        ctx = EndedOnceCtx()
        result = await track_request(ctx, "B", lambda: self._ok(2), lambda r: "b-done")
        self.assertEqual(result, 2)
        done = [t for t in ctx.tasks if t.status_indicator == "complete"]
        self.assertTrue(any(t.content == "b-done" for t in done))

    async def test_describe_failure_still_completes_card(self):
        ctx = FakeAgentCtx()

        def bad_describe(result):
            raise ZeroDivisionError("nope")

        result = await track_request(ctx, "T", lambda: self._ok({"x": 1}), bad_describe)
        self.assertEqual(result, {"x": 1})
        self.assertEqual(ctx.tasks[0].status_indicator, "complete")
        self.assertEqual(ctx.ended, 1)

    async def test_attach_search_images_matches_names_case_insensitively(self):
        from app.server import attach_search_images

        with patch("app.catalog.catalog", AsyncMock(return_value={"1": {"id": "1", "name": "Moff Gideon", "image": "http://img/mg"}})):
            result = await attach_search_images({"cards": [{"name": "moff gideon", "text": "x"}, {"name": "Unknown", "text": "y"}]})
        self.assertEqual(result["cards"][0]["image"], "http://img/mg")
        self.assertEqual(result["cards"][0]["id"], "1")
        self.assertNotIn("image", result["cards"][1])
        self.assertNotIn("id", result["cards"][1])


class DescribeTests(unittest.TestCase):
    def test_error_results_stay_human_readable(self):
        self.assertTrue(describe_cards("q", {"error": "boom", "cards": [], "count": 0}).startswith(FAILED_PREFIX))
        self.assertTrue(describe_decks({"error": "timeout"}).startswith(FAILED_PREFIX))
        self.assertEqual(describe_decks({"error": "not_authenticated"}), "SWUStats login needed to list saved decks.")
        self.assertEqual(
            describe_deck_contents({"error": "token_expired"}),
            "SWUStats login needed to load this deck.",
        )
        self.assertTrue(describe_evidence({"error": "gone"}).startswith(FAILED_PREFIX))

    def test_success_results_render_query_count_and_names(self):
        cards = {"error": None, "count": 2, "cards": [{"name": "A"}, {"name": "B"}]}
        payload = json.loads(describe_cards("q", cards))
        self.assertEqual(payload["query"], "q")
        self.assertEqual(payload["count"], 2)
        self.assertEqual([c["name"] for c in payload["cards"]], ["A", "B"])

    def test_hover_payload_carries_card_art(self):
        payload = json.loads(describe_cards("q", {
            "error": None, "count": 2,
            "cards": [{"name": "A", "image": "http://img/a"}, {"name": "B"}],
        }))
        self.assertEqual(payload["cards"][0]["image"], "http://img/a")
        self.assertIsNone(payload["cards"][1]["image"])


        decks = {"error": None, "count": 1, "decks": [{"id": 7, "name": "Mine"}]}
        self.assertIn("Mine", describe_decks(decks))
        contents = {
            "error": None,
            "metadata": {"name": "Mine"},
            "deck": [{"count": 3}],
            "sideboard": [{"count": 1}],
        }
        summary = describe_deck_contents(contents)
        self.assertIn("Mine", summary)
        self.assertIn("3 main-deck cards", summary)
        evidence = {
            "card_statistics": [{"id": "a"}],
            "matchups": [],
            "window": "all-time",
            "retrieved_at": "now",
            "notices": [],
        }
        summary = describe_evidence(evidence)
        self.assertIn("1 card observations", summary)
        self.assertNotIn("Failed", summary)

    def test_empty_evidence_reports_failure(self):
        result = {"card_statistics": [], "matchups": [], "retrieved_at": None, "notices": []}
        self.assertTrue(describe_evidence(result).startswith(FAILED_PREFIX))


class SwuClientTests(unittest.TestCase):
    def test_client_looks_like_a_browser_with_roomy_timeout(self):
        client = swu_client()
        self.assertIn("Mozilla", client.headers["user-agent"])
        self.assertIn("Chrome", BROWSER_USER_AGENT)
        self.assertEqual(client.timeout.connect, 30.0)


class SearchHtmlParserTests(unittest.TestCase):
    def test_link_text_becomes_name_and_rest_becomes_rules(self):
        from app.server import _parse_search_html

        html = (
            "<ul><li><a href='card.php?id=1'>Moff Gideon</a>"
            "Leadership Imperial - When you play an event, deal 2 damage.</li></ul>"
        )
        cards = _parse_search_html(html)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["name"], "Moff Gideon")
        self.assertIn("deal 2 damage", cards[0]["text"])

    def test_plain_items_fall_back_to_first_sentence(self):
        from app.server import _parse_search_html

        html = "<ul><li>Superlaser Blast. Deal 7 damage divided as you choose.</li></ul>"
        cards = _parse_search_html(html)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["name"], "Superlaser Blast")
        self.assertIn("Deal 7 damage", cards[0]["text"])

    def test_empty_page_gives_no_cards_and_junk_pages_are_capped(self):
        from app.server import _parse_search_html

        self.assertEqual(_parse_search_html("<html><body>nope</body></html>"), [])
        many = "<ul>" + "".join(f"<li><a>C{i}</a> text</li>" for i in range(40)) + "</ul>"
        self.assertEqual(len(_parse_search_html(many)), 25)

    def test_summaries_use_names_not_rules(self):
        result = {
            "error": None,
            "count": 1,
            "cards": [{"name": "Moff Gideon", "text": "Defeat a unit. Raid 1."}],
        }
        summary = describe_cards("q", result)
        self.assertIn("Moff Gideon", summary)
        self.assertNotIn("Defeat a unit", summary)


class CardWidgetSerializationTests(unittest.TestCase):
    def test_serialize_keeps_name_and_art_keys_only(self):
        from app.card_search_widget import _serialize_card

        self.assertEqual(
            _serialize_card({"name": "Moff Gideon", "text": "When you play...", "id": "1", "image": "http://img/mg"}),
            {"name": "Moff Gideon", "id": "1", "image": "http://img/mg"},
        )
        self.assertEqual(_serialize_card({}), {"name": "Unknown", "id": None, "image": None})


class OfficialSearchParseTests(unittest.TestCase):
    def test_ids_parsed_from_message(self):
        from app.server import _official_ids

        self.assertEqual(_official_ids("specificCards=aaa,bbb , ccc"), ["aaa", "bbb", "ccc"])
        self.assertEqual(_official_ids("nothing here"), [])
        self.assertEqual(_official_ids(""), [])


class SearchNarrationGuardTests(unittest.TestCase):
    def test_draft_search_tools_share_no_dump_rule(self):
        from app.server import assistant_agent

        instructions = assistant_agent.instructions or ""
        for tool in ("search_deck_cards", "find_build_cards", "get_build_candidates"):
            self.assertIn(tool, instructions)
        self.assertIn("Card matches", instructions)


if __name__ == "__main__":
    unittest.main()
