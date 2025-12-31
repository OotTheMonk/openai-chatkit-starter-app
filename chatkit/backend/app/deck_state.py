"""
Manages per-thread deck state following ChatKit best practices.
Inspired by the customer-support example's AirlineStateManager pattern.
"""

from __future__ import annotations

from typing import Dict, Any
from pydantic import BaseModel, Field


class DeckState(BaseModel):
    """State for a user's deck management session."""
    
    active_deck_id: int | None = Field(default=None, description="Currently active deck ID")
    active_deck_name: str | None = Field(default=None, description="Name of active deck")
    deck_contents: Dict[str, Any] | None = Field(default=None, description="Full contents of the active deck")
    
    def set_active_deck(self, deck_id: int, deck_name: str) -> None:
        """Set the active deck for this session."""
        self.active_deck_id = deck_id
        self.active_deck_name = deck_name
        # Clear contents when switching decks - will be loaded on demand
        self.deck_contents = None
    
    def clear_active_deck(self) -> None:
        """Clear the active deck."""
        self.active_deck_id = None
        self.active_deck_name = None
        self.deck_contents = None
    
    def has_active_deck(self) -> bool:
        """Check if there's an active deck."""
        return self.active_deck_id is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for serialization."""
        return {
            "active_deck_id": self.active_deck_id,
            "active_deck_name": self.active_deck_name,
            "deck_contents": self.deck_contents,
        }


class DeckStateManager:
    """Manages per-thread deck state."""
    
    def __init__(self) -> None:
        self._states: Dict[str, DeckState] = {}
        import logging
        self._logger = logging.getLogger(__name__)
    
    def get_state(self, thread_id: str) -> DeckState:
        """Get or create state for a thread."""
        if thread_id not in self._states:
            self._logger.info(f"🆕 Creating new state for thread: {thread_id}")
            self._states[thread_id] = DeckState()
        return self._states[thread_id]
    
    def set_active_deck(self, thread_id: str, deck_id: int, deck_name: str) -> str:
        """Set the active deck for a thread."""
        self._logger.info(f"💾 Setting active deck for thread {thread_id}: {deck_name} (ID: {deck_id})")
        state = self.get_state(thread_id)
        state.set_active_deck(deck_id, deck_name)
        self._logger.info(f"💾 State after set: {state.to_dict()}")
        self._logger.info(f"💾 All threads with state: {list(self._states.keys())}")
        return f"✅ Active deck set to: **{deck_name}** (ID: {deck_id})"
    
    def get_active_deck(self, thread_id: str) -> tuple[int | None, str | None]:
        """Get the active deck ID and name for a thread."""
        state = self.get_state(thread_id)
        return state.active_deck_id, state.active_deck_name
    
    def clear_active_deck(self, thread_id: str) -> str:
        """Clear the active deck for a thread."""
        state = self.get_state(thread_id)
        old_name = state.active_deck_name
        state.clear_active_deck()
        if old_name:
            return f"✅ Cleared active deck: **{old_name}**"
        return "No active deck was set."
    
    def has_active_deck(self, thread_id: str) -> bool:
        """Check if thread has an active deck."""
        state = self.get_state(thread_id)
        return state.has_active_deck()
    
    def to_dict(self, thread_id: str) -> Dict[str, Any]:
        """Get state as dictionary for debugging/API."""
        state = self.get_state(thread_id)
        return state.to_dict()
