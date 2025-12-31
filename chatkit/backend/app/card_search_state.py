"""
Manages per-thread card search state to allow AI to reference search results.
"""

from __future__ import annotations

from typing import Dict, Any, List
from pydantic import BaseModel, Field


class CardSearchResult(BaseModel):
    """A single card from search results."""
    
    index: int = Field(description="1-based index of this card in the search results")
    ability: str = Field(description="Card ability text")
    raw: str = Field(description="Raw card text from API")
    

class CardSearchState(BaseModel):
    """State for card search results in a session."""
    
    query: str | None = Field(default=None, description="Most recent search query")
    results: List[CardSearchResult] = Field(default_factory=list, description="Most recent search results")
    
    def set_results(self, query: str, cards: List[Dict[str, Any]]) -> None:
        """Store search results with 1-based indexing."""
        self.query = query
        self.results = [
            CardSearchResult(
                index=i + 1,  # 1-based indexing for user-friendly references
                ability=card.get("name", ""),
                raw=card.get("raw", "")
            )
            for i, card in enumerate(cards)
        ]
    
    def get_card_by_index(self, index: int) -> CardSearchResult | None:
        """Get a card by its 1-based index."""
        if 1 <= index <= len(self.results):
            return self.results[index - 1]
        return None
    
    def has_results(self) -> bool:
        """Check if there are any stored results."""
        return len(self.results) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for serialization."""
        return {
            "query": self.query,
            "results": [r.model_dump() for r in self.results],
            "count": len(self.results)
        }


class CardSearchStateManager:
    """Manages per-thread card search state."""
    
    def __init__(self) -> None:
        self._states: Dict[str, CardSearchState] = {}
        import logging
        self._logger = logging.getLogger(__name__)
    
    def get_state(self, thread_id: str) -> CardSearchState:
        """Get or create state for a thread."""
        if thread_id not in self._states:
            self._logger.info(f"🆕 Creating new card search state for thread: {thread_id}")
            self._states[thread_id] = CardSearchState()
        return self._states[thread_id]
    
    def store_results(self, thread_id: str, query: str, cards: List[Dict[str, Any]]) -> None:
        """Store search results for a thread."""
        self._logger.info(f"💾 Storing {len(cards)} card search results for thread {thread_id}")
        state = self.get_state(thread_id)
        state.set_results(query, cards)
    
    def get_results(self, thread_id: str) -> List[CardSearchResult]:
        """Get stored search results for a thread."""
        state = self.get_state(thread_id)
        return state.results
    
    def get_card(self, thread_id: str, index: int) -> CardSearchResult | None:
        """Get a specific card by index from stored results."""
        state = self.get_state(thread_id)
        return state.get_card_by_index(index)
    
    def has_results(self, thread_id: str) -> bool:
        """Check if thread has stored search results."""
        state = self.get_state(thread_id)
        return state.has_results()
    
    def to_dict(self, thread_id: str) -> Dict[str, Any]:
        """Get state as dictionary for debugging/API."""
        state = self.get_state(thread_id)
        return state.to_dict()
