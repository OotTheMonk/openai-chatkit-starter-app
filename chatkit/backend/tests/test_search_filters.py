import unittest
from unittest.mock import patch,AsyncMock
from app.server import build_search_request,apply_search_filters

class BuildSearchRequestTests(unittest.TestCase):
    def test_plain_query_unchanged(self):
        self.assertEqual(build_search_request("stealth"),"stealth")
    def test_discrete_tokens(self):
        self.assertEqual(build_search_request("units",aspect="Aggression",card_type="Unit"),"aspect:Aggression type:Unit units")
    def test_cost_bound(self):
        self.assertEqual(build_search_request("removal",max_cost=3),"cost<=3 removal")
    def test_equal_bounds_collapse(self):
        self.assertEqual(build_search_request("x",min_cost=2,max_cost=2),"cost:2 x")
    def test_unique(self):
        self.assertEqual(build_search_request("leader",unique_only=True),"unique:true leader")
    def test_filters_without_query(self):
        self.assertEqual(build_search_request("",trait="Trooper"),"trait:Trooper")

FAKE={"u1":{"id":"u1","name":"A","cost":2,"type":"Unit","aspects":["Aggression"],"traits":["Mandalorian"],"arenas":["Ground"],"hp":3},
      "u2":{"id":"u2","name":"B","cost":5,"type":"Event","aspects":["Cunning"],"traits":[],"arenas":[],"hp":None},
      "u3":{"id":"u3","name":"C","cost":None,"type":"Unit","aspects":["Aggression"],"traits":[],"arenas":[],"hp":None}}

class ApplySearchFiltersTests(unittest.IsolatedAsyncioTestCase):
    async def test_narrows_and_keeps_unknown(self):
        with patch("app.catalog.catalog",AsyncMock(return_value=FAKE)):
            out=await apply_search_filters([{"name":"A"},{"name":"B"},{"name":"C"},{"name":"Nope"}],aspect="aggression",max_cost=3)
        self.assertEqual([c["name"] for c in out],["A","C","Nope"])
    async def test_no_filters_returns_same_list(self):
        cards=[{"name":"A"}]
        with patch("app.catalog.catalog",AsyncMock(return_value={})):
            out=await apply_search_filters(cards)
        self.assertIs(out,cards)

if __name__=="__main__":unittest.main()
