/* ══════════════════════════════════════════════════════════════════════
   INSPECTOR
   ══════════════════════════════════════════════════════════════════════ */
async function doProbe(fresh){
  const path = $('#probePath').value.trim();
  if(!path) return toast('Give a file path','Type or paste the path you want to inspect.','bad');
  $('#probeOut').innerHTML = '<div class="empty">Reading…</div>';
  try{
    const j = await api('/api/probe',{method:'POST',body:JSON.stringify({path, fresh:!!fresh})});
    renderProbe(j.summary, path);
  }catch(e){ $('#probeOut').innerHTML = `<div class="note">${esc(e.message)}</div>`; }
}

let probePath = '', probeChapters = [];
on('probeUse',      d=>useStream(probePath, d.t, +d.n));
on('probeToLab',    ()=>sendToLab(probePath));
on('probePreview',  ()=>previewFile(probePath));
on('probeSplitCh',  ()=>sendToLab(probePath, 'split_chapters'));
on('probeClip',     d=>{ const c = probeChapters[+d.i]; clipChapter(probePath, c.start, c.end); });

function renderProbe(s, path){
  probePath = path; probeChapters = s.chapters || [];
  const typeCounts = {};
  const streamRows = s.streams.map(st=>{
    const relativeIndex = typeCounts[st.type] || 0;
    typeCounts[st.type] = relativeIndex + 1;
    const extra = st.type==='video'
      ? `${st.width}×${st.height} · ${String(st.fps||'').replace('/1','')} fps · ${st.pix_fmt||''}`
      : st.type==='audio'
      ? `${st.sample_rate||''} Hz · ${st.channel_layout||st.channels||''} · ${st.sample_fmt||''}`
      : (st.title||'');
    return `<tr>
      <td class="num mono">${st.index}</td>
      <td><span class="tag ${st.type==='subtitle'?'subtitle':st.type}">${esc(st.type)}</span></td>
      <td class="mono">${esc(st.codec||'')}</td>
      <td>${esc(st.language||'—')}</td>
      <td class="muted">${esc(extra)}</td>
      <td class="num mono">${st.bitrate?Math.round(st.bitrate/1000)+'k':''}</td>
      <td>${st.default?'default ':''}${st.forced?'forced':''}</td>
      <td><button class="btn sm" data-act="probeUse" data-t="${st.type}" data-n="${relativeIndex}">Use</button></td></tr>`;
  }).join('');
  $('#probeOut').innerHTML = `
    <div class="cols">
      <div class="panel"><div class="panel-head"><h3>Container</h3></div><div class="panel-body">
        <dl class="kv">
          <dt>File</dt><dd>${esc(s.filename||'')}</dd>
          <dt>Format</dt><dd>${esc(s.format_long||s.format_name||'')}</dd>
          <dt>Duration</dt><dd>${fmtDur(s.duration)}</dd>
          <dt>Size</dt><dd>${fmtBytes(s.size)}</dd>
          <dt>Bitrate</dt><dd>${s.bitrate?Math.round(s.bitrate/1000)+' kbps':'—'}</dd>
          <dt>Streams</dt><dd>${s.nb_streams}</dd>
          ${Object.entries(s.tags||{}).slice(0,10).map(([k,v])=>
            `<dt>${esc(k)}</dt><dd>${esc(String(v).slice(0,200))}</dd>`).join('')}
        </dl>
        <div class="btns" style="margin-top:11px">
          <button class="btn sm alt" data-act="probeToLab">Send to Media lab</button>
          <button class="btn sm" data-act="probePreview">Preview</button>
        </div></div></div>
      <div class="panel"><div class="panel-head"><h3>Streams</h3></div><div class="panel-body" style="padding:0">
        <div class="tbl-wrap" style="border:0">
          <table><thead><tr><th>#</th><th>Type</th><th>Codec</th><th>Lang</th><th>Details</th><th>kbps</th><th>Flags</th><th></th></tr></thead>
          <tbody>${streamRows}</tbody></table></div></div></div>
    </div>
    ${s.chapters.length?`<div class="panel"><div class="panel-head"><h3>Chapters</h3>
      <span class="hint">${s.chapters.length}</span><div class="spacer"></div>
      <button class="btn sm alt" data-act="probeSplitCh">Split by chapter</button></div>
      <div class="panel-body" style="padding:0"><div class="tbl-wrap" style="border:0"><table>
      <thead><tr><th>#</th><th>Start</th><th>End</th><th>Title</th><th></th></tr></thead><tbody>
      ${s.chapters.map((c,n)=>`<tr><td class="num">${n+1}</td><td class="mono">${fmtDur(c.start)}</td>
        <td class="mono">${fmtDur(c.end)}</td><td>${esc(c.title)}</td>
        <td><button class="btn sm" data-act="probeClip" data-i="${n}">Clip</button></td></tr>`).join('')}
      </tbody></table></div></div></div>`:''}`;
}
function useStream(path, type, index){
  const op = type==='audio' ? 'extract_audio'
           : type==='subtitle' ? 'extract_subs' : 'extract_video';
  sendToLab(path, op);
  lab.params.index = index;
  renderLab();
}
function clipChapter(path, start, end){
  sendToLab(path, 'trim');
  $('#seekSS').value = fmtDur(start); $('#seekTo').value = fmtDur(end);
  syncLab();
}

/* ══════════════════════════════════════════════════════════════════════
   LIBRARY
   ══════════════════════════════════════════════════════════════════════ */
const KINDS = ['video','audio','image','subtitle','data','other'];
function renderKindChips(){
  $('#kindChips').innerHTML = KINDS.map(k=>
    `<button class="chip" data-k="${esc(k)}" data-act="kindChip">${esc(k)}</button>`).join('');
}
async function loadLibrary(){
  // A refresh can replace the previewed file; do not leave an orphan playing.
  if(libState.reloading) stopPreviewMedia();
  const kinds = $$('#kindChips .chip.on').map(c=>c.dataset.k).join(',');
  const p = new URLSearchParams({ dir:libState.dir, q:$('#libSearch').value,
    recursive:$('#libRecursive').checked?'1':'0', kind:kinds });
  try{
    const j = await api('/api/files?'+p);
    libState.base = j.base; libState.files = j.files; libState.dirs = j.dirs;
    libState.parent = j.parent; libState.roots = j.roots;
    renderCrumbs(); renderLibrary();
  }catch(e){ $('#libList').innerHTML = `<div class="note">${esc(e.message)}</div>`; }
}
function renderCrumbs(){
  const parts = (libState.base||'').split('/').filter(Boolean);
  let acc = '';
  crumbPaths = [''];
  $('#crumbs').innerHTML = `<button data-act="libCrumb" data-i="0">home</button>` + parts.map(p=>{
    acc += '/'+p; crumbPaths.push(acc);
    return ` / <button data-act="libCrumb" data-i="${crumbPaths.length-1}">${esc(p)}</button>`;
  }).join('');
}
function libGo(dir){ libState.dir = dir; libState.sel.clear(); loadLibrary(); }
function libSort(k){
  if(libState.sort===k) libState.desc=!libState.desc; else {libState.sort=k;libState.desc=true;}
  renderLibrary();
}
function renderLibrary(){
  const k = libState.sort;
  const files = libState.files.slice().sort((a,b)=>{
    const x=a[k], y=b[k];
    return (typeof x==='string'? x.localeCompare(y) : (x||0)-(y||0)) * (libState.desc?-1:1);
  });
  // Rows are rendered from this sorted copy, so the indices in the markup must
  // resolve against it too. Indexing the unsorted array made every button act
  // on a different file than the one it sat next to.
  libState.view = files;
  const dirsHtml = libState.dirs.map((d,di)=>
    `<div class="filerow" data-act="libOpenDir" data-i="${di}">
      <span><span class="tag other">DIR</span></span>
      <span class="fname">${esc(d.name)}/</span>
      <span class="fmeta size">${d.entries} items</span>
      <span class="fmeta date"></span>
      <span></span></div>`).join('');
  const grid = $('#libGrid').checked;
  const filesHtml = grid
    ? `<div class="grid-files">${files.map((f,fi)=>{
        const c = f.caps || {};
        return `
        <div class="card ${libState.sel.has(f.path)?'picked':''} ${c.partial?'partial':''}"
          ${c.process?`data-act="libToggle" data-i="${fi}"`:''}>
          <div class="thumb">${['video','image'].includes(f.kind) && !c.partial
            ? `<img loading="lazy" src="/api/thumb?path=${encodeURIComponent(f.path)}" onerror="this.replaceWith(document.createTextNode('▤'))">`
            : (c.partial?'⋯':(f.kind==='audio'?'♪':'▤'))}</div>
          <div class="cap"><div class="n" title="${esc(f.name)}">${esc(f.name)}</div>
            <div class="m">${esc(f.size_h)} · ${esc(c.partial?'incomplete':f.ext)}</div></div></div>`;}).join('')}</div>`
    : `<div class="tbl-wrap"><div class="filerow head">
        <span></span>
        <span class="lbl" style="margin:0;cursor:pointer" onclick="libSort('name')">Name</span>
        <span class="lbl fmeta size" style="margin:0;cursor:pointer" onclick="libSort('size')">Size</span>
        <span class="lbl fmeta date" style="margin:0;cursor:pointer" onclick="libSort('mtime')">Modified</span>
        <span></span></div>
      ${dirsHtml}
      ${files.map((f,fi)=>{
        const c = f.caps || {};
        return `
        <div class="filerow ${libState.sel.has(f.path)?'picked':''} ${c.partial?'partial':''}"
          data-row="${fi}" ${c.process?`data-act="libToggle" data-i="${fi}"`:''}
          title="${c.partial?'Still downloading or left over from an interrupted run':''}">
          <span><span class="tag ${f.kind}">${esc(c.partial?'part':(f.ext||'?'))}</span></span>
          <span class="fname" title="${esc(f.path)}">${esc(f.rel||f.name)}</span>
          <span class="fmeta size">${esc(f.size_h)}</span>
          <span class="fmeta date">${esc(f.mtime_h)}</span>
          <button class="rowmenu-btn" data-act="libMenu" data-i="${fi}" data-stop="1"
            aria-label="Actions">⋯</button>
        </div>`;}).join('')}</div>`;
  $('#libList').innerHTML = (dirsHtml||files.length)
    ? (grid ? dirsHtml + (files.length?filesHtml:'') : filesHtml)
    : `<div class="empty"><b>Nothing here</b>Downloads will show up in this folder.</div>`;
  updateLibSel();
}
let crumbPaths = [''];

/* ── Row actions menu ──────────────────────────────────────────────────
   Opened from the ⋯ button so the row itself can give its width to the
   file name. Positioned against the button and clamped to the viewport. */
function closeRowMenu(){
  const m = $('#rowmenu');
  if(m) m.hidden = true;
  $$('.filerow.menuopen').forEach(r=>r.classList.remove('menuopen'));
}

on('libMenu', (d, el)=>{
  const i = +d.i, f = libState.view[i];
  if(!f) return;
  const c = f.caps || {};
  let m = $('#rowmenu');
  if(!m){
    m = document.createElement('div');
    m.className = 'rowmenu'; m.id = 'rowmenu'; m.hidden = true;
    document.body.appendChild(m);
  }
  const row = el.closest('.filerow');
  const already = row.classList.contains('menuopen');
  closeRowMenu();
  if(already) return;
  row.classList.add('menuopen');

  m.innerHTML = `
    <div class="rm-head">${esc(f.name)}</div>
    ${c.preview?`<button data-act="libPreview" data-i="${i}">${
      ['video','audio'].includes(f.kind)?'Play':'View'}</button>`:''}
    ${c.process?`<button data-act="libToLab" data-i="${i}">Send to Media lab</button>`:''}
    ${c.probe?`<button data-act="libToProbe" data-i="${i}">Inspect</button>`:''}
    ${(c.preview||c.process||c.probe)?'<div class="rm-sep"></div>':''}
    <button data-act="libRename" data-i="${i}">Rename</button>
    <button data-act="libMove" data-i="${i}">Move…</button>
    <a href="/api/files/download?path=${encodeURIComponent(f.path)}">Download</a>
    <button data-act="libCopyPath" data-i="${i}">Copy path</button>
    <div class="rm-sep"></div>
    <button class="bad" data-act="libDelete" data-i="${i}">Delete</button>`;

  m.hidden = false;
  const r = el.getBoundingClientRect(), mb = m.getBoundingClientRect();
  let top = r.bottom + 4, left = r.right - mb.width;
  if(top + mb.height > window.innerHeight - 8) top = Math.max(8, r.top - mb.height - 4);
  m.style.top = top + 'px';
  m.style.left = Math.max(8, left) + 'px';
});

on('libCopyPath', d=>{ copyText(libState.view[+d.i].path); closeRowMenu(); });

// Any click outside the menu, any scroll, and any view change dismisses it.
document.addEventListener('click', e=>{
  if(!e.target.closest('#rowmenu') && !e.target.closest('[data-act="libMenu"]')) closeRowMenu();
}, true);
window.addEventListener('resize', closeRowMenu);


on('libToggle',  d=>toggleFile(libState.view[+d.i].path));
on('libPreview', d=>{ closeRowMenu(); previewFile(libState.view[+d.i].path); });
on('libToLab',   d=>{ closeRowMenu(); sendToLab(libState.view[+d.i].path); });
on('libToProbe', d=>{ closeRowMenu(); $('#probePath').value = libState.view[+d.i].path; show('inspect'); doProbe(); });
on('libRename',  d=>{ const f = libState.view[+d.i]; closeRowMenu(); renameFile(f.path, f.name); });
on('libDelete',  d=>{ closeRowMenu(); deleteFiles([libState.view[+d.i].path]); });
on('libOpenDir', d=>libGo(libState.dirs[+d.i].path));
on('libCrumb',   d=>libGo(crumbPaths[+d.i]));
on('libPreviewClose', ()=>{ stopPreviewMedia(); $('#libPreview').innerHTML = ''; });
on('libPreviewToLab', ()=>sendToLab(previewPath));

function toggleFile(p){
  const f = libState.files.find(x=>x.path===p);
  if(f && f.caps && !f.caps.process){
    toast('Not usable as an input', f.caps.partial
      ? 'This file is still being written or was left behind by an interrupted download.'
      : 'No decoder for this file type.', 'bad');
    return;
  }
  libState.sel.has(p)?libState.sel.delete(p):libState.sel.add(p); renderLibrary();
}
function clearSelection(){ libState.sel.clear(); renderLibrary(); }
function updateLibSel(){
  const n = libState.sel.size;
  $('#libActions').hidden = n===0;
  $('#libSel').textContent = `${n} selected`;
}
function sendSelection(where){
  const selectedFiles = libState.files.filter(f => libState.sel.has(f.path) && (!f.caps || f.caps.process || f.kind === 'subtitle'));
  const sel = selectedFiles.map(f => f.path);
  if(!sel.length) return toast('Nothing selected', 'Select files ffmpeg can use.', 'bad');

  if(where === 'lab'){
    const kinds = selectedFiles.map(f => f.kind);
    let targetOp = lab.op;
    let ordered = sel.slice();

    if(sel.length === 2){
      const vIdx = kinds.indexOf('video'), aIdx = kinds.indexOf('audio'),
            sIdx = kinds.indexOf('subtitle'), iIdx = kinds.indexOf('image');
      if(vIdx !== -1 && sIdx !== -1){
        targetOp = 'add_subs'; ordered = [sel[vIdx], sel[sIdx]];
      } else if(vIdx !== -1 && aIdx !== -1){
        targetOp = 'add_audio'; ordered = [sel[vIdx], sel[aIdx]];
      } else if(aIdx !== -1 && iIdx !== -1){
        targetOp = 'add_cover'; ordered = [sel[aIdx], sel[iIdx]];
      } else if(vIdx !== -1 && iIdx !== -1 && !['watermark','pip','stack'].includes(lab.op)){
        targetOp = 'watermark'; ordered = [sel[vIdx], sel[iIdx]];
      } else if(kinds[0] === 'video' && kinds[1] === 'video' && (opMeta().inputs === 1)){
        targetOp = 'concat';
      }
    } else if(sel.length > 2 && opMeta().inputs !== 0){
      targetOp = 'concat';
    } else if(sel.length === 1 && kinds[0] === 'audio' && !['audio_convert','extract_audio','loudnorm2','trim','transcode','probe','silencedetect','waveform','spectrogram','visualizer'].includes(lab.op)){
      targetOp = 'audio_convert';
    }

    if(targetOp !== lab.op){
      lab.op = targetOp; lab.params = {}; lab.enc = {};
      toast('Switched operation', (BOOT.ff_ops.find(o => o.id === targetOp) || {}).label || targetOp);
    }
    const m = opMeta();
    const maxIn = m.inputs === 0 ? ordered.length : Math.max(1, m.inputs || 1);
    lab.inputs = ordered.slice(0, maxIn);
    while(lab.inputs.length < (m.inputs || 1)) lab.inputs.push('');
    lab.output_mode = 'auto';
    lab.output = suggestedOutput(lab.inputs[0], lab.op);
    $('#labOut').value = lab.output;
    show('lab'); renderLab();
    return;
  }
  if(where === 'batch'){ batchFiles = Array.from(new Set(batchFiles.concat(sel))); show('batch'); renderBatch(); }
  if(where === 'pipeline'){ $('#pipeIn').value = sel[0]; show('pipeline'); syncPipeline(); }
  if(where === 'inspect'){ $('#probePath').value = sel[0]; show('inspect'); doProbe(); }
}
async function deleteSelection(){ deleteFiles(Array.from(libState.sel)); }
async function deleteFiles(paths){
  if(!paths.length) return;
  if(BOOT.config.confirm_destructive &&
     !confirm(`Delete ${paths.length} item${paths.length>1?'s':''}? This cannot be undone.`)) return;
  try{ const j = await api('/api/files/delete',{method:'POST',body:JSON.stringify({paths})});
    toast(`Deleted ${j.removed}`); libState.sel.clear();
    if(paths.includes(previewPath)){ stopPreviewMedia(); $('#libPreview').innerHTML = ''; }
    loadLibrary();
  }catch(e){ fail(e); }
}
async function renameFile(path, name){
  const n = prompt('New name', name); if(!n || n===name) return;
  try{ await api('/api/files/rename',{method:'POST',body:JSON.stringify({path,name:n})});
    toast('Renamed'); loadLibrary(); }catch(e){ fail(e); }
}
async function newFolder(){
  const n = prompt('Folder name'); if(!n) return;
  try{ await api('/api/files/mkdir',{method:'POST',body:JSON.stringify({dir:libState.base,name:n})});
    loadLibrary(); }catch(e){ fail(e); }
}
on('libMove', d=>{ closeRowMenu(); moveFiles([libState.view[+d.i].path]); });
async function moveSelection(){ return moveFiles(Array.from(libState.sel)); }
async function moveFiles(paths){
  if(!paths.length) return;
  const dest = prompt('Move to folder', libState.base || '');
  if(!dest) return;
  try{
    const j = await api('/api/files/move',{method:'POST',body:JSON.stringify({paths, dest})});
    toast(`Moved ${j.moved} file(s)`); libState.sel.clear(); loadLibrary();
  }catch(e){ fail(e); }
}
let previewPath = '', prevIn = 0, prevOut = 0;
function markPrevIn(){ const m = $('#prevMedia'); if(m){ prevIn = m.currentTime || 0; $('#prevInLbl').textContent = prevIn.toFixed(2)+'s'; } }
function markPrevOut(){ const m = $('#prevMedia'); if(m){ prevOut = m.currentTime || 0; $('#prevOutLbl').textContent = prevOut.toFixed(2)+'s'; } }
function grabPrevFrame(){
  const m = $('#prevMedia'); const t = m ? (m.currentTime || 0).toFixed(3) : '0';
  lab.op = 'screenshot'; lab.inputs = [previewPath]; lab.params = {time: t};
  lab.output_mode = 'auto'; lab.output = suggestedOutput(previewPath, 'screenshot');
  $('#labOut').value = lab.output; show('lab'); renderLab();
}
function trimPrevInOut(){
  const a = Math.min(prevIn, prevOut || prevIn), b = Math.max(prevIn, prevOut);
  if(b <= a) return toast('Set In and Out points first', 'Play/seek and click [ In and Out ].', 'bad');
  clipChapter(previewPath, a, b);
}
function previewFile(path){
  stopPreviewMedia();
  const url = '/api/media?path='+encodeURIComponent(path);
  const ext = path.split('.').pop().toLowerCase();
  const isVid = ['mp4','mkv','webm','mov','m4v','ogv'].includes(ext);
  const isAud = ['mp3','m4a','opus','ogg','wav','flac','aac'].includes(ext);
  let body;
  if(isVid)
    body = `<video id="prevMedia" class="player" src="${url}" controls autoplay></video>`;
  else if(isAud)
    body = `<audio id="prevMedia" class="player" src="${url}" controls autoplay style="height:54px"></audio>`;
  else if(['jpg','jpeg','png','webp','gif','avif','bmp'].includes(ext))
    body = `<img class="player" src="${url}">`;
  else if(['srt','vtt','ass','txt','json','log','nfo','description'].includes(ext))
    body = `<div class="term" id="txtPrev" style="height:50vh">loading…</div>`;
  else body = `<div class="empty"><b>No preview for .${esc(ext)}</b>Save it to open in another application.</div>`;
  previewPath = path; prevIn = 0; prevOut = 0;
  const deck = (isVid || isAud) ? `
    <div class="rowflex" style="margin-top:9px">
      <button class="btn sm" onclick="markPrevIn()">[ In</button>
      <span class="mono muted" id="prevInLbl">0.00s</span>
      <button class="btn sm" onclick="markPrevOut()">Out ]</button>
      <span class="mono muted" id="prevOutLbl">0.00s</span>
      <div class="spacer"></div>
      <button class="btn sm alt" onclick="trimPrevInOut()">Trim In → Out in Lab</button>
      ${isVid ? `<button class="btn sm" onclick="grabPrevFrame()">Grab Frame</button>` : ''}
    </div>` : '';
  $('#libPreview').innerHTML = `<div class="panel"><div class="panel-head"><h3>Preview</h3>
    <span class="hint">${esc(path.split('/').pop())}</span><div class="spacer"></div>
    <button class="btn sm" data-act="libPreviewToLab">Send to lab</button>
    <button class="btn sm" data-act="libPreviewClose">Close</button></div>
    <div class="panel-body">${body}${deck}</div></div>`;
  if(body.includes('txtPrev'))
    api('/api/files/read?path='+encodeURIComponent(path))
      .then(j=>$('#txtPrev').textContent = j.text)
      .catch(e=>$('#txtPrev').textContent = e.message);
}

