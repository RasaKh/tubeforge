/* ══════════════════════════════════════════════════════════════════════
   FETCH — yt-dlp form is generated from the option registry
   ══════════════════════════════════════════════════════════════════════ */
/* Checkboxes carried their explanation as a line of small text under the
   label, which made every group of options twice as tall. The text now lives
   behind a ? beside the label. */
function checkWithHint(inner, title, help){
  if(!help) return inner;
  return `<div class="check-wrap">${inner}<button class="qmark" data-tip-title="${
    esc(title)}" data-tip="${esc(help)}" aria-label="Help" type="button">?</button></div>`;
}

function ctrlFor(o){
  const v = ytOpts[o.id] ?? '';
  const idAttr = `yt_${o.id}`;
  const helpHtml = o.help ? `<p class="help">${esc(o.help)}</p>` : '';
  if(o.type === 'bool'){
    return checkWithHint(`<label class="check ${v?'on':''}">
      <input type="checkbox" id="${idAttr}" ${v?'checked':''} onchange="setOpt('${o.id}', this.checked)">
      <span>${esc(o.label)}</span></label>`, o.label, o.help);
  }
  let input;
  if(o.type === 'select'){
    const labels = o.labels || {};
    input = `<select id="${idAttr}" onchange="setOpt('${o.id}', this.value)">` +
      (o.choices||[]).map(c=>`<option value="${esc(c)}" ${c===v?'selected':''}>${
        esc(labels[c] || (c===''?'— not set —':c))}</option>`).join('') + `</select>`;
  } else if(o.type === 'list'){
    input = `<textarea id="${idAttr}" rows="2" placeholder="${esc(o.placeholder||'')}"
      oninput="setOpt('${o.id}', this.value)">${esc(v)}</textarea>`;
  } else if(o.type === 'path'){
    input = `<div class="inline"><input type="text" id="${idAttr}" value="${esc(v)}"
      placeholder="${esc(o.placeholder||'')}" oninput="setOpt('${o.id}', this.value)">
      <button class="btn sm" type="button" onclick="browseInto('#${idAttr}','${o.id==='paths'?'dir':'file'}','Select ${esc(o.label)}')">Browse…</button></div>`;
  } else {
    const t = o.secret ? 'password' : (o.type==='number' ? 'number' : 'text');
    input = `<input type="${t}" id="${idAttr}" value="${esc(v)}"
      placeholder="${esc(o.placeholder||'')}" oninput="setOpt('${o.id}', this.value)">`;
  }
  return `<div class="field"><label>${esc(o.label)}</label>${input}${helpHtml}</div>`;
}

let optGroup = 'format';

function ytGroupHits(gid, q, adv){
  return BOOT.ytdlp_options.filter(o =>
    o.group === gid && !o.hidden && (adv || !o.adv) &&
    (!q || o.label.toLowerCase().includes(q) || o.id.includes(q) ||
     (o.flag||'').includes(q) || (o.help||'').toLowerCase().includes(q)));
}

function renderYtOptions(){
  const q = ($('#optSearch').value||'').toLowerCase();
  const adv = $('#showAdv').checked;

  // Group list. A search narrows to groups that still contain a match and jumps
  // to the first of them, so filtering never leaves an empty pane on screen.
  const groups = BOOT.ytdlp_groups.map(g=>({
    ...g, hits: ytGroupHits(g.id, q, adv),
    set: BOOT.ytdlp_options.filter(o=>o.group===g.id && ytOpts[o.id]).length
  }));
  const visible = groups.filter(g=>g.hits.length);
  if(q && visible.length && !visible.some(g=>g.id===optGroup)) optGroup = visible[0].id;
  if(!visible.some(g=>g.id===optGroup) && visible.length) optGroup = visible[0].id;

  $('#optGroupList').innerHTML = visible.map(g=>`
    <button class="optgroup ${g.id===optGroup?'on':''} ${g.set?'has':''}"
      title="${g.set?g.set+' set':g.hits.length+' available'} — ${esc(g.hint)}"
      data-act="optGroup" data-g="${esc(g.id)}">
      <span class="g-label">${esc(g.label)}</span>
      <span class="n">${g.set || g.hits.length}</span>
      <span class="g-hint">${esc(g.hint)}</span>
    </button>`).join('') || `<div class="empty" style="padding:18px">No matches.</div>`;

  const total = groups.reduce((n,g)=>n+g.hits.length,0);
  $('#optHitCount').textContent = q ? `${total} matching` : '';

  const g = visible.find(x=>x.id===optGroup);
  if(!g){ $('#optGroupPane').innerHTML = `<div class="empty"><b>Nothing matches</b>Try a different word, or switch on advanced options.</div>`; return; }
  const bools = g.hits.filter(o=>o.type==='bool');
  const rest  = g.hits.filter(o=>o.type!=='bool');
  $('#optGroupPane').innerHTML = `
    <div class="optbrowse-head"><h4>${esc(g.label)}</h4><p>${esc(g.hint)}</p></div>
    ${rest.length?`<div class="cols-3">${rest.map(ctrlFor).join('')}</div>`:''}
    ${bools.length&&rest.length?'<div class="sep"></div>':''}
    ${bools.length?`<div class="checks">${bools.map(ctrlFor).join('')}</div>`:''}`;
}

function pickOptGroup(id){ optGroup = id; renderYtOptions(); }

const YTDLP_MUTEX = {
  no_overwrites: ['force_overwrites'],
  force_overwrites: ['no_overwrites'],
  ignore_errors: ['abort_on_error'],
  abort_on_error: ['ignore_errors'],
  force_ipv4: ['force_ipv6'],
  force_ipv6: ['force_ipv4'],
  live_from_start: ['no_live_from_start'],
  no_live_from_start: ['live_from_start'],
  verbose_flag: ['quiet'],
  quiet: ['verbose_flag'],
  embed_chapters: ['no_chapters'],
  no_chapters: ['embed_chapters'],
};

function setOpt(id, val){
  if(val === '' || val === false) delete ytOpts[id]; else ytOpts[id] = val;
  let needRender = false;
  if(val === true && YTDLP_MUTEX[id]){
    YTDLP_MUTEX[id].forEach(m => { if(ytOpts[m]){ delete ytOpts[m]; needRender = true; } });
  }
  if(['sub_langs', 'sub_format', 'convert_subs'].includes(id) && val){
    if(!ytOpts.write_subs && !ytOpts.write_auto_subs && !ytOpts.embed_subs){
      ytOpts.write_subs = true;
      needRender = true;
      toast("Enabled 'Write subtitle files'");
    }
  }
  if(id === 'output_chapter' && val && !ytOpts.split_chapters){
    ytOpts.split_chapters = true;
    needRender = true;
  }
  // Naming a target audio codec only means anything while extracting audio, so
  // choosing one switches extraction on rather than being quietly ignored.
  if(id === 'audio_format'){
    if(val) ytOpts.extract_audio = true;
    else if(!/\bbestaudio\b|\bworstaudio\b/.test(ytOpts.format||'')) delete ytOpts.extract_audio;
  }
  if(needRender) renderYtOptions();
  saveLocal(); renderActiveStrip(); renderFormatChips(); renderTplSummary(); syncFetch();
}
function resetYtOptions(){ ytOpts = {}; saveLocal(); renderYtOptions(); renderActiveStrip(); renderFormatChips(); syncFetch(); }

function renderActiveStrip(){
  const keys = Object.keys(ytOpts).filter(k=>ytOpts[k]!=='' && ytOpts[k]!==false);
  const strip = $('#activeStrip');
  if(!keys.length){ strip.innerHTML = '<span class="none">No options set — defaults will be used.</span>'; return; }
  const idx = {}; BOOT.ytdlp_options.forEach(o=>idx[o.id]=o);
  strip.innerHTML = keys.map(k=>{
    const o = idx[k]||{label:k}; const v = ytOpts[k];
    const shown = v === true ? '' : ': ' + String(v).slice(0,26).replace(/\n/g,' ');
    return `<span class="set" title="Remove this option" data-act="unsetOpt" data-k="${esc(k)}"><b>${esc(o.label)}</b>${esc(shown)} ×</span>`;
  }).join('');
}

function fetchSpec(extra={}){
  return Object.assign({
    urls: $('#dlUrls').value,
    opts: ytOpts,
    split_jobs: $('#dlSplit').checked
  }, extra);
}

function paintCmd(el, cmd){
  const parts = String(cmd || '').match(/'[^']*'|"[^"]*"|\S+/g) || [];
  el.innerHTML = parts.map((p, i) => {
    if(i === 0) return `<span class="bin">${esc(p)}</span>`;
    if(p.startsWith('-')) return `<span class="flag">${esc(p)}</span>`;
    return `<span class="str">${esc(p)}</span>`;
  }).join(' ') + `<button class="copy-btn" data-act="copyEl">Copy</button>`;
}

on('optGroup',     d=>pickOptGroup(d.g));
on('pickOp',       d=>pickOp(d.o));
on('setContainer', d=>setContainer(d.c));
on('unsetOpt',     d=>setOpt(d.k, ''));
on('fmtPreset',    d=>applyFormatPreset(+d.i));
on('tplPreset',    d=>{
  const val = BOOT.output_presets[+d.i].value;
  if(val.startsWith('chapter:')){
    setOpt('output_chapter', val.slice('chapter:'.length));
    setOpt('split_chapters', true);
  } else {
    setOpt('output', val);
  }
  renderYtOptions();
});
on('insToken',     d=>insertToken(d.t));
on('setAccent',    d=>setAccent(d.a));
on('palRun',       d=>runPal(+d.i));
on('kindChip',     (d, el)=>{ el.classList.toggle('on'); loadLibrary(); });
on('copyEl', (d, el)=>{
  // The button lives inside the block it copies, so its own label has to go.
  const host = el.classList.contains('copy-btn') ? el.parentElement : el;
  const text = Array.from(host.childNodes)
    .filter(n=>!(n.nodeType===1 && n.classList && n.classList.contains('copy-btn')))
    .map(n=>n.textContent).join('').trim();
  copyText(text);
});

function optLabel(id){
  const o = BOOT.ytdlp_options.find(x=>x.id===id);
  return o ? o.label : id;
}

// Every option any preset can switch on. A preset owns this whole set, not just
// the keys it happens to set, so moving from an audio preset to a video one
// clears the extraction flag instead of leaving it silently enabled.
function renderFormatChips(){
  const cur = ytOpts.format || '';
  $('#fmtChips').innerHTML = BOOT.format_presets.map((p,i)=>{
    const extras = Object.keys(p.sets||{});
    const tip = esc(p.value) + (extras.length
      ? ' — also turns on: ' + extras.map(k=>optLabel(k)).join(', ') : '');
    return `<button class="chip ${p.value===cur?'on':''}" title="${tip}"
      data-act="fmtPreset" data-i="${i}">${esc(p.label)}</button>`;
  }).join('');
}

function presetManagedKeys(){
  const keys = new Set();
  BOOT.format_presets.forEach(p=>Object.keys(p.sets||{}).forEach(k=>keys.add(k)));
  return keys;
}

function applyFormatPreset(i){
  const p = BOOT.format_presets[i];
  const sets = p.sets || {};
  const cleared = [];
  presetManagedKeys().forEach(k=>{
    if(!(k in sets) && ytOpts[k]){ delete ytOpts[k]; cleared.push(k); }
  });
  ytOpts.format = p.value;
  Object.entries(sets).forEach(([k,v])=>{ ytOpts[k] = v; });
  saveLocal(); renderYtOptions(); renderActiveStrip(); renderFormatChips(); syncFetch();

  const added = Object.keys(sets).map(optLabel);
  const detail = [added.length ? 'on: '+added.join(', ') : '',
                  cleared.length ? 'off: '+cleared.map(optLabel).join(', ') : '']
                 .filter(Boolean).join('  \u00b7  ');
  toast(p.label, detail);
}

function applyFix(json){
  const patch = JSON.parse(json);
  Object.entries(patch).forEach(([k,v])=>{ ytOpts[k] = v; });
  saveLocal(); renderYtOptions(); renderActiveStrip(); syncFetch();
  toast('Applied', Object.keys(patch).map(optLabel).join(', '));
}

function renderTplSummary(){
  const el = $('#tplSummary'); if(!el) return;
  const t = ytOpts.output || '';
  el.textContent = t ? (t.length > 34 ? t.slice(0,33)+'…' : t) : 'default template';
}

function renderWarnings(list){
  const host = $('#dlWarnings');
  if(!list || !list.length){ host.innerHTML = ''; return; }
  host.innerHTML = list.map(w=>`
    <div class="note ${w.level==='block'?'':'info'}">
      <b>${esc(w.text)}</b>
      ${w.why?`<div style="margin-top:3px;opacity:.85">${esc(w.why)}</div>`:''}
      ${w.fix?`<div style="margin-top:3px">${esc(w.fix)}</div>`:''}
      ${w.apply?`<button class="btn sm alt" style="margin-top:7px"
        onclick='applyFix(${JSON.stringify(JSON.stringify(w.apply)).replace(/'/g,"&#39;")})'>${
        esc(w.apply_label||'Fix this')}</button>`:''}
    </div>`).join('');
}

const syncFetch = debounce(async ()=>{
  const urls = $('#dlUrls').value.split('\n').filter(u=>u.trim() && !u.trim().startsWith('#'));
  $('#urlCount').textContent = urls.length ? `${urls.length} link${urls.length>1?'s':''}` : 'no links yet';
  try{
    const j = await api('/api/ytdlp/preview', {method:'POST', body:JSON.stringify(fetchSpec())});
    paintCmd($('#dlCmd'), j.cmd);
    renderWarnings(j.warnings);
  }catch(e){ $('#dlCmd').textContent = e.message; }
  saveLocal();
}, 200);

async function runFetch(extra){
  const spec = fetchSpec();
  if(extra && extra.simulate) spec.opts = Object.assign({}, spec.opts, {simulate:true});
  if(extra && extra.ignore) spec.ignore_warnings = true;
  if(!spec.urls.trim()) return toast('Add a link first','Paste at least one URL into Sources.','bad');
  try{
    const r = await fetch('/api/ytdlp/run', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(spec)});
    const j = await r.json();
    if(r.status === 409 && j.blocked){ showBlocker(j.warnings); return; }
    if(!r.ok || j.ok === false) throw new Error(j.error || 'Request failed');
    const n = j.jobs ? j.jobs.length : 1;
    toast(`Queued ${n} job${n>1?'s':''}`, extra&&extra.simulate?'Simulating — nothing will be written.':'');
    openDock();
    if(j.job) selectJob(j.job);
  }catch(e){ fail(e); }
}

function showBlocker(warnings){
  const w = (warnings||[]).find(x=>x.level==='block') || {};
  modal('This will not work as configured', `
    <div class="note"><b>${esc(w.text||'')}</b>
      ${w.why?`<div style="margin-top:6px;opacity:.85">${esc(w.why)}</div>`:''}
      ${w.fix?`<div style="margin-top:6px">${esc(w.fix)}</div>`:''}</div>`,
    `${w.apply?`<button class="btn go" onclick='applyFix(${
      JSON.stringify(JSON.stringify(w.apply)).replace(/'/g,"&#39;")});closeModal()'>${
      esc(w.apply_label||'Fix this')}</button>`:''}
     <button class="btn" onclick="closeModal();runFetch({ignore:true})">Download anyway</button>`);
}

async function pasteUrls(){
  try{
    const t = await navigator.clipboard.readText();
    const box = $('#dlUrls');
    box.value = (box.value.trim() ? box.value.replace(/\s*$/,'\n') : '') + t.trim();
    syncFetch();
  }catch(e){ toast('Clipboard unavailable','Your browser blocked the read. Paste with Ctrl+V instead.','bad'); }
}

function goFormats(){
  const first = $('#dlUrls').value.split('\n').find(u=>u.trim() && !u.trim().startsWith('#'));
  if(first) $('#fmtUrl').value = first.trim();
  show('formats');
  if(first) loadFormats();
}

/* ══════════════════════════════════════════════════════════════════════
   FORMATS
   ══════════════════════════════════════════════════════════════════════ */
async function loadFormats(flat){
  const url = $('#fmtUrl').value.trim();
  if(!url) return toast('Add a link first','Paste the URL you want to inspect.','bad');
  $('#fmtInfo').innerHTML = '<div class="empty"><b>Asking the site…</b>This can take a few seconds.</div>';
  $('#fmtTable').innerHTML = '';
  try{
    const j = await api('/api/ytdlp/info', {method:'POST', body:JSON.stringify({url, flat:!!flat})});
    if(j.kind === 'playlist'){ renderPlaylist(j); return; }
    fmtState.rows = j.formats; fmtState.sel = new Set(); fmtState.info = j.info;
    renderVideoInfo(j.info); $('#fmtFilters').hidden = false; renderFormats();
  }catch(e){ $('#fmtInfo').innerHTML = `<div class="note">${esc(e.message)}</div>`; }
}

function renderVideoInfo(i){
  $('#fmtInfo').innerHTML = `
    <div class="panel"><div class="panel-body" style="display:grid;grid-template-columns:auto 1fr;gap:16px">
      ${i.thumbnail?`<img src="${esc(i.thumbnail)}" style="width:260px;border-radius:4px;border:1px solid var(--seam)">`:''}
      <div>
        <h2 style="font-size:1rem;margin-bottom:7px">${esc(i.title||'Untitled')}</h2>
        <dl class="kv">
          <dt>Channel</dt><dd>${esc(i.uploader||'—')}</dd>
          <dt>Duration</dt><dd>${esc(i.duration_h||'—')}</dd>
          <dt>Uploaded</dt><dd>${esc(i.upload_date||'—')}</dd>
          <dt>Views</dt><dd>${i.view_count!=null?Number(i.view_count).toLocaleString():'—'}</dd>
          <dt>Source</dt><dd>${esc(i.extractor||'—')}${i.is_live?' · live':''}</dd>
          <dt>Chapters</dt><dd>${(i.chapters||[]).length}</dd>
          <dt>Subtitles</dt><dd>${(i.subtitles||[]).join(', ')||'none'}</dd>
          <dt>Auto captions</dt><dd>${(i.auto_captions||[]).slice(0,14).join(', ')||'none'}</dd>
        </dl>
        <div class="btns" style="margin-top:10px">
          <button class="btn sm" data-act="fmtToFetch">Send to Fetch</button>
          ${(i.chapters||[]).length?`<button class="btn sm alt" data-act="fmtChapters">View chapters</button>`:''}
        </div>
      </div></div></div>`;
}

function showChapters(){
  const ch = (fmtState.info.chapters||[]);
  modal('Chapters', `<div class="tbl-wrap"><table><thead><tr><th>#</th><th>Start</th><th>End</th><th>Title</th></tr></thead>
    <tbody>${ch.map((c,n)=>`<tr><td class="num">${n+1}</td><td class="mono">${fmtDur(c.start_time)}</td>
    <td class="mono">${fmtDur(c.end_time)}</td><td>${esc(c.title||'')}</td></tr>`).join('')}</tbody></table></div>`);
}

function renderPlaylist(j){
  $('#fmtFilters').hidden = true;
  $('#fmtInfo').innerHTML = `<div class="panel"><div class="panel-head"><h3>${esc(j.title||'Playlist')}</h3>
    <span class="hint">${j.count} entries</span><div class="spacer"></div>
    <button class="btn sm alt" data-act="plSelToFetch">Send selected to Fetch</button>
    <button class="btn sm" data-act="plAllToFetch">Send all to Fetch</button></div></div>`;
  window._pl = j.entries;
  window._plSel = new Set();
  $('#fmtTable').innerHTML = `<div class="tbl-wrap"><table><thead><tr><th></th><th>#</th><th>Title</th><th>Channel</th><th>Length</th><th></th></tr></thead>
    <tbody>${j.entries.map((e,n)=>`<tr>
      <td><input type="checkbox" data-act="plToggle" data-i="${n}"></td>
      <td class="num">${n+1}</td><td>${esc(e.title||e.id)}</td>
      <td>${esc(e.uploader||'')}</td><td class="mono">${esc(e.duration_h||'')}</td>
      <td><button class="btn sm" data-act="plOneToFetch" data-i="${n}">Fetch</button></td>
    </tr>`).join('')}</tbody></table></div>`;
}
function playlistToFetch(onlySelected){
  const entries = window._pl || [];
  const chosen = onlySelected
    ? entries.filter((_, i) => window._plSel && window._plSel.has(i))
    : entries;
  if(onlySelected && !chosen.length) return toast('Nothing selected', 'Tick playlist entries first.', 'bad');
  $('#dlUrls').value = chosen.map(e=>e.url).filter(Boolean).join('\n');
  show('fetch'); syncFetch();
}

on('fmtFilter', (d, el)=>{
  $$('#fmtFilters .chip').forEach(c=>c.classList.remove('on'));
  el.classList.add('on'); fmtState.filter = d.k; renderFormats();
});
on('fmtSort',  d=>fmtSort(d.k));
on('fmtPick',  d=>{ const r = (fmtState.view||[])[+d.i]; if(r) toggleFmt(r.format_id); });
on('fmtToFetch', ()=>{ $('#dlUrls').value = (fmtState.info||{}).webpage_url || ''; show('fetch'); syncFetch(); });
on('fmtChapters', ()=>showChapters());
on('plAllToFetch', ()=>playlistToFetch(false));
on('plSelToFetch', ()=>playlistToFetch(true));
on('plToggle', d=>{
  window._plSel = window._plSel || new Set();
  const idx = +d.i;
  window._plSel.has(idx) ? window._plSel.delete(idx) : window._plSel.add(idx);
});
on('plOneToFetch', d=>{ $('#dlUrls').value = (window._pl||[])[+d.i].url || ''; show('fetch'); syncFetch(); });
function fmtSort(key){
  if(fmtState.sort===key) fmtState.desc = !fmtState.desc; else { fmtState.sort=key; fmtState.desc=true; }
  renderFormats();
}
function renderFormats(){
  let rows = fmtState.rows.slice();
  if(fmtState.filter!=='all') rows = rows.filter(r=>r.kind===fmtState.filter);
  const k = fmtState.sort;
  rows.sort((a,b)=>{ const x=a[k]??0, y=b[k]??0;
    return (typeof x==='string'? String(x).localeCompare(String(y)) : x-y) * (fmtState.desc?-1:1); });
  fmtState.view = rows;
  const cols = [['format_id','ID'],['ext','Ext'],['kind','Type'],['resolution','Resolution'],
    ['fps','FPS'],['vcodec','Video'],['acodec','Audio'],['tbr','kbps'],['filesize','Size'],
    ['dynamic_range','HDR'],['protocol','Protocol'],['format_note','Note']];
  $('#fmtTable').innerHTML = `<div class="tbl-wrap"><table><thead><tr><th></th>${
    cols.map(c=>`<th class="${fmtState.sort===c[0]?'sorted':''}" data-act="fmtSort" data-k="${c[0]}">${c[1]}</th>`).join('')
  }</tr></thead><tbody>${rows.map((r,ri)=>`
    <tr class="${fmtState.sel.has(r.format_id)?'picked':''}" data-act="fmtPick" data-i="${ri}">
      <td><input type="checkbox" ${fmtState.sel.has(r.format_id)?'checked':''} data-act="fmtPick" data-i="${ri}" data-stop="1"></td>
      <td class="mono">${esc(r.format_id)}</td><td>${esc(r.ext||'')}</td>
      <td><span class="tag ${r.kind}">${esc(r.kind)}</span></td>
      <td class="mono">${esc(r.resolution||'—')}</td><td class="num">${r.fps||''}</td>
      <td class="mono">${esc((r.vcodec||'').split('.')[0])}</td>
      <td class="mono">${esc((r.acodec||'').split('.')[0])}</td>
      <td class="num">${r.tbr?Math.round(r.tbr):''}</td>
      <td class="num">${esc(r.filesize_h||'')}</td>
      <td>${esc(r.dynamic_range||'')}</td><td>${esc(r.protocol||'')}</td>
      <td class="muted">${esc(r.format_note||'')}</td></tr>`).join('')}</tbody></table></div>`;
  updateFmtPick();
}
function sortedFmtIds(){
  const order = { video: 0, both: 1, audio: 2 };
  return Array.from(fmtState.sel).sort((a, b) => {
    const ra = fmtState.rows.find(r => r.format_id === a) || {};
    const rb = fmtState.rows.find(r => r.format_id === b) || {};
    return (order[ra.kind] ?? 3) - (order[rb.kind] ?? 3);
  });
}
function toggleFmt(id){
  fmtState.sel.has(id) ? fmtState.sel.delete(id) : fmtState.sel.add(id);
  renderFormats();
}
function updateFmtPick(){
  const ids = sortedFmtIds();
  if(!ids.length){ $('#fmtPick').textContent = 'nothing selected'; return; }
  const totalBytes = ids.reduce((sum, id) => {
    const r = fmtState.rows.find(x => x.format_id === id);
    return sum + (r && r.filesize ? Number(r.filesize) : 0);
  }, 0);
  const sizeTxt = totalBytes > 0 ? ` (~${(totalBytes / 1048576).toFixed(1)} MB)` : '';
  $('#fmtPick').textContent = ids.join('+') + sizeTxt;
}
function useSelectedFormats(){
  if(!fmtState.sel.size) return toast('Nothing selected','Tick the rows you want first.','bad');
  const ids = sortedFmtIds();
  ytOpts.format = ids.join('+');
  const selectedRows = ids.map(id => fmtState.rows.find(r => r.format_id === id)).filter(Boolean);
  if(selectedRows.length && selectedRows.every(r => r.kind === 'audio')){
    ytOpts.extract_audio = true;
  } else if(selectedRows.some(r => r.kind === 'video' || r.kind === 'both')){
    delete ytOpts.extract_audio;
  }

  // Format IDs like "137+140" belong to the video they were read from — they
  // mean nothing on any other link. So the URL box is set to that video rather
  // than left holding whatever was there before.
  const url = (fmtState.info || {}).webpage_url || $('#fmtUrl').value.trim();
  let replaced = false;
  if(url){
    const existing = $('#dlUrls').value.split('\n').map(s=>s.trim()).filter(Boolean);
    replaced = existing.length > 0 && !(existing.length === 1 && existing[0] === url);
    $('#dlUrls').value = url;
  }
  show('fetch'); renderYtOptions(); renderActiveStrip(); renderFormatChips(); syncFetch();
  toast('Format applied', replaced
    ? `${ytOpts.format} — the link was replaced, since these IDs only apply to that video`
    : ytOpts.format);
}

