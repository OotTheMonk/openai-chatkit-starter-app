import { ChatKit, useChatKit } from "@openai/chatkit-react";
import { useEffect, useRef } from "react";
import { CHATKIT_API_DOMAIN_KEY, CHATKIT_API_URL } from "../lib/config";

interface EffectEvent {
  name: string;
  data?: Record<string, unknown>;
}

interface ChatKitPanelProps {
  onThreadChange?: (threadId: string | null) => void;
  onEffect?: (event: EffectEvent) => void;
}

export function ChatKitPanel({ onThreadChange, onEffect }: ChatKitPanelProps) {
  const chatkit = useChatKit({
    api: { url: CHATKIT_API_URL, domainKey: CHATKIT_API_DOMAIN_KEY },
    composer: {
      // File uploads are disabled for the demo backend.
      attachments: { enabled: false },
    },
    onEffect: (event: EffectEvent) => {
      console.log("📤 ChatKit effect received:", event);
      onEffect?.(event);
    },
  });

  // Extract thread ID from the internal state when it changes
  // The control object exposes thread info through its internal structure
  const threadId = (chatkit.control as unknown as { thread?: { id: string } })?.thread?.id ?? null;
  const lastThreadId = useRef<string | null>(null);
  
  // Notify parent of thread changes using useEffect
  useEffect(() => {
    if (threadId !== lastThreadId.current) {
      console.log("🔗 Thread ID changed:", lastThreadId.current, "->", threadId);
      lastThreadId.current = threadId;
      onThreadChange?.(threadId);
    }
  }, [threadId, onThreadChange]);

  return (
    <div className="relative pb-8 flex h-[90vh] w-full rounded-2xl flex-col overflow-hidden bg-white shadow-sm transition-colors dark:bg-slate-900">
      <ChatKit control={chatkit.control} className="block h-full w-full" />
    </div>
  );
}
