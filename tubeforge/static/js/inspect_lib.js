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
