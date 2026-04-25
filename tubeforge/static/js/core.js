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
