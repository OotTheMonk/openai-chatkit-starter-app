"""Tool for getting the currently active deck."""

import logging
from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext

logger = logging.getLogger(__name__)


@function_tool
def get_active_deck_tool(
    ctx: RunContextWrapper[AgentContext],
) -> str:
    """
    Get the currently active deck for this conversation.
    
    Returns:
        str: Information about the active deck, or a message if none is set
    """
    deck_manager = ctx.context.request_context.get("deck_manager")
    if not deck_manager:
        return "❌ Error: Deck manager not available"
    
    thread_id = ctx.context.thread.id
    logger.info(f"🔍 get_active_deck_tool: thread_id={thread_id}")
    logger.info(f"🔍 All stored states: {list(deck_manager._states.keys())}")
    
    deck_id, deck_name = deck_manager.get_active_deck(thread_id)
    logger.info(f"🔍 Retrieved: deck_id={deck_id}, deck_name={deck_name}")
    
    if deck_id is None:
        return "ℹ️ No active deck is currently set. Ask the user which deck they want to work on, or use get_user_decks_tool to show them their decks."
    
    return f"✅ Active deck: **{deck_name}** (ID: {deck_id})"
