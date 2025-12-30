"""Tool for setting the active deck."""

from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext


@function_tool
def set_active_deck_tool(
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
    return result
