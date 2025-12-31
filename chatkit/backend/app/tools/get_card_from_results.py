"""Tool for getting specific card details from stored search results."""

from __future__ import annotations

import logging
from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@function_tool
async def get_card_from_results_tool(
    ctx: RunContextWrapper[AgentContext],
    card_number: int,
) -> str:
    """
    Get details about a specific card from the most recent search results.
    
    Args:
        card_number: The number of the card from the search results (1-based index)
    
    Returns:
        Details about the requested card
    """
    try:
        logger.info(f"🔍 GET_CARD_FROM_RESULTS TOOL CALLED with card_number={card_number}")
        
        # Get the card search manager from context
        card_search_manager = ctx.context.request_context.get("card_search_manager")
        if not card_search_manager:
            return "❌ Card search manager not available."
        
        thread_id = ctx.context.thread.id
        
        # Check if there are stored results
        if not card_search_manager.has_results(thread_id):
            return "❌ No search results available. Please search for cards first using the search tool."
        
        # Get the specific card
        card = card_search_manager.get_card(thread_id, card_number)
        if not card:
            state = card_search_manager.get_state(thread_id)
            return (
                f"❌ Card number {card_number} not found. "
                f"The most recent search returned {len(state.results)} card(s). "
                f"Please use a number between 1 and {len(state.results)}."
            )
        
        logger.info(f"✅ Retrieved card #{card_number}: {card.ability[:50]}...")
        
        return (
            f"**Card #{card.index}**\n"
            f"Ability: {card.ability}\n"
            f"\n"
            f"Note: The card search API provides ability text only. "
            f"Card IDs and names are not available from the current data source."
        )
        
    except Exception as e:
        logger.error(f"❌ EXCEPTION in get_card_from_results_tool: {type(e).__name__}: {e}", exc_info=True)
        return f"Error: {str(e)}"
