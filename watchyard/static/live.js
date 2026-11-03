'use strict';
(() => {
 const sessions=new Map(), visible=new Set(), retries=new Map();
 const expanded=$('expanded-live');
 let observer;
 const current=video=>sessions.get(video);
 function label(video,text){
  const s=current(video);if(s)s.label=text;
  if(video===expanded)$('expanded-live-label').textContent=text;
  else{const badge=$('badge-'+video.dataset.camera);if(badge)badge.textContent=text;}
 }
 function stop(video){
  const s=current(video);if(!s)return;
  sessions.delete(video);
  video.onplaying=video.oncanplay=video.onerror=video.onwaiting=video.ontimeupdate=video.onpause=null;
  if(s.hls)s.hls.destroy();
  video.pause();video.removeAttribute('src');video.load();video.classList.remove('live-visible');
  label(video,'Preview');
 }
 function reset(){for(const video of [...sessions.keys()])stop(video);retries.clear();}
 function measure(video,s){
  const quality=video.getVideoPlaybackQuality?.();
  const frames=quality?quality.totalVideoFrames-quality.droppedVideoFrames:video.webkitDecodedFrameCount;
  if(!Number.isFinite(frames))return;
  const now=performance.now();
  video.dataset.videoFrames=String(frames);video.dataset.sampledAt=String(Date.now());
  if(!s.sample){s.sample={frames,time:now};return;}
  if(now-s.sample.time>=1500){
   const fps=Math.max(0,(frames-s.sample.frames)*1000/(now-s.sample.time));
   video.dataset.measuredFps=fps.toFixed(1);
   if(s.label?.startsWith('Live'))label(video,`Live · ${Math.round(fps)} fps`);
   s.sample={frames,time:now};
  }
 }
 function fail(video,s){
  if(current(video)!==s)return;
  stop(video);retries.set(video,Date.now()+5000);label(video,'Reconnecting');
 }
 function manual(video,s){
  if(current(video)===s){video.classList.add('live-visible');label(video,'Tap to play');}
 }
 function start(video,camera){
  if(current(video)||Date.now()<(retries.get(video)||0))return;
  const s={hls:null,playing:false,progress:Date.now()};sessions.set(video,s);
  video.muted=true;video.autoplay=true;video.playsInline=true;
  video.poster=`/api/cameras/${camera}/snapshot`;
  label(video,'Connecting');
  video.oncanplay=()=>{if(current(video)===s){video.classList.add('live-visible');if(!s.attempted){s.attempted=true;video.play().catch(()=>manual(video,s));}}};
  video.onplaying=()=>{if(current(video)===s){s.playing=true;s.sample=null;delete video.dataset.measuredFps;s.progress=Date.now();video.classList.add('live-visible');label(video,'Live');}};
  video.ontimeupdate=()=>{s.progress=Date.now();};
  video.onpause=()=>{if(current(video)===s){s.playing=false;label(video,'Paused');}};
  video.onwaiting=()=>{if(current(video)===s)label(video,'Buffering');};
  video.onerror=()=>fail(video,s);
  const url=`/api/cameras/${camera}/live/index.m3u8`;
  if(video.canPlayType('application/vnd.apple.mpegurl')){
   video.src=url;video.play().catch(()=>manual(video,s));
  }else if(window.Hls?.isSupported()){
   const hls=new Hls({enableWorker:false,lowLatencyMode:true,liveSyncDurationCount:2,
    liveMaxLatencyDurationCount:5,maxLiveSyncPlaybackRate:1.05,backBufferLength:0,
    maxBufferLength:4,maxMaxBufferLength:6,maxBufferSize:4*1024*1024});
   s.hls=hls;
   hls.on(Hls.Events.ERROR,(_event,data)=>{
    if(data.response?.code===401){showLogin();return;}
    if(data.fatal)fail(video,s);
   });
   hls.attachMedia(video);hls.loadSource(url);
  }else{
   stop(video);retries.set(video,Infinity);label(video,'Preview');
  }
 }
 function sync(){
  const wanted=new Map();
  if(signedIn&&!document.hidden&&state){
   for(const camera of state.cameras){
    const picture=$('camera-'+camera.id)?.closest('.camera-picture');
    if(picture&&!picture.querySelector('video')){
     const video=document.createElement('video');video.className='camera-live-video';video.dataset.camera=camera.id;
     video.setAttribute('muted','');video.setAttribute('playsinline','');video.setAttribute('autoplay','');
     video.setAttribute('aria-hidden','true');
     video.setAttribute('aria-label','Live '+camera.name+' view');picture.insertBefore(video,picture.querySelector('.preview-badge'));
     observer.observe(picture);
    }
   }
   const modal=document.querySelector('dialog[open]');
   if(modal?.id==='camera-dialog'&&activeCamera&&state.cameras.find(c=>c.id===activeCamera)?.online){
    wanted.set(expanded,activeCamera);
   }else if(!modal&&currentView==='home'){
    for(const camera of state.cameras){
     const video=$('camera-'+camera.id)?.closest('.camera-picture')?.querySelector('video');
     if(video&&camera.online&&visible.has(video.parentElement))wanted.set(video,camera.id);
    }
   }
  }
  for(const video of [...sessions.keys()])if(!wanted.has(video))stop(video);
  for(const [video,camera] of wanted){
   const s=current(video);
   if(s&&s.camera!==camera){stop(video);}
   const active=current(video);
   if(active?.playing&&!video.paused&&Date.now()-active.progress>12000)fail(video,active);
   if(active?.playing&&!video.paused)measure(video,active);
   start(video,camera);
   if(current(video))current(video).camera=camera;
  }
 }
 observer=new IntersectionObserver(entries=>{
  for(const entry of entries){if(entry.isIntersecting&&entry.intersectionRatio>.12)visible.add(entry.target);else visible.delete(entry.target);}
  sync();
 },{threshold:[0,.12,.5]});
 for(const dialog of document.querySelectorAll('dialog'))new MutationObserver(sync).observe(dialog,{attributes:true,attributeFilter:['open']});
 document.addEventListener('visibilitychange',sync);
 window.addEventListener('pagehide',reset);
 $('go-live').addEventListener('click',()=>{stop(expanded);retries.delete(expanded);sync();});
 window.WatchyardLive={sync,reset,retry(){reset();sync();},label(id){
  const video=$('camera-'+id)?.closest('.camera-picture')?.querySelector('video');
  return current(video)?.label;
 },playing(id){
  const video=$('camera-'+id)?.closest('.camera-picture')?.querySelector('video');
  return Boolean(video&&current(video)?.playing&&!video.paused);
 },expandedPlaying(){return Boolean(current(expanded)?.playing&&!expanded.paused);}};
 setInterval(sync,2000);
})();
