"""Aggregate evidence for original builds; no reference deck retrieval."""
import json
from agents import function_tool, RunContextWrapper
from chatkit.agents import AgentContext
from .swu import track_request, describe_evidence
from .swustats_stats import evidence

async def research(deck,format):
    return await evidence(deck,format)

@function_tool
async def research_build_statistics(ctx:RunContextWrapper[AgentContext],card_ids:list[str],start_week:int|None=None,end_week:int|None=None)->str:
    """Look up SWUStats matchup context and usage/performance observations for up to 20 verified candidate cards. No decklists. Default is explicitly all-time; only supply week IDs known from API evidence or the user, never guess calendar conversion. Statistics inform an original playstyle, not a highest-win-rate shopping list."""
    from .drafts import ensure_draft
    from .catalog import catalog
    manager=ctx.context.request_context['deck_manager'];thread=ctx.context.thread.id
    state=await ensure_draft(manager,thread);expected=state.active_deck_id
    cards=await catalog()
    if len(card_ids)>20 or any(i not in cards for i in card_ids):return 'Choose at most 20 verified card IDs from the catalog.'
    async def call():
        try:return await evidence(state.deck_contents,state.build_preferences.get('format','Premier'),card_ids,start_week,end_week)
        except ValueError as exc:return {'error':str(exc)}
    result=await track_request(ctx.context,f"Loading SWUStats statistics for {len(card_ids)} cards",call,describe_evidence)
    if isinstance(result,dict) and result.get('error') and 'kind' not in result:return result['error']
    if manager.get_state(thread) is not state or state.active_deck_id!=expected:return 'Deck changed. Research the current draft again.'
    state.research=result;manager.save()
    return json.dumps(result)
