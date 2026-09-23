"""Verified card metadata for draft edits; cached for one day."""
import asyncio
import json
import time
from pathlib import Path
import httpx

CACHE = Path(__file__).parent.parent / ".workspace" / "cards.json"
_cards = {}
_loaded = 0.
_lock = asyncio.Lock()

async def catalog():
    global _cards, _loaded
    async with _lock:
        if _cards and time.time()-_loaded < 86400:
            return _cards
        if not _cards and CACHE.exists():
            try:
                cached=json.loads(CACHE.read_text(encoding="utf-8"))
                if cached.get("version")!=4:raise ValueError("Old catalog")
                _cards, _loaded=cached["cards"],cached["time"]
                if time.time()-_loaded < 86400:return _cards
            except (ValueError,KeyError,OSError):pass
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                responses=await asyncio.gather(*[client.get("https://api.swu-db.com/cards/search",params={"q":q}) for q in ["c>=0","type:Base","type:Leader"]])
            cards={}
            for response in responses:
                response.raise_for_status()
                for c in response.json().get("data",[]):
                    if not c.get("cid"):continue
                    def strings(values):return [v.get("S","") if isinstance(v,dict) else v for v in values or []]
                    cid=str(c["cid"])
                    printing={"set":c.get("Set",""),"number":str(c.get("Number",""))}
                    if cid in cards:
                        if printing not in cards[cid]["printings"]:cards[cid]["printings"].append(printing)
                        continue
                    cards[cid]={"id":cid,"name":c["Name"]+(" — "+c["Subtitle"] if c.get("Subtitle") else ""),
                        "cost":int(c["Cost"]) if str(c.get("Cost","")).isdigit() else None,
                        "type":c.get("Type"),"aspects":strings(c.get("Aspects")),"text":c.get("FrontText", ""),
                        "arenas":strings(c.get("Arenas")),"back_text":c.get("BackText", ""),"traits":strings(c.get("Traits")),
                        "printings":[printing],"image":c.get("FrontArt"),"hp":c.get("HP")}
            if not cards:raise ValueError("Empty catalog")
            _cards,_loaded=cards,time.time()
            CACHE.parent.mkdir(exist_ok=True)
            CACHE.write_text(json.dumps({"version":4,"time":_loaded,"cards":cards}),encoding="utf-8")
        except (httpx.HTTPError,ValueError,OSError):
            if not _cards:return {}
        return _cards

async def enrich(deck):
    cards=await catalog()
    for c in [deck.get("leader"),deck.get("base"),*deck.get("deck",[]),*deck.get("sideboard",[])]:
        if c and str(c.get("id")) in cards:c.update(cards[str(c["id"])])
    return deck
