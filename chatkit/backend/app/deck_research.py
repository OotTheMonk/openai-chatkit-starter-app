"""Aggregate evidence for original builds; no reference deck retrieval."""
import json
import logging
logger=logging.getLogger("app.deck_research")
from agents import function_tool, RunContextWrapper
from chatkit.agents import AgentContext
from .swu import track_request, describe_evidence
from .swustats_stats import evidence

async def research(deck,format):
    return await evidence(deck,format)

@function_tool
async def research_build_statistics(ctx:RunContextWrapper[AgentContext],card_ids:list[str]|None=None,start_week:int|None=None,end_week:int|None=None)->str:
    """Look up SWUStats matchup context and usage/performance observations. Pass up to 20 verified candidate IDs for a focused question, or omit card_ids to research the entire active deck at once; never split one deck into batched calls. No decklists. Default is explicitly all-time; only supply week IDs known from API evidence or the user, never guess calendar conversion. Statistics inform an original playstyle, not a highest-win-rate shopping list."""
    from .drafts import ensure_draft
    from .catalog import catalog
    manager=ctx.context.request_context['deck_manager'];thread=ctx.context.thread.id
    state=await ensure_draft(manager,thread);expected=state.active_deck_id
    cards=await catalog()
    if card_ids is not None and (len(card_ids)>20 or any(i not in cards for i in card_ids)):return 'Choose at most 20 verified card IDs from the catalog.'
    async def call():
        try:return await evidence(state.deck_contents,state.build_preferences.get('format','Premier'),card_ids,start_week,end_week)
        except ValueError as exc:return {'error':str(exc)}
    title=f"Loading SWUStats statistics for {len(card_ids)} cards" if card_ids is not None else "Loading SWUStats statistics for the active deck"
    result=await track_request(ctx.context,title,call,describe_evidence)
    if isinstance(result,dict) and result.get('error') and 'kind' not in result:return result['error']
    if manager.get_state(thread) is not state or state.active_deck_id!=expected:return 'Deck changed. Research the current draft again.'
    state.research=result;manager.save()
    stats=[c for c in result.get("card_statistics",[]) if isinstance(c,dict)]
    if not stats and not result.get("matchups") and result.get("retrieved_at") is None:
        detail="; ".join(n for n in result.get("notices",[]) if n) or "the service did not return usable data"
        return ("SWUStats statistics are temporarily unavailable "
            f"({detail}). No win-rate inference can be made. "
            "Wait about a minute before retrying rather than retrying immediately.")
    if stats:
        try:
            from .stats_widget import build_stats_widget
            stats.sort(key=lambda c:(c.get("win_rate_when_played") is None,-(c.get("win_rate_when_played") or 0)))
            rows=[{**c,"image":(cards.get(str(c.get("id")),{}) or {}).get("image")} for c in stats]
            subtitle=f"{state.build_preferences.get('format','Premier')} · {len(stats)} card observation{'' if len(stats)==1 else 's'}"
            if any((c.get("sample_label") or "")!="Observed usage" for c in stats):subtitle+=" · small samples, treat as directional"
            logger.info(f"📊 Stats widget building for {len(rows)} rows")
            widget=build_stats_widget("Card performance",subtitle,rows)
            lines=[f"{c.get('name') or c.get('id')} — Play {c.get('play_rate')} · Win when played {c.get('win_rate_when_played')} ({c.get('sample_label') or 'unknown sample'})" for c in stats]
            await ctx.context.stream_widget(widget,copy_text="\n".join(lines))
            logger.info("📊 Stats widget streamed")
        except Exception as exc:
            logger.warning(f"Stats widget unavailable, returning numbers without it: {exc}")
    return json.dumps(result)
