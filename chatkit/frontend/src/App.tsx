import { useState, useEffect, useRef, useCallback, type CSSProperties } from "react";
import { ChatKitPanel, type ChatHandle } from "./components/ChatKitPanel";
import { LeaderDiscovery } from "./components/LeaderDiscovery";
import { DeckPanel } from "./components/DeckPanel";
import { DeckLibrary } from "./components/DeckLibrary";
import { AccountConnection } from "./components/AccountConnection";
import { Icon } from "./components/Icon";
import { CHATKIT_API_URL } from "./lib/config";
import { type Draft, goals } from "./lib/deck";
const base = CHATKIT_API_URL.replace(/\/chatkit\/?$/, "");
type CardSection = "deck" | "sideboard";
type CardEdit = {cardId:string;section:CardSection;kind:"add"|"remove";allCopies?:boolean;name?:string};
function applyCardEdit(prev:Draft,edit:CardEdit):Draft|null {
 const contents=prev.deck_contents;
 if(!contents)return null;
 const rows=contents[edit.section].map(card=>({...card}));
 const index=rows.findIndex(card=>String(card.id)===edit.cardId);
 if(edit.kind==="add"){
  if(index>=0){if(rows[index].count>=99)return null;rows[index].count++;}
  else rows.push({id:edit.cardId,name:edit.name||edit.cardId,count:1});
 }else{
  if(index<0)return null;
  if(edit.allCopies||rows[index].count<=1)rows.splice(index,1);
  else rows[index].count--;
 }
 return {...prev,deck_contents:{...contents,[edit.section]:rows},proposal:null,dirty:prev.source==="local"||prev.dirty,can_undo:true};
}
function replayEdits(confirmed:Draft,edits:CardEdit[]):Draft {
 return edits.reduce((current,edit)=>applyCardEdit(current,edit)||current,confirmed);
}
function preference(key: string, fallback: number) { const v = Number(localStorage.getItem(key)); return Number.isFinite(v) && v > 0 ? v : fallback; }
export default function App() {
 const [view,setView]=useState<"assistant"|"library"|"discovery">("assistant");
 const [threadId,setThreadId]=useState<string|null>(()=>localStorage.getItem("builder-thread"));
 const [draft,setDraft]=useState<Draft|null>(null);
 const [connected,setConnected]=useState(false);
 const [collapsed,setCollapsed]=useState(()=>localStorage.getItem("nav-expanded")!=="true");
 const [theme,setTheme]=useState<"light"|"dark">(()=>document.documentElement.dataset.theme==="dark"?"dark":"light");
 const [split,setSplit]=useState(()=>Math.max(35,Math.min(60,preference("deck-width",48))));
 const [inspectorOpen,setInspectorOpen]=useState(false);
 const [notice,setNotice]=useState("");
 useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(""),6000);return ()=>clearTimeout(timer);},[notice]);
 const [refresh,setRefresh]=useState(0);
 const [loading,setLoading]=useState(false);
 const [recovering,setRecovering]=useState(false);
 const draftRef=useRef<Draft|null>(null),confirmedDraft=useRef<Draft|null>(null);
 const pendingEdits=useRef<CardEdit[]>([]),savingEdits=useRef(false),recoveringRef=useRef(false),editGeneration=useRef(0),threadRef=useRef(threadId);
 const [goal,setGoal]=useState<string|null>(null),[detail,setDetail]=useState("");
 useEffect(()=>{
   if(!goal)return;
   const previous=document.activeElement as HTMLElement|null;
   const trap=(event:KeyboardEvent)=>{
     if(event.key!=="Tab")return;
     const controls=Array.from(document.querySelectorAll<HTMLElement>(".goal-dialog button,.goal-dialog textarea"));
     const first=controls[0],last=controls[controls.length-1];
     if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
     else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
   };
   document.addEventListener("keydown",trap);
   return()=>{document.removeEventListener("keydown",trap);previous?.focus();};
 },[goal]);
 const chat=useRef<ChatHandle>(null),body=useRef<HTMLDivElement>(null);
 const activeDeckId=draft?.active_deck_id??null;
 const activeName=draft?.active_deck_name||draft?.deck_contents?.metadata.name;
 const effect=useCallback((event:{name:string;data?:Record<string,unknown>})=>{
   if(event.name==="discover_leaders"){setView("discovery");setInspectorOpen(false);}
   if(event.name==="view_library"){setView("library");setInspectorOpen(false);}
   if(event.name==="deck_refresh"||event.name==="draft_refresh"){setRefresh(v=>v+1);setInspectorOpen(true);}
 },[]);
 const changeThread=useCallback((id:string|null)=>{
   editGeneration.current++;pendingEdits.current=[];savingEdits.current=false;recoveringRef.current=false;setRecovering(false);
   threadRef.current=id;draftRef.current=null;confirmedDraft.current=null;
   setThreadId(id);setDraft(null);
 },[]);
 useEffect(()=>{
   if(!threadId)return;
   const abort=new AbortController(),generation=editGeneration.current;setLoading(true);
   fetch(base+"/api/deck-state/"+encodeURIComponent(threadId),{signal:abort.signal}).then(async r=>{
     const d=await r.json() as Draft & {error?:string};if(!r.ok)throw Error(d.error||"Unable to load this working draft.");return d as Draft;
   }).then(d=>{if(!abort.signal.aborted&&generation===editGeneration.current&&!pendingEdits.current.length){
     if(confirmedDraft.current?.active_deck_id===d.active_deck_id&&d.revision<confirmedDraft.current.revision)return;
     confirmedDraft.current=d;draftRef.current=d;setDraft(d);recoveringRef.current=false;setRecovering(false);if(d.active_deck_id)setInspectorOpen(true);
   }})
   .catch((e:unknown)=>{if(!abort.signal.aborted)setNotice(e instanceof Error?e.message:"Unable to load draft.");}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
   return ()=>abort.abort();
 },[threadId,refresh]);
 const run=async(action:()=>Promise<void>|undefined)=>{
   setNotice("");try{await action();}catch{setNotice("The assistant couldn't complete that request. Please retry.");}
 };
 const selectDeck=async(deck:{id:number;name:string})=>{
   setView("assistant");setInspectorOpen(true);
   const recent=JSON.parse(localStorage.getItem("recent-decks")||"[]") as number[];
   localStorage.setItem("recent-decks",JSON.stringify([deck.id,...recent.filter(id=>id!==deck.id)].slice(0,20)));
   await run(()=>chat.current?.selectDeck(deck.id,deck.name,!!threadId));setRefresh(v=>v+1);
 };
 async function drainEdits(generation:number,editThread:string,deckId:number){
  if(savingEdits.current)return;
  savingEdits.current=true;
  try{
   while(pendingEdits.current.length&&generation===editGeneration.current){
    const edit=pendingEdits.current[0],confirmed=confirmedDraft.current;
    if(!confirmed||confirmed.active_deck_id!==deckId)throw Error("The active deck changed.");
    const r=await fetch(base+"/api/workspace/"+encodeURIComponent(editThread)+"/"+edit.kind,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({deck_id:deckId,revision:confirmed.revision,card_id:edit.cardId,section:edit.section,...(edit.kind==="remove"?{all_copies:!!edit.allCopies}:{})})});
    const data=await r.json() as Draft&{error?:string};
    if(generation!==editGeneration.current)return;
    if(!r.ok)throw Error(data.error||"Could not save the card change.");
    confirmedDraft.current=data;pendingEdits.current.shift();
    const visible=replayEdits(data,pendingEdits.current);draftRef.current=visible;setDraft(visible);
   }
  }catch(error){
   if(generation!==editGeneration.current)return;
   pendingEdits.current=[];
   recoveringRef.current=true;setRecovering(true);
   const message=error instanceof Error?error.message:"Could not save the card change.";
   try{
    const r=await fetch(base+"/api/deck-state/"+encodeURIComponent(editThread));
    const data=await r.json() as Draft&{error?:string};
    if(!r.ok)throw Error(data.error||"Could not reload the deck.");
    if(generation!==editGeneration.current)return;
    confirmedDraft.current=data;draftRef.current=data;setDraft(data);
    recoveringRef.current=false;setRecovering(false);
    setNotice(message+" Your deck has been re-synced.");
   }catch{
    if(generation!==editGeneration.current)return;
    draftRef.current=confirmedDraft.current;setDraft(confirmedDraft.current);
    setNotice(message+" The deck could not be re-synced; reload it before editing again.");
   }
  }finally{
   if(generation===editGeneration.current){savingEdits.current=false;if(pendingEdits.current.length)void drainEdits(generation,editThread,deckId);}
  }
 }
 const editCards=(edits:CardEdit[])=>{
  const current=draftRef.current,editThread=threadRef.current;
  if(!current||!editThread||!current.active_deck_id||recoveringRef.current)return;
  let visible=current;const accepted:CardEdit[]=[];
  for(const edit of edits){const next=applyCardEdit(visible,edit);if(next){visible=next;accepted.push(edit);}}
  if(!accepted.length)return;
  pendingEdits.current.push(...accepted);draftRef.current=visible;setDraft(visible);setNotice("");
  void drainEdits(editGeneration.current,editThread,current.active_deck_id);
 };
 const addCard=(cardId:string,section:CardSection,name?:string)=>editCards([{cardId,section,kind:"add",name}]);
 const removeCard=(cardId:string,section:CardSection,allCopies:boolean)=>editCards([{cardId,section,kind:"remove",allCopies}]);
 const removeAllCard=(ids:string[],section:CardSection)=>editCards(ids.map(cardId=>({cardId,section,kind:"remove",allCopies:true})));
 const chooseGoal=(value:string)=>{setGoal(value);setDetail("");setView("assistant");};
 const submitGoal=()=>{const text=goal==="Adjust proposal"?"Adjust the pending proposal":goal;setGoal(null);void run(()=>chat.current?.ask(text+" for my active working draft. "+(detail.trim()||"Ask me one focused question about my goal before proposing changes.")+" Read the working draft first. Propose changes for review; don't apply them."));};
 const resize=(value:number)=>{const n=Math.max(35,Math.min(60,value));setSplit(n);localStorage.setItem("deck-width",String(n));};
 const toggleTheme=()=>{const next=theme==="light"?"dark":"light";setTheme(next);document.documentElement.dataset.theme=next;localStorage.setItem("chat-tcg-theme",next);};
 return <div className={"app-shell builder-shell "+(collapsed?"nav-collapsed":"")}>
 <a className="skip-link" href="#workspace">Skip to workspace</a>
 <aside className="sidebar">
  <a href="/" className="brand" aria-label="Chat TCG home"><span className="brand-mark"><Icon name="cards" size={25}/></span><span className="nav-copy">ChatTCG<small>DECK BUILDER</small></span></a>
  <nav aria-label="Workspace">
   <button title="Discover leaders" aria-label="Discover leaders" className={"nav-item "+(view==="discovery"?"current":"")} onClick={()=>{setView("discovery");setInspectorOpen(false);}}><Icon name="search"/><span className="nav-copy">Discover leaders</span></button>
   <button title="Assistant" aria-label="Assistant" className={"nav-item "+(view==="assistant"?"current":"")} onClick={()=>setView("assistant")}><Icon name="chat"/><span className="nav-copy">Assistant</span></button>
   <button title="Deck library" aria-label="Deck library" className={"nav-item "+(view==="library"?"current":"")} onClick={()=>{setView("library");setInspectorOpen(false);}}><Icon name="cards"/><span className="nav-copy">Deck library</span></button>
   <button title="Conversation history" aria-label="Conversation history" className="nav-item" onClick={()=>{setView("assistant");void run(()=>chat.current?.history());}}><Icon name="history"/><span className="nav-copy">Conversations</span></button>
  </nav>
  <button className="nav-item theme-toggle" title={theme==="light"?"Switch to dark mode":"Switch to light mode"} aria-label={theme==="light"?"Switch to dark mode":"Switch to light mode"} aria-pressed={theme==="dark"} onClick={toggleTheme}><Icon name={theme==="light"?"moon":"sun"}/><span className="nav-copy">{theme==="light"?"Dark mode":"Light mode"}</span></button>
  <button className="nav-item collapse-nav" title={collapsed?"Expand navigation":"Collapse navigation"} aria-label={collapsed?"Expand navigation":"Collapse navigation"} aria-expanded={!collapsed} onClick={()=>{setCollapsed(!collapsed);localStorage.setItem("nav-expanded",String(collapsed));}}><span aria-hidden="true">{collapsed?"»":"«"}</span><span className="nav-copy">Collapse</span></button>
 </aside>
 <main id="workspace" className="workspace">
  <header className="workspace-header"><h1>{view==="library"?"Deck library":view==="discovery"?"Discover leaders":"Deck builder"}</h1><div className="header-actions"><AccountConnection onChange={setConnected}/><button className="secondary-button" title="Start a new conversation" onClick={()=>{setView("assistant");void run(()=>chat.current?.newChat());}}><Icon name="plus" size={16}/><span>New chat</span></button><button className="secondary-button" aria-expanded={inspectorOpen} onClick={()=>setInspectorOpen(!inspectorOpen)}><Icon name="cards" size={16}/>Deck</button></div></header>
  {notice&&<div className="toast" role="alert">{notice}<button aria-label="Dismiss" onClick={()=>setNotice("")}>×</button></div>}
  <div className={"workspace-body "+(inspectorOpen?"with-deck":"")} ref={body} style={{"--deck-width":split+"%"} as CSSProperties}>
   <div className="main-content">
    <section className={view==="assistant"?"assistant-view":"assistant-view is-hidden"} aria-label="Conversation">
     <ChatKitPanel ref={chat} onThreadChange={changeThread} onEffect={effect} activeDeckId={activeDeckId} draft={draft} cardBusy={recovering} onAddCard={(id,name)=>addCard(id,"deck",name)} onRemoveCard={id=>removeCard(id,"deck",false)} context={<div className="conversation-context">
      <div>{activeDeckId?<><span>Working on <strong>{activeName||"selected deck"}</strong></span><span className="draft-badge">{draft?.dirty?"Unsaved draft":"Saved deck"}</span><button className="text-button" onClick={()=>{setView("library");setInspectorOpen(false);}}>Change deck</button></>:<><span>Select a deck to start building together.</span><button className="text-button" onClick={()=>{setView("library");setInspectorOpen(false);}}>Browse decks</button></>}</div>
      {activeDeckId&&<div className="goal-actions">{goals.map(g=><button key={g} onClick={()=>chooseGoal(g)}>{g}</button>)}</div>}
     </div>}/>
    </section>
    {view==="discovery"&&<LeaderDiscovery threadId={threadId} onBuild={async(id,prompt)=>{await chat.current?.openThread(id);setView("assistant");setInspectorOpen(true);setRefresh(v=>v+1);await chat.current?.ask(prompt);}}/>}
    {view==="library"&&<DeckLibrary connected={connected} activeDeckId={activeDeckId} onSelect={d=>void selectDeck(d)}/>}
   </div>
   {inspectorOpen&&<><div className="splitter" role="separator" tabIndex={0} aria-label="Resize conversation and deck" aria-orientation="vertical" aria-valuemin={35} aria-valuemax={60} aria-valuenow={Math.round(split)} onKeyDown={e=>{if(e.key==="ArrowLeft"||e.key==="ArrowRight"){e.preventDefault();resize(split+(e.key==="ArrowLeft"?2:-2));}}} onPointerDown={e=>e.currentTarget.setPointerCapture(e.pointerId)} onPointerMove={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId)&&body.current){const r=body.current.getBoundingClientRect();resize(100*(r.right-e.clientX)/r.width);}}} onPointerUp={e=>e.currentTarget.releasePointerCapture(e.pointerId)}><span/></div>
    <aside className="deck-inspector is-open" aria-label="Working deck"><div className="inspector-heading"><button title="Close deck pane" className="icon-button" aria-label="Close deck pane" onClick={()=>setInspectorOpen(false)}><Icon name="close" size={18}/></button></div>
     <DeckPanel onRemove={(id,section,all)=>removeCard(id,section,all)} onRemoveAll={(ids,section)=>removeAllCard(ids,section)} onAdd={(id,section)=>addCard(id,section)} draft={draft} threadId={threadId} loading={loading} busy={recovering} onBrowse={()=>{setView("library");setInspectorOpen(false);}}/>
    </aside></>}
  </div>
 </main>
 {goal&&<div className="goal-overlay" onClick={e=>{if(e.target===e.currentTarget)setGoal(null);}}><section role="dialog" aria-modal="true" aria-labelledby="goal-title" className="goal-dialog" onKeyDown={e=>{if(e.key==="Escape")setGoal(null);}}><button className="icon-button dialog-close" aria-label="Cancel" onClick={()=>setGoal(null)}><Icon name="close"/></button><span className="eyebrow">BUILD WITH A PURPOSE</span><h2 id="goal-title">{goal}</h2><label htmlFor="goal-detail">What should we aim for?</label><textarea autoFocus id="goal-detail" value={detail} onChange={e=>setDetail(e.target.value)} placeholder={goal==="Adjust for a matchup"?"Which leader or strategy are you facing?":"For example: smoother opening hands, keep my favorite cards, and avoid expensive upgrades."}/><p>The assistant will prepare a proposal for you to review.</p><div className="proposal-actions"><button className="secondary-button" onClick={()=>setGoal(null)}>Cancel</button><button className="primary-button" onClick={submitGoal}>{detail.trim()?"Prepare proposal":"Help me choose a goal"}</button></div></section></div>}
 </div>;
}
