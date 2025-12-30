"""ChatKit server that streams responses from a single assistant."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Annotated
from pathlib import Path
from datetime import datetime

from agents import Runner, Agent, StopAtTools
from chatkit.agents import AgentContext, simple_to_agent_input, stream_agent_response
from chatkit.server import ChatKitServer
from chatkit.types import (
    ThreadMetadata, 
    ThreadStreamEvent, 
    UserMessageItem,
    AssistantMessageItem,
    AssistantMessageContent,
    ThreadItemDoneEvent,
    ThreadItemReplacedEvent,
    Action,
    WidgetItem,
)
from pydantic import Field

from .memory_store import MemoryStore
from .tools import search_cards_tool, get_user_decks_tool, set_active_deck_tool, get_active_deck_tool
from .deck_state import DeckStateManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MAX_RECENT_ITEMS = 30
MODEL = "gpt-4o"  # Use full gpt-4o for better tool calling support


# ============================================================================
# Custom Agent Context
# ============================================================================

class CardSearchAgentContext(AgentContext):
    """Agent context with access to card search functionality."""
    store: Annotated[MemoryStore, Field(exclude=True)]
    widget_data: dict[str, Any] = Field(default_factory=dict, exclude=True)




# ============================================================================
# Create Agent with Card Search and Deck Tools
# ============================================================================

assistant_agent = Agent[CardSearchAgentContext](
    model=MODEL,
    name="Card Search & Deck Assistant",
    instructions=(
        "You are an expert Star Wars Unlimited card game assistant. "
        "You help players search for cards and manage their deck lists."
        "\n"
        "Available commands:"
        "- Search for cards: 'Find [card name or mechanic]', 'Search for...', 'What cards...'"
        "- View deck lists: 'Show my decks', 'List my decks', 'What decks do I have'"
        "- Check active deck: 'What deck am I working on?', 'Which deck is active?'"
        "- Set active deck: User will click a button in the deck list widget"
        "\n"
        "Use the appropriate tools for each query."
    ),
    tools=[search_cards_tool, get_user_decks_tool, set_active_deck_tool, get_active_deck_tool],
    # Only stop at tools that produce widgets - get_active_deck_tool returns a string
    # that the agent should use to formulate a response
    tool_use_behavior=StopAtTools(stop_at_tool_names=["search_cards_tool", "get_user_decks_tool"]),
)

logger.info(f"✅ Agent created with {len(assistant_agent.tools)} tools")
logger.info(f"✅ Model: {MODEL}")
logger.info(f"✅ Tool names: {[str(t) for t in assistant_agent.tools]}")


class StarterChatServer(ChatKitServer[dict[str, Any]]):
    """Server implementation that keeps conversation state in memory."""

    def __init__(self) -> None:
        self.store: MemoryStore = MemoryStore()
        self.deck_manager: DeckStateManager = DeckStateManager()
        super().__init__(self.store)

    async def respond(
        self,
        thread: ThreadMetadata,
        item: UserMessageItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        logger.info(f"📨 User message: {item.content if item else 'None'}")
        
        # Inject deck manager into request context so tools can access it
        context["deck_manager"] = self.deck_manager
        
        # Create agent context with card search capabilities
        agent_context = CardSearchAgentContext(
            thread=thread,
            store=self.store,
            request_context=context,
        )
        
        items_page = await self.store.load_thread_items(
            thread.id,
            after=None,
            limit=MAX_RECENT_ITEMS,
            order="desc",
            context=context,
        )
        items = list(reversed(items_page.data))
        agent_input = await simple_to_agent_input(items)

        logger.info(f"🤖 Running agent with {len(items)} conversation items")
        logger.info(f"🛠️ Agent has tools: {[t.name if hasattr(t, 'name') else str(t) for t in assistant_agent.tools]}")
        
        result = Runner.run_streamed(
            assistant_agent,
            agent_input,
            context=agent_context,
        )
        
        logger.info(f"💭 Runner returned: {type(result)}")
        
        event_count = 0
        async for event in stream_agent_response(agent_context, result):
            event_count += 1
            event_type = type(event).__name__
            logger.info(f"📤 Event {event_count}: {event_type}")
            if hasattr(event, 'content'):
                content_preview = str(event.content)[:100]
                logger.info(f"   Content: {content_preview}")
            yield event
        
        logger.info(f"✅ Finished streaming {event_count} events")

    async def action(
        self,
        thread: ThreadMetadata,
        action: Action[str, Any],
        sender: WidgetItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        """Handle widget button actions."""
        logger.info(f"🎬 ========== ACTION HANDLER ==========")
        logger.info(f"🎬 Action received: {action.type}")
        logger.info(f"🎬 Payload: {action.payload}")
        logger.info(f"🎬 Sender: {sender}")
        logger.info(f"🎬 Sender type: {type(sender)}")
        logger.info(f"🎬 Thread ID: {thread.id}")
        
        if action.type == "select_deck":
            logger.info(f"🎬 Routing to _handle_select_deck_action")
            async for event in self._handle_select_deck_action(thread, action, sender, context):
                yield event
            return
        
        logger.warning(f"⚠️ Unknown action type: {action.type}")
        return

    async def _handle_select_deck_action(
        self,
        thread: ThreadMetadata,
        action: Action[str, Any],
        sender: WidgetItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        """Handle selecting a deck as active."""
        logger.info(f"🎬 _handle_select_deck_action called")
        logger.info(f"🎬 sender: {sender}")
        logger.info(f"🎬 sender type: {type(sender)}")
        
        deck_id = action.payload.get("deck_id")
        deck_name = action.payload.get("deck_name")
        
        logger.info(f"🎬 deck_id: {deck_id}, deck_name: {deck_name}")
        
        if not deck_id or not deck_name:
            logger.error(f"❌ Missing deck_id or deck_name in action payload")
            # Send error message to user
            error_message = AssistantMessageItem(
                thread_id=thread.id,
                id=self.store.generate_item_id("message", thread, context),
                created_at=datetime.now(),
                content=[AssistantMessageContent(text="❌ Error: Could not select deck - missing information")],
            )
            yield ThreadItemDoneEvent(item=error_message)
            return
        
        # Set the active deck
        result = self.deck_manager.set_active_deck(thread.id, deck_id, deck_name)
        logger.info(f"✅ {result}")
        
        # Import the deck fetching function and widget builder
        from .tools.deck_list import fetch_user_decks
        from .deck_list_widget import build_deck_list_widget
        
        # Fetch updated deck list to refresh the widget
        deck_result = await fetch_user_decks()
        logger.info(f"🎬 deck_result: {deck_result['count']} decks fetched")
        
        if deck_result["decks"] and sender:
            # Sort decks: favorites first, then by name
            sorted_decks = sorted(
                deck_result["decks"],
                key=lambda d: (not d.get("is_favorite", False), d.get("name") or f"Unnamed {d.get('id', 0)}")
            )
            
            # Build updated widget with new active deck
            active_deck_id, active_deck_name = self.deck_manager.get_active_deck(thread.id)
            logger.info(f"🎬 Building updated widget with active_deck_id: {active_deck_id}")
            updated_widget = build_deck_list_widget(
                sorted_decks,
                deck_result["count"],
                active_deck_id=active_deck_id,
                active_deck_name=active_deck_name
            )
            
            # Replace the existing widget in place
            updated_widget_item = sender.model_copy(update={"widget": updated_widget})
            logger.info(f"🎬 Yielding ThreadItemReplacedEvent")
            yield ThreadItemReplacedEvent(item=updated_widget_item)
        elif not sender:
            logger.warning(f"⚠️ No sender widget provided - cannot update widget in place")
        
        # Always send a confirmation message
        logger.info(f"🎬 Sending confirmation message")
        message_item = AssistantMessageItem(
            thread_id=thread.id,
            id=self.store.generate_item_id("message", thread, context),
            created_at=datetime.now(),
            content=[AssistantMessageContent(text=result)],
        )
        yield ThreadItemDoneEvent(item=message_item)
        logger.info(f"🎬 _handle_select_deck_action completed")
