"""ChatKit server that streams responses from a single assistant."""

from __future__ import annotations

import asyncio
import logging
import os
from html.parser import HTMLParser

import httpx
from typing import Any, AsyncIterator, Annotated
from pathlib import Path
from .swu import swu_client, track_request, describe_cards
from .models import agent_for
from .config import SWU_CARD_SEARCH_URL, SWU_ELASTIC_SEARCH_URL, get_access_token
import re
from datetime import datetime

from agents import Runner, Agent, function_tool, RunContextWrapper
from chatkit.agents import AgentContext, simple_to_agent_input, stream_agent_response
from chatkit.server import ChatKitServer
from chatkit.actions import Action
from chatkit.types import (
    ThreadMetadata, 
    ThreadStreamEvent, 
    UserMessageItem,
    AssistantMessageItem,
    AssistantMessageContent,
    ThreadItemDoneEvent,
)
from chatkit.widgets import WidgetTemplate
from pydantic import Field

from .drafts import get_working_draft, search_deck_cards, propose_deck_changes, get_build_candidates, find_build_cards, set_build_plan, analyze_deck_changes
from .discovery import discover_leaders
from .deck_research import research_build_statistics
from .memory_store import MemoryStore
from .card_search_widget import build_card_search_widget
from .deck_state import DeckStateManager
from .tools import (
    get_user_decks_tool,
    set_active_deck_tool,
    get_active_deck_tool,
    load_deck_contents_tool,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MAX_RECENT_ITEMS = 30
MODEL = "gpt-4o"  # Use full gpt-4o for better tool calling support


def agent_max_turns() -> int:
    """Cap on agent loop turns (override with CHATKIT_MAX_TURNS).

    Deck builds chain many tool calls (draft, searches, statistics,
    analysis, proposal), so the SDK default of 10 aborts real work.
    """
    try:
        return max(1, int(os.getenv("CHATKIT_MAX_TURNS", "30")))
    except ValueError:
        return 30


# ============================================================================
# Custom Agent Context
# ============================================================================

class CardSearchAgentContext(AgentContext):
    """Agent context with access to card search functionality."""
    store: Annotated[MemoryStore, Field(exclude=True)]
    widget_data: dict[str, Any] = Field(default_factory=dict, exclude=True)


# ============================================================================
# Card Search Tool
# ============================================================================

class _CardListParser(HTMLParser):
    """Collect search-result items as (name, detail) pairs.

    Each <li> names its card in the first link; any other text in the
    item is rules text, not part of the name.
    """

    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str]] = []
        self._collecting = False
        self._in_first_link = False
        self._link_done = False
        self._link_text: list[str] = []
        self._tail_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self._collecting = True
            self._in_first_link = False
            self._link_done = False
            self._link_text = []
            self._tail_text = []
        elif tag == "a" and self._collecting and not self._link_done:
            self._in_first_link = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._collecting:
            self._in_first_link = False
            self._link_done = True
        elif tag == "li" and self._collecting:
            self._collecting = False
            name = " ".join("".join(self._link_text).split())
            detail = " ".join("".join(self._tail_text).split())
            if not name and detail:
                first, _, rest = detail.partition(". ")
                name, detail = first[:80], rest[:300]
            if name:
                self.items.append((name[:80], detail[:300]))

    def handle_data(self, data: str) -> None:
        if not self._collecting:
            return
        if self._in_first_link:
            self._link_text.append(data)
        else:
            self._tail_text.append(data)


async def attach_search_images(result: dict[str, Any]) -> dict[str, Any]:
    """Best-effort card art for hover popups: match result names to catalog images.

    Failures leave results imageless; the search itself never depends on art.
    """
    try:
        from .catalog import catalog
        cards = await catalog()
        by_name: dict[str, Any] = {}
        for meta in cards.values():
            by_name.setdefault(str(meta.get("name", "")).casefold(), meta)
        for card in result.get("cards", []):
            match = by_name.get(str(card.get("name", "")).casefold())
            if not match:
                continue
            if match.get("id"):
                card["id"] = match["id"]
            if match.get("image"):
                card["image"] = match["image"]
    except Exception as exc:
        logger.warning(f"Card art lookup failed: {exc}")
    return result


def _parse_search_html(html: str) -> list[dict[str, Any]]:
    """Turn the search result list into {name, text} cards.

    Scoped to the first <ul> as before, capped so a junk page cannot
    flood the agent with rows. A card row never shows rules text as its
    name: names come from link text (or the first sentence fallback).
    """
    ul_match = re.search(r"<ul>(.*?)</ul>", html, re.DOTALL)
    if not ul_match:
        return []
    parser = _CardListParser()
    parser.feed(ul_match.group(1))
    return [{"name": name, "text": detail} for name, detail in parser.items[:25]]


def _official_ids(message: str) -> list[str]:
    """Card UUIDs from the official search message; [] when absent."""
    if not isinstance(message, str) or "specificCards" not in message:
        return []
    return [part.strip() for part in message.split("=", 1)[1].split(",") if part.strip()]


def build_search_request(query,aspect=None,card_type=None,trait=None,arena=None,unique_only=False,min_cost=None,max_cost=None,min_power=None,max_power=None,min_hp=None,max_hp=None):
    """Combine semantic text with discrete pre-filter tokens for the official search endpoint."""
    tokens=[]
    if aspect:tokens.append(f"aspect:{aspect}")
    if card_type:tokens.append(f"type:{card_type}")
    if trait:tokens.append(f"trait:{trait}")
    if arena:tokens.append(f"arena:{arena}")
    if unique_only:tokens.append("unique:true")
    for key,lo,hi in (("cost",min_cost,max_cost),("power",min_power,max_power),("hp",min_hp,max_hp)):
        if lo is not None and hi is not None and lo==hi:tokens.append(f"{key}:{lo}")
        else:
            if lo is not None:tokens.append(f"{key}>={lo}")
            if hi is not None:tokens.append(f"{key}<={hi}")
    text=(query or "").strip()
    if text:tokens.append(text)
    return " ".join(tokens)


def _num(value):
    try:return int(str(value))
    except (TypeError,ValueError):return None


async def apply_search_filters(cards,aspect=None,card_type=None,trait=None,arena=None,unique_only=False,min_cost=None,max_cost=None,min_power=None,max_power=None,min_hp=None,max_hp=None):
    """Best-effort local narrowing for fallback results; keep cards matching verifiable fields.

    Power and uniqueness have no local data and are skipped; cards whose metadata
    lacks a filtered field are kept rather than dropped.
    """
    if not any([aspect,card_type,trait,arena,unique_only,min_cost,max_cost,min_power,max_power,min_hp,max_hp]):return cards
    from .catalog import catalog
    metas=await catalog()
    by_name={}
    for meta in metas.values():by_name.setdefault(str(meta.get("name","")).casefold(),meta)
    out=[]
    for card in cards:
        meta=by_name.get(str(card.get("name","")).casefold())
        if not meta:out.append(card);continue
        if aspect and str(aspect).casefold() not in [str(a).casefold() for a in meta.get("aspects",[])]:continue
        if card_type and str(meta.get("type","")).casefold()!=str(card_type).casefold():continue
        if trait and str(trait).casefold() not in [str(t).casefold() for t in meta.get("traits",[])]:continue
        if arena and str(arena).casefold() not in [str(a).casefold() for a in meta.get("arenas",[])]:continue
        cost=_num(meta.get("cost"));hp=_num(meta.get("hp"))
        if min_cost is not None and cost is not None and cost<min_cost:continue
        if max_cost is not None and cost is not None and cost>max_cost:continue
        if min_hp is not None and hp is not None and hp<min_hp:continue
        if max_hp is not None and hp is not None and hp>max_hp:continue
        out.append(card)
    return out


async def search_official(query: str) -> dict[str, Any] | None:
    """Official OAuth semantic search, resolved through the local catalog.

    Returns None when unavailable (no token, HTTP error, unexpected shape)
    so callers fall back to direct search.
    """
    try:
        token = await get_access_token()
        if not token:
            return None
        async with swu_client() as client:
            resp = await client.get(
                SWU_ELASTIC_SEARCH_URL,
                params={"request": query, "access_token": token},
                timeout=30.0
            )
        if resp.status_code != 200:
            logger.warning(f"Official card search HTTP {resp.status_code} for {query!r}")
            return None
        data = resp.json()
        message = data.get("message", "") if isinstance(data, dict) else ""
        ids = _official_ids(message)
        if not ids and "specificCards" not in str(message):
            return None
        from .catalog import catalog
        cards = await catalog()
        out = []
        for uid in ids[:10]:
            meta = cards.get(uid)
            if meta:
                out.append({"id": uid, "name": meta.get("name") or uid, "text": meta.get("text") or ""})
            else:
                out.append({"id": uid, "name": uid, "text": ""})
        return {"query": query, "cards": out, "count": len(out), "error": None}
    except Exception as exc:
        logger.warning(f"Official card search unavailable: {exc}")
        return None


async def search_cards_direct(query: str) -> dict[str, Any]:
    """
    Directly search for Star Wars Unlimited cards (not a tool, used internally).

    Args:
        query: Card name, keywords, or any search term

    Returns:
        Dictionary with card results and metadata for widget display
    """
    try:
        resp = None
        for attempt in (1, 2):
            try:
                async with swu_client() as client:
                    resp = await client.post(
                        SWU_CARD_SEARCH_URL,
                        data={"searchInput": query},
                        timeout=30.0
                    )
                break
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt == 2:
                    raise
                await asyncio.sleep(1.0)
        cards = _parse_search_html(resp.text)
        return {
            "query": query,
            "cards": cards,
            "count": len(cards),
            "error": None
        }
    except Exception as e:
        return {
            "query": query,
            "cards": [],
            "count": 0,
            "error": f"Error searching cards: {e}"
        }


@function_tool
async def search_cards(
    ctx: RunContextWrapper[CardSearchAgentContext],
    query: str,
    aspect: str | None = None,
    card_type: str | None = None,
    trait: str | None = None,
    arena: str | None = None,
    unique_only: bool = False,
    min_cost: int | None = None,
    max_cost: int | None = None,
    min_power: int | None = None,
    max_power: int | None = None,
    min_hp: int | None = None,
    max_hp: int | None = None,
) -> str:
    """
    Search for Star Wars Unlimited cards, optionally narrowed with discrete pre-filters.

    Args:
        query: Semantic search text: card name, keywords, or rules concept.
        aspect: Only cards with this aspect, e.g. "Aggression".
        card_type: Only this card type: Unit, Event, Upgrade, Leader or Base.
        trait: Only cards with this trait, e.g. "Mandalorian".
        arena: Only cards for this arena: Ground or Space.
        unique_only: Only unique cards.
        min_cost: Printed cost at least this much.
        max_cost: Printed cost at most this much, e.g. 3 for "cost 3 or less".
        min_power: Unit power at least this much.
        max_power: Unit power at most this much.
        min_hp: Unit HP at least this much.
        max_hp: Unit HP at most this much.

    All filters are optional: omit every filter the request does not state and
    never invent values. Remove words consumed by a filter from the query text
    (with trait='Imperial', the query must not still say 'imperial'); the query
    may be empty when filters capture the whole request. An exact cost N means
    min_cost=N and max_cost=N.

    Pre-filters apply server-side on official search; on the fallback they are
    applied best-effort locally (power and uniqueness cannot be checked locally
    and are skipped there).

    Returns:
        Message confirming widget was displayed
    """
    try:
        manager=ctx.context.request_context.get("deck_manager")
        if manager and manager.get_state(ctx.context.thread.id).source=="local":
            return "For this new local draft, call get_build_candidates now. It returns real in-aspect cards and verified IDs. Do not guess card names or infer collection ownership from search results."
        request = build_search_request(query,aspect=aspect,card_type=card_type,trait=trait,arena=arena,unique_only=unique_only,min_cost=min_cost,max_cost=max_cost,min_power=min_power,max_power=max_power,min_hp=min_hp,max_hp=max_hp)
        logger.info(f"🔍 SEARCH TOOL CALLED with query: {request}")
        async def call():
            found = await search_official(request)
            if found is None:
                found = await search_cards_direct(query)
                found["cards"] = await apply_search_filters(found["cards"],aspect=aspect,card_type=card_type,trait=trait,arena=arena,unique_only=unique_only,min_cost=min_cost,max_cost=max_cost,min_power=min_power,max_power=max_power,min_hp=min_hp,max_hp=max_hp)
                found["count"] = len(found["cards"])
                found["query"] = request
            else:
                logger.info(f"Official search returned {found['count']} cards for {request!r}")
            await attach_search_images(found)
            return found
        result = await track_request(ctx.context, f"Card search: {request}", call, lambda r: describe_cards(request, r))
        logger.info(f"✅ Search returned {result['count']} cards")
        
        # Handle errors
        if result["error"]:
            logger.warning(f"⚠️ Search error: {result['error']}")
            return f"Error: {result['error']}"
        
        if not result["cards"]:
            logger.info(f"No cards found for '{request}'")
            return f"No cards found matching '{request}'."
        
        # Build and stream the widget with card results
        logger.info(f"📊 Building widget for {result['count']} cards")
        widget = build_card_search_widget(request, result["cards"], result["count"])
        logger.info(f"📊 Widget built successfully")
        
        copy_text = "\n".join([card['name'] for card in result["cards"]])
        logger.info(f"📊 About to stream widget with copy_text length: {len(copy_text)}")
        
        await ctx.context.stream_widget(widget, copy_text=copy_text)
        logger.info(f"✅ Widget streamed with {result['count']} cards for '{request}'")
        
        return f"Found {result['count']} results for '{request}'."
    except Exception as e:
        logger.error(f"❌ EXCEPTION in search_cards: {type(e).__name__}: {e}", exc_info=True)
        return f"Error: {str(e)}"


# ============================================================================
# Create Agent with Card Search Tool
# ============================================================================

assistant_agent = Agent[CardSearchAgentContext](
    model=MODEL,
    name="Card Search Assistant",
    instructions=(
        "You are an expert Star Wars Unlimited card game assistant. "
        "You can search for cards and manage the user's deck collections.\n"
        "LEADER DISCOVERY: For requests about recent/new leaders, returning to the game, rotation, or leaders the player might enjoy, ALWAYS call discover_leaders. "
        "Never pass these concepts to semantic search_cards. If format is unspecified, pass null and ask them to choose in discovery. "
        "A saved deck is evidence of interest, not proof of their tastes or current legality. Do not assume all old decks rotated. "
        "When building a new local draft, use its build_preferences as the brief. ALWAYS call get_build_candidates BEFORE naming possible additions, then propose a starting shell for review. "
        "For full deck construction, first set_build_plan with the opening plan, stabilization, win condition and dependencies. "
        "Use find_build_cards to explore additional roles/cost bands beyond the initial samples. Use get_build_candidates (includes aggregate matchup context) or research_build_statistics. Use statistics as context for original builds: prioritize the player’s fun playstyle, coherent synergies and testable experiments. Never fetch or copy public lists. Do not rank cards purely by win rate or popularity. Distinguish observed associations from a synergy hypothesis. Call included/played counts observations, NEVER distinct decks or games unless the source explicitly establishes those units. Do not call a win rate average or above average without a valid comparison. Card statistics span all leaders; exact leader/base matchup statistics still mix lists and pilots. All-time data is not current-meta evidence. Missing data is not evidence against an innovative card. Explain what to test during play and propose alternatives that preserve the desired experience. In proposal reasons, distinguish the gameplay role, a rules-grounded synergy hypothesis, and any observed statistical evidence. Never claim a build is unprecedented or proven without evidence. Never claim unavailable popularity or win-rate data. "
        "Choose coherent card packages and role coverage; inspect actual rules. Conditional healing, granting sentinel, and incidental word matches are not interchangeable with reliable healing or blockers. "
        "Mandatory workflow: call analyze_deck_changes with exact changes, inspect warnings and opening probability, revise weaknesses and reanalyze before propose_deck_changes. "
        "Analysis alone does not create a proposal. For a requested proposal, finish by calling propose_deck_changes and confirm its success before your final reply. "
        "Explain intentional target exceptions; never pretend an incomplete shell is a finished deck or a heuristic is verified performance. "
        "Do NOT use search_cards for draft construction. Never invent candidate names first and try searching for them later. "
        "An empty search means the search found nothing, NOT that the user must own or import cards. There is no physical collection restriction. "
        "Discovery format checks are a dated snapshot; they do not certify a whole deck or competitive strength.\n"
        "\n"
        "TOOLS AVAILABLE:\n"
        "- search_cards: Search the card database\n"
        "- get_user_decks: Retrieve user's saved deck lists\n"
        "- set_active_deck: Select which deck to work with\n"
        "- get_active_deck: See which deck is currently active\n"
        "- load_deck_contents: Load and view a deck's cards\n"
        "\n"
        "WHEN TO USE EACH TOOL:\n"
        "\n"
        "CARD SEARCHES: Use search_cards for:\n"
        "- 'Find Luke Skywalker'\n"
        "- 'Search for cards with stealth'\n"
        "- 'What cards cancel opponent events?'\n"
        "- 'Show me Yoda cards'\n"
        "- 'Cheap Mandalorian units' -> query='', trait='Mandalorian', max_cost=3\n"
        "- 'Aggression events' -> query='events', aspect='Aggression', card_type='Event'\n"
        "- '5 cost Imperial units' -> query='', trait='Imperial', card_type='Unit', min_cost=5, max_cost=5\n"
        "Pass discrete constraints (aspect, type, trait, arena, unique, cost/power/hp bounds) as filter params, not query prose; keep the query itself to the concept or name.\n"
        "\n"
        "DECK MANAGEMENT: Use deck tools for:\n"
        "- 'Show my decks' or 'List my decks' -> use get_user_decks\n"
        "- 'Load my deck' or 'Show my deck contents' -> use load_deck_contents\n"
        "- 'Select deck X' or 'Use deck X' -> use set_active_deck\n"
        "- 'What deck am I using?' -> use get_active_deck\n"
        "\n"
        "AFTER CALLING search_cards:\n"
        "The results are already displayed in an interactive widget. "
        "Do NOT list, repeat, or describe any cards in your text response. "
        "Do NOT invent card names or abilities that were not returned by the tool. "
        "Simply confirm, e.g., 'I found X cards matching your query — see the results above.'\n"
        "\n"
        "AFTER CALLING search_deck_cards, find_build_cards OR get_build_candidates:\n"
        "The raw matches are already visible to the user on the tool card. "
        "Do NOT paste the result list back into chat: no 'Card matches' sections and no bare ability-text dumps. "
        "Discuss only the specific cards you recommend, by name with a one-line gameplay reason each.\n"
        "\n"
        "IMPORTANT: When user asks about their decks, ALWAYS authenticate first.\n"
        "If you get an authentication error, provide them with the login URL\n"
        "and let them know they need to log in to SWU Stats.\n"
        "\n"
        "Always use the relevant tool for the user's request - don't guess!"
        "\nKeep responses concise and focused on gameplay. Do not show internal card or deck IDs "
        "unless the user asks for them. The deck inspector already shows the loaded cards. "
        "You collaboratively build local working drafts. Ask for a goal when it is unclear. "
        "Always read get_working_draft before advice or edits. Use search_deck_cards for verified card IDs, costs and rules. "
        "Use propose_deck_changes for specific additions/removals with reasons. The user reviews and applies the proposal inline in chat with its Apply and Dismiss buttons; never paste card image URLs or markdown card links in replies because the proposal widget already lists every change. "
        "never claim a proposal was applied. Applied drafts can be undone and exported but are NOT saved to SWUStats. "
        "Never overwrite a working draft by reloading the saved deck. Do not invent legality, costs, card identities, or rules."
    ),
    tools=[
        discover_leaders, get_build_candidates, find_build_cards, set_build_plan, analyze_deck_changes, research_build_statistics,
        get_working_draft, search_deck_cards, propose_deck_changes,
        search_cards,
        get_user_decks_tool,
        set_active_deck_tool,
        get_active_deck_tool,
        load_deck_contents_tool,
    ],
)

logger.info(f"✅ Agent created with {len(assistant_agent.tools)} tools")
logger.info(f"✅ Model: {MODEL}")
logger.info(f"✅ Tool names: {[str(t) for t in assistant_agent.tools]}")



class StarterChatServer(ChatKitServer[dict[str, Any]]):
    """Server implementation that keeps conversation state in memory."""

    def __init__(self) -> None:
        self.store: MemoryStore = MemoryStore(Path(__file__).parent.parent / ".workspace" / "conversations.json")
        self.deck_manager: DeckStateManager = DeckStateManager()
        super().__init__(self.store)

    async def respond(
        self,
        thread: ThreadMetadata,
        item: UserMessageItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        logger.info(f"📨 User message: {item.content if item else 'None'}")
        
        # Ensure deck_manager is in context
        if "deck_manager" not in context:
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
            agent_for(thread.id),
            agent_input,
            context=agent_context,
            max_turns=agent_max_turns(),
        )
        
        logger.info(f"💭 Runner returned: {type(result)}")
        
        event_count = 0
        async for event in stream_agent_response(agent_context, result):
            event_count += 1
            event_type = type(event).__name__
            if event_type == "ThreadItemUpdatedEvent" and event_count % 1000 != 0:
                logger.debug(f"Event {event_count}: {event_type}")
            else:
                logger.info(f"📤 Event {event_count}: {event_type}")
            if hasattr(event, 'content'):
                content_preview = str(event.content)[:100]
                logger.debug(f"   Content: {content_preview}")
            yield event

        # A rejected proposal tool call must not end as a prose-only success claim.
        # Retry with the actual tool history, never apply or fabricate changes here.
        for _ in range(2):
            if not context.get('unfinished_proposal'):break
            followup=result.to_input_list()+[{"role":"developer","content":"Your proposal tool did not succeed. No reviewable proposal was created. Resolve its reported prerequisites (build plan, statistics, exact-change analysis), then call propose_deck_changes successfully. Do not merely describe a proposal. If blocked, explain the actual blocker without claiming success. Statistics counts are observations, not distinct decks or verified games; do not call a rate average without a comparison baseline."}]
            result=Runner.run_streamed(agent_for(thread.id),followup,context=agent_context)
            async for event in stream_agent_response(agent_context,result):yield event
        
        logger.info(f"✅ Finished streaming {event_count} events")

    async def action(
        self,
        thread: ThreadMetadata,
        action: Action[str, Any],
        sender: Any | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        """
        Handle widget actions (e.g., deck selection).
        
        Args:
            thread: Thread metadata
            action: Action object with type and payload
            sender: Widget item that sent the action
            context: Request context
        
        Yields:
            ThreadStreamEvent responses
        """
        logger.info(f"🎯 ACTION HANDLER called")
        logger.info(f"   Action type: {action.type}")
        logger.info(f"   Action payload: {action.payload}")
        logger.info(f"   Sender: {sender}")
        
        # Handle deck selection actions
        if action.type == "view_library":
            from chatkit.types import ClientEffectEvent
            yield ClientEffectEvent(name="view_library",data={})
            return
        if action.type == "select_model":
            from chatkit.types import ClientEffectEvent
            from .models import set_model, model_for, available_models
            try:
                active = set_model(thread.id, (action.payload or {}).get("model_id"))
            except ValueError as exc:
                yield ClientEffectEvent(name="model_changed", data={"error": str(exc), "active": model_for(thread.id), "models": available_models()})
                return
            yield ClientEffectEvent(name="model_changed", data={"active": active, "models": available_models()})
            return
        if action.type == "get_models":
            from chatkit.types import ClientEffectEvent
            from .models import model_for, available_models
            yield ClientEffectEvent(name="models_list", data={"active": model_for(thread.id), "models": available_models()})
            return
        if action.type in ("apply_proposal", "dismiss_proposal"):
            from chatkit.types import ClientEffectEvent
            from . import drafts
            from .models import model_for, available_models
            try:
                await drafts.act(
                    self.deck_manager,
                    thread.id,
                    "apply" if action.type == "apply_proposal" else "dismiss",
                    (action.payload or {}).get("proposal_id"),
                )
            except ValueError as exc:
                if "no longer current" not in str(exc):
                    yield ClientEffectEvent(name="model_changed", data={
                        "error": str(exc),
                        "active": model_for(thread.id),
                        "models": available_models(),
                    })
                else:
                    logger.warning(f"Proposal action not applied: {exc}")
            yield ClientEffectEvent(name="draft_refresh", data={})
            return
        if action.type == "select_deck":
            try:
                deck_id = action.payload.get("deck_id")
                deck_name = action.payload.get("deck_name")
                
                if not deck_id or not deck_name:
                    logger.error(f"❌ Invalid payload for select_deck: {action.payload}")
                    return
                
                logger.info(f"✅ Deck selected: {deck_name} (ID: {deck_id})")
                
                # Set the active deck using the server's deck_manager
                thread_id = thread.id
                result = self.deck_manager.set_active_deck(thread_id, deck_id, deck_name)
                logger.info(f"✅ Deck manager result: {result}")
                
                # Emit client effect to refresh UI
                from chatkit.types import ClientEffectEvent
                yield ClientEffectEvent(
                    name="deck_refresh",
                    data={"deck_id": deck_id, "deck_name": deck_name},
                )
                
            except Exception as e:
                logger.error(f"❌ Error handling select_deck action: {e}", exc_info=True)
        else:
            logger.warning(f"⚠️ Unknown action type: {action.type}")
