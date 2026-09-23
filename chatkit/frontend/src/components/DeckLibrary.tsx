import { useEffect, useMemo, useState } from "react";
import { CHATKIT_API_URL } from "../lib/config";
import { swuCardImage } from "../lib/deck";
import { Icon } from "./Icon";
interface Deck {
    id: number;
    name: string | null;
    is_favorite?: boolean;
    keyIndicator1?: string;
}
function LeaderThumbnail({deck}:{deck:Deck}) {
    const [failed,setFailed]=useState(false);
    return <span className="deck-monogram" aria-hidden="true">{deck.keyIndicator1 && !failed ? <img alt="" loading="lazy" src={swuCardImage(deck.keyIndicator1,true)} onError={()=>setFailed(true)}/> : (deck.name||"D").slice(0,1).toUpperCase()}</span>;
}
export function DeckLibrary({ connected, activeDeckId, onSelect }: {
    connected: boolean;
    activeDeckId: number | null;
    onSelect: (deck: {
        id: number;
        name: string;
    }) => void;
}) {
    const [decks, setDecks] = useState<Deck[]>([]), [query, setQuery] = useState(""), [favorites, setFavorites] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState(""), [attempt, setAttempt] = useState(0);
    const [sort,setSort] = useState("favorites"), [recentOnly,setRecentOnly] = useState(false);
    const recent = useMemo(() => JSON.parse(localStorage.getItem("recent-decks") || "[]") as number[], []);
    const apiBase = CHATKIT_API_URL.replace(/\/chatkit\/?$/, "");
    useEffect(() => {
        if (!connected) {
            setDecks([]);
            return;
        }
        const controller = new AbortController();
        setLoading(true);
        setError("");
        void fetch(`${apiBase}/api/decks`, { signal: controller.signal }).then(async (response) => {
            const data = await response.json() as {
                decks: Deck[];
                error?: string;
            };
            if (!response.ok || data.error)
                throw new Error(data.error === "not_authenticated" || data.error === "token_expired" ? "Please reconnect your SWUStats account to see your decks." : "Your decks couldn’t be loaded. Please try again.");
            setDecks(data.decks);
        }).catch((err: unknown) => { if (!controller.signal.aborted)
            setError(err instanceof Error ? err.message : "Your decks could not be loaded."); }).finally(() => { if (!controller.signal.aborted)
            setLoading(false); });
        return () => controller.abort();
    }, [connected, apiBase, attempt]);
    const filtered = useMemo(() => decks.filter(d => (!favorites || d.is_favorite) && (!recentOnly || recent.includes(d.id)) && (d.name || `Deck ${d.id}`).toLowerCase().includes(query.toLowerCase())).sort((a, b) => (sort === "favorites" ? Number(!!b.is_favorite) - Number(!!a.is_favorite) : sort === "recent" ? (recent.includes(a.id) ? recent.indexOf(a.id) : 999) - (recent.includes(b.id) ? recent.indexOf(b.id) : 999) : 0) || (a.name || `Deck ${a.id}`).localeCompare(b.name || `Deck ${b.id}`)), [decks, query, favorites, sort, recentOnly, recent]);
    return <section className="library" aria-label="Deck library">
  <div className="section-intro"><h2>Your saved decks</h2><p>Choose a deck to start or resume a working draft.</p></div>
  <div className="library-toolbar"><label className="search-field"><Icon name="search" size={18}/><input aria-label="Search saved decks" placeholder="Search your decks…" value={query} onChange={e => setQuery(e.target.value)}/></label><button className={`filter-button ${favorites ? "selected" : ""}`} aria-pressed={favorites} onClick={() => setFavorites(!favorites)}><Icon name="star" size={16}/> Favorites</button><button className={`filter-button ${recentOnly ? "selected" : ""}`} aria-pressed={recentOnly} onClick={() => setRecentOnly(!recentOnly)}>Recent</button><select aria-label="Sort decks" value={sort} onChange={e => setSort(e.target.value)}><option value="favorites">Favorites first</option><option value="name">Name A–Z</option><option value="recent">Recently opened</option></select><button className="icon-button" aria-label="Refresh decks" onClick={() => setAttempt(attempt + 1)} disabled={loading || !connected}><Icon name="refresh" size={18}/></button></div>
  {!connected ? <div className="empty-state"><span className="empty-icon"><Icon name="link" size={28}/></span><h3>Your collection belongs here.</h3><p>Connect SWUStats to browse and load your saved decks.</p><a className="primary-button" href={`${apiBase}/oauth/login`} target="_blank" rel="noreferrer">Connect SWUStats <Icon name="arrow" size={16}/></a></div>
            : error ? <div className="empty-state" role="alert"><h3>Let’s try that again.</h3><p>{error}</p><button className="secondary-button" onClick={() => setAttempt(attempt + 1)}>Retry</button></div>
                : loading ? <div className="deck-grid compact-library" aria-label="Loading decks" aria-busy="true">{Array.from({ length: 6 }, (_, i) => <div key={i} className="deck-skeleton"/>)}</div>
                    : <><div className="results-summary"><span>{filtered.length} {filtered.length === 1 ? "deck" : "decks"}{query || favorites ? ` of ${decks.length}` : " in your collection"}</span><span>Recent = opened on this device</span></div>
    {!filtered.length ? <div className="empty-state"><Icon name="search" size={28}/><h3>{decks.length ? "No matching decks" : "A fresh start."}</h3><p>{decks.length ? "Try another name or clear your filters." : "Your saved SWUStats decks will appear here."}</p>{decks.length > 0 && <button className="secondary-button" onClick={() => { setQuery(""); setFavorites(false); setRecentOnly(false); }}>Clear filters</button>}</div>
                            : <div className="deck-grid compact-library">{filtered.map(deck => <button key={deck.id} className={`deck-tile ${activeDeckId === deck.id ? "active" : ""}`} aria-current={activeDeckId === deck.id ? "true" : undefined} onClick={() => onSelect({ id: deck.id, name: deck.name || `Deck ${deck.id}` })}><div className="tile-top"><LeaderThumbnail deck={deck}/>{deck.is_favorite && <span className="favorite-mark" aria-label="Favorite"><Icon name="star" size={16}/></span>}</div><h3>{deck.name || `Deck ${deck.id}`}</h3><div className="tile-bottom"><span>{activeDeckId === deck.id ? "Active" : "Open deck"}</span><Icon name={activeDeckId === deck.id ? "check" : "arrow"} size={18}/></div></button>)}</div>}</>}
 </section>;
}
