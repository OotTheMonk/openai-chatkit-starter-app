import { useEffect, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import { CHATKIT_API_URL } from "../lib/config";
import { swuCardImage, type Draft } from "../lib/deck";
import { Icon } from "./Icon";
import { useCardPreview } from "./useCardPreview";
import "./CardPreview.css";
import "./ResidualSimulation.css";

const base = CHATKIT_API_URL.replace(/\/chatkit\/?$/, "");
type SimulationMode = "residual" | "full_game";
type Opponent = { id: string; label: string; group: string; leaderId?: string | null; baseId?: string | null };
type OpponentCard = { printingId: string; id: string; name: string; cost: number | null; type: string; arenas: string[]; count: number };
type OpponentDeck = { id: string; label: string; leader: OpponentCard | null; base: OpponentCard | null; deck: OpponentCard[]; total: number };
type Sample = {
  status: string; seed: string; selectedAttack: string | null;
  winner?: number; rounds?: number; appliedSteps?: number;
  replayId?: string;
  engineError?: string;
  attackAvailability?: { reason: string; legalUnitAttack: boolean } | null;
  beforeAttack?: { units: Record<string, Record<string, unknown[]>> } | null;
  summary?: { unitCount: Record<string, Record<string, number>>; remainingUnitHealth: Record<string, Record<string, number>> };
  afterAttack?: { baseHealth: Record<string, number> };
  baseHealthTimeline?: { round: number; ours: number; opponent: number }[];
  trace?: { step: number; seat: number; round: number; action: string; rule: string; chosenCards?: string[] }[];
};
type Report = {
  mode: SimulationMode; revision: number; deckHash: string; engineRevision: string | null; policy: string; elapsedMs?: number;
  opponent: string; aggregate: {
    counts: { ahead: number; equal: number; behind: number; no_unit_attack: number; failed: number;
      ours: number; opponent: number; incomplete: number };
    meanUnitDifference?: number | null; meanRemainingUnitHealthDifference?: number | null;
    meanBaseHealth?: { ours: number | null; opponent: number | null }; scoredSamples?: number;
    completedGames?: number; ourWinRate?: number | null; meanRounds?: number | null;
    meanActions?: number | null; meanOurBaseHealthInWins?: number | null;
    meanOpponentBaseHealthInLosses?: number | null;
  }; samples: Sample[];
};

const attackReason: Record<string, string> = {
  opponent_no_unit: "Opponent has no unit",
  our_no_unit: "Your side has no unit",
  different_arenas: "Units are in different arenas",
  attacker_unready: "No opponent unit is ready in a shared arena",
  no_legal_unit_attack: "Engine offers no legal unit attack",
};

function arenaCounts(sample: Sample, seat: string): string | null {
  const units = sample.beforeAttack?.units?.[seat];
  return units ? `${units.Ground?.length ?? 0} ground, ${units.Space?.length ?? 0} space` : null;
}

function OpponentIdentity({ item }: { item: Opponent }) {
  return <span className="residual-opponent-identity" aria-hidden="true">
    {item.leaderId && <img src={swuCardImage(item.leaderId)} alt="" loading="lazy" />}
    {item.baseId && <img src={swuCardImage(item.baseId)} alt="" loading="lazy" />}
  </span>;
}

function OpponentDeckSection({ title, cards, onPreview, onQueuePreview, onMovePreview, onHidePreview, wide = false }: {
  title: string; cards: OpponentCard[]; onPreview: (card: OpponentCard, element: HTMLButtonElement, x: number, y: number) => void;
  onQueuePreview: (card: OpponentCard, element: HTMLButtonElement, x: number, y: number) => void;
  onMovePreview: (element: HTMLButtonElement, x: number, y: number) => void;
  onHidePreview: () => void; wide?: boolean;
}) {
  const costs = [...new Set(cards.map(card => card.cost))].sort((a, b) => a == null ? 1 : b == null ? -1 : a - b);
  const accent = (cost: number | null) => cost == null ? "#607168" : `hsl(${220 - Math.min(Math.max(cost, 0), 8) * 27.5} 72% 38%)`;
  return <section className={`residual-deck-section${wide ? " is-wide" : ""}`}>
    <h4>{title}<small>{cards.reduce((total, card) => total + card.count, 0)} cards</small></h4>
    {cards.length === 0 && <p className="muted">No cards in this section.</p>}
    {costs.map(cost => <div key={cost ?? "unknown"} className="residual-cost-group" style={{ "--cost-accent": accent(cost), "--card-count": cards.filter(card => card.cost === cost).length } as CSSProperties}>
      <div className="residual-cost-heading" aria-label={cost == null ? "Unknown cost" : `Cost ${cost}`}><span>{cost ?? "?"}</span><i aria-hidden="true" /></div>
      <div className="residual-cost-cards">{cards.filter(card => card.cost === cost).map(card => <button type="button" key={card.printingId} className="residual-deck-row card-preview-target"
        onPointerEnter={event => onQueuePreview(card, event.currentTarget, event.clientX, event.clientY)}
        onPointerMove={event => onMovePreview(event.currentTarget, event.clientX, event.clientY)} onPointerLeave={onHidePreview}
        onFocus={event => { if (event.currentTarget.matches(":focus-visible")) { const rect = event.currentTarget.getBoundingClientRect(); onPreview(card, event.currentTarget, rect.right, rect.top); } }}
        onBlur={onHidePreview} onClick={event => { const rect = event.currentTarget.getBoundingClientRect(); onPreview(card, event.currentTarget, event.detail ? event.clientX : rect.right, event.detail ? event.clientY : rect.top); }}
        aria-label={`Preview ${card.name}, ${card.count} copies, ${cost == null ? "unknown cost" : `cost ${cost}`}`}>
        {card.id && <img src={swuCardImage(card.id, false)} alt="" loading="lazy" />}
        {!card.id && <span className="residual-deck-image-fallback">{card.name}</span>}
        <span className="residual-deck-count" aria-hidden="true">{Array.from({ length: card.count }, (_, index) => <i key={index} />)}</span>
      </button>)}</div>
    </div>)}
  </section>;
}

function BaseHealthTimeline({ points }: { points: NonNullable<Sample["baseHealthTimeline"]> }) {
  const ordered = [...points].sort((a, b) => a.round - b.round);
  const width = 560;
  const height = 220;
  const left = 38;
  const right = 16;
  const top = 14;
  const bottom = 34;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const lastRound = Math.max(1, ...ordered.map(point => point.round));
  const maxHealth = Math.max(10, Math.ceil(Math.max(...ordered.flatMap(point => [point.ours, point.opponent])) / 10) * 10);
  const x = (round: number) => left + round / lastRound * plotWidth;
  const y = (health: number) => top + (1 - health / maxHealth) * plotHeight;
  const roundStep = Math.max(1, Math.ceil(lastRound / 8));
  const sides = ["ours", "opponent"] as const;
  return <div className="residual-health-timeline" aria-label="Base health by round">
    <div className="residual-health-legend"><span className="ours">Your base</span><span className="opponent">Opponent base</span></div>
    <svg className="residual-health-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Your base and opponent base health by round">
      <desc>{ordered.map(point => `${point.round === 0 ? "Start" : `Round ${point.round}`}: yours ${point.ours}, opponent ${point.opponent}`).join("; ")}</desc>
      {[0, maxHealth / 2, maxHealth].map(value => <g key={value}>
        <line className="grid" x1={left} x2={width - right} y1={y(value)} y2={y(value)} />
        <text x={left - 8} y={y(value) + 4} textAnchor="end">{value}</text>
      </g>)}
      {ordered.filter(point => point.round === 0 || point.round === lastRound || point.round % roundStep === 0).map(point =>
        <text key={point.round} x={x(point.round)} y={height - 11} textAnchor="middle">{point.round === 0 ? "Start" : point.round}</text>
      )}
      {sides.map(side => <polyline key={side} className={`series ${side}`}
        points={ordered.map(point => `${x(point.round)},${y(point[side])}`).join(" ")} />)}
      {sides.flatMap(side => ordered.map(point => <circle key={`${side}-${point.round}`} className={`point ${side}`}
        cx={x(point.round)} cy={y(point[side])} r={4}>
        <title>{`${side === "ours" ? "Your" : "Opponent"} base: ${point[side]} HP ${point.round === 0 ? "at start" : `after round ${point.round}`}`}</title>
      </circle>))}
    </svg>
  </div>;
}

export function ResidualSimulation({ draft, threadId }: { draft: Draft; threadId: string | null }) {
  const [opponents, setOpponents] = useState<Opponent[]>([]);
  const [opponent, setOpponent] = useState("");
  const [mode, setMode] = useState<SimulationMode>("residual");
  const [seed, setSeed] = useState("opening");
  const [samples, setSamples] = useState(8);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [actionLog, setActionLog] = useState<Sample | null>(null);
  const [openingReplay, setOpeningReplay] = useState<string | null>(null);
  const [inspectedOpponent, setInspectedOpponent] = useState<Opponent | null>(null);
  const [inspectedDeck, setInspectedDeck] = useState<OpponentDeck | null>(null);
  const [deckError, setDeckError] = useState("");
  const opponentMenu = useRef<HTMLDetailsElement>(null);
  const actionDialog = useRef<HTMLDialogElement>(null);
  const deckDialog = useRef<HTMLDialogElement>(null);
  const { tooltip: cardTooltip, card: previewCard, show: showCardPreview, queue: queueCardPreview, move: movePendingCardPreview, hide: hideCardPreview } = useCardPreview<OpponentCard>();
  const deckDrag = useRef<{ pointerId: number; offsetX: number; offsetY: number } | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    void fetch(`${base}/api/simulations/opponents`, { signal: abort.signal })
      .then(r => r.ok ? r.json() : Promise.reject(new Error("Could not load opponents.")))
      .then((data: unknown) => {
        const list = (data as { opponents?: Opponent[] }).opponents || [];
        setOpponents(list);
        setOpponent(current => current || list[0]?.id || "");
      }).catch(() => {});
    return () => abort.abort();
  }, []);
  useEffect(() => { setReport(null); setError(""); setActionLog(null); }, [draft.active_deck_id]);
  useEffect(() => {
    if (actionLog && !actionDialog.current?.open) actionDialog.current?.showModal();
    if (!actionLog && actionDialog.current?.open) actionDialog.current.close();
  }, [actionLog]);
  useEffect(() => {
    if (!inspectedOpponent) {
      if (deckDialog.current?.open) deckDialog.current.close();
      const dialog = deckDialog.current;
      if (dialog) {
        dialog.style.removeProperty("inset");
        dialog.style.removeProperty("transform");
        dialog.style.removeProperty("left");
        dialog.style.removeProperty("top");
      }
      deckDrag.current = null;
      return;
    }
    if (!deckDialog.current?.open) deckDialog.current?.showModal();
    const abort = new AbortController();
    void fetch(`${base}/api/simulations/opponents/${encodeURIComponent(inspectedOpponent.id)}`, { signal: abort.signal })
      .then(async response => {
        const data = await response.json() as OpponentDeck & { error?: string };
        if (!response.ok) throw new Error(data.error || "Could not load this deck list.");
        return data;
      })
      .then(setInspectedDeck)
      .catch(cause => { if (!abort.signal.aborted) setDeckError(cause instanceof Error ? cause.message : "Could not load this deck list."); });
    return () => abort.abort();
  }, [inspectedOpponent]);
  function inspectOpponent() {
    if (!selectedOpponent) return;
    setInspectedDeck(null); setDeckError(""); hideCardPreview(); setInspectedOpponent(selectedOpponent);
  }
  function startDeckDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
    const dialog = deckDialog.current;
    if (!dialog) return;
    const rect = dialog.getBoundingClientRect();
    deckDrag.current = { pointerId: event.pointerId, offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top };
    dialog.style.inset = "auto";
    dialog.style.transform = "none";
    dialog.style.left = `${rect.left}px`;
    dialog.style.top = `${rect.top}px`;
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }
  function moveDeckDrag(event: PointerEvent<HTMLDivElement>) {
    const drag = deckDrag.current;
    const dialog = deckDialog.current;
    if (!drag || drag.pointerId !== event.pointerId || !dialog) return;
    const rect = dialog.getBoundingClientRect();
    const left = Math.max(8, Math.min(event.clientX - drag.offsetX, window.innerWidth - rect.width - 8));
    const top = Math.max(8, Math.min(event.clientY - drag.offsetY, window.innerHeight - rect.height - 8));
    dialog.style.left = `${left}px`;
    dialog.style.top = `${top}px`;
  }
  function stopDeckDrag(event: PointerEvent<HTMLDivElement>) {
    if (deckDrag.current?.pointerId !== event.pointerId) return;
    deckDrag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }
  async function run() {
    if (!threadId || !opponent) return;
    setRunning(true); setError(""); setReport(null); setActionLog(null);
    try {
      const response = await fetch(`${base}/api/simulations/run/${encodeURIComponent(threadId)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ opponent, seed, samples, mode }),
      });
      const data = await response.json() as Report & { error?: string };
      if (!response.ok) throw new Error(data.error || "Simulation failed.");
      setReport(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Simulation failed.");
    } finally { setRunning(false); }
  }
  async function openReplay(sample: Sample) {
    if (!sample.replayId || openingReplay) return;
    const tab = window.open("", "_blank");
    if (tab) tab.opener = null;
    setOpeningReplay(sample.seed); setError("");
    try {
      const response = await fetch(`${base}/api/simulations/replay/${encodeURIComponent(sample.replayId)}`, { method: "POST" });
      const result = await response.json() as { url?: string; error?: string };
      if (!response.ok || !result.url) throw new Error(result.error || "Could not open the replay.");
      if (tab) tab.location.href = result.url;
      else window.location.assign(result.url);
    } catch (cause) {
      tab?.close();
      setError(cause instanceof Error ? cause.message : "Could not open the replay.");
    } finally { setOpeningReplay(null); }
  }
  const counts = report?.aggregate.counts;
  const selectedOpponent = opponents.find(item => item.id === opponent);
  return <details className="residual-simulation">
    <summary>Deck simulations</summary>
    <p className="muted">{mode === "residual" ? "Sample real openings. The opponent gets the first unit attack in round two." : "Play complete games with SWUSim's normal heuristic bot for both decks. The opponent starts with initiative."}</p>
    <div className="residual-controls">
      <label className="residual-mode-field">Mode<select value={mode} disabled={running} onChange={event => {
        const next = event.target.value as SimulationMode;
        setMode(next); setSamples(next === "full_game" ? 4 : 8); setReport(null);
      }}><option value="residual">First-turn residual value</option><option value="full_game">Full game wins</option></select></label>
      <div className="residual-opponent-field"><span className="residual-field-label">Opponent</span>
        <div className="residual-opponent-control"><details className="residual-opponent-menu" ref={opponentMenu}>
          <summary aria-label={`Opponent: ${selectedOpponent?.label.replace(/^Real-deck self-play fixture — /, "") || "Choose opponent"}`}>
            {selectedOpponent && <OpponentIdentity item={selectedOpponent} />}
            <span className="residual-opponent-name">{selectedOpponent?.label.replace(/^Real-deck self-play fixture — /, "") || "Choose opponent"}</span>
            <Icon name="chevronDown" size={18} />
          </summary>
          <div className="residual-opponent-options" role="group" aria-label="Opponents">
            {opponents.map(item => <button type="button" key={item.id} className={item.id === opponent ? "is-selected" : ""}
              aria-current={item.id === opponent ? "true" : undefined} disabled={running}
              onClick={() => { setOpponent(item.id); if (opponentMenu.current) opponentMenu.current.open = false; }}>
              <OpponentIdentity item={item} /><span>{item.label.replace(/^Real-deck self-play fixture — /, "")}</span>
            </button>)}
          </div>
        </details><button type="button" className="residual-inspect-button" onClick={inspectOpponent} disabled={!selectedOpponent} title="View selected opponent deck list" aria-label="View selected opponent deck list"><Icon name="search" size={20} /></button></div>
      </div>
      <label>Samples<input type="number" min={1} max={12} value={samples} onChange={event => setSamples(Number(event.target.value))} disabled={running}/></label>
      <label>Seed<input value={seed} maxLength={64} onChange={event => setSeed(event.target.value)} disabled={running}/></label>
      <button className="primary-button" disabled={running || !opponent || !threadId} onClick={() => void run()}>{running ? "Simulating…" : "Run simulation"}</button>
    </div>
    {error && <p role="alert" className="residual-error">{error}</p>}
    {report && <div className="residual-results">
      {report.mode === "full_game" ? <>
        <p><strong>{counts?.ours}</strong> wins · <strong>{counts?.opponent}</strong> losses · <strong>{counts?.incomplete}</strong> incomplete</p>
        <p className="muted">Win rate: {report.aggregate.ourWinRate == null ? "—" : `${(report.aggregate.ourWinRate * 100).toFixed(1)}%`} of {report.aggregate.completedGames} completed games. Average game length: {report.aggregate.meanRounds?.toFixed(1) ?? "—"} rounds.</p>
        <div className="residual-game-metrics">
          <div><strong>{report.aggregate.meanActions?.toFixed(1) ?? "—"}</strong><span>Avg. bot actions / game</span></div>
          <div><strong>{report.aggregate.meanOurBaseHealthInWins?.toFixed(1) ?? "—"}</strong><span>Your base HP left in wins</span></div>
          <div><strong>{report.aggregate.meanOpponentBaseHealthInLosses?.toFixed(1) ?? "—"}</strong><span>Opponent base HP left in losses</span></div>
        </div>
      </> : <>
        <p><strong>{counts?.ahead}</strong> ahead · <strong>{counts?.equal}</strong> equal · <strong>{counts?.behind}</strong> behind</p>
        <p className="muted">{report.aggregate.scoredSamples} scored openings · {counts?.no_unit_attack} without a legal unit attack · {counts?.failed} failed. Mean unit difference: {report.aggregate.meanUnitDifference?.toFixed(2) ?? "—"}.</p>
        <p className="muted">Mean remaining unit health difference: {report.aggregate.meanRemainingUnitHealthDifference?.toFixed(2) ?? "—"}. Mean base health: yours {report.aggregate.meanBaseHealth?.ours?.toFixed(1) ?? "—"}, opponent {report.aggregate.meanBaseHealth?.opponent?.toFixed(1) ?? "—"}.</p>
      </>}
      {report.elapsedMs !== undefined && <p className="muted">Batch time: {(report.elapsedMs / 1000).toFixed(1)} seconds.</p>}
      {draft.revision !== report.revision && <p className="residual-error">This result uses revision {report.revision}; the working deck has since changed.</p>}
      <small>Opponent: {report.opponent} · policy: {report.policy} · engine: {report.engineRevision?.slice(0, 8) || "unknown"} · deck: {report.deckHash.slice(0, 8)}</small>
      <details><summary>Inspect samples</summary>{report.samples.map(sample => <details key={sample.seed} className="residual-sample"><summary>{sample.seed} · {report.mode === "full_game" ? sample.status === "completed" ? `${sample.winner === 2 ? "win" : "loss"} in ${sample.rounds} rounds` : sample.status : `${sample.status}${sample.summary ? ` · units ${Object.values(sample.summary.unitCount["2"]).reduce((a,b)=>a+b,0)}–${Object.values(sample.summary.unitCount["1"]).reduce((a,b)=>a+b,0)}` : ""}`}</summary>
        {report.mode === "full_game" ? <>
          {sample.engineError ? <p className="residual-error">{sample.engineError}</p> : <p>{sample.appliedSteps} bot actions · final base health: yours {sample.afterAttack?.baseHealth["2"]}, opponent {sample.afterAttack?.baseHealth["1"]}.</p>}
          {sample.baseHealthTimeline?.length ? <BaseHealthTimeline points={sample.baseHealthTimeline} /> : <p className="muted">No base health timeline available.</p>}
          {sample.replayId && <button type="button" className="residual-log-button" disabled={!!openingReplay} onClick={() => void openReplay(sample)}>
            {openingReplay === sample.seed ? "Opening replay…" : "View replay in Petranaki ↗"}
          </button>}
          {!!sample.trace?.length && <button type="button" className="residual-log-button" onClick={() => setActionLog(sample)}>View action log</button>}
        </> : sample.engineError ? <p className="residual-error">{sample.engineError}</p> : <p>
          {sample.status === "no_unit_attack" ? attackReason[sample.attackAvailability?.reason || ""] || "No legal unit attack" : `Selected attack: ${sample.selectedAttack || "none"}`}.
          {arenaCounts(sample, "1") && ` Before attack: opponent ${arenaCounts(sample, "1")}; yours ${arenaCounts(sample, "2")}.`}
          {` Base health: ours ${sample.afterAttack?.baseHealth["2"]}, opponent ${sample.afterAttack?.baseHealth["1"]}.`}
        </p>}
        {report.mode === "residual" && <ol>{sample.trace?.map(item => <li key={item.step}>Round {item.round}, P{item.seat}: {item.action}{item.chosenCards?.length ? ` [${item.chosenCards.join(", ")}]` : ""} <small>({item.rule})</small></li>)}</ol>}
      </details>)}</details>
    </div>}
    <dialog ref={actionDialog} className="residual-action-dialog" onClose={() => setActionLog(null)} aria-label={actionLog ? `Action log for ${actionLog.seed}` : "Action log"}>
      {actionLog && <><div className="residual-action-header"><div><h3>{actionLog.seed} · action log</h3><p className="muted">Last {actionLog.trace?.length ?? 0} of {actionLog.appliedSteps ?? 0} bot actions</p></div><button type="button" onClick={() => setActionLog(null)} aria-label="Close action log">×</button></div>
        <ol>{actionLog.trace?.map(item => <li key={item.step}>Round {item.round}, {item.seat === 2 ? "you" : "opponent"}: {item.action}{item.chosenCards?.length ? ` [${item.chosenCards.join(", ")}]` : ""} <small>({item.rule})</small></li>)}</ol>
      </>}
    </dialog>
    <dialog ref={deckDialog} className="residual-deck-dialog" onClose={() => { hideCardPreview(); setInspectedOpponent(null); }} onScroll={hideCardPreview} onClick={event => {
      if (event.target !== event.currentTarget) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) setInspectedOpponent(null);
    }} aria-label={inspectedOpponent ? `Deck list for ${inspectedOpponent.label}` : "Opponent deck list"}>
      <div className="residual-action-header" onPointerDown={startDeckDrag} onPointerMove={moveDeckDrag} onPointerUp={stopDeckDrag} onPointerCancel={stopDeckDrag}>
        <h3 className="residual-deck-title">{inspectedDeck ? (["leader", "base"] as const).map(section => {
          const card = inspectedDeck[section];
          return card && <span key={section} className="residual-deck-title-card">{card.id && <img src={swuCardImage(card.id, true)} alt="" />}{card.name}</span>;
        }) : inspectedOpponent?.label.replace(/^Real-deck self-play fixture — /, "")}</h3>
        <button type="button" onClick={() => setInspectedOpponent(null)} aria-label="Close opponent deck list"><Icon name="close" size={22} /></button>
      </div>
      {deckError && <p role="alert" className="residual-error">{deckError}</p>}
      {!inspectedDeck && !deckError && <p className="muted">Loading deck list…</p>}
      {inspectedDeck && <>
        <div className="residual-deck-main">
          <div className="residual-deck-sections">
            <OpponentDeckSection title="Space units" cards={inspectedDeck.deck.filter(card => card.type.toLowerCase() === "unit" && card.arenas.some(arena => arena.toLowerCase() === "space"))} onPreview={showCardPreview} onQueuePreview={queueCardPreview} onMovePreview={movePendingCardPreview} onHidePreview={hideCardPreview} />
            <OpponentDeckSection title="Ground units" cards={inspectedDeck.deck.filter(card => card.type.toLowerCase() === "unit" && card.arenas.some(arena => arena.toLowerCase() === "ground") && !card.arenas.some(arena => arena.toLowerCase() === "space"))} onPreview={showCardPreview} onQueuePreview={queueCardPreview} onMovePreview={movePendingCardPreview} onHidePreview={hideCardPreview} />
            <OpponentDeckSection title="Upgrades & events" cards={inspectedDeck.deck.filter(card => card.type.toLowerCase() !== "unit" || !card.arenas.some(arena => ["space", "ground"].includes(arena.toLowerCase())))} onPreview={showCardPreview} onQueuePreview={queueCardPreview} onMovePreview={movePendingCardPreview} onHidePreview={hideCardPreview} wide />
          </div>
        </div>
      </>}
      <div ref={cardTooltip} popover="manual" className="card-preview-tooltip" role="tooltip">
        {previewCard?.id && <img src={swuCardImage(previewCard.id, true)} alt="" />}
        {previewCard && <strong>{previewCard.name}</strong>}
      </div>
    </dialog>
  </details>;
}
