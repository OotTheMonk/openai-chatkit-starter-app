import unittest
from types import SimpleNamespace
from app.memory_store import MemoryStore

def item(id,text=""):
    return SimpleNamespace(id=id,content=[{"text":text}])

class MemoryStoreItemIdTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store=MemoryStore()
    async def test_add_distinct_ids_appends(self):
        await self.store.add_thread_item("t",item("msg_a","hi"),{})
        await self.store.add_thread_item("t",item("msg_b","yo"),{})
        self.assertEqual([i.id for i in self.store.items["t"]],["msg_a","msg_b"])
    async def test_add_reused_placeholder_id_collapses(self):
        await self.store.add_thread_item("t",item("__fake_id__",""),{})
        await self.store.add_thread_item("t",item("__fake_id__","\n\n"),{})
        await self.store.add_thread_item("t",item("msg_real","done"),{})
        ids=[i.id for i in self.store.items["t"]]
        self.assertEqual(ids,["__fake_id__","msg_real"])
        self.assertEqual(self.store.items["t"][0].content,[{"text":"\n\n"}])
    async def test_save_item_replaces_by_id(self):
        await self.store.add_thread_item("t",item("msg_a","old"),{})
        await self.store.save_item("t",item("msg_a","new"),{})
        self.assertEqual(len(self.store.items["t"]),1)
        self.assertEqual(self.store.items["t"][0].content,[{"text":"new"}])

if __name__=="__main__":unittest.main()
