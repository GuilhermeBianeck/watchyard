'use strict';
(() => {
 let current=null, timer=null, loaded='', saved=[], signature='';
 const player=$('replay-video'), dialog=$('replay-dialog');
 const formatDate=t=>new Date(t*1000).toLocaleString([],{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
 const show=(id,visible)=>$(id).classList.toggle('hidden',!visible);

 function clearPlayer(){player.pause();player.removeAttribute('src');player.removeAttribute('poster');player.load();loaded='';}
 function reset(){clearTimeout(timer);current=null;clearPlayer();$('replay-preview').removeAttribute('src');if(dialog.open)dialog.close();signature='';saved=[];$('saved-clips').replaceChildren();}

 async function refreshSaved(){
  const result=await api('/api/clips/saved');
  const next=JSON.stringify(result);saved=result;
  if(next===signature)return;signature=next;
  $('saved-usage').textContent=result.length?`${result.length} · ${Math.max(1,Math.round(result.reduce((sum,c)=>sum+c.size,0)/1024**2))} MB of 2 GB`:'';
  $('saved-clips').innerHTML=result.length?result.map(c=>`<button class="event saved-clip" data-saved-clip="${c.id}" aria-label="Watch saved ${esc(c.camera_name)} clip"><img class="event-thumb" src="/api/clips/${c.id}/poster" alt="" loading="lazy"><span class="event-info"><h3>${esc(c.camera_name)}</h3><p>${esc(title(c.label))} · ${formatDate(c.event_created)}</p><span class="delivery">${Math.round(c.duration)} seconds · kept on this server</span></span><span class="saved-play" aria-hidden="true">▶</span></button>`).join(''):'<div class="empty-state"><h3>No saved clips yet</h3><p>Open an alert, watch its replay, then choose Keep clip.</p></div>';
  document.querySelectorAll('[data-saved-clip]').forEach(b=>b.addEventListener('click',()=>open({clip:saved.find(c=>c.id===b.dataset.savedClip)})));
 }

 function render(clip){
  if(!current||!dialog.open)return;
  current.clip=clip;
  const ready=clip.state==='ready';
  const pending=['queued','preparing'].includes(clip.state);
  show('replay-progress',pending);show('download-replay',ready);show('keep-replay',ready&&admin);
  show('retry-replay',!ready&&!pending&&Boolean(current.event));
  show('replay-error',Boolean(clip.error));$('replay-error').textContent=clip.error||'';
  show('replay-warning',Boolean(clip.warning));$('replay-warning').textContent=clip.warning||'';
  $('replay-state').textContent=ready?`Ready to watch · ${Math.round(clip.duration)} seconds`:clip.waiting_for_recording?'Waiting for the recording to finish…':clip.state==='queued'?'Your replay is queued…':clip.state==='preparing'?'Preparing your replay…':'Replay unavailable';
  $('replay-state').classList.toggle('replay-ready',ready);
  $('replay-footnote').textContent=pending?'You can close this sheet and return to the alert. Preparation continues on your server.':ready?(clip.saved?'Kept in Activity → Saved clips. Video only, up to 720p.':'Temporary preview. Choose Keep clip to preserve it. Video only, up to 720p.'):'The alert snapshot remains available in Activity.';
  if(ready){
   show('replay-video',true);show('replay-preview',false);
   if(loaded!==clip.id){player.poster=`/api/clips/${clip.id}/poster`;player.src=`/api/clips/${clip.id}/video`;loaded=clip.id;}
   $('download-replay').href=`/api/clips/${clip.id}/video?download=true`;
   $('keep-replay').textContent=clip.saved?'Remove from Saved':'Keep clip';
  }
 }

 async function poll(context){
  if(current!==context||!dialog.open)return;
  try{
   const clip=await api('/api/clips/'+context.clip.id);
   if(current!==context)return;
   render(clip);
   if(['queued','preparing'].includes(clip.state))timer=setTimeout(()=>poll(context),2000);
  }catch(e){if(current===context){show('replay-progress',false);show('replay-error',true);$('replay-error').textContent=e.message;show('retry-replay',Boolean(context.event));}}
 }

 async function prepare(context){
  clearTimeout(timer);clearPlayer();show('replay-video',false);show('replay-preview',true);
  for(const id of ['replay-error','replay-warning','download-replay','keep-replay','retry-replay'])show(id,false);
  show('replay-progress',true);$('replay-state').textContent='Finding your recording…';
  try{
   const clip=await api('/api/events/'+context.event.id+'/replay',{});
   if(current!==context)return;
   render(clip);
   if(['queued','preparing'].includes(clip.state))timer=setTimeout(()=>poll(context),1500);
  }catch(e){if(current===context){show('replay-progress',false);show('replay-error',true);$('replay-error').textContent=e.message;$('replay-state').textContent='Replay unavailable';show('retry-replay',true);}}
 }

 function open(context){
  if(!context.event&&!context.clip)return;
  clearTimeout(timer);clearPlayer();current=context;
  const item=context.event||context.clip;
  const stamp=context.event?item.created:item.event_created;
  $('replay-title').textContent=item.camera_name;
  $('replay-caption').textContent=`${title(item.label)} alert · ${formatDate(stamp)}`;
  $('replay-preview').src=context.event?'/api/events/'+item.snapshot:`/api/clips/${item.id}/poster`;
  $('replay-footnote').textContent='You can close this sheet while the replay prepares.';
  if(!dialog.open)dialog.showModal();
  if(context.clip){render(context.clip);}else prepare(context);
 }

 $('event-replay').addEventListener('click',()=>{
  const event=events.find(e=>e.id===activeEvent);
  if(!event)return;
  $('image-dialog').close();open({event});
 });
 $('close-replay').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('close',()=>{clearTimeout(timer);current=null;clearPlayer();});
 $('retry-replay').addEventListener('click',()=>{if(current?.event)prepare(current);});
 $('keep-replay').addEventListener('click',async()=>{
  if(!current?.clip||!admin)return;
  const context=current;const button=$('keep-replay');button.disabled=true;
  try{
   const clip=await api('/api/clips/'+context.clip.id+'/keep',{saved:!context.clip.saved});
   if(current===context)render(clip);
   notice(clip.saved?'Clip kept in Saved clips':'Removed from Saved. It is now a temporary preview.');
   await refreshSaved();
  }catch(e){notice(e.message);}finally{button.disabled=false;}
 });
 player.addEventListener('error',()=>{if(current&&loaded){show('replay-error',true);$('replay-error').textContent='The video could not load. Try again or download the clip.';show('retry-replay',Boolean(current.event));}});
 window.WatchyardReplay={refreshSaved,reset,openEvent(id){
  const event=events.find(e=>e.id===id);
  if(event)open({event});else notice('This alert is no longer in history. Check Saved clips in Activity.');
 }};
})();
