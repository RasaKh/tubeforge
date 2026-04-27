/* ── tiny helpers ──────────────────────────────────────────────────── */
const $  = (s,r=document)=>r.querySelector(s);
const $$ = (s,r=document)=>Array.from(r.querySelectorAll(s));
const esc = s => String(s==null?'':s).replace(/[&<>"']/g, c => (
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const debounce = (fn,ms=260)=>{let t;return(...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),ms)}};
const fmtBytes = n => { if(n==null) return '—'; const u=['B','KB','MB','GB','TB']; let i=0;
  n=Number(n); while(n>=1024&&i<u.length-1){n/=1024;i++;} return (i?n.toFixed(1):n)+' '+u[i]; };
const fmtDur = s => { if(s==null||isNaN(s)) return '—'; s=Math.floor(s);
  const h=Math.floor(s/3600), m=Math.floor(s%3600/60), x=s%60;
  return h? `${h}:${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}`
          : `${m}:${String(x).padStart(2,'0')}`; };

/* Markup and script are edited independently, so a lookup that returns null
   should degrade quietly rather than abort boot and leave a blank page. */
function setText(sel, value){
  const el = typeof sel === 'string' ? $(sel) : sel;
  if(el) el.textContent = value;
  else console.warn('setText: no element for', sel);
  return el;
}
function setHTML(sel, value){
  const el = typeof sel === 'string' ? $(sel) : sel;
  if(el) el.innerHTML = value;
  else console.warn('setHTML: no element for', sel);
  return el;
}

async function api(path, opts={}){
  const r = await fetch(path, Object.assign({headers:{'Content-Type':'application/json'}}, opts));
  let j; try{ j = await r.json(); }catch(e){ throw new Error('Server sent something unreadable.'); }
  if(r.status === 401){
    const token = window.prompt('TubeForge access token:');
    if(token){
      await api('/api/auth/login', {method:'POST', body:JSON.stringify({token})});
      return api(path, opts);
    }
  }
  if(!r.ok || j.ok === false) throw new Error(j.error || ('Request failed: '+r.status));
  return j;
}

/* ── Event delegation ──────────────────────────────────────────────────
   Inline handlers built by string interpolation are unsafe here: browsers
   HTML-decode an attribute before the JS parser sees it, so a filename
   containing a quote closes the string and the rest of the name executes.
   Filenames come from video titles off the internet, so that input is
   attacker-controlled. Instead, generated markup carries only a data-act
   name and an index; the real values are looked up from JS state, never
   round-tripped through HTML. */
const ACTIONS = {};
function on(name, fn){ ACTIONS[name] = fn; }

document.addEventListener('click', e=>{
  const el = e.target.closest('[data-act]');
  if(!el) return;
  const fn = ACTIONS[el.dataset.act];
  if(!fn) return;
  if(el.dataset.stop) e.stopPropagation();
  fn(el.dataset, el, e);
});
document.addEventListener('change', e=>{
  const el = e.target.closest('[data-change]');
  if(!el) return;
  const fn = ACTIONS[el.dataset.change];
  if(fn) fn(el.dataset, el, e);
});

/* Hover help. One floating element serves every ? on the page, positioned
   against whichever one asked for it and clamped inside the viewport. */
function showTip(el){
  const text = el.dataset.tip;
  if(!text) return;
  let t = $('#tip');
  if(!t){ t = document.createElement('div'); t.id = 'tip'; t.hidden = true; document.body.appendChild(t); }
  const title = el.dataset.tipTitle;
  t.innerHTML = (title ? `<b>${esc(title)}</b>` : '') +
    esc(text).replace(/`([^`]+)`/g, '<code>$1</code>');
  t.hidden = false;
  const r = el.getBoundingClientRect(), tb = t.getBoundingClientRect();
  let left = r.left, top = r.bottom + 7;
  if(left + tb.width > window.innerWidth - 10) left = window.innerWidth - tb.width - 10;
  if(top + tb.height > window.innerHeight - 10) top = Math.max(10, r.top - tb.height - 7);
  t.style.left = Math.max(10, left) + 'px';
  t.style.top = top + 'px';
}
function hideTip(){ const t = $('#tip'); if(t) t.hidden = true; }

document.addEventListener('mouseover', e=>{
  const q = e.target.closest('.qmark');
  if(q) showTip(q);
});
document.addEventListener('mouseout', e=>{
  if(e.target.closest('.qmark')) hideTip();
});
document.addEventListener('focusin', e=>{
  const q = e.target.closest('.qmark');
  q ? showTip(q) : hideTip();
});
window.addEventListener('scroll', hideTip, true);
window.addEventListener('resize', hideTip);

let toastId = 0;
function toast(title, detail='', kind=''){
  const box = $('#toasts'); const d = document.createElement('div');
  d.className = 'toast '+kind; d.id = 'toast'+(++toastId);
  d.innerHTML = `<div class="t">${esc(title)}</div>` + (detail?`<div class="d">${esc(detail)}</div>`:'');
  box.appendChild(d);
  setTimeout(()=>{ d.style.opacity=0; setTimeout(()=>d.remove(),250); }, kind==='bad'?7000:3800);
}
function fail(e){ toast('That did not work', e.message||String(e), 'bad'); }
function copyText(t){ navigator.clipboard.writeText(t).then(()=>toast('Copied')); }

function modal(title, html, foot=''){
  $('#modalTitle').textContent = title; $('#modalBody').innerHTML = html;
  $('#modalFoot').innerHTML = foot; $('#scrim').hidden = false;
}
function closeModal(){ $('#scrim').hidden = true; focusWork(); }

async function browsePath({ mode = 'file', initial = '', title = 'Select', onPick }){
  try{
    const j = await api('/api/browse', {
      method: 'POST',
      body: JSON.stringify({ mode, initial, title })
    });
    if(j.headless) return openServerFilePicker({ mode, title, onPick });
    if(j.cancelled || !j.path) return;
    if(j.outside_sandbox && j.parent){
      if(confirm(`"${j.path}" is outside your allowed folders.\nAdd "${j.parent}" to Settings → Extra folders so TubeForge can access it?`)){
        const cur = (BOOT.config.extra_roots || []).slice();
        if(!cur.includes(j.parent)) cur.push(j.parent);
        const upd = await api('/api/config', { method: 'POST', body: JSON.stringify({ config: { extra_roots: cur } }) });
        BOOT.config = upd.config;
        toast('Added folder to Extra folders', j.parent);
      }
    }
    if(onPick) onPick(j.path, j.paths || [j.path]);
  }catch(e){ fail(e); }
}

async function openServerFilePicker({ mode = 'file', title = 'Select', onPick, dir = '' }){
  try{
    const j = await api('/api/files?dir=' + encodeURIComponent(dir));
    const dirs = j.dirs || [];
    const files = j.files || [];
    const parent = dir ? dir.split('/').slice(0, -1).join('/') : null;
    const html = `
      <div class="rowflex" style="margin-bottom:8px">
        <span class="mono muted" style="flex:1;overflow:hidden;text-overflow:ellipsis">${esc(j.dir)}</span>
        ${parent !== null ? `<button class="btn sm" id="fpUp">↑ Up</button>` : ''}
        ${mode === 'dir' ? `<button class="btn sm go" id="fpUseDir">Use this folder</button>` : ''}
      </div>
      <div style="max-height:52vh;overflow:auto;border:1px solid var(--seam);border-radius:var(--r)">
        ${dirs.map(d => `<div class="listrow" style="cursor:pointer" data-fpdir="${esc(d.rel)}">
          <span class="tag other">DIR</span><span class="fname">${esc(d.name)}/</span>
          <span class="fmeta">${d.entries} items</span></div>`).join('')}
        ${mode !== 'dir' ? files.map(f => `<div class="listrow" style="cursor:pointer" data-fpfile="${esc(f.path)}">
          <span class="tag ${f.kind}">${esc(f.ext || '?')}</span><span class="fname">${esc(f.name)}</span>
          <span class="fmeta">${esc(f.size_h)}</span></div>`).join('') : ''}
        ${!dirs.length && (mode === 'dir' || !files.length) ? '<div class="empty">Empty folder</div>' : ''}
      </div>`;
    modal(title, html);
    if($('#fpUp')) $('#fpUp').onclick = () => openServerFilePicker({ mode, title, onPick, dir: parent });
    if($('#fpUseDir')) $('#fpUseDir').onclick = () => { closeModal(); if(onPick) onPick(j.dir, [j.dir]); };
    $$('[data-fpdir]').forEach(el => el.onclick = () => openServerFilePicker({ mode, title, onPick, dir: el.dataset.fpdir }));
    $$('[data-fpfile]').forEach(el => el.onclick = () => { closeModal(); if(onPick) onPick(el.dataset.fpfile, [el.dataset.fpfile]); });
  }catch(e){ fail(e); }
}

function browseInto(selector, mode = 'file', title = 'Select'){
  const el = $(selector);
  if(!el) return;
  browsePath({
    mode,
    initial: el.value,
    title,
    onPick: p => {
      el.value = p;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
  });
}
function togglePanel(head){ head.closest('.panel').classList.toggle('collapsed'); }

/* ── state ─────────────────────────────────────────────────────────── */
let BOOT = null;
let ytOpts = {};                                 // yt-dlp form values
let chains = { video: [], audio: [] };           // filter studio
let lab = { op:'transcode', inputs:[''], params:{}, enc:{}, output:'', output_mode:'auto' };
let labAudioCaps = {}, labVideoCaps = {}, labContainerOptions = [], labAudioOnly = false, labRevision = 0;
let pipeSteps = [];
let batchFiles = [];
let libState = { dir:'', files:[], view:[], dirs:[], sel:new Set(), sort:'mtime', desc:true };
let fmtState = { rows:[], sel:new Set(), filter:'all', sort:'height', desc:true, info:null };
let jobs = new Map();
let currentJob = null, jobLogSrc = null;
let historyRows = [];

/* ── navigation ────────────────────────────────────────────────────── */
/* Media keeps playing when its element is merely hidden, so audio follows you
   around the app. Anything leaving the screen gets paused and detached. */
function stopPreviewMedia(){
  $$('#libPreview video, #libPreview audio').forEach(el=>{
    try{ el.pause(); el.removeAttribute('src'); el.load(); }catch(e){}
  });
}

function show(name){
  if(!$('#view-library').classList.contains('on') || name !== 'library') stopPreviewMedia();
  $$('.view').forEach(v=>v.classList.toggle('on', v.id==='view-'+name));
  $$('.nav').forEach(n=>n.classList.toggle('on', n.dataset.view===name));
  $('#rail').classList.remove('open');
  const railR = $('#rail-r'); if(railR) railR.classList.remove('open');
  // Snapping only makes sense where there are zones to snap to.
  $('#work').classList.toggle('snap', name === 'fetch');
  $('#work').scrollTop = 0;
  markJump('top');
  // The nav button that was just clicked holds focus, so arrow keys would
  // scroll the rail. Move focus onto the page the person is now looking at.
  focusWork();
  setTimeout(()=>window.dispatchEvent(new Event('resize')), 60);
  location.hash = name;
  const hooks = { library:loadLibrary, queue:renderQueue, presets:loadPresets,
                  history:loadHistory, filters:renderChains, batch:renderBatch,
                  reference:renderReference, settings:loadDisk, pipeline:renderPipeline };
  if(hooks[name]) hooks[name]();
}
$$('.nav').forEach(n=>n.onclick=()=>show(n.dataset.view));

/* ── Jump rail ─────────────────────────────────────────────────────────
   Two buttons standing in for the ends of the page. The lit one reports where
   you are; scrolling by any means keeps it honest. */
let jumpEnd = 'top';

function jumpTo(where){
  const work = $('#work');
  work.scrollTo({top: where === 'top' ? 0 : work.scrollHeight, behavior:'smooth'});
  markJump(where);
  // Hand focus back, or the next arrow key would act on the button instead of
  // the page it just moved.
  focusWork();
}

function focusWork(){
  const work = $('#work');
  if(!work) return;
  const active = document.activeElement;
  // Never steal focus from something the person is typing into.
  if(active && active !== document.body && active !== work &&
     active.closest('input, textarea, select, [contenteditable]')) return;
  work.focus({preventScroll:true});
}

function markJump(where){
  jumpEnd = where;
  const up = $('#jumpUp'), down = $('#jumpDown');
  if(!up || !down) return;
  up.classList.toggle('on', where === 'top');
  down.classList.toggle('on', where === 'bottom');
}

function wireJumpRail(){
  // Pressing a jump button should move the page, not park focus on the button.
  $$('#jumprail .jump').forEach(b=>{
    b.addEventListener('mousedown', e=>e.preventDefault());
  });
}

function watchScroll(){
  const work = $('#work');
  if(!work) return;
  const update = ()=>{
    const room = work.scrollHeight - work.clientHeight;
    // Nothing to scroll: neither end is meaningfully "where you are".
    // Collapsing the column keeps the rails either side of it in place.
    const none = room < 40;
    $('#body').classList.toggle('nojump', none);
    if(none){ markJump('top'); return; }
    markJump(work.scrollTop > room / 2 ? 'bottom' : 'top');
  };
  work.addEventListener('scroll', ()=>{ update(); closeRowMenu(); }, {passive:true});
  window.addEventListener('resize', update);
  update();
  return update;
}

function toggleTheme(){
  const cur = document.documentElement.dataset.theme==='daylight' ? '' : 'daylight';
  document.documentElement.dataset.theme = cur;
  try{ localStorage.setItem('tf_theme', cur); }catch(e){}
}
function applyFontScale(v){
  document.documentElement.style.setProperty('--fs', v/100);
  setText('#fsLabel', v+'%');
  try{ localStorage.setItem('tf_fs', v); }catch(e){}
}

