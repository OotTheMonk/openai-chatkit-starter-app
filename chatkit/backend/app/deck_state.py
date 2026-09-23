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

    saved_contents: Dict[str, Any] | None = None
    proposal: Dict[str, Any] | None = None
    research: Dict[str, Any] | None = None
    reviewed_changes: str | None = None
    source: str = "swustats"
    build_preferences: Dict[str, Any] = Field(default_factory=dict)
    revision: int = 0
    undo_stack: list[Dict[str, Any]] = Field(default_factory=list)

    def _reset(self) -> None:
        """Clear contents when switching decks - will be loaded on demand."""
        self.deck_contents = None
        self.saved_contents = None
        self.proposal = None
        self.undo_stack = []
        self.revision = 0
        self.research = None
        self.reviewed_changes = None
        self.source = "swustats"
        self.build_preferences = {}

    def set_active_deck(self, deck_id: int, deck_name: str) -> None:
        """Set the active deck for this session."""
        self.active_deck_id = deck_id
        self.active_deck_name = deck_name
        self._reset()

    def clear_active_deck(self) -> None:
        """Clear the active deck."""
        self.active_deck_id = None
        self.active_deck_name = None
        self._reset()

    def has_active_deck(self) -> bool:
        """Check if there's an active deck."""
        return self.active_deck_id is not None

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for serialization."""
        data = self.model_dump()
        data["dirty"] = self.source == "local" or (self.saved_contents is not None and self.deck_contents != self.saved_contents)
        data["can_undo"] = bool(self.undo_stack)
        data.pop("undo_stack",None)
        data.pop("saved_contents",None)
        if data["proposal"]:data["proposal"].pop("contents",None)
        return data



class DeckStateManager:
    """Manages per-thread deck state."""

    def __init__(self, storage_path=None) -> None:
        self._states: Dict[str, DeckState] = {}
        import json
        from pathlib import Path
        self.path = Path(storage_path) if storage_path else Path(__file__).parent.parent / ".workspace" / "drafts.json"
        self._archive = {}
        self.discovery = {}
        if self.path.exists():
            data=json.loads(self.path.read_text(encoding="utf-8"))
            self._states={k:DeckState.model_validate(v) for k,v in data.get("states",{}).items()}
            self._archive=data.get("archive",{})
            self.discovery=data.get("discovery",{})
        import logging
        self._logger = logging.getLogger(__name__)

    def save(self):
        import json
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"states":{k:v.model_dump() for k,v in self._states.items()},"archive":self._archive,"discovery":self.discovery}),encoding="utf-8")
        temp.replace(self.path)

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
        if state.active_deck_id != deck_id:
            if state.active_deck_id is not None:
                self._archive[f"{thread_id}:{state.active_deck_id}"]=state.model_dump()
            previous=self._archive.get(f"{thread_id}:{deck_id}")
            if previous:
                state=DeckState.model_validate(previous)
                self._states[thread_id]=state
            else:state.set_active_deck(deck_id,deck_name)
        self.save()
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
