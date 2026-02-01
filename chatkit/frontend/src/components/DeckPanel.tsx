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

// Helper to get card image URL
const getCardImageUrl = (cardId: string, type: 'square' | 'full' = 'square') => {
  const baseUrl = type === 'square' 
    ? 'https://www.swustats.net/TCGEngine/SWUDeck/concat/'
    : 'https://www.swustats.net/TCGEngine/SWUDeck/WebpImages/';
  return `${baseUrl}${cardId}.webp`;
};

export function DeckPanel({ threadId, activeDeckId }: DeckPanelProps) {
  const [deckState, setDeckState] = useState<DeckState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedDeckId, setCopiedDeckId] = useState(false);

  const fetchDeckContents = useCallback(async (deckId: number) => {
    console.log("🔍 fetchDeckContents called with deckId:", deckId);
    const apiUrl = `${CHATKIT_API_URL.replace('/chatkit', '')}/api/deck/${deckId}`;
    console.log("🔍 Fetching from:", apiUrl);

    try {
      setLoading(true);
      const response = await fetch(apiUrl);
      console.log("🔍 Response status:", response.status);
      console.log("🔍 Response headers:", {
        contentType: response.headers.get('content-type'),
      });
      
      // Log the raw response text to help debug
      const responseText = await response.text();
      console.log("🔍 Response text (first 500 chars):", responseText.substring(0, 500));
      
      if (!response.ok) {
        throw new Error(`Failed to fetch deck: ${response.status}`);
      }
      
      // Parse the JSON
      try {
        const contents = JSON.parse(responseText) as DeckContents;
        console.log("📦 DeckPanel received deck contents:", contents);
        
        // Set the deck state with the fetched contents
        setDeckState({
          active_deck_id: deckId,
          active_deck_name: contents.metadata?.name || `Deck ${deckId}`,
          deck_contents: contents,
        });
        setError(null);
      } catch (parseErr) {
        console.error("Error parsing JSON response:", parseErr);
        throw new Error(`Invalid JSON response: ${parseErr instanceof Error ? parseErr.message : 'Unknown error'}`);
      }
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

  const copyDeckId = () => {
    if (deckState?.active_deck_id) {
      navigator.clipboard.writeText(deckState.active_deck_id.toString());
      setCopiedDeckId(true);
      setTimeout(() => setCopiedDeckId(false), 2000);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-shrink-0 p-4 border-b border-slate-700">
        <h3 className="text-lg font-semibold text-white">Active Deck</h3>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4">
        <div className="bg-gradient-to-br from-slate-800 to-slate-900 rounded-lg p-4 mb-4 shadow-lg">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold text-white text-lg">{deckState.active_deck_name}</h4>
            <button
              onClick={copyDeckId}
              className="group relative p-2 hover:bg-slate-700 rounded transition-colors"
              title="Deck ID"
            >
              <svg className="w-4 h-4 text-gray-400 group-hover:text-white transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div className="absolute right-0 top-full mt-2 px-2 py-1 bg-slate-700 text-xs text-white rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
                {copiedDeckId ? 'Copied!' : `ID: ${deckState.active_deck_id}`}
              </div>
            </button>
          </div>
        </div>

        {contents && !contents.error && (
          <div className="space-y-6">
            {/* Leader & Base */}
            {(contents.leader || contents.base) && (
              <div>
                <h4 className="text-sm font-semibold text-gray-300 mb-3 uppercase tracking-wide">Identity</h4>
                <div className="grid grid-cols-2 gap-3">
                  {contents.leader && (
                    <div className="relative group cursor-pointer">
                      <img 
                        src={getCardImageUrl(contents.leader.id, 'square')} 
                        alt={contents.leader.name || contents.leader.id}
                        className="w-full rounded-lg shadow-lg transition-all duration-300 group-hover:shadow-2xl group-hover:shadow-blue-500/50 group-hover:scale-105"
                        loading="lazy"
                      />
                      <div className="absolute inset-0 rounded-lg bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-2">
                        <span className="text-xs text-white font-medium">Leader</span>
                      </div>
                    </div>
                  )}
                  {contents.base && (
                    <div className="relative group cursor-pointer">
                      <img 
                        src={getCardImageUrl(contents.base.id, 'square')} 
                        alt={contents.base.name || contents.base.id}
                        className="w-full rounded-lg shadow-lg transition-all duration-300 group-hover:shadow-2xl group-hover:shadow-blue-500/50 group-hover:scale-105"
                        loading="lazy"
                      />
                      <div className="absolute inset-0 rounded-lg bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-2">
                        <span className="text-xs text-white font-medium">Base</span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Main Deck */}
            {contents.deck.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-gray-300 mb-3 uppercase tracking-wide">
                  Main Deck <span className="text-gray-500">({mainDeckCount})</span>
                </h4>
                <div className="grid grid-cols-3 gap-2">
                  {contents.deck.map((card, idx) => (
                    <div
                      key={`${card.id}-${idx}`}
                      className="relative group cursor-pointer"
                    >
                      <img 
                        src={getCardImageUrl(card.id, 'square')} 
                        alt={card.name || card.id}
                        className="w-full rounded-lg shadow-md transition-all duration-300 group-hover:shadow-2xl group-hover:shadow-amber-500/50 group-hover:scale-105"
                        loading="lazy"
                      />
                      {card.count > 1 && (
                        <div className="absolute top-1 right-1 bg-gradient-to-br from-amber-500 to-orange-600 text-white text-xs font-bold rounded-full w-6 h-6 flex items-center justify-center shadow-lg border-2 border-white">
                          {card.count}
                        </div>
                      )}
                      <div className="absolute inset-0 rounded-lg ring-2 ring-transparent group-hover:ring-amber-500/50 transition-all pointer-events-none"></div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Sideboard */}
            {contents.sideboard.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-gray-300 mb-3 uppercase tracking-wide">
                  Sideboard <span className="text-gray-500">({sideboardCount})</span>
                </h4>
                <div className="grid grid-cols-3 gap-2">
                  {contents.sideboard.map((card, idx) => (
                    <div
                      key={`${card.id}-${idx}`}
                      className="relative group cursor-pointer"
                    >
                      <img 
                        src={getCardImageUrl(card.id, 'square')} 
                        alt={card.name || card.id}
                        className="w-full rounded-lg shadow-md transition-all duration-300 group-hover:shadow-2xl group-hover:shadow-purple-500/50 group-hover:scale-105"
                        loading="lazy"
                      />
                      {card.count > 1 && (
                        <div className="absolute top-1 right-1 bg-gradient-to-br from-purple-500 to-pink-600 text-white text-xs font-bold rounded-full w-6 h-6 flex items-center justify-center shadow-lg border-2 border-white">
                          {card.count}
                        </div>
                      )}
                      <div className="absolute inset-0 rounded-lg ring-2 ring-transparent group-hover:ring-purple-500/50 transition-all pointer-events-none"></div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {contents?.error && (
          <div className="text-sm text-red-400 mt-4">
            {contents.error}
          </div>
        )}
      </div>
    </div>
  );
}
