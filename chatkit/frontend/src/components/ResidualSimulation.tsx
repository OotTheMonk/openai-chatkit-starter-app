import { useEffect, useRef, useState } from "react";
import { CHATKIT_API_URL } from "../lib/config";
import { swuCardImage, type Draft } from "../lib/deck";
import "./ResidualSimulation.css";

const base = CHATKIT_API_URL.replace(/\/chatkit\/?$/, "");
type SimulationMode = "residual" | "full_game";
type Opponent = { id: string; label: string; group: string; leaderId?: string | null; baseId?: string | null };
type Sample = {
  status: string; seed: string; selectedAttack: string | null;
  winner?: number; rounds?: number; appliedSteps?: number;
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
  const opponentMenu = useRef<HTMLDetailsElement>(null);
  const actionDialog = useRef<HTMLDialogElement>(null);
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
        <details className="residual-opponent-menu" ref={opponentMenu}>
          <summary aria-label={`Opponent: ${selectedOpponent?.label.replace(/^Real-deck self-play fixture — /, "") || "Choose opponent"}`}>
            {selectedOpponent && <OpponentIdentity item={selectedOpponent} />}
            <span>{selectedOpponent?.label.replace(/^Real-deck self-play fixture — /, "") || "Choose opponent"}</span>
          </summary>
          <div className="residual-opponent-options" role="group" aria-label="Opponents">
            {opponents.map(item => <button type="button" key={item.id} className={item.id === opponent ? "is-selected" : ""}
              aria-current={item.id === opponent ? "true" : undefined} disabled={running}
              onClick={() => { setOpponent(item.id); if (opponentMenu.current) opponentMenu.current.open = false; }}>
              <OpponentIdentity item={item} /><span>{item.label.replace(/^Real-deck self-play fixture — /, "")}</span>
            </button>)}
          </div>
        </details>
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
  </details>;
}
