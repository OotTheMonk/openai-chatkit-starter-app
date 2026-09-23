import unittest
from unittest.mock import patch,AsyncMock
from app.swustats_stats import normalize_card,card_evidence,matchup_evidence,window_params,evidence

class StatisticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_is_scoped_by_window_and_does_not_leak_mutations(self):
        from app.swustats_stats import request,_cache
        from types import SimpleNamespace
        _cache.clear()
        client=AsyncMock();client.__aenter__.return_value=client
        client.get.return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:[{'cardUid':'a'}])
        with patch('app.swustats_stats.httpx.AsyncClient',return_value=client):
            first=await request('Stats/CardMetaStatsAPI.php',{'format':'premier'})
            first['data'].clear()
            second=await request('Stats/CardMetaStatsAPI.php',{'format':'premier'})
            self.assertEqual(len(second['data']),1)
            self.assertEqual(client.get.await_count,1)
            await request('Stats/CardMetaStatsAPI.php',{'format':'premier','startWeek':2})
            self.assertEqual(client.get.await_count,2)
        _cache.clear()

    def test_live_matchup_identifier_conversion(self):
        from app.swustats_stats import api_card_key
        self.assertEqual(api_card_key({'id':'1997690465','printings':[{'set':'ASH','number':'004'}]}),'ASH_004')
        self.assertEqual(api_card_key({'id':'123'}),'123')

    async def test_evidence_maps_opponent_names_and_preserves_window(self):
        metadata={'l':{'id':'l','name':'Leader','printings':[{'set':'ASH','number':'4'}]},'b':{'id':'b','name':'Base','printings':[{'set':'ASH','number':'19'}]}}
        mock_match=AsyncMock(return_value={'matchups':[{'opponent_leader_id':'ASH_004','opponent_base_id':'green','games':10,'win_rate':40}],'retrieved_at':'now','error':None,'scope':'aggregate'})
        with patch('app.swustats_stats.catalog',AsyncMock(return_value=metadata)),patch('app.swustats_stats.matchup_evidence',mock_match),patch('app.swustats_stats.card_evidence',AsyncMock(return_value={'cards':[],'missing_ids':[],'retrieved_at':'now','error':None,'scope':'all leaders'})):
            r=await evidence({'leader':{'id':'l'},'base':{'id':'b'}},'Premier',[],4,8)
            mock_match.assert_awaited_once_with('ASH_004','ASH_019','Premier',4,8)
            self.assertEqual(r['matchups'][0]['opponent_leader'],'Leader')
            self.assertIn('unspecified',r['matchups'][0]['opponent_base'])
            self.assertIn('4–8',r['window'])

    def test_live_and_documented_shapes_missing_and_zero(self):
        c=normalize_card({'cardUid':'a','timesIncluded':100,'timesIncludedInWins':40,'timesPlayed':0,'percentPlayedInWins':'0.00'})
        self.assertEqual(c['win_rate_when_included'],40)
        self.assertIsNone(c['win_rate_when_played'])
        c=normalize_card({'cardId':'a','timesIncluded':20,'timesPlayed':10,'winRateWhenPlayed':60})
        self.assertEqual(c['win_rate_when_played'],60)
        self.assertEqual(c['sample_label'],'Limited observations')
        self.assertIsNone(normalize_card({'cardId':'a'})['included'])
        self.assertIsNone(normalize_card({'cardId':'a','timesIncluded':5,'timesIncludedInWins':8})['win_rate_when_included'])

    async def test_bulk_response_is_matched_by_identity(self):
        with patch('app.swustats_stats.request',AsyncMock(return_value={'data':[{'cardUid':'other','timesIncluded':900},{'cardUid':'wanted','timesIncluded':10}],'error':None,'retrieved_at':'now'})):
            r=await card_evidence(['wanted','absent'],'Premier')
            self.assertEqual([c['id'] for c in r['cards']],['wanted'])
            self.assertEqual(r['missing_ids'],['absent'])

    async def test_matchups_validate_samples_and_preserve_scope(self):
        rows=[{'opponentLeaderID':'o','opponentBaseID':'b','numPlays':20,'numWins':8},{'leaderID':'wrong','opponentLeaderID':'o','opponentBaseID':'b','numPlays':100,'numWins':80},{'opponentLeaderID':'o','opponentBaseID':'b','numPlays':5,'numWins':8}]
        with patch('app.swustats_stats.request',AsyncMock(return_value={'data':rows,'error':None,'retrieved_at':'now'})):
            r=await matchup_evidence('l','b','Premier')
            self.assertEqual(len(r['matchups']),1)
            self.assertEqual(r['matchups'][0]['win_rate'],40)
            self.assertTrue(r['matchups'][0]['limited_sample'])

    async def test_empty_results_are_not_negative_evidence(self):
        with patch('app.swustats_stats.request',AsyncMock(return_value={'data':[],'error':None,'retrieved_at':'now'})),patch('app.swustats_stats.catalog',AsyncMock(return_value={})):
            r=await evidence({'leader':{'id':'l'},'base':{'id':'b'}},'Premier')
            self.assertIn('All-time',r['window'])
            self.assertTrue(any('not evidence' in n for n in r['notices']))
            self.assertEqual(r['card_statistics'],[])

    def test_windows_and_formats_are_not_guessed(self):
        self.assertEqual(window_params('Eternal',2,4),{'format':'eternal','startWeek':2,'endWeek':4})
        for args in [('typo',None,None),('Premier',5,2),('Premier',-1,None)]:
            with self.assertRaises(ValueError):window_params(*args)
