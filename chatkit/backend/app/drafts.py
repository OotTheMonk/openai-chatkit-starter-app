"""Reviewable drafts. Committed changes to a linked deck persist to SWUStats
in atomic batches; proposals stay local until applied; local drafts stay local."""
from copy import deepcopy
from uuid import uuid4
from pydantic import BaseModel, Field
from typing import Literal
from agents import function_tool,RunContextWrapper
from chatkit.agents import AgentContext
from chatkit.types import ClientEffectEvent
from .catalog import catalog,enrich
from .swu import track_request,describe_evidence

class Change(BaseModel):
    card_id: str
    delta: int = Field(ge=-99,le=99)
    section: Literal["deck","sideboard"]
    reason: str = Field(min_length=1,max_length=1000)

async def ensure_draft(manager, thread_id):
    from .tools.load_deck import fetch_deck_contents
    state=manager.get_state(thread_id)
    if not state.active_deck_id:raise ValueError("Select a deck first.")
    if not state.deck_contents or state.deck_contents.get("error"):
        if state.source == "local":raise ValueError("This local draft is missing its contents; choose a new starting point.")
        expected_id=state.active_deck_id
        contents=await fetch_deck_contents(expected_id)
        contents=await enrich(contents)
        if manager.get_state(thread_id) is not state or state.active_deck_id!=expected_id:
            raise ValueError("The active deck changed. Try again.")
        if contents.get("error"):raise ValueError("Reconnect SWUStats or retry loading this deck.")
        state.deck_contents=contents
    await enrich(state.deck_contents)
    if state.saved_contents is not None:await enrich(state.saved_contents)
    if state.saved_contents is None:state.saved_contents=deepcopy(state.deck_contents)
    manager.save()
    return state

def proposed_contents(state,changes,cards):
    result=deepcopy(state.deck_contents)
    seen=set()
    normalized=[]
    for change in changes:
        key=(change.section,change.card_id)
        if key in seen or not change.delta:raise ValueError("Each card/section must have one nonzero change.")
        seen.add(key)
        rows=result[change.section]
        existing=next((c for c in rows if str(c["id"])==change.card_id),None)
        metadata=cards.get(change.card_id) or existing
        if not metadata:raise ValueError("Search for a verified card ID before adding it.")
        if change.delta>0 and metadata.get("type") in {"Leader","Base"}:
            raise ValueError("Leaders and bases cannot be added to the main deck or sideboard.")
        count=(existing["count"] if existing else 0)+change.delta
        if count<0 or count>99:raise ValueError("The proposed quantity is outside the valid range.")
        if existing:
            if count:existing["count"]=count
            else:rows.remove(existing)
        elif count:rows.append({**metadata,"count":count})
        normalized.append({**change.model_dump(),"name":metadata.get("name") or change.card_id})
    return result,normalized

async def propose(manager,thread_id,changes,goal):
    state=await ensure_draft(manager,thread_id)
    expected_id,revision=state.active_deck_id,state.revision
    cards=await catalog()
    if manager.get_state(thread_id) is not state or state.active_deck_id!=expected_id or state.revision!=revision:
        raise ValueError("The working draft changed. Read it again before proposing edits.")
    result,normalized=proposed_contents(state,changes,cards)
    if state.build_preferences.get("format"):
        from .discovery import eligible, merged_cards, identity
        from datetime import date
        merged={identity(c):c for c in merged_cards(cards)}
        for change in changes:
            card=cards.get(change.card_id)
            if change.delta>0 and (not card or not eligible(merged[identity(card)],state.build_preferences["format"],date.today())):
                raise ValueError("An addition is outside this draft's recorded format pool or has a known suspension. Search for another card.")
    if not normalized:raise ValueError("Include at least one change.")
    from .deck_analysis import analyze
    state.proposal={"analysis":analyze(result,state.build_preferences),"evidence":state.research,"id":str(uuid4()),"revision":state.revision,"goal":goal,"changes":normalized,"contents":result}
    manager.save()
    return state.proposal

def _linked(state):
    """A deck with a SWUStats id persists remotely; local drafts stay local."""
    return state.active_deck_id is not None and state.source != "local"


def _op(action, card_id, count, zone):
    """One bulk-endpoint op."""
    return {"action": action, "cardID": str(card_id), "count": count, "zone": zone}


def _ops_from_changes(changes):
    """Normalized proposal rows to bulk-endpoint ops."""
    ops = []
    for change in changes:
        delta = change.get("delta", 0) or 0
        if not delta:
            continue
        ops.append(_op("add" if delta > 0 else "remove", change.get("card_id"),
                        abs(delta), "main" if change.get("section") == "deck" else "side"))
    return ops


def diff_contents(old, new):
    """Bulk-endpoint ops that turn old contents into new (deck/sideboard counts)."""
    ops = []
    for section, zone in (("deck", "main"), ("sideboard", "side")):
        old_counts, new_counts = {}, {}
        for row in old.get(section) or []:
            key = str(row.get("id"))
            old_counts[key] = old_counts.get(key, 0) + (row.get("count", 0) or 0)
        for row in new.get(section) or []:
            key = str(row.get("id"))
            new_counts[key] = new_counts.get(key, 0) + (row.get("count", 0) or 0)
        for card_id in sorted(set(old_counts) | set(new_counts)):
            delta = new_counts.get(card_id, 0) - old_counts.get(card_id, 0)
            if delta:
                ops.append(_op("add" if delta > 0 else "remove", card_id, abs(delta), zone))
    return ops


async def _commit_linked(manager, state, ops, refresh=True):
    """Push ops to SWUStats, then adopt the authoritative contents."""
    from .swustats_write import push_deck_changes
    from .tools.load_deck import fetch_deck_contents
    if not ops:
        return state.deck_contents
    await push_deck_changes(state.active_deck_id, ops)
    if not refresh and state.deck_contents:
        for op in ops:
            section="deck" if op.get("zone")=="main" else "sideboard"
            rows=state.deck_contents.get(section,[])
            card=next((c for c in rows if str(c.get("id"))==str(op.get("cardID"))),None)
            if card is None:break
            n=op.get("count") or 0
            if op.get("action")=="add":card["count"]=(card.get("count") or 0)+n
            else:
                card["count"]=(card.get("count") or 0)-n
                if card["count"]<=0:rows.remove(card)
        else:
            await enrich(state.deck_contents)
            state.saved_contents=deepcopy(state.deck_contents)
            return state.deck_contents
    result = await fetch_deck_contents(state.active_deck_id)
    if result.get("error"):
        raise ValueError(f"Saved to SWUStats but the refresh failed ({result['error']}); reopen the deck to sync.")
    state.deck_contents = await enrich(result)
    state.saved_contents = deepcopy(state.deck_contents)
    return state.deck_contents


def _record(manager,state,pre):
    state.undo_stack.append(pre);state.undo_stack=state.undo_stack[-20:]
    state.revision+=1;state.proposal=None;state.reviewed_changes=None
    manager.save()
    return state


async def act(manager,thread_id,action,proposal_id=None):
    state=manager.get_state(thread_id)
    if action in {"apply","dismiss"}:
        proposal=state.proposal
        if not proposal or proposal["id"]!=proposal_id or proposal["revision"]!=state.revision:
            raise ValueError("This proposal is no longer current. Refresh the draft.")
        if action=="apply":
            pre=deepcopy(state.deck_contents)
            if _linked(state):
                await _commit_linked(manager,state,_ops_from_changes(proposal["changes"]))
            else:
                state.deck_contents=deepcopy(proposal["contents"])
            state.undo_stack.append(pre)
            state.undo_stack=state.undo_stack[-20:]
            state.revision+=1
        state.proposal=None
    elif action=="undo":
        if not state.undo_stack:raise ValueError("There is no change to undo.")
        target=state.undo_stack.pop()
        if _linked(state):
            try:
                ops=diff_contents(state.deck_contents or {},target)
                if ops:
                    await _commit_linked(manager,state,ops)
                else:
                    state.deck_contents=deepcopy(target)
                    state.saved_contents=deepcopy(target)
            except Exception:
                state.undo_stack.append(target)
                raise
        else:
            state.deck_contents=target
        state.revision+=1
        state.proposal=None
    else:raise ValueError("Unknown draft action.")
    manager.save()
    return state

async def remove_card(manager,thread_id,deck_id,revision,card_id,section,all_copies=False):
    state=manager.get_state(thread_id)
    if state.active_deck_id!=deck_id or state.revision!=revision:raise ValueError("The deck changed. Refresh before removing cards.")
    if section not in {"deck","sideboard"} or not state.deck_contents:raise ValueError("Choose a card in the main deck or sideboard.")
    rows=state.deck_contents.get(section,[])
    card=next((c for c in rows if str(c['id'])==card_id),None)
    if not card:raise ValueError("This card is no longer in that section.")
    pre=deepcopy(state.deck_contents)
    if _linked(state):
        count=card["count"] if all_copies else 1
        zone="main" if section=="deck" else "side"
        try:
            await _commit_linked(manager,state,[_op("remove",card["id"],count,zone)],refresh=False)
        except ValueError as exc:
            if "specified zone" not in str(exc):raise
            from .tools.load_deck import fetch_deck_contents
            fresh=await fetch_deck_contents(state.active_deck_id)
            if fresh.get("error"):raise ValueError("Reconnect SWUStats or retry loading this deck.") from exc
            hit_zone=hit_count=None
            for sec,z in (("deck","main"),("sideboard","side")):
                hit=next((c for c in fresh.get(sec) or [] if str(c.get("id"))==card_id),None)
                if hit:
                    hit_zone,hit_count=z,hit.get("count") or 0
                    break
            if not hit_zone or not hit_count:raise ValueError("SWUStats no longer has that card; reselect the deck to sync, then try again.") from exc
            await _commit_linked(manager,state,[_op("remove",card["id"],hit_count if all_copies else 1,hit_zone)])
    else:
        if all_copies or card['count']==1:rows.remove(card)
        else:card['count']-=1
    return _record(manager,state,pre)

async def add_card(manager,thread_id,deck_id,revision,card_id,section):
    """Add one copy of a row already in the draft. Linked decks push a single add op."""
    state=manager.get_state(thread_id)
    if state.active_deck_id!=deck_id or state.revision!=revision:raise ValueError("The deck changed. Refresh before editing cards.")
    if section not in {"deck","sideboard"} or not state.deck_contents:raise ValueError("Choose a card in the main deck or sideboard.")
    rows=state.deck_contents.get(section,[])
    card=next((c for c in rows if str(c['id'])==card_id),None)
    if not card:raise ValueError("This card is no longer in that section.")
    pre=deepcopy(state.deck_contents)
    if _linked(state):
        await _commit_linked(manager,state,[_op("add",card["id"],1,"main" if section=="deck" else "side")],refresh=False)
    else:
        card['count']+=1
    return _record(manager,state,pre)

def slim_card(c):
    # Small candidate rows keep big candidate lists inside model context limits.
    # Fetch full rules text on demand with search_deck_cards.
    return {'id':c.get('id'),'name':c.get('name'),'cost':c.get('cost'),'type':c.get('type'),'aspects':c.get('aspects') or []}

def change_signature(state,changes):
    import hashlib,json
    # Editing explanatory wording or row order doesn't change the deck being analyzed.
    rows=sorted((c.section,c.card_id,c.delta) for c in changes)
    return hashlib.sha256(json.dumps([state.active_deck_id,state.revision,state.build_preferences,rows],sort_keys=True).encode()).hexdigest()

@function_tool
async def set_build_plan(ctx:RunContextWrapper[AgentContext],game_plan:str,style:Literal['Control','Fast pressure','Midrange','Combo'],early_units_min:int,expensive_max:int,interaction_min:int)->str:
    """Set an explicit construction plan before building: opening turns, stabilization, win condition and dependencies. Targets are flexible design choices, not universal rules. Explain departures from normal targets."""
    import json
    if not game_plan.strip() or any(not 0<=v<=60 for v in [early_units_min,expensive_max,interaction_min]):return 'Supply a game plan and targets between 0 and 60.'
    manager=ctx.context.request_context['deck_manager'];state=await ensure_draft(manager,ctx.context.thread.id)
    state.build_preferences.update({'game_plan':game_plan,'style':style,'targets':{'early_units_min':early_units_min,'expensive_max':expensive_max,'interaction_min':interaction_min}})
    state.reviewed_changes=None;manager.save()
    return json.dumps(state.build_preferences)

@function_tool
async def analyze_deck_changes(ctx:RunContextWrapper[AgentContext],changes:list[Change])->str:
    """Analyze an exact proposed deck BEFORE proposing it. Review opening probability, effective curve, roles, conditional dependencies and warnings. Revise weaknesses, reanalyze revised changes, then propose the identical changes. This does not mutate deck cards."""
    import json
    from .deck_analysis import analyze
    manager=ctx.context.request_context['deck_manager'];state=await ensure_draft(manager,ctx.context.thread.id)
    expected_id,revision=state.active_deck_id,state.revision
    cards=await catalog()
    if manager.get_state(ctx.context.thread.id) is not state or state.active_deck_id!=expected_id or state.revision!=revision:return 'Draft changed. Analyze it again.'
    try:result,_=proposed_contents(state,changes,cards)
    except ValueError as exc:return str(exc)
    state.reviewed_changes=change_signature(state,changes);manager.save()
    return json.dumps({"status":"analysis_only_no_proposal_exists","required_next_action":"After reviewing warnings, call propose_deck_changes with these identical changes to create the review UI. Do not tell the player a proposal is ready until that tool confirms success. If revising, analyze the revised changes first.","analysis":analyze(result,state.build_preferences)})

@function_tool
async def get_build_candidates(ctx:RunContextWrapper[AgentContext])->str:
    """Get real, in-aspect cards from the current draft's recorded format pool to build a starting shell. Use BEFORE naming cards for a new deck. Returns a capped sample of verified IDs with cost/type signals; use search_deck_cards for full rules text. Do not invent candidates."""
    import json
    from collections import Counter
    from datetime import date
    from .discovery import eligible,merged_cards
    from .deck_analysis import roles,analyze
    from .deck_research import research
    manager=ctx.context.request_context["deck_manager"]
    state=await ensure_draft(manager,ctx.context.thread.id)
    cards=await catalog()
    deck=state.deck_contents
    expected_id=state.active_deck_id
    evidence=await track_request(ctx.context,"Loading SWUStats matchup context",lambda: research(deck,state.build_preferences.get("format","Premier")),describe_evidence)
    if manager.get_state(ctx.context.thread.id) is not state or state.active_deck_id!=expected_id:return "The active deck changed. Retry."
    state.research=evidence;manager.save()
    available=Counter(deck.get("leader",{}).get("aspects",[])+deck.get("base",{}).get("aspects",[]))
    pool=[c for c in merged_cards(cards) if c.get("type") not in {"Leader","Base","Token"} and eligible(c,state.build_preferences.get("format","Premier"),date.today()) and not (Counter(c.get("aspects",[]))-available)]
    chosen={}
    # Role/curve coverage replaces shared-word similarity. No candidate is called proven.
    buckets={role:[c for c in pool if role in roles(c)] for role in ['interaction','healing','defense','card_advantage','space','finishers']}
    buckets['early_units']=[c for c in pool if c.get('type')=='Unit' and c.get('cost') is not None and c['cost']<=2]
    buckets['midgame_units']=[c for c in pool if c.get('type')=='Unit' and c.get('cost') is not None and 3<=c['cost']<=5]
    for category,options in buckets.items():
        options.sort(key=lambda c:(c.get('cost') if c.get('cost') is not None else 99,c['name']))
        for c in options[:5]:chosen[c['id']]=c
    from .swustats_stats import evidence as load_statistics
    evidence=await track_request(ctx.context,"Loading SWUStats card statistics",lambda: load_statistics(deck,state.build_preferences.get("format","Premier"),list(chosen)),describe_evidence)
    if manager.get_state(ctx.context.thread.id) is not state or state.active_deck_id!=expected_id:return "The active deck changed. Retry."
    state.research=evidence;manager.save()
    return json.dumps({"brief":state.build_preferences,"current_analysis":analyze(deck,state.build_preferences),"statistical_context":evidence,"note":"Candidates are a capped sample (5 per role, 35 max) with ID, name, cost, type and role signals but no full rules text, to fit model context limits. Use search_deck_cards for full rules of shortlisted names before analyzing or proposing. Read those rules and conditions: sentinel granted to another unit is not a standalone blocker, conditional healing is not guaranteed stabilization. Use research_build_statistics for shortlisted candidates; do not select cards purely by popularity or observed win rate. Set a build plan, analyze proposed changes, revise weaknesses, then submit for review.","cards":[{**slim_card(c),'role_signals':roles(c)} for c in chosen.values()]})

@function_tool
async def find_build_cards(ctx:RunContextWrapper[AgentContext],role:Literal['any','units','space','healing','defense','interaction','card_advantage','finishers'],min_cost:int=0,max_cost:int=20,offset:int=0)->str:
    """Browse additional verified in-aspect candidates by role and printed cost when the initial role samples miss a package. Paginated in groups of 30. Roles are text signals: inspect conditions, don't assume the label guarantees the function."""
    import json
    from collections import Counter
    from datetime import date
    from .discovery import merged_cards,eligible
    from .deck_analysis import roles
    if not 0<=min_cost<=max_cost<=30 or offset<0:return 'Use costs 0–30 and a nonnegative offset.'
    state=await ensure_draft(ctx.context.request_context['deck_manager'],ctx.context.thread.id)
    deck=state.deck_contents;cards=await catalog()
    available=Counter(deck.get('leader',{}).get('aspects',[])+deck.get('base',{}).get('aspects',[]))
    pool=[c for c in merged_cards(cards) if c.get('type') not in {'Leader','Base','Token'} and c.get('cost') is not None and min_cost<=c['cost']<=max_cost and not (Counter(c.get('aspects',[]))-available) and eligible(c,state.build_preferences.get('format','Premier'),date.today()) and (role=='any' or role in roles(c))]
    pool.sort(key=lambda c:(c['cost'],c['name']))
    return json.dumps({'total':len(pool),'next_offset':offset+30 if offset+30<len(pool) else None,'cards':[slim_card(c) for c in pool[offset:offset+30]]})

@function_tool
async def search_deck_cards(ctx:RunContextWrapper[AgentContext],query:str)->str:
    """Find verified card IDs, names, costs, types and rules text for draft proposals. Search by card name."""
    import json
    cards=await catalog()
    matches=[c for c in cards.values() if query.casefold() in c["name"].casefold()]
    state=ctx.context.request_context["deck_manager"].get_state(ctx.context.thread.id)
    if state.build_preferences.get("format"):
        from .discovery import eligible,merged_cards
        from datetime import date
        matches=[c for c in merged_cards({c["id"]:c for c in matches}) if eligible(c,state.build_preferences["format"],date.today())]
    return json.dumps(matches[:30])

@function_tool
async def get_working_draft(ctx:RunContextWrapper[AgentContext])->str:
    """Read the CURRENT draft including applied edits. Use before reasoning about or proposing edits."""
    import json
    try:
        state=await ensure_draft(ctx.context.request_context["deck_manager"],ctx.context.thread.id)
        return json.dumps(state.to_dict())
    except ValueError as exc:return str(exc)

@function_tool
async def propose_deck_changes(ctx:RunContextWrapper[AgentContext],goal:str,changes:list[Change])->str:
    """Propose adds/cuts to the active draft. Does NOT apply. Use verified IDs from the draft or search_deck_cards. Each row needs a reason. User reviews and applies via UI."""
    ctx.context.request_context['unfinished_proposal']=True
    try:
        manager=ctx.context.request_context['deck_manager'];state=manager.get_state(ctx.context.thread.id)
        if sum(c.delta for c in changes)>=40 and not state.build_preferences.get('game_plan'):return 'Call set_build_plan first with the opening plan, stabilization, win condition and role targets, then analyze this proposed deck.'
        if sum(c.delta for c in changes)>=40 and state.research is None:return 'Call research_build_statistics or get_build_candidates first to establish what statistical context is available. No public decklists should be copied.'
        if state.reviewed_changes!=change_signature(state,changes):return 'Call analyze_deck_changes with these exact changes first. Address the warnings and reanalyze if you revise the list.'
        current=state.proposal
        if (current and current.get("revision")==state.revision
                and [(c.card_id,c.delta,c.section) for c in changes]
                == [(r.get("card_id"),r.get("delta"),r.get("section")) for r in current.get("changes",[])]):
            ctx.context.request_context['unfinished_proposal']=False
            return 'That exact proposal is already shown inline above with its Apply and Dismiss buttons. Do not call this tool again for it; present your response now and refer the user to the inline proposal.'
        from .swustats_stats import evidence
        expected_id,revision=state.active_deck_id,state.revision
        stats=await evidence(state.deck_contents,state.build_preferences.get('format','Premier'),list(dict.fromkeys(c.card_id for c in changes if c.delta>0)),(state.research or {}).get('start_week'),(state.research or {}).get('end_week'))
        if manager.get_state(ctx.context.thread.id) is not state or state.active_deck_id!=expected_id or state.revision!=revision:return 'Draft changed during research. Analyze the new draft again.'
        state.research=stats
        proposal=await propose(manager,ctx.context.thread.id,changes,goal)
        from .proposal_widget import build_proposal_widget
        contents = state.deck_contents or {}
        main = sum((c.get("count", 0) or 0) for c in contents.get("deck", []))
        removed = sum(-c.delta for c in changes if c.section == "deck" and c.delta < 0)
        apply_label = "Replace deck" if main > 0 and removed >= main else "Apply changes"
        widget = build_proposal_widget(goal, proposal["id"], apply_label, proposal["changes"])
        copy_text = "\n".join(
            f"{'Add' if c['delta'] > 0 else 'Remove'} {abs(c['delta'])}x {c.get('name', c['card_id'])}"
            for c in proposal["changes"]
        )
        await ctx.context.stream_widget(widget, copy_text=copy_text)
        await ctx.context.stream(ClientEffectEvent(name="draft_refresh",data={}))
        ctx.context.request_context['unfinished_proposal']=False
        return f"Proposal ready for review: {len(proposal['changes'])} changes. Nothing applied; the proposal is shown inline in this chat with Apply and Dismiss buttons. Do not list the proposed cards as text or markdown links. The evidence panel contains the verified statistics and their scope. In your response, focus on the gameplay hypothesis and what to test; refer the user to the inline proposal for numbers. Earlier conversation may have mislabeled card inclusion/played observations as distinct decks or games: those units are not established by this API."
    except ValueError as exc:return str(exc)
