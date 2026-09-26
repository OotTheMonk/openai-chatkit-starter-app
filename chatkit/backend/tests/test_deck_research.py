"""research_build_statistics must never mask statistics behind widget or title bugs.

Regression tests: the progress card showed Done while the agent reported a
win-rate error. Two defects could cause that shape: the tool title crashed on
omitted card_ids (len(None)), and a widget build/stream failure raised after
the statistics were already retrieved, turning good numbers into a tool error.
A total SWUStats outage must also return a readable retry message instead of
a bare JSON blob the agent misreads as "try again now" (instant retries hit
the deliberate 60s error backoff and can never succeed).
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents import RunContextWrapper

from app.deck_research import research_build_statistics


def success_evidence(cards):
    return {'kind': 'aggregate_statistics', 'source': 'SWUStats', 'source_url': 'u',
        'format': 'Premier', 'window': 'All-time', 'start_week': None, 'end_week': None,
        'retrieved_at': 'now', 'card_statistics': cards, 'missing_card_ids': [],
        'matchups': [], 'notices': [], 'scope': 'scope', 'design_policy': 'policy'}


def stat_row():
    return {'id': 'c1', 'name': 'Alpha', 'included': 120, 'played': 60, 'resourced': None,
        'win_rate_when_included': 50, 'win_rate_when_played': 55, 'play_rate': 50,
        'resource_rate': None, 'sample_label': 'Observed usage'}


def make_state():
    return SimpleNamespace(active_deck_id=7,
        deck_contents={'deck': [], 'sideboard': [], 'leader': {}, 'base': {}},
        saved_contents=None, build_preferences={'format': 'Premier'}, research=None)


class ResearchBuildStatisticsTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, state, stream, args):
        manager = SimpleNamespace(get_state=lambda thread_id: state, save=lambda: None)
        inner = SimpleNamespace(request_context={'deck_manager': manager},
            thread=SimpleNamespace(id='thr_test'), stream_widget=stream)
        wrapper = RunContextWrapper(context=inner)
        with patch('app.drafts.ensure_draft', AsyncMock(return_value=state)), \
             patch('app.catalog.catalog', AsyncMock(return_value={'c1': {'id': 'c1', 'image': 'img'}})):
            return await research_build_statistics.on_invoke_tool(wrapper, json.dumps(args))

    async def test_none_card_ids_researches_whole_deck(self):
        state, stream = make_state(), AsyncMock()
        with patch('app.deck_research.evidence',
                   AsyncMock(return_value=success_evidence([stat_row()]))) as mock_evidence:
            result = await self.invoke(state, stream, {})
        mock_evidence.assert_awaited_once()
        self.assertIsNone(mock_evidence.await_args[0][2])
        self.assertEqual(json.loads(result)['card_statistics'][0]['id'], 'c1')
        stream.assert_awaited_once()

    async def test_widget_failure_still_returns_statistics(self):
        state, stream = make_state(), AsyncMock(side_effect=RuntimeError('widget gone'))
        with patch('app.deck_research.evidence',
                   AsyncMock(return_value=success_evidence([stat_row()]))):
            result = await self.invoke(state, stream, {'card_ids': ['c1']})
        self.assertEqual(json.loads(result)['card_statistics'][0]['win_rate_when_played'], 55)

    async def test_total_failure_reports_retry_timing(self):
        state, stream = make_state(), AsyncMock()
        failed = {**success_evidence([]), 'retrieved_at': None,
            'notices': ['SWUStats statistics are temporarily unavailable. No performance inference can be made.']}
        with patch('app.deck_research.evidence', AsyncMock(return_value=failed)):
            result = await self.invoke(state, stream, {'card_ids': ['c1']})
        self.assertIn('temporarily unavailable', result)
        self.assertIn('minute', result)
        stream.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
