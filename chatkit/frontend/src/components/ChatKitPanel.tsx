import { forwardRef, useImperativeHandle, useState, useRef, useEffect, useMemo, type ReactNode } from "react";
import { CHATKIT_API_URL } from "../lib/config";
import { swuCardImage } from "../lib/deck";
import { Icon } from "./Icon";
export interface ChatHandle { openThread:(id:string)=>Promise<void>; ask:(text:string)=>Promise<void>; newChat:()=>Promise<void>; history:()=>Promise<void>; selectDeck:(id:number,name:string,hasThread:boolean)=>Promise<void> }
interface Action {type:string;payload?:Record<string,unknown>}
interface Widget {type:string;value?:string;label?:string;children?:Widget[];onClickAction?:Action;id?:string;image?:string;name?:string}
interface ToolTask {type?:string;title?:string|null;content?:string|null;status_indicator?:string}

interface Item {id:string;type:string;content?:{text?:string}[];widget?:Widget;workflow?:{tasks?:ToolTask[]}}
interface ModelOption {id:string;label?:string;provider?:string;hint?:string;available?:boolean}
const DEFAULT_MODELS:ModelOption[]=[{id:"gpt-4o",label:"GPT-4o",provider:"openai",available:true},{id:"gpt-4o-mini",label:"GPT-4o Mini",provider:"openai",available:true}];
const storedModel=()=>{try{return localStorage.getItem("builder-model")||"gpt-4o";}catch{return "gpt-4o";}};
interface Event {type:string;thread?:{id:string};item?:Item;item_id?:string;update?:{type:string;delta?:string;task?:ToolTask;task_index?:number};name?:string;data?:Record<string,unknown>;message?:string}
const base=CHATKIT_API_URL.replace(/\/chatkit\/?$/,"");
function Text({text}:{text:string}) {
 return <>{text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)]+\))/g).map((part,i)=>{
   if(part.startsWith("**")&&part.endsWith("**"))return <strong key={i}>{part.slice(2,-2)}</strong>;
   const link=/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/.exec(part);
   return link?<a key={i} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>:part;
 })}</>;
}
function WidgetView({node,activeDeckId,act,disabled}:{node:Widget;activeDeckId:number|null;act:(a:Action)=>void;disabled:boolean}) {
 if(node.type==="CardImage"){
  const name=typeof node.name==="string"&&node.name?node.name:(node.label||"Card");
  const art=typeof node.id==="string"&&node.id?swuCardImage(node.id):(typeof node.image==="string"&&node.image?node.image:null);
  if(!art)return <span className="hover-chip">{name}</span>;
  const full=typeof node.id==="string"&&node.id?swuCardImage(node.id,true):(typeof node.image==="string"&&node.image?node.image:undefined);
  return <HoverThumb name={name} image={art} full={full}/>;
 }
 if(node.type==="Button"){
  const active=node.onClickAction?.type==="select_deck"&&node.onClickAction.payload?.deck_id===activeDeckId;
  return <button className={active?"widget-active":"secondary-button"} disabled={disabled||active} onClick={()=>node.onClickAction&&act(node.onClickAction)}>{active?"Active":node.onClickAction?.type==="select_deck"?"Open deck":node.label}</button>;
 }
 if(node.value){if(node.value.startsWith("Active:"))return null;return <span className="widget-text"><Text text={node.value}/></span>;}
 return <div className={"native-widget-"+node.type.toLowerCase()}>{node.children?.map((n,i)=><WidgetView key={i} node={n} activeDeckId={activeDeckId} act={act} disabled={disabled}/>)}</div>;
}
function HoverThumb({name,image,full}:{name:string;image:string;full?:string}) {
 const [failed,setFailed]=useState(false),[fullOk,setFullOk]=useState(true);
 if(failed)return <span className="hover-chip">{name}</span>;
 const big=full||image;
 return <span className="hover-thumb"><img src={image} alt={name} title={name} loading="lazy" onError={()=>setFailed(true)}/><span className="hover-name">{name}</span>{fullOk&&<span className="hover-full"><img src={big} alt={name} loading="lazy" onError={()=>setFullOk(false)}/></span>}</span>;
}
const cardArt=(id:unknown)=>typeof id==="string"&&id?swuCardImage(id):null;
const dedupeIds=(list:Item[])=>{const seen=new Map<string,number>();return list.map(it=>{const n=seen.get(it.id)??0;seen.set(it.id,n+1);return n?{...it,id:it.id+"#"+n}:it;});};
function HoverContent({text}:{text:string}) {
 const data=useMemo(()=>{
  try{
   const parsed:unknown=JSON.parse(text);
   if(Array.isArray(parsed))return {query:null as string|null,count:parsed.length,cards:parsed as unknown[]};
   if(parsed&&typeof parsed==="object"&&Array.isArray((parsed as {cards?:unknown}).cards)){
    const p=parsed as {query?:unknown;count?:unknown;cards?:unknown[]};
    return {query:typeof p.query==="string"?p.query:null,count:typeof p.count==="number"?p.count:(p.cards as unknown[]).length,cards:p.cards as unknown[]};
   }
  }catch{/* not card JSON; show raw text */}
  return null;
 },[text]);
 if(!data)return <span className="tool-hover">{text}</span>;
 const cards=(data.cards as {name?:unknown;image?:unknown;id?:unknown;card_id?:unknown;cardID?:unknown}[]).filter(c=>c&&typeof c==="object");
 const shown=cards.slice(0,10);
 return <span className="tool-hover rich"><span className="hover-query">{data.query||`${data.count} card${data.count===1?"":"s"}`}{data.query?` (${data.count})`:""}</span><span className="hover-grid">{shown.map((c,i)=>{
  const art=typeof c.image==="string"&&c.image?c.image:cardArt(c.id??c.card_id??c.cardID);
  const name=typeof c.name==="string"&&c.name?c.name:"Card";
  return art?<HoverThumb key={i} name={name} image={art}/>:<span key={i} className="hover-chip">{name}</span>;
 })}</span>{cards.length>shown.length&&<span className="hover-more">+{cards.length-shown.length} more</span>}</span>;
}
function ActivitySection({id,tasks,open,onToggle}:{id:string;tasks:ToolTask[];open:boolean;onToggle:(id:string,expand:boolean)=>void}) {
 if(!tasks.length)return null;
 const working=tasks.some(t=>t.status_indicator==="loading");
 const failed=tasks.some(t=>(t.content||"").indexOf("Failed: ")===0);
 const status=working?"working":failed?"failed":"done";
 const label=working?"Working":failed?"Finished with errors":"Done";
 return <details className={"tool-activity is-"+status} open={open} onToggle={e=>onToggle(id,e.currentTarget.open)}><summary><span className="tool-dot" aria-hidden="true"/><span className="tool-title">{tasks.length} tool call{tasks.length===1?"":"s"}</span><span className="tool-status">{label}</span></summary><div className="tool-cards">{tasks.map((t,i)=>{
  const failed=(t.content||"").indexOf("Failed: ")===0;
  const st=t.status_indicator==="loading"?"working":failed?"failed":"done";
  const lb=t.status_indicator==="loading"?"Working":failed?"Failed":"Done";
  return <div key={i} className={"tool-card is-"+st}><span className="tool-dot" aria-hidden="true"/><span className="tool-title">{t.title||"Request"}</span><span className="tool-status">{lb}</span>{t.content&&<HoverContent text={t.content}/>}</div>;
 })}</div></details>;
}
export const ChatKitPanel=forwardRef<ChatHandle,{onThreadChange:(id:string|null)=>void;onEffect:(event:{name:string;data?:Record<string,unknown>})=>void;context:ReactNode;activeDeckId:number|null}>(({onThreadChange,onEffect,context,activeDeckId},ref)=>{
 const current=useRef<string|null>(localStorage.getItem("builder-thread"));
 const [items,setItems]=useState<Item[]>([]),[input,setInput]=useState(""),[error,setError]=useState(""),[busy,setBusy]=useState(false),[streamText,setStreamText]=useState(""),[history,setHistory]=useState<{id:string;title:string}[]|null>(null),[folded,setFolded]=useState<Record<string,boolean>>({}),[models,setModels]=useState<ModelOption[]>(DEFAULT_MODELS),[modelId,setModelId]=useState<string>(storedModel);
 const locked=useRef(false),end=useRef<HTMLDivElement>(null),scroll=useRef<HTMLDivElement>(null),follow=useRef(true),mounted=useRef(true),requestController=useRef<AbortController|null>(null),epoch=useRef(0);
 const abortWork=()=>{epoch.current++;requestController.current?.abort();requestController.current=null;locked.current=false;setBusy(false);setStreamText("");};
 const setThread=(id:string|null)=>{current.current=id;if(id)localStorage.setItem("builder-thread",id);else localStorage.removeItem("builder-thread");setFolded({});onThreadChange(id);};
 async function load(id:string){const r=await fetch(base+"/api/conversations/"+encodeURIComponent(id));if(!r.ok)throw Error("Conversation couldn't be loaded.");const data=await r.json() as Item[];if(current.current===id){setItems(dedupeIds(data));}}
 useEffect(()=>{mounted.current=true;if(current.current)void load(current.current).catch((e:unknown)=>setError(e instanceof Error?e.message:"Unable to load conversation."));void fetch(base+"/api/models").then(r=>{if(!r.ok)throw Error("models");return r.json();}).then(d=>{if(!mounted.current)return;const m=d as {models?:unknown;active?:unknown};if(Array.isArray(m.models))setModels(m.models.filter(x=>typeof x==="object"&&x!==null) as ModelOption[]);if(typeof m.active==="string")setModelId(m.active);}).catch(()=>{});return()=>{mounted.current=false;requestController.current?.abort();};},[]);
 useEffect(()=>{if(follow.current)end.current?.scrollIntoView({block:"end"});},[items,streamText,busy]);
 async function send(type:string,params:Record<string,unknown>,quiet?:boolean){
  if(locked.current)throw Error("Wait for the current response to finish.");
  locked.current=true;const my=quiet?epoch.current:++epoch.current;if(!quiet){setBusy(true);setError("");setStreamText("");}follow.current=true;
  const controller=new AbortController();requestController.current=controller;
  try{
   const r=await fetch(CHATKIT_API_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({type,params}),signal:controller.signal});
   if(!r.ok||!r.body)throw Error("The assistant couldn't respond. Please retry.");
   const reader=r.body.getReader(),decoder=new TextDecoder();let buffer="";
   const event=(frame:string)=>{
    if(my!==epoch.current)return;
    const data=frame.split("\n").filter(l=>l.startsWith("data:")).map(l=>l.slice(5).trim()).join("\n");if(!data||data==="[DONE]")return;
    const e=JSON.parse(data) as Event;
    if(e.type==="thread.created"&&e.thread)setThread(e.thread.id);
    if(e.type==="client_effect"&&e.name){
      if(e.name==="models_list"||e.name==="model_changed"){
        const d=e.data as {active?:unknown;models?:unknown;error?:unknown};
        if(Array.isArray(d.models))setModels(d.models.filter(m=>typeof m==="object"&&m!==null) as ModelOption[]);
        if(typeof d.active==="string"){setModelId(d.active);try{localStorage.setItem("builder-model",d.active);}catch{/* storage unavailable */}}
        if(typeof d.error==="string")setError(d.error);
      }
      else onEffect({name:e.name,data:e.data});
    }
    if(e.type==="error")throw Error(e.message||"The assistant couldn't finish. Please retry.");
    if(e.item&&e.item.type!=="workflow"&&(e.type==="thread.item.done"||(e.type==="thread.item.added"&&e.item.type==="user_message"))){
      const item=e.item;setItems(old=>old.some(v=>v.id===item.id)?old.map(v=>v.id===item.id?item:v):[...old,item]);if(item.type==="assistant_message")setStreamText("");
    }
    if(e.item&&(e.type==="thread.item.added"||e.type==="thread.item.done")&&e.item.type==="workflow"&&e.item.workflow){const item=e.item;setItems(old=>old.some(v=>v.id===item.id)?old.map(v=>v.id===item.id?item:v):[...old,item]);}
    if(e.type==="thread.item.updated"&&e.item_id&&e.update&&e.update.task){const task=e.update.task,idx=e.update.task_index;setItems(old=>old.map(v=>{if(v.id!==e.item_id||v.type!=="workflow"||!v.workflow)return v;const tasks=[...(v.workflow.tasks||[])];if(typeof idx==="number")tasks[idx]=task;else tasks.push(task);return {...v,workflow:{...v.workflow,tasks}};}));}
    if(e.type==="thread.item.updated"&&e.update?.type==="assistant_message.content_part.text_delta")setStreamText(old=>old+(e.update?.delta||""));
   };
   while(true){const {done,value}=await reader.read();buffer+=decoder.decode(value,{stream:!done}).replace(/\r\n/g,"\n");let index;while((index=buffer.indexOf("\n\n"))!==-1){event(buffer.slice(0,index));buffer=buffer.slice(index+2);}if(done)break;}
   if(buffer.trim())event(buffer);
   if(current.current)await load(current.current);
  }catch(e){if(my!==epoch.current)return;const message=e instanceof Error?e.message:"Something went wrong.";if(mounted.current&&!quiet)setError(message);throw e;}
  finally{if(my===epoch.current){locked.current=false;if(mounted.current&&!quiet){setBusy(false);setStreamText("");}requestController.current=null;}}
 }
 async function ask(text:string){setHistory(null);const params={input:{content:[{type:"input_text",text}],attachments:[],inference_options:{}}};await send(current.current?"threads.add_user_message":"threads.create",current.current?{...params,thread_id:current.current}:params);}
 const modelAction=(type:string,payload?:Record<string,unknown>)=>{if(current.current&&!locked.current&&mounted.current)void send("threads.custom_action",{thread_id:current.current,action:{type,payload}},true).catch(()=>{});};
 const pullModels=()=>modelAction("get_models");
 const pushModel=(id:string)=>modelAction("select_model",{model_id:id});
 const chooseModel=(id:string)=>{setModelId(id);try{localStorage.setItem("builder-model",id);}catch{/* storage unavailable */}pushModel(id);};
 async function selectDeck(id:number){
  if(locked.current)throw Error("Wait for the current response to finish.");
  locked.current=true;const my=epoch.current;setBusy(true);setError("");setHistory(null);
  try{const r=await fetch(base+"/api/workspace/select",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({thread_id:current.current,deck_id:id})});const d=await r.json() as {thread_id:string;error?:string};if(!r.ok)throw Error(d.error||"Deck couldn't be loaded.");if(my!==epoch.current)return;setThread(d.thread_id);await load(d.thread_id);onEffect({name:"deck_refresh",data:{deck_id:id}});}
  catch(e){if(my!==epoch.current)return;setError(e instanceof Error?e.message:"Deck couldn't be loaded.");throw e;}
  finally{if(my===epoch.current){locked.current=false;setBusy(false);}}
 }
 async function showHistory(){if(locked.current)throw Error("Wait for the current response to finish.");const my=epoch.current;const r=await fetch(base+"/api/conversations");if(!r.ok)throw Error("History couldn't be loaded.");if(my!==epoch.current)return;setHistory(await r.json() as {id:string;title:string}[]);}
 useImperativeHandle(ref,()=>({openThread:async(id:string)=>{abortWork();setThread(id);setItems([]);setError("");setHistory(null);await load(id);pullModels();},ask,selectDeck,history:showHistory,newChat:()=>{abortWork();setThread(null);setItems([]);setError("");setHistory(null);setInput("");return Promise.resolve();}}));
 const action=(a:Action)=>{if(a.type==="view_library"){onEffect({name:"view_library"});return;}if(a.type==="select_deck"){void selectDeck(Number(a.payload?.deck_id)).catch(()=>{});return;}if(current.current)void send("threads.custom_action",{thread_id:current.current,action:a}).catch(()=>{});};
 const submit=()=>{const text=input.trim();if(!text||busy)return;setInput("");void ask(text).catch(()=>setInput(text));};
 const renderItem=(item:Item,ix:number)=>{
  if(item.type!=="user_message"&&item.type!=="workflow"&&!item.widget&&!(item.content||[]).some(c=>c.text&&c.text.trim()))return null;
  if(item.type==="workflow"&&item.workflow&&(item.workflow.tasks||[]).length)return <ActivitySection key={item.id} id={item.id} tasks={item.workflow.tasks||[]} open={folded[item.id]??!items.slice(ix+1).some(later=>later.type==="assistant_message"||later.type==="widget"||later.type==="user_message")} onToggle={(id,expand)=>setFolded(f=>f[id]===expand?f:{...f,[id]:expand})}/>;
  return ["user_message","assistant_message","widget"].includes(item.type)?<article key={item.id} className={"chat-message "+(item.type==="user_message"?"from-user":"from-assistant")} aria-label={item.type==="user_message"?"Your message":"Assistant response"}>{item.type!=="user_message"&&<span className="message-author">DECK ASSISTANT</span>}{item.content?.filter(c=>c.text&&c.text.trim()).map((c,i)=><p key={i}><Text text={c.text||""}/></p>)}{item.widget&&<WidgetView node={item.widget} activeDeckId={activeDeckId} act={action} disabled={busy}/>}</article>:null;
 };
 const renderGroups=()=>{
  const nodes:ReactNode[]=[];let i=0;
  while(i<items.length){
   const item=items[i];
   if(item.type==="workflow"&&item.workflow&&(item.workflow.tasks||[]).length){
    const run=[item.id],tasks=[...(item.workflow.tasks||[])];let j=i+1;
    while(j<items.length&&items[j].type==="workflow"&&items[j].workflow&&(items[j].workflow.tasks||[]).length){run.push(items[j].id);tasks.push(...(items[j].workflow?.tasks||[]));j++;}
    if(run.length>1)nodes.push(<ActivitySection key={run.join("+")} id={run[0]} tasks={tasks} open={folded[run[0]]??!items.slice(j).some(later=>later.type==="assistant_message"||later.type==="widget"||later.type==="user_message")} onToggle={(id,expand)=>setFolded(f=>f[id]===expand?f:{...f,[id]:expand})}/>);
    else nodes.push(renderItem(item,i));
    i=j;
   }else{nodes.push(renderItem(item,i));i++;}
  }
  return nodes;
 };
 return <div className="native-chat">
  {error&&<div className="notice" role="alert">{error}<button aria-label="Dismiss error" onClick={()=>setError("")}>×</button></div>}
  <div className="chat-transcript" ref={scroll} onScroll={()=>{const el=scroll.current;if(el)follow.current=el.scrollHeight-el.scrollTop-el.clientHeight<100;}} aria-label="Conversation messages">
   {history?<section className="conversation-history"><h2>Conversations</h2><button className="text-button" onClick={()=>setHistory(null)}>Back to conversation</button>{history.length?history.map(t=><button key={t.id} onClick={()=>{setThread(t.id);setHistory(null);setItems([]);void load(t.id).catch(()=>setError("Conversation couldn't be loaded."));pullModels();}}>{t.title}<Icon name="arrow" size={16}/></button>):<p>No conversations yet.</p>}</section>:<>
    {!items.length&&!busy&&<section className="chat-welcome"><span className="eyebrow">YOUR DECK. YOUR NEXT MOVE.</span><h2>{activeDeckId?"What should we improve?":"Build something worth playing."}</h2><p>{activeDeckId?"Set a goal below. I'll prepare changes with reasons for you to review.":"Choose a saved deck, then work with the assistant on a plan."}</p>{!activeDeckId&&<button className="primary-button" onClick={()=>onEffect({name:"view_library"})}>Choose a deck <Icon name="arrow" size={16}/></button>}</section>}
    {renderGroups()}
    {streamText&&<article className="chat-message from-assistant"><span className="message-author">DECK ASSISTANT</span><p><Text text={streamText}/></p></article>}
    {busy&&<p role="status" className="thinking-status">Working on it…</p>}
   </>}<div ref={end}/>
  </div>
  <div className="composer-region">{context}<div className="model-picker"><label htmlFor="model-select">Model</label><select id="model-select" value={modelId} disabled={busy} onChange={e=>chooseModel(e.target.value)}>{models.map(m=><option key={m.id} value={m.id} disabled={m.available===false} title={m.hint}>{m.label||m.id}{m.available===false?" (needs key)":""}</option>)}</select></div><form className="native-composer" onSubmit={e=>{e.preventDefault();submit();}}><label className="sr-only" htmlFor="deck-message">Message your deck assistant</label><textarea id="deck-message" rows={2} value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();submit();}}} placeholder="Describe a goal, a matchup, or a change to try…"/><button className="primary-button" type="submit" disabled={busy||!input.trim()} aria-label="Send message"><Icon name="arrow" size={19}/></button></form></div>
 </div>;
});
ChatKitPanel.displayName="ChatKitPanel";
