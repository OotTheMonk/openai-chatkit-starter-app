import type { Evidence } from "../lib/deck";
const percent=(n:number|null|undefined)=>n==null?"Unknown":n.toFixed(1)+"%";
export function StatisticalEvidence({evidence}:{evidence:Evidence}) {
 return <details className="proposal-analysis"><summary>SWUStats evidence · original build</summary>
  <p><a href="https://www.swustats.net/TCGEngine/Stats/APIs.php" target="_blank" rel="noreferrer">Statistics provided by SWUStats</a> · {evidence.format}</p>
  <p>{evidence.window}</p><small>Retrieved {evidence.retrieved_at?new Date(evidence.retrieved_at).toLocaleString():"unavailable"}. Evidence supports experimentation; it does not determine the deck.</small>
  {evidence.notices.map((n,i)=><p key={i}>{n}</p>)}
  {!!evidence.card_statistics?.length&&<><h4>Candidate observations</h4><div className="proposal-table"><table><thead><tr><th>Card</th><th>Included observations</th><th>Win % when included</th><th>Win % when played</th></tr></thead><tbody>{evidence.card_statistics.map(c=><tr key={c.id}><th>{c.name}<small>{c.sample_label}</small></th><td>{c.included??"Unknown"}</td><td>{percent(c.win_rate_when_included)}</td><td>{percent(c.win_rate_when_played)}<small>{c.played??"Unknown"} played observations</small></td></tr>)}</tbody></table></div></>}
  {!!evidence.matchups?.length&&<><h4>Matchups to test</h4><div className="proposal-table"><table><thead><tr><th>Opponent</th><th>Games</th><th>Observed win %</th></tr></thead><tbody>{evidence.matchups.map((m,i)=><tr key={i}><th>{m.opponent_leader||"Unknown leader"}<small>{m.opponent_base||"Unknown base"}</small></th><td>{m.games}{m.limited_sample&&<small>Small sample</small>}</td><td>{percent(m.win_rate)}</td></tr>)}</tbody></table></div><p>These aggregate results help choose playtest matchups; they do not predict this draft’s win rate.</p></>}
  <small>{evidence.scope}</small>
 </details>;
}
