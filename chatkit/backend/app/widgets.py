"""
Widget components for ChatKit UI rendering.

This module provides reusable widget components that can be rendered
in the chat interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator
import httpx
import re


@dataclass
class CardSearchWidget:
    """
    Widget for searching Star Wars Unlimited cards.
    
    This widget provides a reusable card search interface that can be
    integrated into ChatKit responses.
    """
    
    search_input: str = ""
    results: list[str] = field(default_factory=list)
    error: str | None = None
    loading: bool = False
    
    async def fetch_results(self, search_input: str) -> None:
        """
        Fetch card search results from the SWU card search API.
        
        Args:
            search_input: The search query
        """
        self.loading = True
        self.search_input = search_input
        self.results = []
        self.error = None
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://142.11.210.6/es/swucardsearch.php",
                    data={"searchInput": search_input},
                    timeout=10.0
                )
                self.results = self._extract_results(resp.text)
                if not self.results:
                    self.error = "No results found."
        except Exception as e:
            self.error = f"Error searching cards: {e}"
        finally:
            self.loading = False
    
    def _extract_results(self, html: str) -> list[str]:
        """
        Extract card results from HTML response.
        
        Args:
            html: The HTML response from the search API
            
        Returns:
            List of card result strings
        """
        # Extract the <ul>...</ul> block
        ul_match = re.search(r"<ul>(.*?)</ul>", html, re.DOTALL)
        if not ul_match:
            return []
        
        ul_content = ul_match.group(1)
        # Extract all <li>...</li> items
        items = re.findall(r"<li>(.*?)</li>", ul_content, re.DOTALL)
        
        # Clean up and return as list
        results = []
        for item in items:
            cleaned = re.sub(r"<.*?>", "", item).strip()
            if cleaned:
                results.append(cleaned)
        
        return results
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert widget state to dictionary for serialization.
        
        Returns:
            Dictionary representation of widget state
        """
        return {
            "search_input": self.search_input,
            "results": self.results,
            "error": self.error,
            "loading": self.loading,
        }
    
    @classmethod
    async def from_search(cls, search_input: str) -> CardSearchWidget:
        """
        Create a widget instance and fetch results.
        
        Args:
            search_input: The search query
            
        Returns:
            Widget instance with results loaded
        """
        widget = cls(search_input=search_input)
        await widget.fetch_results(search_input)
        return widget
