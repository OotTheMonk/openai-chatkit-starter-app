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
)
from pydantic import Field

from .memory_store import MemoryStore
from .tools import search_cards_tool, get_user_decks_tool

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
        "\n"
        "Use search_cards_tool for any card-related queries and get_user_decks_tool for deck lists."
    ),
    tools=[search_cards_tool, get_user_decks_tool],
    tool_use_behavior=StopAtTools(stop_at_tool_names=["search_cards_tool"]),
)

logger.info(f"✅ Agent created with {len(assistant_agent.tools)} tools")
logger.info(f"✅ Model: {MODEL}")
logger.info(f"✅ Tool names: {[str(t) for t in assistant_agent.tools]}")


class StarterChatServer(ChatKitServer[dict[str, Any]]):
    """Server implementation that keeps conversation state in memory."""

    def __init__(self) -> None:
        self.store: MemoryStore = MemoryStore()
        super().__init__(self.store)

    async def respond(
        self,
        thread: ThreadMetadata,
        item: UserMessageItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        logger.info(f"📨 User message: {item.content if item else 'None'}")
        
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
