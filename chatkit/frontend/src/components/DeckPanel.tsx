import { useState, useEffect, useCallback } from "react";
import { CHATKIT_API_URL } from "../lib/config";

interface DeckCard {
  id: string;
  count: number;
  name?: string;
}

interface DeckContents {
  deck_id: number;
  metadata: {
    name?: string;
    description?: string;
    format?: string;
  };
  leader?: { id: string; name?: string };
  base?: { id: string; name?: string };
  deck: DeckCard[];
  sideboard: DeckCard[];
  error?: string | null;
}

interface DeckState {
  active_deck_id: number | null;
  active_deck_name: string | null;
  deck_contents: DeckContents | null;
}

interface DeckPanelProps {
  threadId: string | null;
  activeDeckId: number | null;
}

export function DeckPanel({ threadId, activeDeckId }: DeckPanelProps) {
  const [deckState, setDeckState] = useState<DeckState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDeckContents = useCallback(async (deckId: number) => {
    console.log("🔍 fetchDeckContents called with deckId:", deckId);
    const apiUrl = `${CHATKIT_API_URL.replace('/chatkit', '')}/api/deck/${deckId}`;
    console.log("🔍 Fetching from:", apiUrl);

    try {
      setLoading(true);
      const response = await fetch(apiUrl);
      console.log("🔍 Response status:", response.status);
      if (!response.ok) {
        throw new Error(`Failed to fetch deck: ${response.status}`);
      }
      const contents = (await response.json()) as DeckContents;
      console.log("📦 DeckPanel received deck contents:", contents);
      
      // Set the deck state with the fetched contents
      setDeckState({
        active_deck_id: deckId,
        active_deck_name: contents.metadata?.name || `Deck ${deckId}`,
        deck_contents: contents,
      });
      setError(null);
    } catch (err) {
      console.error("Error fetching deck contents:", err);
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch when activeDeckId changes
  useEffect(() => {
    console.log("🔄 DeckPanel useEffect triggered - activeDeckId:", activeDeckId);
    if (activeDeckId) {
      void fetchDeckContents(activeDeckId);
    } else {
      setDeckState(null);
    }
  }, [activeDeckId, fetchDeckContents]);

  if (loading && !deckState) {
    return (
      <div className="p-4 text-sm text-gray-500">
        Loading deck state...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-sm text-red-500">
        Error: {error}
      </div>
    );
  }

  if (!deckState?.active_deck_id) {
    return (
      <div className="p-4">
        <h3 className="text-lg font-semibold mb-2 text-white">Active Deck</h3>
        <p className="text-sm text-gray-500">No deck selected</p>
        <p className="text-xs text-gray-400 mt-2">
          Say "show my decks" to select a deck
        </p>
      </div>
    );
  }

  console.log("🎨 Rendering deck with state:", deckState);
  const contents = deckState.deck_contents;
  console.log("🎨 Contents:", contents);
  const mainDeckCount = contents?.deck?.reduce((sum, card) => sum + card.count, 0) ?? 0;
  const sideboardCount = contents?.sideboard?.reduce((sum, card) => sum + card.count, 0) ?? 0;

  return (
    <div className="p-4 h-full overflow-auto">
      <h3 className="text-lg font-semibold mb-3 text-white">Active Deck</h3>
      
      <div className="bg-slate-800 rounded-lg p-3 mb-3">
        <h4 className="font-medium text-white">{deckState.active_deck_name}</h4>
        <p className="text-xs text-gray-400">ID: {deckState.active_deck_id}</p>
      </div>

      {contents && !contents.error && (
        <>
          {/* Deck Summary */}
          <div className="text-sm text-gray-300 mb-4">
            <p>Main deck: {mainDeckCount} cards</p>
            <p>Sideboard: {sideboardCount} cards</p>
          </div>

          {/* Leader & Base */}
          {(contents.leader || contents.base) && (
            <div className="mb-4">
              <h4 className="text-sm font-medium text-gray-200 mb-2">Identity</h4>
              {contents.leader && (
                <div className="text-xs text-gray-400 mb-1">
                  Leader: {contents.leader.id}
                </div>
              )}
              {contents.base && (
                <div className="text-xs text-gray-400">
                  Base: {contents.base.id}
                </div>
              )}
            </div>
          )}

          {/* Main Deck */}
          {contents.deck.length > 0 && (
            <div className="mb-4">
              <h4 className="text-sm font-medium text-gray-200 mb-2">
                Main Deck ({mainDeckCount})
              </h4>
              <div className="space-y-1 max-h-60 overflow-y-auto">
                {contents.deck.map((card, idx) => (
                  <div
                    key={`${card.id}-${idx}`}
                    className="flex justify-between text-xs text-gray-400 py-1 px-2 bg-slate-800 rounded"
                  >
                    <span className="truncate">{card.name || card.id}</span>
                    <span className="ml-2 text-gray-500">×{card.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sideboard */}
          {contents.sideboard.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-200 mb-2">
                Sideboard ({sideboardCount})
              </h4>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {contents.sideboard.map((card, idx) => (
                  <div
                    key={`${card.id}-${idx}`}
                    className="flex justify-between text-xs text-gray-400 py-1 px-2 bg-slate-800 rounded"
                  >
                    <span className="truncate">{card.name || card.id}</span>
                    <span className="ml-2 text-gray-500">×{card.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {contents?.error && (
        <div className="text-sm text-red-400">
          {contents.error}
        </div>
      )}
    </div>
  );
}
