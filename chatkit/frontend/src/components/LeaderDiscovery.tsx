import { useEffect, useRef, useState } from "react";
import { CHATKIT_API_URL } from "../lib/config";
import { swuCardImage } from "../lib/deck";
const api=CHATKIT_API_URL.replace(/\/chatkit\/?$/,"");
type Preferences={format:string;window:string;style:string;use_library:boolean;liked:string[];disliked:string[];goal:string};
type Card={id:string;name:string;image?:string;aspects:string[];text:string;back_text:string;cost?:number;hp?:string};
type Leader=Card&{released:string;set_name:string;release_source:string;reasons:string[];themes:string[];tradeoff:string;format_status:string};
type Results={leaders:Leader[];bases:Card[];matching_count:number;profile:{name:string;leader:string;favorite:boolean}[];checked_at:string;stale:boolean;sources:{label:string;url:string}[];note:string;library_status:string};
const defaults:Preferences={format:"Premier",window:"12",style:"Any",use_library:true,liked:[],disliked:[],goal:""};
export function LeaderDiscovery({threadId,onBuild}:{threadId:string|null;onBuild:(thread:string,prompt:string)=>Promise<void>}) {
 const [prefs,setPrefs]=useState<Preferences>(defaults),[result,setResult]=useState<Results|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[compared,setCompared]=useState<string[]>([]),[selected,setSelected]=useState<Leader|null>(null),[baseId,setBaseId]=useState("");
 const request=useRef<AbortController|null>(null),generation=useRef(0),buildSection=useRef<HTMLElement|null>(null);
 useEffect(()=>{if(selected)buildSection.current?.scrollIntoView({block:"nearest",behavior:"smooth"});},[selected]);
 useEffect(()=>{
  const controller=new AbortController();
  if(threadId)void fetch(api+"/api/discovery/"+encodeURIComponent(threadId),{signal:controller.signal}).then(r=>r.json()).then((d:{request:Preferences})=>{if(!controller.signal.aborted)setPrefs(d.request);}).catch(()=>{});
  return()=>{controller.abort();request.current?.abort();};
 },[threadId]);
 async function search(next:Preferences){
  request.current?.abort();const controller=new AbortController();request.current=controller;const version=++generation.current;setBusy(true);setError("");setResult(null);setSelected(null);setCompared([]);
  try{const r=await fetch(api+"/api/discovery"+(threadId?"?thread_id="+encodeURIComponent(threadId):""),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(next),signal:controller.signal});const data=await r.json() as Results&{error?:string};if(!r.ok)throw Error(data.error||"Discovery couldn't load. Please retry.");if(version===generation.current)setResult(data);}
  catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Discovery couldn't load.");}
  finally{if(version===generation.current)setBusy(false);}
 }
 const update=(change:Partial<Preferences>)=>{request.current?.abort();generation.current++;setBusy(false);setPrefs(p=>({...p,...change}));setResult(null);setSelected(null);};
 const feedback=(leader:Leader,like:boolean)=>{
  const next={...prefs,liked:like?[...new Set([...prefs.liked,leader.id])].slice(-30):prefs.liked.filter(id=>id!==leader.id),disliked:like?prefs.disliked.filter(id=>id!==leader.id):[...new Set([...prefs.disliked,leader.id])].slice(-30)};
  setPrefs(next);void search(next);
 };
 async function build(){
  if(!selected||!baseId)return;setBusy(true);setError("");
  try{const r=await fetch(api+"/api/workspace/new-draft",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({leader_id:selected.id,base_id:baseId,preferences:prefs})});const d=await r.json() as {thread_id:string;error?:string};if(!r.ok)throw Error(d.error||"Draft couldn't be created.");await onBuild(d.thread_id,`Read my new working draft and its build_preferences. Build around ${selected.name} for ${prefs.format}. My preferred style is ${prefs.style}. ${prefs.goal||"Ask me one focused question about my intended game plan, then propose a starting shell."} Use verified card IDs and prepare a proposal for review. Do not apply changes or claim full tournament legality.`);}
  catch(e){setError(e instanceof Error?e.message:"Draft couldn't be created.");}
  finally{setBusy(false);}
 }
 return <section className="leader-discovery" aria-label="Leader discovery">
  <span className="eyebrow">FIND YOUR NEXT DECK</span><h2>A new leader. A familiar spark.</h2><p>Start with the way you like to play. Explore a few directions, compare them, then build one together.</p>
  <form className="discovery-filters" onSubmit={e=>{e.preventDefault();void search(prefs);}}>
   <label>Format<select value={prefs.format} onChange={e=>update({format:e.target.value})}><option>Premier</option><option>Eternal</option></select></label>
   <label>First released<select value={prefs.window} onChange={e=>update({window:e.target.value})}><option value="6">Within 6 months</option><option value="12">Within 12 months</option><option value="all">All recorded releases</option></select></label>
   <label>What sounds fun?<select value={prefs.style} onChange={e=>update({style:e.target.value})}>{["Any","Fast pressure","Control","Card advantage","Synergy"].map(v=><option key={v}>{v}</option>)}</select></label>
   <label className="discovery-library"><input type="checkbox" checked={prefs.use_library} onChange={e=>update({use_library:e.target.checked})}/>Use my saved decks and favorites as clues</label>
   <button className="primary-button" disabled={busy}>{busy?"Finding your next deck…":result?"Refresh recommendations":"Find leaders"}</button>
  </form>
  {!result&&<p className="discovery-explainer">Confirm your format above. Premier has rotation; Eternal uses a broader card pool. An old deck is not automatically unusable. We check leaders here; a full deck needs its own review.</p>}
  {error&&<p className="notice" role="alert">{error}</p>}
  {result&&<>
   <div className="discovery-context"><strong>{result.matching_count} leaders match · showing {result.leaders.length}</strong><p>{result.profile.length?`Tentative clues from ${result.profile.map(d=>d.name+(d.favorite?" (favorite)":"")).join(", ")}. Change the style or give feedback to steer the shortlist.`:result.library_status==="unavailable"?"SWUStats isn't available. You can still discover leaders; connect your account in the header to personalize them.":"Exploring without a saved-deck profile. Choose a style or use More like this to steer your recommendations."}</p><small>Rules snapshot: {result.checked_at}. {result.stale?"Out of date — current format eligibility is unverified.":"Recorded release pool and known suspensions checked; verify before an event."}</small></div>
   {prefs.liked.length+prefs.disliked.length>0&&<button className="text-button" disabled={busy} onClick={()=>{const next={...prefs,liked:[],disliked:[]};setPrefs(next);void search(next);}}>Reset recommendation feedback</button>}
   {compared.length>0&&<section className="leader-comparison" aria-label="Compare leaders"><h3>Compare your options</h3><div className="comparison-scroll"><table><thead><tr><th>Leader</th><th>Aspects</th><th>Deploy</th><th>Rules themes</th></tr></thead><tbody>{result.leaders.filter(l=>compared.includes(l.id)).map(l=><tr key={l.id}><th>{l.name}</th><td>{l.aspects.join(" / ")}</td><td>{l.cost??"Unknown"}</td><td>{l.themes.join(" · ")||"Read rules below"}</td></tr>)}</tbody></table></div><p>Themes are inferred from rules text, not competitive archetype ratings.</p></section>}
   <div className="leader-grid">{result.leaders.map(leader=><article className="leader-option" key={leader.id}>
    <img src={leader.image||swuCardImage(leader.id,true)} alt={leader.name} loading="lazy"/>
    <div className="leader-option-body"><span className="eyebrow">{leader.aspects.join(" · ")}</span><h3>{leader.name}</h3><a className="leader-release" href={leader.release_source} target="_blank" rel="noreferrer">{leader.set_name} · {leader.released}</a><p className="leader-fit">{leader.reasons.join(" ")}</p><p>{leader.tradeoff}</p><details><summary>Game plan & card rules</summary><p>Build a support package that makes this ability useful repeatedly:</p><p className="card-rules">{leader.text||"Rules text unavailable."}</p><strong>When deployed</strong><p className="card-rules">{leader.back_text||"Deployed text unavailable."}</p></details><div className="leader-feedback"><button disabled={busy} onClick={()=>feedback(leader,true)}>More like this</button><button disabled={busy} onClick={()=>feedback(leader,false)}>Not for me</button><label><input type="checkbox" checked={compared.includes(leader.id)} onChange={e=>setCompared(old=>e.target.checked?[...old,leader.id]:old.filter(id=>id!==leader.id))}/>Compare</label></div><button className="primary-button" disabled={busy} onClick={()=>{setSelected(leader);setBaseId("");}}>Build around this leader</button></div>
   </article>)}</div>
   {!result.leaders.length&&<p role="status">No leaders match these choices. Broaden the release window, choose another style, or reset your feedback.</p>}
   {selected&&<section ref={buildSection} className="discovery-build" aria-label="Start a new draft"><h3>Build around {selected.name}</h3><p>Choose a base and a goal. This opens a separate conversation and local draft; your existing deck is preserved.</p><label>Base<select value={baseId} onChange={e=>setBaseId(e.target.value)}><option value="">Choose a base…</option>{result.bases.map(b=><option key={b.id} value={b.id}>{b.name} — {b.aspects.join(" / ")||"Neutral"} · {b.hp??"?"} HP</option>)}</select></label>{baseId&&<p className="card-rules">{result.bases.find(b=>b.id===baseId)?.text||"No additional printed ability."}</p>}<label>Build brief<textarea value={prefs.goal} maxLength={1000} onChange={e=>setPrefs({...prefs,goal:e.target.value})} placeholder="For example: proactive midrange, a modest budget, and a forgiving learning curve."/></label><div className="proposal-actions"><button className="primary-button" disabled={busy||!baseId} onClick={()=>void build()}>Create draft & plan together</button><button className="secondary-button" disabled={busy} onClick={()=>setSelected(null)}>Cancel</button></div></section>}
   <footer className="discovery-sources"><p>{result.note}</p>{result.sources.map(s=><a key={s.url} href={s.url} target="_blank" rel="noreferrer">{s.label}</a>)}</footer>
  </>}
 </section>;
}
