import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app.discovery import DiscoveryRequest, recommend, create_draft, eligible
from app.deck_state import DeckStateManager
from app.drafts import ensure_draft, propose, Change, act

TODAY=date(2026,9,19)
def card(id,name,set="ASH",type="Leader",aspects=None,text="Draw a card"):
    return {"id":id,"name":name,"type":type,"aspects":aspects or ["Vigilance"],"traits":[],"text":text,"cost":5,"printings":[{"set":set,"number":"001"}]}

class DiscoveryTests(unittest.TestCase):
    def test_release_rotation_previews_and_suspension_identity(self):
        cards={c["id"]:c for c in [card("old","Old leader","SOR"),card("new","New leader"),card("preview","Preview","HMW"),card("banned","Cad Bane — Still Faster Than You"),card("other","Cad Bane — Another identity")]}
        result=recommend(cards,[],DiscoveryRequest(window="all"),TODAY)
        self.assertEqual({c['id'] for c in result['leaders']},{"new","other"})
        eternal=recommend(cards,[],DiscoveryRequest(format="Eternal",window="all"),TODAY)
        self.assertIn("old",{c['id'] for c in eternal['leaders']})
        self.assertIn("banned",{c['id'] for c in eternal['leaders']})
        self.assertFalse(eligible(cards['new'],"Premier",date(2026,1,1)))

    def test_reprint_is_eligible_but_not_recent_and_duplicates_merge(self):
        old=card("old","Same leader","SOR");new=card("new","Same leader","ASH")
        cards={"old":old,"new":new}
        self.assertEqual(recommend(cards,[],DiscoveryRequest(),TODAY)['leaders'],[])
        self.assertEqual(len(recommend(cards,[],DiscoveryRequest(window="all"),TODAY)['leaders']),1)

    def test_preferences_feedback_and_unknown_library(self):
        cards={"a":card("a","A",aspects=["Vigilance"]),"b":card("b","B",aspects=["Cunning"])}
        decks=[{"name":"My favorite","keyIndicator1":"b","is_favorite":True},{"name":"Unknown","keyIndicator1":"missing"}]
        result=recommend(cards,decks,DiscoveryRequest(),TODAY)
        self.assertEqual(result['leaders'][0]['id'],'b')
        self.assertIn("Cunning",result['leaders'][0]['reasons'][0])
        self.assertEqual(len(result['profile']),1)
        self.assertEqual(recommend(cards,decks,DiscoveryRequest(disliked=['b']),TODAY)['leaders'][0]['id'],'a')
        self.assertEqual(recommend(cards,decks,DiscoveryRequest(use_library=False),TODAY)['profile'],[])
        self.assertTrue(recommend(cards,[],DiscoveryRequest(),date(2027,1,1))['stale'])

class NewDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_starting_candidates_are_real_in_aspect_and_in_recorded_pool(self):
        import json
        from types import SimpleNamespace
        from agents import RunContextWrapper
        from app.drafts import get_build_candidates
        cards={c['id']:c for c in [card('l','Leader'),card('b','Base',type='Base'),card('yes','Supported unit',type='Unit'),card('no','Off-aspect',type='Unit',aspects=['Cunning']),card('old','Rotated','SOR',type='Unit'),card('preview','Preview','HMW',type='Unit')]}
        with tempfile.TemporaryDirectory() as temp:
            manager=DeckStateManager(Path(temp)/'state.json')
            with patch('app.discovery.catalog',AsyncMock(return_value=cards)),patch('app.drafts.catalog',AsyncMock(return_value=cards)),patch('app.drafts.enrich',AsyncMock(side_effect=lambda x:x)),patch('app.deck_research.research',AsyncMock(return_value={})),patch('app.swustats_stats.evidence',AsyncMock(return_value={})):
                await create_draft(manager,'t','l','b',DiscoveryRequest())
                context=RunContextWrapper(context=SimpleNamespace(request_context={'deck_manager':manager},thread=SimpleNamespace(id='t')))
                result=json.loads(await get_build_candidates.on_invoke_tool(context,'{}'))
                self.assertEqual([c['id'] for c in result['cards']],['yes'])

    async def test_local_draft_persists_and_proposals_never_fetch_or_overwrite_saved_deck(self):
        cards={"leader":card("leader","New leader"),"base":card("base","New base",type="Base"),"unit":card("unit","Unit",type="Unit"),"old":card("old","Old unit","SOR",type="Unit")}
        with tempfile.TemporaryDirectory() as temp:
            manager=DeckStateManager(Path(temp)/'state.json')
            manager.set_active_deck('existing',123,'Saved deck')
            with patch('app.discovery.catalog',AsyncMock(return_value=cards)),patch('app.drafts.catalog',AsyncMock(return_value=cards)),patch('app.drafts.enrich',AsyncMock(side_effect=lambda x:x)),patch('app.tools.load_deck.fetch_deck_contents',AsyncMock()) as remote:
                state=await create_draft(manager,'new','leader','base',DiscoveryRequest(goal="Midrange"))
                await ensure_draft(manager,'new')
                self.assertEqual(state.source,'local');self.assertTrue(state.to_dict()['dirty'])
                self.assertEqual(manager.get_state('existing').active_deck_id,123)
                remote.assert_not_called()
                with self.assertRaises(ValueError):await propose(manager,'new',[Change(card_id='old',delta=3,section='deck',reason='Rotated')],'Test')
                p=await propose(manager,'new',[Change(card_id='unit',delta=3,section='deck',reason='Early play')],'Starting shell')
                await act(manager,'new','apply',p['id']);self.assertEqual(state.deck_contents['deck'][0]['count'],3)
                await act(manager,'new','undo');self.assertEqual(state.deck_contents['deck'],[])
                restored=DeckStateManager(manager.path).get_state('new')
                self.assertEqual(restored.build_preferences['goal'],'Midrange')
                self.assertEqual(restored.source,'local')

    async def test_invalid_identity_does_not_mutate_state(self):
        with tempfile.TemporaryDirectory() as temp:
            manager=DeckStateManager(Path(temp)/'state.json')
            with patch('app.discovery.catalog',AsyncMock(return_value={'x':card('x','Unit',type='Unit')})):
                with self.assertRaises(ValueError):await create_draft(manager,'t','x','x',DiscoveryRequest())
            self.assertNotIn('t',manager._states)
