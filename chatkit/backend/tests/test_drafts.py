import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch,AsyncMock
from app.deck_state import DeckStateManager
from app.drafts import Change,propose,act,remove_card,add_card
from tests.test_swustats_write import FakeSWU

CARDS={'a':{'id':'a','name':'Card A','type':'Unit','cost':5},'b':{'id':'b','name':'Card B','type':'Event','cost':2}}
DECK={'metadata':{'name':'Test deck'},'deck':[{'id':'a','name':'Card A','count':3}],'sideboard':[]}
class DraftTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'drafts.json'
        self.manager=DeckStateManager(self.path);self.manager.set_active_deck('thread',1,'Test deck')
        self.state=self.manager.get_state('thread');self.state.deck_contents=deepcopy(DECK)
        self.catalog=patch('app.drafts.catalog',AsyncMock(return_value=CARDS));self.catalog.start()
        self.enrich=patch("app.drafts.enrich",AsyncMock(side_effect=lambda value:value));self.enrich.start()
        self.evidence=patch("app.swustats_stats.evidence",AsyncMock(return_value={}));self.evidence.start()
        self.fake=FakeSWU(DECK)
        self.push=patch("app.swustats_write.push_deck_changes",side_effect=self.fake.push);self.push.start()
        self.fetch=patch("app.tools.load_deck.fetch_deck_contents",side_effect=self.fake.fetch);self.fetch.start()
    def tearDown(self):self.catalog.stop();self.enrich.stop();self.evidence.stop();self.push.stop();self.fetch.stop();self.temp.cleanup()
    async def proposal(self):
        return await propose(self.manager,'thread',[Change(card_id='a',delta=-2,section='deck',reason='Lower the curve'),Change(card_id='b',delta=2,section='deck',reason='Early interaction')],'Improve consistency')
    async def test_apply_undo_and_persistence(self):
        p=await self.proposal();self.assertEqual(self.state.deck_contents,DECK)
        self.assertNotIn('contents',self.state.to_dict()['proposal'])
        await act(self.manager,'thread','apply',p['id'])
        self.assertFalse(self.state.to_dict()['dirty']);self.assertEqual(self.state.saved_contents['deck'],self.state.deck_contents['deck'])
        self.assertEqual([c['count'] for c in self.state.deck_contents['deck']],[1,2])
        self.assertEqual(self.fake.pushed[-1][1],[{'action':'remove','cardID':'a','count':2,'zone':'main'},{'action':'add','cardID':'b','count':2,'zone':'main'}])
        with self.assertRaises(ValueError):await act(self.manager,'thread','apply',p['id'])
        restored=DeckStateManager(self.path);self.assertFalse(restored.get_state('thread').to_dict()['dirty'])
        await act(restored,'thread','undo');self.assertEqual(restored.get_state('thread').deck_contents,DECK)
        self.assertFalse(restored.get_state('thread').to_dict()['dirty'])
    async def test_dismiss_and_stale_proposal(self):
        old=await self.proposal();new=await self.proposal()
        with self.assertRaises(ValueError):await act(self.manager,'thread','apply',old['id'])
        await act(self.manager,'thread','dismiss',new['id']);self.assertEqual(self.state.deck_contents,DECK)
    async def test_invalid_changes_are_atomic(self):
        for changes in [[Change(card_id='a',delta=-4,section='deck',reason='Too many')],[Change(card_id='unknown',delta=1,section='deck',reason='Unverified')]]:
            with self.assertRaises(ValueError):await propose(self.manager,'thread',changes,'Test')
            self.assertEqual(self.state.deck_contents,DECK);self.assertIsNone(self.state.proposal)
    async def test_switch_preserves_draft_and_isolates_threads(self):
        p=await self.proposal();await act(self.manager,'thread','apply',p['id'])
        self.manager.set_active_deck('thread',2,'Other');self.manager.set_active_deck('thread',1,'Test deck')
        self.assertFalse(self.manager.get_state('thread').to_dict()['dirty'])
        self.assertIsNone(self.manager.get_state('other-thread').deck_contents)
    async def test_local_draft_applies_without_server(self):
        local=self.manager.get_state('local-thread');local.source='local';local.deck_contents=deepcopy(DECK)
        p=await propose(self.manager,'local-thread',[Change(card_id='a',delta=-1,section='deck',reason='Trim top end')],'Local tune')
        await act(self.manager,'local-thread','apply',p['id'])
        self.assertTrue(self.manager.get_state('local-thread').to_dict()['dirty'])
        self.assertEqual(self.fake.pushed,[])
        await act(self.manager,'local-thread','undo')
        self.assertEqual(self.manager.get_state('local-thread').deck_contents,DECK)

class RemoveReconcileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'drafts.json'
        self.manager=DeckStateManager(self.path);self.manager.set_active_deck('thread',1,'Test deck')
        self.state=self.manager.get_state('thread');self.state.deck_contents=deepcopy(DECK)
        self.fake=FakeSWU(DECK)
        self.push=patch("app.swustats_write.push_deck_changes",side_effect=self.fake.push);self.push.start()
        self.fetch=patch("app.tools.load_deck.fetch_deck_contents",side_effect=self.fake.fetch);self.fetch.start()
    def tearDown(self):self.push.stop();self.fetch.stop();self.temp.cleanup()
    async def test_remove_uses_authoritative_zone_and_count(self):
        self.fake.contents={'metadata':{'name':'Test deck'},'deck':[],'sideboard':[{'id':'a','name':'Card A','count':2}]}
        await remove_card(self.manager,'thread',1,0,'a','deck',True)
        self.assertEqual(self.fake.pushed[-1][1],[{'action':'remove','cardID':'a','count':2,'zone':'side'}])
    async def test_remove_missing_remotely_reports_drift(self):
        self.fake.contents={'metadata':{'name':'Test deck'},'deck':[],'sideboard':[]}
        with self.assertRaises(ValueError) as ctx:
            await remove_card(self.manager,'thread',1,0,'a','deck',True)
        self.assertIn("no longer has that card",str(ctx.exception))
        self.assertEqual(len(self.fake.pushed),1)
    async def test_linked_remove_enriches_refetched_rows(self):
        self.fake.contents={'metadata':{'name':'Test deck'},'deck':[{'id':'a','count':3}],'sideboard':[]}
        full={'id':'a','name':'Card A','cost':5,'type':'Unit'}
        with patch("app.catalog.catalog",AsyncMock(return_value={'a':full})):
            await remove_card(self.manager,'thread',1,0,'a','deck',False)
        row=next(c for c in self.state.deck_contents['deck'] if c['id']=='a')
        self.assertEqual(row['name'],'Card A')
        self.assertEqual(row['type'],'Unit')
    async def test_linked_remove_skips_refresh_fetch(self):
        with patch("app.tools.load_deck.fetch_deck_contents") as mock_fetch:
            await remove_card(self.manager,'thread',1,0,'a','deck',False)
        mock_fetch.assert_not_called()
        self.assertEqual(self.fake.pushed[-1][1],[{'action':'remove','cardID':'a','count':1,'zone':'main'}])
        row=next(c for c in self.state.deck_contents['deck'] if c['id']=='a')
        self.assertEqual(row['count'],2)
        self.assertFalse(self.state.to_dict()['dirty'])


class AddCardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'drafts.json'
        self.manager=DeckStateManager(self.path);self.manager.set_active_deck('thread',1,'Test deck')
        self.state=self.manager.get_state('thread');self.state.deck_contents=deepcopy(DECK)
        self.fake=FakeSWU(DECK)
        self.push=patch("app.swustats_write.push_deck_changes",side_effect=self.fake.push);self.push.start()
        self.fetch=patch("app.tools.load_deck.fetch_deck_contents",side_effect=self.fake.fetch);self.fetch.start()
    def tearDown(self):self.push.stop();self.fetch.stop();self.temp.cleanup()
    async def test_linked_add_pushes_single_copy(self):
        await add_card(self.manager,'thread',1,0,'a','deck')
        self.assertEqual(self.fake.pushed[-1][1],[{'action':'add','cardID':'a','count':1,'zone':'main'}])
        row=next(c for c in self.state.deck_contents['deck'] if c['id']=='a')
        self.assertEqual(row['count'],4)
    async def test_local_add_increments_without_push(self):
        self.state.source='local'
        await add_card(self.manager,'thread',1,0,'a','deck')
        row=next(c for c in self.state.deck_contents['deck'] if c['id']=='a')
        self.assertEqual(row['count'],4)
        self.assertEqual(self.fake.pushed,[])
    async def test_linked_add_skips_refresh_fetch(self):
        with patch("app.tools.load_deck.fetch_deck_contents") as mock_fetch:
            await add_card(self.manager,'thread',1,0,'a','deck')
        mock_fetch.assert_not_called()
        self.assertEqual(self.fake.pushed[-1][1],[{'action':'add','cardID':'a','count':1,'zone':'main'}])
        row=next(c for c in self.state.deck_contents['deck'] if c['id']=='a')
        self.assertEqual(row['count'],4)
        self.assertFalse(self.state.to_dict()['dirty'])


class ConversationPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_and_messages_survive_restart(self):
        from app.memory_store import MemoryStore
        from chatkit.types import ThreadMetadata,AssistantMessageItem,AssistantMessageContent
        from datetime import datetime,timezone
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"conversations.json"
            store=MemoryStore(path)
            now=datetime.now(timezone.utc)
            await store.save_thread(ThreadMetadata(id="t",created_at=now,title="Deck"),{})
            item=AssistantMessageItem(id="m",thread_id="t",created_at=now,content=[AssistantMessageContent(text="Proposal ready")])
            await store.add_thread_item("t",item,{})
            restored=MemoryStore(path)
            self.assertEqual((await restored.load_item("t","m",{})).content[0].text,"Proposal ready")
            await restored.delete_thread("t",{})
            self.assertNotIn("t",MemoryStore(path).threads)

if __name__=='__main__':unittest.main()
