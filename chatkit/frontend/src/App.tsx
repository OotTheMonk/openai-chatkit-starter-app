import { useState, useEffect, useRef, useCallback } from "react";
import { ChatKitPanel } from "./components/ChatKitPanel";
import { DeckPanel } from "./components/DeckPanel";

interface EffectEvent {
  name: string;
  data?: Record<string, unknown>;
}

export default function App() {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [activeDeckId, setActiveDeckId] = useState<number | null>(null);
  const lastThreadId = useRef<string | null>(null);

  // Handle ChatKit effects (e.g., deck refresh)
  const handleEffect = useCallback((event: EffectEvent) => {
    console.log("🎯 App received effect:", event);
    if (event.name === "deck_refresh") {
      const deckId = event.data?.deck_id as number;
      console.log("🔄 Setting active deck ID:", deckId);
      setActiveDeckId(deckId);
    }
  }, []);

  // When thread changes, clear the active deck
  useEffect(() => {
    if (threadId !== lastThreadId.current) {
      lastThreadId.current = threadId;
      setActiveDeckId(null);
    }
  }, [threadId]);

  return (
    <main className="flex min-h-screen bg-slate-100 dark:bg-slate-950">
      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col items-center justify-end p-4">
        <div className="w-full max-w-4xl">
          <ChatKitPanel onThreadChange={setThreadId} onEffect={handleEffect} />
        </div>
      </div>

      {/* Deck Sidebar */}
      <aside className="w-80 bg-slate-900 border-l border-slate-800 flex-shrink-0 overflow-hidden">
        <div className="h-screen">
          <DeckPanel threadId={threadId} activeDeckId={activeDeckId} />
        </div>
      </aside>
    </main>
  );
}
