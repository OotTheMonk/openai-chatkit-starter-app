"""Tool for setting the active deck."""

import logging
from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext
from chatkit.types import ClientEffectEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@function_tool
async def set_active_deck_tool(
    ctx: RunContextWrapper[AgentContext],
    deck_id: int,
    deck_name: str,
) -> str:
    """
    Set the active deck for the current conversation.
    
    Args:
        deck_id: The ID of the deck to set as active
        deck_name: The name of the deck
    
    Returns:
        str: Confirmation message
    """
    # Get the deck state manager from the context
    # We'll inject this via the agent context
    deck_manager = ctx.context.request_context.get("deck_manager")
    if not deck_manager:
        return "❌ Error: Deck manager not available"
    
    thread_id = ctx.context.thread.id
    result = deck_manager.set_active_deck(thread_id, deck_id, deck_name)
    
    # Load the deck contents immediately
    from .load_deck import fetch_deck_contents
    logger.info(f"📦 Loading deck contents for deck {deck_id}")
    contents = await fetch_deck_contents(deck_id)
    
    # Store the deck contents in the deck state
    deck_state = deck_manager.get_state(thread_id)
    deck_state.deck_contents = contents
    logger.info(f"✅ Stored deck contents in state for thread {thread_id}")
    
    # Emit a client effect to notify the frontend to refresh the deck panel
    logger.info(f"📤 Emitting deck_refresh effect for deck {deck_id}")
    await ctx.context.stream(
        ClientEffectEvent(
            name="deck_refresh",
            data={"deck_id": deck_id, "deck_name": deck_name},
        )
    )
    
    return result
