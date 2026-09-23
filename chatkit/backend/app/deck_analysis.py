"""Deterministic construction checks. Strategic targets are heuristics, not win rates."""
from collections import Counter
from math import comb
import re

def roles(card):
    text=card.get("text","").lower()
    found=[]
    if card.get("type")=="Unit":found.append("units")
    if "Space" in card.get("arenas",[]):found.append("space")
    if re.search(r"restore\s*\d|heal.*(?:base|damage)",text):found.append("healing")
    if re.search(r"sentinel",text):found.append("defense")
    if re.search(r"(?:defeat|exhaust|return|capture).*enemy|deal.*damage.*(?:unit|enemy)",text):found.append("interaction")
    if re.search(r"draw.*card",text):found.append("card_advantage")
    if card.get("type")=="Unit" and (card.get("cost") or 0)>=6:found.append("finishers")
    return found

def effective_cost(card,deck):
    cost=card.get("cost")
    if cost is None:return None
    available=Counter(deck.get("leader",{}).get("aspects",[])+deck.get("base",{}).get("aspects",[]))
    return cost+2*sum(max(0,n-available[a]) for a,n in Counter(card.get("aspects",[])).items())

def analyze(deck,preferences=None):
    preferences=preferences or {}
    style=preferences.get("style","Any")
    if style=="Any" and re.search(r"control|stall|late.game",preferences.get("goal",""),re.I):style="Control"
    main=deck.get("deck",[]);side=deck.get("sideboard",[])
    total=sum(c["count"] for c in main)
    curve=Counter();role_counts=Counter();conditional=[];off_aspect=[];unknown=[]
    early=0
    for c in main:
        n=c["count"];cost=effective_cost(c,deck)
        if cost is None:unknown.append(c.get("name",c["id"]))
        else:
            curve[str(min(cost,7))]+=n
            if cost<=2 and c.get("type")=="Unit":early+=n
            if cost!=c.get("cost"):off_aspect.append(c.get("name",c["id"]))
        role_counts.update({role:n for role in roles(c)})
        if re.search(r"\bif\b|\bwhile\b|\bfor each\b|\banother\b",c.get("text",""),re.I):conditional.append(c.get("name",c["id"]))
    # Suggestions for a 50-card baseline, adjustable through explicit preferences.
    targets={"early_units_min":12 if style=="Fast pressure" else 8,"expensive_max":8 if style=="Fast pressure" else 12,"interaction_min":9 if style=="Control" else 6}
    overrides=preferences.get("targets",{})
    for key in targets:
        if isinstance(overrides.get(key),int):targets[key]=max(0,min(60,overrides[key]))
    warnings=[]
    if total<50:warnings.append(f"Incomplete shell: {total}/50 main-deck cards.")
    if sum(c['count'] for c in side)>10:warnings.append("More than 10 sideboard cards; review format and base rules.")
    quantities=Counter()
    for c in main+side:quantities[c.get("name") or c["id"]]+=c["count"]
    excess=[name for name,n in quantities.items() if n>3]
    if excess:warnings.append("More than three copies across main and sideboard: "+", ".join(excess)+". Check explicit exceptions.")
    if unknown:warnings.append("Unknown costs: "+", ".join(unknown))
    if off_aspect:warnings.append("Aspect penalties affect the curve: "+", ".join(off_aspect)+". Discounts and special rules are not modeled.")
    if total>=50:
        if early<targets['early_units_min']:warnings.append(f"Only {early} units playable for 0–2 resources before discounts; target at least {targets['early_units_min']} or explain another opening plan.")
        expensive=sum(c['count'] for c in main if (effective_cost(c,deck) or 0)>=6)
        if expensive>targets['expensive_max']:warnings.append(f"Top-heavy: {expensive} cards cost 6+ after aspect penalties; suggested maximum {targets['expensive_max']}.")
        if role_counts['interaction']<targets['interaction_min']:warnings.append("Few rules-text signals for interaction; review actual removal and disruption options.")
        if not role_counts['space']:warnings.append("No verified space units; explain how the deck contests or races space.")
    probability=None
    if total>=6:probability=round(100*(1-(comb(total-early,6)/comb(total,6) if total-early>=6 else 0)),1)
    return {"main_count":total,"side_count":sum(c['count'] for c in side),"style":style,"targets":targets,"curve":dict(curve),"early_units":early,"opening_early_probability":probability,"roles":dict(role_counts),"conditional_cards":conditional,"warnings":warnings,"note":"Heuristic 50-card baseline. Opening probability is at least one 0–2-cost unit in six cards, without mulligan. Roles are rules-text signals, not verified strategic functions; review conditions and dependencies. Special base/deckbuilding rules and discounts require separate review."}
