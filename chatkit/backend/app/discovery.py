"""Leader discovery uses structured releases and explainable taste signals, not vector search.

Rules are a dated, source-backed snapshot, not a live tournament certification.
Unknown sets and future previews are deliberately excluded.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
from typing import Literal
from uuid import uuid4
import json
import re
from pydantic import BaseModel, Field
from agents import function_tool, RunContextWrapper
from chatkit.agents import AgentContext
from chatkit.types import ClientEffectEvent
from .catalog import catalog
from .tools.deck_list import fetch_user_decks

CHECKED = date(2026, 9, 19)
VALID_UNTIL = date(2026, 9, 26)
SETS = {
    "SOR": ("Spark of Rebellion", "2024-03-08", 1),
    "SHD": ("Shadows of the Galaxy", "2024-07-12", 2),
    "TWI": ("Twilight of the Republic", "2024-11-08", 3),
    "JTL": ("Jump to Lightspeed", "2025-03-14", 4),
    "LOF": ("Legends of the Force", "2025-07-11", 5),
    "SEC": ("Secrets of Power", "2025-11-07", 6),
    "LAW": ("A Lawless Time", "2026-03-13", 7),
    "ASH": ("Ashes of the Empire", "2026-07-17", 8),
}
SOURCES = [
    {"label":"Rotation and reprints", "url":"https://starwarsunlimited.com/articles/updates-and-rotations"},
    {"label":"Cad Bane suspension", "url":"https://starwarsunlimited.com/articles/cad-banned"},
    {"label":"Eternal suspensions", "url":"https://starwarsunlimited.com/articles/eternal-format-update-april-2026"},
]
RELEASE_SOURCES = {key: "https://starwarsunlimited.com/products/set-"+str(value[2])+"-"+value[0].lower().replace(" ","-") for key,value in SETS.items()}
# Card identity is the full name AND subtitle. Never ban every version of a character.
SUSPENSIONS = {
    "Premier": {"cad bane — still faster than you", "boba fett — collecting the bounty", "jango fett — concealing the conspiracy", "triple dark raid", "dj — blatant thief", "force throw"},
    "Eternal": {"war juggernaut", "ig-2000 — assassin's aggressor"},
}
SIGNALS = {
    "Fast pressure": r"raid|saboteur|damage to.*base|attack",
    "Control": r"exhaust.*enemy|defeat.*enemy|restore|shield",
    "Card advantage": r"draw|discard|look at.*card",
    "Synergy": r"token|force|pilot|coordinate|exploit|bounty|mandalorian",
}

class DiscoveryRequest(BaseModel):
    format: Literal["Premier", "Eternal"] = "Premier"
    window: Literal["6", "12", "all"] = "12"
    style: Literal["Any", "Fast pressure", "Control", "Card advantage", "Synergy"] = "Any"
    use_library: bool = True
    liked: list[str] = Field(default_factory=list, max_length=30)
    disliked: list[str] = Field(default_factory=list, max_length=30)
    goal: str = Field(default="", max_length=1000)

def tags(card):
    text = (card.get("text", "") + " " + card.get("back_text", "")).casefold()
    return {label for label, pattern in SIGNALS.items() if re.search(pattern, text)}

def identity(card):
    return (card.get("type"), card["name"].casefold())

def merged_cards(cards):
    """Reprints may have different cids; union printings by exact gameplay identity."""
    grouped = {}
    for card in cards.values():
        key = identity(card)
        if key not in grouped:grouped[key] = deepcopy(card)
        else:
            for printing in card.get("printings", []):
                if printing not in grouped[key].setdefault("printings", []):grouped[key]["printings"].append(printing)
    return list(grouped.values())

def release_info(card, today):
    releases = sorted((SETS[p["set"]][1],p["set"]) for p in card.get("printings", []) if p["set"] in SETS and SETS[p["set"]][1] <= today.isoformat())
    return releases

def eligible(card, format, today):
    releases = release_info(card,today)
    if not releases or card["name"].casefold() in SUSPENSIONS[format]:return False
    return format == "Eternal" or any(SETS[s][2] >= 4 for _,s in releases)

def recommend(cards, decks, request, today=None):
    today = today or date.today()
    leaders = [c for c in merged_cards(cards) if c.get("type") == "Leader"]
    aspects, traits, mechanics = Counter(), Counter(), Counter()
    evidence = []
    if request.use_library:
        for deck in decks:
            card = cards.get(str(deck.get("keyIndicator1")))
            if not card:continue
            weight = 3 if deck.get("is_favorite") else 1
            aspects.update({a:weight for a in card.get("aspects",[]) if a not in {"Heroism","Villainy"}})
            traits.update({t:weight for t in card.get("traits",[])})
            mechanics.update({t:weight for t in tags(card)})
            evidence.append({"name":deck.get("name") or card["name"],"leader":card["name"],"favorite":bool(deck.get("is_favorite"))})
    liked = [cards[i] for i in request.liked if i in cards]
    cutoff = date.min if request.window == "all" else today-timedelta(days=183 if request.window == "6" else 366)
    excluded = {identity(cards[i]) for i in request.disliked if i in cards}
    ranked = []
    for card in leaders:
        releases = release_info(card,today)
        if not eligible(card,request.format,today) or identity(card) in excluded:continue
        # A reprint is not a new leader. Compare its earliest known release.
        first, set_code = releases[0]
        if first < cutoff.isoformat():continue
        themes = tags(card)
        if request.style != "Any" and request.style not in themes:continue
        shared = sorted({a for a in card.get("aspects",[]) if aspects[a]})
        similar = [c["name"] for c in liked if (set(c.get("aspects",[]))-{"Heroism","Villainy"}) & set(card.get("aspects",[])) or tags(c)&themes]
        score = sum(aspects[a] for a in shared)+sum(traits[t]*.3 for t in card.get("traits",[]))+sum(mechanics[t]*.2 for t in themes)+len(similar)*100
        reasons = []
        if similar:reasons.append("Similar aspects or rules themes to your pick: "+similar[0]+".")
        if shared:reasons.append("Shares "+" / ".join(shared)+" with leaders in your saved decks; favorites count more.")
        if request.style != "Any":reasons.append("Its rules contain signals for your selected style: "+request.style+".")
        if not reasons:reasons.append("An exploratory pick from the release window; no strong preference match yet.")
        ranked.append((score,first,{**card,"released":first,"set_name":SETS[set_code][0],"release_source":RELEASE_SOURCES[set_code],"reasons":reasons,"themes":sorted(themes),"tradeoff":"Deploys at "+str(card.get("cost"))+" resources; consider how your opening turns support that plan." if card.get("cost") else "Review both sides and its support cards before committing.","format_status":"Within the recorded format pool; no known suspension"}))
    ranked.sort(key=lambda row:(-row[0],-date.fromisoformat(row[1]).toordinal(),row[2]["name"]))
    # Reserve the last place for a different aspect combination when possible.
    shortlist = [row[2] for row in ranked[:4]]
    if len(ranked)>4:
        seen = {tuple(sorted(c.get("aspects",[]))) for c in shortlist}
        shortlist.append(next((r[2] for r in ranked[4:] if tuple(sorted(r[2].get("aspects",[]))) not in seen),ranked[4][2]))
    bases = [c for c in merged_cards(cards) if c.get("type")=="Base" and eligible(c,request.format,today)]
    return {"request":request.model_dump(),"leaders":shortlist,"matching_count":len(ranked),"bases":sorted(bases,key=lambda c:c["name"]),"profile":sorted(evidence,key=lambda d:not d["favorite"])[:6],"checked_at":CHECKED.isoformat(),"stale":not CHECKED<=today<=VALID_UNTIL,"sources":SOURCES,"note":"Recommendations use card rules and tentative library preferences, not win-rate rankings. Format checks cover recorded booster releases and known suspensions, not complete deck legality. Unknown products and previews are excluded."}

async def discover(request):
    cards = await catalog()
    if not cards:raise ValueError("The card catalog is unavailable. Retry shortly.")
    library = await fetch_user_decks() if request.use_library else {"decks":[]}
    result = recommend(cards,library.get("decks",[]),request)
    result["library_status"] = "unavailable" if library.get("error") else "used" if request.use_library else "off"
    return result

async def create_draft(manager, thread_id, leader_id, base_id, request):
    cards = await catalog()
    all_cards = merged_cards(cards)
    leader, base = cards.get(leader_id), cards.get(base_id)
    if not leader or leader.get("type")!="Leader" or not base or base.get("type")!="Base":raise ValueError("Choose a verified leader and base.")
    for card in (leader,base):
        merged = next(c for c in all_cards if identity(c)==identity(card))
        if not eligible(merged,request.format,date.today()):raise ValueError("This leader or base is outside the recorded format pool or has a known suspension.")
    deck_id = -int(uuid4().hex[:12],16)
    manager.set_active_deck(thread_id,deck_id,leader["name"]+" draft")
    state=manager.get_state(thread_id)
    state.source="local"
    state.build_preferences=request.model_dump()
    state.deck_contents={"deck_id":deck_id,"metadata":{"name":state.active_deck_name},"leader":{**leader,"count":1},"base":{**base,"count":1},"deck":[],"sideboard":[]}
    state.saved_contents=deepcopy(state.deck_contents)
    manager.discovery[thread_id]={"request":request.model_dump(),"needs_format":False}
    manager.save()
    return state

@function_tool
async def discover_leaders(ctx:RunContextWrapper[AgentContext], format:Literal["Premier","Eternal"]|None=None, style:Literal["Any","Fast pressure","Control","Card advantage","Synergy"]="Any", months:Literal["6","12","all"]="12", goal:str="")->str:
    """Discover leaders a player might enjoy, especially returning players asking about recent leaders or rotation. Opens an interactive shortlist with preferences, format, comparison and new-draft actions. NEVER use semantic card search for this intent. Leave format null if the player has not specified it; the UI asks them to choose before making rotation claims."""
    request=DiscoveryRequest(format=format or "Premier",style=style,window=months,goal=goal)
    manager=ctx.context.request_context["deck_manager"]
    manager.discovery[ctx.context.thread.id]={"request":request.model_dump(),"needs_format":format is None}
    manager.save()
    await ctx.context.stream(ClientEffectEvent(name="discover_leaders",data={}))
    if format is None:return "Leader discovery opened. Ask the player to select Premier or Eternal and a release window there. Do not claim their decks rotated or recommend unverified cards."
    result=await discover(request)
    return json.dumps({k:v for k,v in result.items() if k not in {"bases"}})
