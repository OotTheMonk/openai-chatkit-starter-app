import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from agents import RunContextWrapper
from app.deck_analysis import analyze
from app.deck_state import DeckStateManager
from app.drafts import remove_card,act,Change,propose,analyze_deck_changes,propose_deck_changes
from app.deck_research import research
from tests.test_swustats_write import FakeSWU

def card(id,cost=2,count=3,**kw):return {'id':id,'name':id,'count':count,'cost':cost,'type':'Unit','aspects':['Vigilance'],'text':'','printings':[{'set':'ASH','number':'1'}],**kw}

class AnalysisTests(unittest.TestCase):
    def test_effective_cost_probabilities_and_warnings(self):
        deck={'leader':{'aspects':['Vigilance']},'base':{'aspects':[]},'deck':[card('early',count=8),card('late',cost=7,count=39),card('off',aspects=['Cunning'])],'sideboard':[]}
        report=analyze(deck,{'style':'Control'})
        self.assertEqual(report['main_count'],50)
        self.assertEqual(report['early_units'],8)
        self.assertEqual(report['curve']['4'],3)
        self.assertGreater(report['opening_early_probability'],60)
        self.assertTrue(any('Top-heavy' in w for w in report['warnings']))
        self.assertTrue(any('Aspect penalties' in w for w in report['warnings']))
    def test_unknown_cost_and_cross_section_copies(self):
        report=analyze({'deck':[card('a',cost=None)],'sideboard':[card('a',count=2)]})
        self.assertTrue(any('Unknown costs' in w for w in report['warnings']))
        self.assertTrue(any('three copies' in w for w in report['warnings']))
        self.assertIsNone(report['opening_early_probability'])

class EditingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.manager=DeckStateManager(Path(self.temp.name)/'state.json')
        self.manager.set_active_deck('t',10,'Test');self.state=self.manager.get_state('t')
        self.state.deck_contents={'deck':[card('a')],'sideboard':[card('b',count=2)]}
        self.fake=FakeSWU(self.state.deck_contents)
        self.push=patch("app.swustats_write.push_deck_changes",side_effect=self.fake.push);self.push.start()
        self.fetch=patch("app.tools.load_deck.fetch_deck_contents",side_effect=self.fake.fetch);self.fetch.start()
    def tearDown(self):self.push.stop();self.fetch.stop();self.temp.cleanup()
    async def test_remove_one_all_undo_persist_and_invalidate_proposal(self):
        self.state.proposal={'id':'old','revision':0}
        await remove_card(self.manager,'t',10,0,'a','deck')
        self.assertEqual(self.state.deck_contents['deck'][0]['count'],2);self.assertIsNone(self.state.proposal)
        with self.assertRaises(ValueError):await remove_card(self.manager,'t',10,0,'b','sideboard')
        with self.assertRaises(ValueError):await remove_card(self.manager,'t',11,1,'b','sideboard')
        await remove_card(self.manager,'t',10,1,'b','sideboard',True)
        self.assertEqual(self.state.deck_contents['sideboard'],[])
        self.assertEqual(self.fake.pushed[-1][1],[{'action':'remove','cardID':'b','count':2,'zone':'side'}])
        await act(self.manager,'t','undo')
        restored=DeckStateManager(self.manager.path).get_state('t')
        self.assertEqual(restored.deck_contents['sideboard'][0]['count'],2)
    async def test_agent_must_analyze_exact_revision_and_changes(self):
        ctx=RunContextWrapper(context=SimpleNamespace(request_context={'deck_manager':self.manager},thread=SimpleNamespace(id='t'),stream=AsyncMock(),stream_widget=AsyncMock()))
        changes=[Change(card_id='a',delta=-1,section='deck',reason='Test cut')]
        args=json.dumps({'goal':'Test','changes':[c.model_dump() for c in changes]})
        with patch('app.drafts.catalog',AsyncMock(return_value={'a':card('a')})),patch('app.drafts.enrich',AsyncMock(side_effect=lambda x:x)),patch('app.swustats_stats.evidence',AsyncMock(return_value={'kind':'aggregate_statistics'})):
            blocked=await propose_deck_changes.on_invoke_tool(ctx,args)
            self.assertIn('analyze_deck_changes',blocked)
            await analyze_deck_changes.on_invoke_tool(ctx,json.dumps({'changes':[c.model_dump() for c in changes]}))
            result=await propose_deck_changes.on_invoke_tool(ctx,args)
            self.assertIn('ready for review',result)
            self.assertIn('analysis',self.state.proposal)
            self.assertTrue(ctx.context.stream_widget.await_count>=1)
            await remove_card(self.manager,'t',10,0,'b','sideboard')
            self.assertIn('analyze_deck_changes',await propose_deck_changes.on_invoke_tool(ctx,args))
    async def test_repropose_same_changes_streams_widget_once(self):
        ctx=RunContextWrapper(context=SimpleNamespace(request_context={'deck_manager':self.manager},thread=SimpleNamespace(id='t'),stream=AsyncMock(),stream_widget=AsyncMock()))
        changes=[Change(card_id='a',delta=-1,section='deck',reason='Test cut')]
        args=json.dumps({'goal':'Test','changes':[c.model_dump() for c in changes]})
        with patch('app.drafts.catalog',AsyncMock(return_value={'a':card('a')})),patch('app.drafts.enrich',AsyncMock(side_effect=lambda x:x)),patch('app.swustats_stats.evidence',AsyncMock(return_value={'kind':'aggregate_statistics'})):
            await analyze_deck_changes.on_invoke_tool(ctx,json.dumps({'changes':[c.model_dump() for c in changes]}))
            first=await propose_deck_changes.on_invoke_tool(ctx,args)
            self.assertIn('ready for review',first)
            second=await propose_deck_changes.on_invoke_tool(ctx,args)
            self.assertIn('already shown',second)
            self.assertEqual(ctx.context.stream_widget.await_count,1)

class ResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_accepts_old_naive_and_new_aware_dates(self):
        from app.memory_store import MemoryStore
        from chatkit.types import ThreadMetadata
        from datetime import datetime,timezone
        store=MemoryStore()
        await store.save_thread(ThreadMetadata(id='old',created_at=datetime(2025,1,1)),{})
        await store.save_thread(ThreadMetadata(id='new',created_at=datetime(2026,1,1,tzinfo=timezone.utc)),{})
        self.assertEqual([t.id for t in (await store.load_threads(10,None,'desc',{})).data],['new','old'])
