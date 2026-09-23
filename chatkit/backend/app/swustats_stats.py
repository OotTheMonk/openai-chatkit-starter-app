"""Read-only, cached aggregate evidence. Never retrieves or copies public decklists."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import math
import time
import httpx
from .catalog import catalog
from .swu import SWU_HEADERS

ROOT='https://www.swustats.net/TCGEngine/'
SOURCE=ROOT+'Stats/APIs.php'
_cache={}
_lock=asyncio.Lock()

def api_card_key(card):
    """The live matchup API uses SET_NNN keys, unlike its UID examples."""
    from .discovery import SETS
    printings=sorted((p for p in card.get('printings',[]) if p.get('set') in SETS),key=lambda p:SETS[p['set']][2])
    return printings[0]['set']+'_'+str(printings[0]['number']).zfill(3) if printings else str(card.get('id',''))

def window_params(format,start_week=None,end_week=None):
    if format.lower() not in {'premier','eternal'}:raise ValueError('Choose Premier or Eternal.')
    if any(v is not None and (isinstance(v,bool) or not isinstance(v,int) or v<0) for v in [start_week,end_week]):raise ValueError('Week IDs must be nonnegative integers.')
    if start_week is not None and end_week is not None and start_week>end_week:raise ValueError('Start week must not exceed end week.')
    p={'format':format.lower()}
    if start_week is not None:p['startWeek']=start_week
    if end_week is not None:p['endWeek']=end_week
    return p

async def request(path,params):
    key=(path,tuple(sorted(params.items())))
    async with _lock:
        cached=_cache.get(key)
        if cached and time.monotonic()-cached[0]<1800:return deepcopy(cached[1])
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=SWU_HEADERS) as client:
                response=await client.get(ROOT+path,params=params)
                response.raise_for_status();data=response.json()
            if not isinstance(data,(dict,list)):raise ValueError('Unexpected statistics response')
            if isinstance(data,dict) and (data.get('error') or data.get('success') is False):raise ValueError('Statistics unavailable')
            result={'data':data,'retrieved_at':datetime.now(timezone.utc).isoformat(),'error':None}
            _cache[key]=(time.monotonic(),result)
        except (httpx.HTTPError,ValueError):
            result={'data':None,'retrieved_at':None,'error':'SWUStats statistics are temporarily unavailable. No performance inference can be made.'}
            # Back off on failures as well; do not silently reuse stale evidence.
            _cache[key]=(time.monotonic()-1740,result)
        if len(_cache)>100:_cache.pop(next(iter(_cache)))
        return deepcopy(result)

def number(value):
    if value is None or isinstance(value,bool):return None
    try:
        n=float(value)
        return n if math.isfinite(n) and n>=0 else None
    except (ValueError,TypeError):return None

def percentage(value):
    n=number(value)
    return n if n is not None and n<=100 else None

def rate(wins,plays):
    a,b=number(wins),number(plays)
    return round(100*a/b,2) if a is not None and b and a<=b else None

def normalize_card(row):
    cid=row.get('cardUid') or row.get('cardId')
    if not cid:return None
    included=number(row.get('timesIncluded'));played=number(row.get('timesPlayed'));resourced=number(row.get('timesResourced'))
    return {'id':str(cid),'name':row.get('cardName') or row.get('name') or str(cid),
        'included':included,'played':played,'resourced':resourced,
        'win_rate_when_included':rate(row.get('timesIncludedInWins'),included) if 'timesIncludedInWins' in row else percentage(row.get('percentIncludedInWins')) if included else None,
        'win_rate_when_played':(rate(row.get('timesPlayedInWins'),played) if 'timesPlayedInWins' in row else percentage(row.get('winRateWhenPlayed',row.get('percentPlayedInWins')))) if played else None,
        'play_rate':rate(played,included),'resource_rate':rate(resourced,included),
        'sample_label':'Unknown sample' if included is None else 'No observations' if included==0 else 'Limited observations' if included<100 else 'Observed usage'}

async def card_evidence(ids,format,start_week=None,end_week=None):
    params=window_params(format,start_week,end_week)
    response=await request('Stats/CardMetaStatsAPI.php',params)
    data=response['data'];rows=data if isinstance(data,list) else [data] if isinstance(data,dict) else []
    wanted=set(ids);found={}
    for row in rows:
        if not isinstance(row,dict):continue
        c=normalize_card(row)
        if c and c['id'] in wanted:found[c['id']]=c
    return {**{k:v for k,v in response.items() if k!='data'},'cards':[found[i] for i in ids if i in found],'missing_ids':[i for i in ids if i not in found],
        'scope':'Format-wide card observations across all leaders and decks, not this leader or your proposed list. Inclusion counts are observations, not unique deck counts. Win rate when played is conditional and selection-biased, not the effect of adding this card.'}

async def matchup_evidence(leader_id,base_id,format,start_week=None,end_week=None):
    params={**window_params(format,start_week,end_week),'leaderID':leader_id,'baseID':base_id}
    response=await request('APIs/DeckMetaMatchupStatsAPI.php',params)
    rows=response['data'] if isinstance(response['data'],list) else []
    matchups=[]
    for row in rows:
        if not isinstance(row,dict) or not row.get('opponentLeaderID') or not row.get('opponentBaseID'):continue
        # Reject rows for a different own identity if the provider includes it.
        if row.get('leaderID',leader_id)!=leader_id or row.get('baseID',base_id)!=base_id:continue
        n=number(row.get('numPlays'));w=number(row.get('numWins'))
        if not n or w is None or w>n:continue
        matchups.append({'opponent_leader_id':str(row['opponentLeaderID']),'opponent_base_id':str(row['opponentBaseID']),'games':n,'wins':w,'win_rate':rate(w,n),'limited_sample':n<30})
    matchups.sort(key=lambda r:-r['games'])
    return {**{k:v for k,v in response.items() if k!='data'},'matchups':matchups[:12],
        'scope':'Exact leader/base aggregate across different lists and pilots. Opponents ordered by observed games; this is not a forecast for your experimental build.'}

async def evidence(deck,format,ids=None,start_week=None,end_week=None):
    window_params(format,start_week,end_week)
    ids=list(dict.fromkeys(ids or [str(c['id']) for c in deck.get('deck',[])]))[:80]
    metadata=await catalog()
    leader=deck.get('leader',{});base=deck.get('base',{})
    leader=metadata.get(str(leader.get('id')),leader);base=metadata.get(str(base.get('id')),base)
    matchup,cards=await asyncio.gather(matchup_evidence(api_card_key(leader),api_card_key(base),format,start_week,end_week),card_evidence(ids,format,start_week,end_week))
    names={c['id']:c['name'] for c in metadata.values()}
    for c in metadata.values():
        for p in c.get('printings',[]):names[p['set']+'_'+str(p['number']).zfill(3)]=c['name']
    for row in matchup['matchups']:
        row['opponent_leader']=names.get(row['opponent_leader_id'],'Unknown leader')
        row['opponent_base']=names.get(row['opponent_base_id'],row['opponent_base_id'].title()+' base (type unspecified)')
    window='All-time; may span different sets, rotations and balance changes.' if start_week is None and end_week is None else f'API weeks {start_week if start_week is not None else 0}–{end_week if end_week is not None else "latest"}; calendar mapping unverified.'
    return {'kind':'aggregate_statistics','source':'SWUStats','source_url':SOURCE,'format':format,'window':window,'start_week':start_week,'end_week':end_week,
        'retrieved_at':cards['retrieved_at'] or matchup['retrieved_at'],'card_statistics':cards['cards'],'missing_card_ids':cards['missing_ids'],'matchups':matchup['matchups'],
        'notices':[n for n in [cards['error'],matchup['error'],None if matchup['matchups'] else 'No matchup observations available for this exact leader/base and window. This is not evidence the deck is bad.'] if n],
        'scope':cards['scope']+' '+matchup['scope'],
        'design_policy':'Start from the player’s desired experience and a rules-grounded synergy hypothesis. Statistics suggest risks to test, not mandatory cards. Low usage is not a reason to reject a novel idea. No public decklists are fetched.'}
