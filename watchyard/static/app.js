'use strict';
const $ = id => document.getElementById(id);
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const esc = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const title = s => ({person:'Person',car:'Vehicle',dog:'Dog',cat:'Cat'}[s]||s);
const delivery = s => ({sent:'Alert delivered',grouped:'Added to existing alert',pending:'Waiting to send',muted:'Saved quietly',recorded:'Local history',unpaired:'Saved on server',partial:'Partly delivered',expired:'Saved on server'}[s]||s);
let diagnostics=null,policyCamera=null,activeEvent=null,admin=true,deviceInfo=null,deviceSignature='';
let linkedEvent=location.hash.startsWith('#event=')?location.hash.slice(7):null;
let state=null,events=[],signedIn=false,localDevice=false,currentView='home',filter='all',activeCamera=null,editing=null,points=[],zoneImage=new Image(),tick=0,toastTimer,busy=false,eventSignature='', cameraFilter='';
const scrollPositions={home:0,activity:0,settings:0};
function notice(message){$('notice').textContent=message;$('notice').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('notice').classList.add('hidden'),6000);}
function showLogin(){signedIn=false;window.WatchyardReplay?.reset();window.WatchyardLive?.reset();$('app-shell').classList.add('hidden');$('login-screen').classList.remove('hidden');document.querySelectorAll('dialog[open]').forEach(d=>d.close());document.querySelectorAll('.camera-picture img').forEach(i=>i.removeAttribute('src'));}
async function api(path,data,{signal}={}){const response=await fetch(path,data===undefined?{cache:'no-store',signal}:{method:'POST',headers:{'Content-Type':'application/json','X-Watchyard-Client':'dashboard'},body:JSON.stringify(data)});if(!response.ok){if(response.status===401&&path!=='/api/login')showLogin();const r=await response.json().catch(()=>({detail:'Cannot connect to Watchyard'}));throw Error(typeof r.detail==='string'?r.detail:'Check the values and try again');}return response.json();}
async function action(path,data,message){try{await api(path,data);if(message)notice(message);await refresh();}catch(e){notice(e.message);}}
function navigate(view,writeHash=true){if(view.startsWith('join='))view='home';if(view.startsWith('event='))view='activity';if(view.startsWith('group=')){view='activity';writeHash=false;}if(!['home','activity','settings'].includes(view))view='home';scrollPositions[currentView]=window.scrollY;currentView=view;document.querySelectorAll('.view').forEach(v=>v.classList.toggle('hidden',v.id!=='view-'+view));document.querySelectorAll('[data-nav]').forEach(b=>{if(b.dataset.nav===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});if(writeHash&&location.hash!=='#'+view)history.replaceState(null,'','#'+view);window.scrollTo(0,scrollPositions[view]||0);document.title=({home:'Cameras',activity:'Activity',settings:'Settings'}[view])+' | Watchyard';if(state){renderCameras();renderEvents(true);}document.dispatchEvent(new Event('watchyard:navigate'));}
function emptyState(message) {
  return `<div class="empty-state"><p>${esc(message)}</p></div>`;
}

function eventMarkup(event, compact = false) {
  const date = new Date(event.created * 1000);
  const time = date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  const stamp = compact ? date.toLocaleDateString([], {day: 'numeric', month: 'short'}) + ' ' + time : time;
  const name = title(event.label);
  return `<div class="event-row">
    <button class="event" data-event="${event.id}" aria-label="View ${esc(name)} at ${esc(event.camera_name)}">
      <img class="event-thumb" src="/api/events/${event.snapshot}" alt="" loading="lazy">
      <span class="event-info"><strong>${esc(name)}</strong><small>${esc(event.camera_name)}${event.plate ? ' · ' + esc(event.vehicle_name || event.plate) : ''}</small></span>
      <time class="event-time" datetime="${date.toISOString()}">${esc(stamp)}</time>
    </button>
    <button class="event-play" data-replay="${event.id}" aria-label="Watch ${esc(name)} replay at ${esc(event.camera_name)}">${icon('play')}</button>
  </div>`;
}

function renderEvents(force = false) {
  const signature = JSON.stringify([filter, cameraFilter, events.map(e => [e.id, e.status, e.feedback, e.plate, e.vehicle_name])]);
  if (!force && signature === eventSignature) return;
  eventSignature = signature;
  $('latest-events').innerHTML = events.length
    ? events.slice(0, 5).map(event => eventMarkup(event, true)).join('')
    : emptyState('No detections recorded yet.');
  const selected = events.filter(e =>
    (!cameraFilter || String(e.camera) === cameraFilter) &&
    (filter === 'all' || e.label === filter || (filter === 'pets' && ['dog', 'cat'].includes(e.label))));
  const groups = new Map();
  for (const event of selected) {
    const day = new Date(event.created * 1000).toLocaleDateString([], {weekday: 'long', day: 'numeric', month: 'short', year: 'numeric'});
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(event);
  }
  $('events').innerHTML = groups.size ? [...groups].map(([day, items]) =>
    `<h2 class="day-heading">${esc(day)}</h2><div class="grouped-list">${items.map(event => eventMarkup(event)).join('')}</div>`
  ).join('') : emptyState('No events match these filters.');
}

function handleEventClick(event) {
  const play = event.target.closest('[data-replay]');
  if (play) {
    window.WatchyardReplay.openEvent(play.dataset.replay);
    return;
  }
  const button = event.target.closest('[data-event]');
  const item = button && events.find(e => e.id === button.dataset.event);
  if (!item) return;
  activeEvent = item.id;
  $('event-image').src = '/api/events/' + item.snapshot;
  $('event-caption').textContent = `${title(item.label)} at ${item.camera_name}, ${new Date(item.created * 1000).toLocaleString()}. ${delivery(item.status)}.${item.plate ? ` Plate: ${item.plate}${item.vehicle_name ? ` (${item.vehicle_name})` : ''}.` : ''}`;
  renderReview(item);
  $('image-dialog').showModal();
}

for (const id of ['events', 'latest-events']) $(id).addEventListener('click', handleEventClick);

function cameraDetail(camera) {
  if (!camera.online) return 'Camera offline';
  if (!camera.enabled) return 'Detection paused';
  if (camera.detections.length) {
    return [...new Set(camera.detections.map(d => title(d.label)))].join(', ') + ' in view';
  }
  return '';
}

function renderCameras() {
  const grid = $('camera-grid');
  if (!grid.children.length) {
    const options = state.cameras.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
    $('camera-switch').innerHTML = options;
    $('activity-camera').insertAdjacentHTML('beforeend', options);
    grid.innerHTML = state.cameras.map(c => `<article class="camera">
      <button class="camera-picture" data-camera="${c.id}" aria-label="Open ${esc(c.name)} camera">
        <span id="placeholder-${c.id}" class="preview-placeholder">Connecting to camera</span>
        <img id="camera-${c.id}" alt="">
        <span class="preview-badge"><span class="dot"></span><span id="badge-${c.id}">Preview</span></span>
        <span class="expand-icon">${icon('expand')}</span>
      </button>
      <div class="camera-bottom"><div><h3>${esc(c.name)}</h3><p id="detail-${c.id}" hidden></p></div>
        <button class="camera-settings" data-zone="${c.id}" aria-label="Edit ${esc(c.name)} alert area">${icon('settings')}</button>
      </div>
    </article>`).join('');
    grid.querySelectorAll('button[data-camera]').forEach(button =>
      button.addEventListener('click', () => openCamera(Number(button.dataset.camera))));
    grid.querySelectorAll('[data-zone]').forEach(button =>
      button.addEventListener('click', () => openZone(Number(button.dataset.zone))));
  }
  for (const camera of state.cameras) {
    const detail = $('detail-' + camera.id);
    detail.textContent = cameraDetail(camera);
    detail.hidden = !detail.textContent;
    $('badge-' + camera.id).textContent = camera.online ? (window.WatchyardLive?.label(camera.id) || 'Preview') : 'Offline';
    $('placeholder-' + camera.id).textContent = camera.online ? 'Loading preview' : 'Camera offline';
    const image = $('camera-' + camera.id);
    if (!camera.online) {
      image.classList.add('unavailable');
    } else if (currentView === 'home' && !window.WatchyardLive?.playing(camera.id)) {
      image.onerror = () => image.classList.add('unavailable');
      image.onload = () => {
        if (state.cameras.find(c => c.id === camera.id)?.online) image.classList.remove('unavailable');
      };
      image.src = `/api/cameras/${camera.id}/snapshot?t=${tick}`;
    }
  }
  if (activeCamera && $('camera-dialog').open) updateExpanded();
  window.WatchyardLive?.sync();
}

function openCamera(id) {
  activeCamera = id;
  updateExpanded();
  $('camera-dialog').showModal();
}

function updateExpanded() {
  const camera = state.cameras.find(c => c.id === activeCamera);
  if (!camera) return;
  $('camera-title').textContent = camera.name;
  $('camera-switch').value = String(camera.id);
  $('expanded-status').textContent = cameraDetail(camera);
  $('expanded-time').textContent = camera.online ? '' : 'Waiting for the camera to reconnect';
  if (!camera.online) {
    $('expanded-camera').removeAttribute('src');
    $('expanded-live-label').textContent = 'Offline';
  } else if (!window.WatchyardLive?.expandedPlaying()) {
    $('expanded-camera').src = `/api/cameras/${camera.id}/snapshot?t=${tick}`;
  }
}

$('camera-switch').addEventListener('change', event => {
  activeCamera = Number(event.target.value);
  window.WatchyardLive?.retry();
  updateExpanded();
});
$('activity-camera').addEventListener('change', event => {
  cameraFilter = event.target.value;
  renderEvents();
});
$('camera-activity').addEventListener('click', () => {
  cameraFilter = String(activeCamera);
  $('activity-camera').value = cameraFilter;
  $('camera-dialog').close();
  navigate('activity');
});

async function refresh(){if(!signedIn||busy)return;busy=true;try{[state,events,diagnostics]=await Promise.all([api('/api/status'),api('/api/events'),api('/api/diagnostics')]);renderReliability();if(admin){deviceInfo=await api('/api/devices');renderDevices();}tick++;renderCameras();renderEvents();if(window.WatchyardReplay)await window.WatchyardReplay.refreshSaved();applyAccess();if(linkedEvent&&window.WatchyardReplay){const id=linkedEvent;linkedEvent=null;window.WatchyardReplay.openEvent(id);}const online=state.cameras.filter(c=>c.online).length;
const count=state.cameras.length;
const analysing=state.cameras.filter(c=>c.enabled&&c.online);
const starting=state.detector==='loading'&&!state.detector_error;
const healthy=!state.detector_error&&!['loading','unavailable'].includes(state.detector)&&analysing.every(c=>Date.now()/1000-c.detected_at<12);
const connection=$('connection-label');
connection.innerHTML=`<span class="dot ${online===count?'online':'offline'}"></span>${online===count?'Connected':'Camera offline'}`;
$('home-status').textContent=`${online} of ${count} cameras online`+(starting?' · Starting detection':healthy?'':' · Detection needs attention');
const muted=state.settings.muted_until>Date.now()/1000;const enabled=state.settings.enabled;$('enabled').checked=enabled;$('alert-state').textContent=!enabled?'Alerts are switched off.':muted?'Quiet until '+new Date(state.settings.muted_until*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'Alerts are enabled.';$('quick-state').textContent=!enabled?'Alerts off':muted?'Quiet time':'Alerts on';$('quick-detail').textContent=muted?'Notifications paused':'Alert settings';$('quick-mute').querySelector('strong').textContent=muted?'Resume alerts':'Mute for 1 hour';$('telegram-status').textContent=state.telegram.error|| (state.telegram.paired?(state.telegram.accounts||1)+' approved account(s)':'Waiting for pairing');const botLink=$('open-telegram');botLink.hidden=!state.telegram.username;if(state.telegram.username)botLink.href='https://t.me/'+encodeURIComponent(state.telegram.username);botLink.classList.toggle('hidden',!state.telegram.username);$('telegram-dot').className='dot '+(state.telegram.paired&&!state.telegram.error?'online':'offline');$('test').disabled=!state.notifications.some(p=>p.destinations)||!admin;for(const provider of state.notifications){const key={'Pushover':'pushover','Custom webhook':'webhook'}[provider.name];if(key)$(key+'-status').textContent=provider.destinations?'Ready':provider.enabled?'Needs configuration':'Off';}$('detector').textContent=state.detector_error||state.detector;$('memory').textContent=state.memory_mb+' MB';if(document.activeElement!==$('confidence')){$('confidence').value=Math.round(state.settings.confidence*100);$('confidence-value').value=$('confidence').value+'%';}}catch(e){if(signedIn){$('connection-label').innerHTML='<span class="dot offline"></span>Connection lost';$('home-status').textContent='Connection lost. Check your network and refresh.';}}finally{busy=false;}}
function drawZone(){const canvas=$('zone-canvas'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,960,540);if(zoneImage.complete&&zoneImage.naturalWidth)ctx.drawImage(zoneImage,0,0,960,540);if(points.length){ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x*960,y*540):ctx.moveTo(x*960,y*540));if(points.length>2)ctx.closePath();ctx.fillStyle='rgba(0,122,255,.24)';ctx.fill();ctx.strokeStyle='#75c4ff';ctx.lineWidth=3;ctx.stroke();for(const [x,y] of points){ctx.beginPath();ctx.arc(x*960,y*540,7,0,2*Math.PI);ctx.fillStyle='#fff';ctx.fill();}}$('zone-instruction').textContent=points.length?(points.length<3?'Add at least three points before saving.':`${points.length} boundary points. Only objects entering this area will alert.`):'Full view selected. Tap the picture to draw a boundary.';}
function openZone(id){if(!admin)return;editing=state.cameras.find(c=>c.id===id);points=editing.zone.map(p=>[...p]);$('zone-title').textContent=editing.name;$('camera-enabled').checked=editing.enabled;document.querySelectorAll('input[name=label]').forEach(i=>i.checked=editing.labels.includes(i.value));zoneImage=new Image();zoneImage.onload=drawZone;zoneImage.src=`/api/cameras/${id}/snapshot?t=${Date.now()}`;$('zone-dialog').showModal();drawZone();}
$('zone-canvas').addEventListener('click',e=>{if(points.length>=20){$('zone-instruction').textContent='Use at most 20 boundary points.';return;}const r=e.target.getBoundingClientRect();points.push([(e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height]);drawZone();});
$('reset-zone').addEventListener('click',()=>{points=[];drawZone();});$('undo-zone').addEventListener('click',()=>{points.pop();drawZone();});$('close-zone').addEventListener('click',()=>$('zone-dialog').close());$('close-image').addEventListener('click',()=>$('image-dialog').close());$('close-camera').addEventListener('click',()=>$('camera-dialog').close());$('camera-dialog').addEventListener('close',()=>activeCamera=null);$('edit-expanded').addEventListener('click',()=>{const id=activeCamera;$('camera-dialog').close();openZone(id);});
$('zone-form').addEventListener('submit',async e=>{e.preventDefault();if(points.length&&points.length<3){$('zone-instruction').textContent='Add three points or choose Full view.';return;}try{await api('/api/cameras/'+editing.id,{enabled:$('camera-enabled').checked,labels:[...document.querySelectorAll('input[name=label]:checked')].map(i=>i.value),zone:points});$('zone-dialog').close();notice('Alert area saved');await refresh();}catch(e){$('zone-instruction').textContent=e.message;}});
function resume(){return action('/api/controls',{enabled:true,mute_minutes:0},'Alerts resumed');}
function quiet(){return action('/api/controls',{mute_minutes:60},'Quiet time enabled for one hour');}
$('mute').addEventListener('click',quiet);$('resume').addEventListener('click',resume);$('quick-mute').addEventListener('click',()=>state.settings.muted_until>Date.now()/1000?resume():quiet());$('quick-alerts').addEventListener('click',()=>navigate('settings'));
$('enabled').addEventListener('change',e=>action('/api/controls',{enabled:e.target.checked}));$('test').addEventListener('click',()=>action('/api/test-notification',{},'Test notification sent'));$('confidence').addEventListener('input',e=>$('confidence-value').value=e.target.value+'%');$('confidence').addEventListener('change',e=>action('/api/controls',{confidence:Number(e.target.value)/100},'Detection threshold saved'));$('refresh').addEventListener('click',()=>{window.WatchyardLive?.retry();refresh();});document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',x===b?'true':'false'));renderEvents(true);}));document.querySelectorAll('[data-nav]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.nav)));window.addEventListener('hashchange',()=>{const hash=location.hash.slice(1);if(hash.startsWith('event='))linkedEvent=hash.slice(6);navigate(hash,false);if(linkedEvent&&signedIn)refresh();});document.querySelectorAll('a[href="#home"]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();navigate('home');}));
async function enter(){const session=await api('/api/session');if(!session.authenticated){showLogin();return;}signedIn=true;localDevice=session.local;admin=session.device?.role==='admin';applyAccess();$('login-screen').classList.add('hidden');$('app-shell').classList.remove('hidden');$('sign-out').classList.toggle('hidden',localDevice);navigate(location.hash.slice(1)||'home');await refresh();}
$('login-form').addEventListener('submit',async e=>{e.preventDefault();$('login-button').disabled=true;$('login-error').textContent='';try{await api('/api/login',{code:$('access-code').value,name:$('device-name').value.trim()||'New browser'});$('access-code').value='';await enter();}catch(e){$('login-error').textContent=e.message;}finally{$('login-button').disabled=false;}});$('sign-out').addEventListener('click',async()=>{try{await api('/api/logout',{});showLogin();}catch(e){notice(e.message);}});
const join=location.hash.startsWith('#join=')?location.hash.slice(6):null;if(join){$('access-code').value=decodeURIComponent(join);history.replaceState(null,'',location.pathname);}
$('device-name').value=/iPhone/.test(navigator.userAgent)?'My iPhone':/iPad/.test(navigator.userAgent)?'My iPad':'My browser';
enter().catch(()=>{$('login-error').textContent='Cannot connect to Watchyard. Check home Wi-Fi.';showLogin();});setInterval(()=>{if(!document.hidden)refresh();},3000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});

function renderReliability(){
 if(!diagnostics)return;
 $('queue-count').textContent=String(diagnostics.delivery.pending||0);
 $('delivery-delay').textContent=diagnostics.mean_delivery_seconds===null?'Collecting':diagnostics.mean_delivery_seconds+'s · '+diagnostics.delivery_sample_count+' sent';
 if(document.activeElement!==$('analysis-rate'))$('analysis-rate').value=String(state.settings.inference_fps);
 const w=diagnostics.watchdog;
 $('watchdog-status').textContent=!w?'Starting':!w.fresh?'Not checking in':w.healthy?'Checking in':'Needs attention';
 $('peak-memory').textContent=diagnostics.peak_memory_mb?diagnostics.peak_memory_mb+' MB':'Collecting';
 const r=diagnostics.reviews;
 $('review-summary').textContent=`${r.useful||0} useful · ${r.false_alarm||0} false`;
 $('delivery-problem').textContent=state.telegram.delivery_error?'Last delivery failure: '+state.telegram.delivery_error:(diagnostics.delivery.expired||0)+' expired alerts retained locally. Delay is measured from confirmation to Telegram acceptance.';
 $('health-history').innerHTML=diagnostics.health_events.slice(0,3).map(e=>`<div class="health-note"><p>${esc(e.body)}</p><small>${new Date(e.created*1000).toLocaleString()} · ${esc(e.status)}</small></div>`).join('');
 if(!$('camera-alert-settings').children.length){$('camera-alert-settings').innerHTML=state.cameras.map(c=>`<button class="settings-row row-button" data-policy="${c.id}"><span class="row-text">${esc(c.name)}<small id="policy-summary-${c.id}"></small></span><span class="chevron">›</span></button>`).join('');document.querySelectorAll('[data-policy]').forEach(b=>b.addEventListener('click',()=>openPolicy(Number(b.dataset.policy))));}
 for(const c of state.cameras){const modes=c.alert_modes||{};const names=Object.values(modes);$('policy-summary-'+c.id).textContent=(c.schedule?.enabled?'Scheduled hours':'Any time')+' · '+(names.every(m=>m==='off')?'local history only':'custom alert preferences');}
 if(activeEvent&&$('image-dialog').open){const e=events.find(e=>e.id===activeEvent);if(e)renderReview(e);}
}
function renderReview(e){$('review-useful').setAttribute('aria-pressed',e.feedback==='useful'?'true':'false');$('review-false').setAttribute('aria-pressed',e.feedback==='false_alarm'?'true':'false');$('event-delivery-detail').textContent=e.detail||'Mark whether this event was useful. Reviews are saved locally and do not automatically change detection.';}
async function review(value){if(!activeEvent)return;try{await api('/api/events/'+activeEvent+'/feedback',{value});notice('Review saved');await refresh();}catch(e){notice(e.message);}}
$('review-useful').addEventListener('click',()=>review('useful'));$('review-false').addEventListener('click',()=>review('false_alarm'));$('review-clear').addEventListener('click',()=>review('unreviewed'));$('image-dialog').addEventListener('close',()=>activeEvent=null);
function openPolicy(id){if(!admin)return;policyCamera=state.cameras.find(c=>c.id===id);$('policy-title').textContent=policyCamera.name+' alerts';const modes=policyCamera.alert_modes||{person:'normal',car:'normal',dog:'silent',cat:'silent'};for(const name of ['person','car','dog','cat'])$('mode-'+name).value=modes[name];const s=policyCamera.schedule||{enabled:false,days:[0,1,2,3,4,5,6],start:'22:00',end:'07:00',timezone:'Europe/Lisbon'};$('policy-scheduled').checked=s.enabled;document.querySelectorAll('input[name=weekday]').forEach(i=>i.checked=s.days.includes(Number(i.value)));$('policy-start').value=s.start;$('policy-end').value=s.end;$('policy-timezone').textContent=s.timezone+'. Overnight windows finish the following morning. Equal times mean a full day.';$('schedule-fields').classList.toggle('hidden',!s.enabled);$('policy-error').textContent='';$('policy-dialog').showModal();}
$('policy-scheduled').addEventListener('change',e=>$('schedule-fields').classList.toggle('hidden',!e.target.checked));$('close-policy').addEventListener('click',()=>$('policy-dialog').close());
$('policy-form').addEventListener('submit',async e=>{e.preventDefault();const alert_modes={};for(const name of ['person','car','dog','cat'])alert_modes[name]=$('mode-'+name).value;const schedule={enabled:$('policy-scheduled').checked,days:[...document.querySelectorAll('input[name=weekday]:checked')].map(i=>Number(i.value)),start:$('policy-start').value,end:$('policy-end').value,timezone:policyCamera.schedule?.timezone||'Europe/Lisbon'};if(schedule.enabled&&!schedule.days.length){$('policy-error').textContent='Choose at least one start day.';return;}try{await api('/api/cameras/'+policyCamera.id+'/alerts',{alert_modes,schedule});$('policy-dialog').close();notice('Alert preferences saved');await refresh();}catch(e){$('policy-error').textContent=e.message;}});

function applyAccess(){
 $('devices-section').classList.toggle('hidden',!admin);
 $('access-role-note').classList.toggle('hidden',admin);
 for(const id of ['enabled','mute','resume','test','confidence','analysis-rate','quick-mute','quick-alerts'])$(id).disabled=!admin;
 document.querySelectorAll('.camera-settings,[data-policy]').forEach(b=>b.disabled=!admin);
 $('edit-expanded').classList.toggle('hidden',!admin);
 document.querySelector('.review-controls').classList.toggle('hidden',!admin);
}
function renderDevices(){
 const signature=JSON.stringify(deviceInfo);if(signature===deviceSignature)return;deviceSignature=signature;
 const current=deviceInfo.current;
 const rows=deviceInfo.devices.filter(d=>d.active);
 $('device-list').innerHTML=(current?.id==='local'?'<div class="settings-row"><span class="row-text">This Mac<small>Owner access on this computer</small></span><span class="member-role">Local</span></div>':'')+rows.map(d=>`<div class="settings-row member-row"><span class="row-text">${esc(d.name)}${current?.id===d.id?' (this device)':''}<small>${d.kind==='telegram'?'Telegram account':'Browser device'} · ${d.role==='admin'?'Manage home':'View only'}${d.kind==='telegram'?(d.alerts?' · alerts on':' · alerts paused'):''}</small></span><button class="remove-device" data-revoke-device="${d.id}" aria-label="Revoke ${esc(d.name)}">Revoke</button></div>`).join('');
 if(!rows.length&&current?.id!=='local')$('device-list').innerHTML='<p class="settings-note">No devices registered yet.</p>';
 $('invitation-list').innerHTML=deviceInfo.invitations.length?'<h3 class="group-heading">Pending invitations</h3><div class="settings-group">'+deviceInfo.invitations.map(i=>`<div class="settings-row member-row"><span class="row-text">${esc(i.name)}<small>${i.kind==='telegram'?'Telegram':'Browser'} · expires ${new Date(i.expires*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</small></span><button class="remove-device" data-revoke-invite="${i.id}">Cancel</button></div>`).join('')+'</div>':'';
 document.querySelectorAll('[data-revoke-device]').forEach(b=>b.addEventListener('click',()=>action('/api/devices/'+b.dataset.revokeDevice+'/revoke',{},'Device access revoked')));
 document.querySelectorAll('[data-revoke-invite]').forEach(b=>b.addEventListener('click',()=>action('/api/invitations/'+b.dataset.revokeInvite+'/revoke',{},'Invitation cancelled')));
}
$('add-device').addEventListener('click',()=>{$('invite-fields').classList.remove('hidden');$('invite-result').classList.add('hidden');$('invite-name').value='';$('invite-kind').value='browser';$('invite-role').value='viewer';$('invite-telegram-note').classList.add('hidden');$('invite-error').textContent='';$('copy-invite').textContent='Copy invitation';$('invite-access-detail').textContent='View cameras and history. Cannot change alerts or invite others.';$('invite-dialog').showModal();});
$('close-invite').addEventListener('click',()=>{$('invite-dialog').close();$('invite-share').value='';$('invite-code').value='';});
$('invite-kind').addEventListener('change',e=>$('invite-telegram-note').classList.toggle('hidden',e.target.value!=='telegram'));
$('invite-role').addEventListener('change',e=>$('invite-access-detail').textContent=e.target.value==='admin'?'Full access: change home settings, manage accounts and invite others.':'View cameras and history. Cannot change alerts or invite others.');
$('invite-form').addEventListener('submit',async e=>{e.preventDefault();$('create-invite').disabled=true;$('invite-error').textContent='';try{const i=await api('/api/invitations',{kind:$('invite-kind').value,name:$('invite-name').value.trim(),role:$('invite-role').value});$('invite-share').value=i.url;$('invite-code').value=i.code;$('invite-fields').classList.add('hidden');$('invite-result').classList.remove('hidden');await refresh();}catch(e){$('invite-error').textContent=e.message;}finally{$('create-invite').disabled=false;}});
$('copy-invite').addEventListener('click',async()=>{const text=$('invite-share').value;try{if(!navigator.clipboard)throw Error();await navigator.clipboard.writeText(text);$('copy-invite').textContent='Copied';}catch(e){$('invite-share').select();$('copy-invite').textContent='Link selected — use Copy';}});

$('analysis-rate').addEventListener('change',e=>action('/api/controls',{inference_fps:Number(e.target.value)},'Analysis rate saved'));
