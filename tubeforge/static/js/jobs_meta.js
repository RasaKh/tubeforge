/* ══════════════════════════════════════════════════════════════════════
   JOBS / DOCK
   ══════════════════════════════════════════════════════════════════════ */
function connectJobs(){
  const src = new EventSource('/api/jobs/stream');
  src.onmessage = e=>{
    const d = JSON.parse(e.data);
    if(d.type==='hello'){ (d.jobs||[]).forEach(j=>jobs.set(j.id,j)); renderDock(); }
    else if(d.type==='job'){
      const prev = jobs.get(d.job.id);
      jobs.set(d.job.id, d.job); renderDock();
      if(prev && prev.status!==d.job.status && ['done','error'].includes(d.job.status) &&
         BOOT.config.notify_on_finish)
        toast(d.job.status==='done'?'Finished':'Failed', d.job.title,
              d.job.status==='done'?'ok':'bad');
      if(d.job.status==='done' && $('#view-library').classList.contains('on')) loadLibrary();
    }
    else if(d.type==='progress'){
      patchJobProgress(d.id, d.progress);
    }
  };
  src.onerror = ()=>{ /* EventSource retries on its own */ };
}

function patchJobProgress(id, progress, status){
  const j = jobs.get(id);
  if(!j) return;
  j.progress = progress;
  if(status) j.status = status;
  const pct = Math.max(0, Math.min(100, progress.pct || 0));
  const meta = [
    progress.speed || '',
    progress.eta ? ('ETA ' + progress.eta) : '',
    progress.line || '',
    j.stages.length > 1 ? `stage ${(j.stage_index || 0) + 1}/${j.stages.length}` : ''
  ].filter(Boolean).join(' \u00b7 ') || j.kind;

  $$(`.job[data-id="${CSS.escape(id)}"]`).forEach(card => {
    const metas = $$('.job-meta', card);
    if(metas[0]) metas[0].textContent = j.status;
    if(metas[1]) metas[1].textContent = meta;
    let bar = $('.bar', card);
    if(!bar && pct > 0){
      card.insertAdjacentHTML('beforeend', `<div class="bar ${j.status}"><i style="width:${pct}%"></i></div>`);
    } else if(bar){
      bar.className = `bar ${j.status}`;
      const fill = $('i', bar);
      if(fill) fill.style.width = `${j.status === 'done' ? 100 : pct}%`;
    }
  });
}

function renderDock(){
  const list = Array.from(jobs.values()).sort((a,b)=>b.created-a.created);
  const active = list.filter(j=>['queued','running'].includes(j.status));
  $$('.qCount').forEach(el=>{ el.textContent = active.length || ''; });
  $('#lamp').classList.toggle('live', active.length>0);
  $('#dockStat').textContent = active.length
    ? `${active.length} running · ${list.length} total`
    : (list.length ? `idle · ${list.length} finished` : 'idle');
  $('#dockJobs').innerHTML = list.length ? list.map(j=>jobCard(j)).join('')
    : `<div class="empty"><b>Nothing queued</b>Jobs you start appear here with live output.</div>`;
  if($('#view-queue').classList.contains('on')) renderQueue();
}

on('jobPick', d=>selectJob(d.id));

function jobCard(j, big){
  const p = j.progress||{};
  const live = ['running','queued'].includes(j.status);
  const pct = Math.max(0, Math.min(100, p.pct||0));
  // Speed and ETA describe a process that is still moving. Once a job stops they
  // are stale, so finished cards report the outcome instead.
  const meta = live
    ? [p.speed||'', p.eta?('ETA '+p.eta):'', p.line||'',
       j.stages.length>1?`stage ${(j.stage_index||0)+1}/${j.stages.length}`:''
      ].filter(Boolean).join(' \u00b7 ')
    : ({ cancelled: pct>0&&pct<100 ? `stopped at ${Math.round(pct)}%` : 'stopped',
         done:      `finished in ${fmtDur(j.duration)}`,
         error:     `failed${j.rc!=null?' (exit '+j.rc+')':''}`
       }[j.status] || j.kind);
  return `<div class="job ${currentJob===j.id?'on':''}" data-act="jobPick" data-id="${esc(j.id)}">
    <div class="job-top"><i class="dot ${j.status}"></i>
      <span class="job-title" title="${esc(j.title)}">${esc(j.title)}</span>
      <span class="job-meta">${esc(j.status)}</span></div>
    <div class="job-meta">${esc(meta || (j.kind))}</div>
    ${live||pct>0
      ? `<div class="bar ${j.status}"><i style="width:${j.status==='done'?100:pct}%"></i></div>` : ''}
    ${big && j.outputs && j.outputs.length
      ? `<div class="job-meta" style="margin-top:5px">→ ${j.outputs.map(o=>esc(o.split('/').pop())).join(', ')}</div>`:''}
  </div>`;
}

function selectJob(id){
  currentJob = id; renderDock();
  const j = jobs.get(id); if(!j) return;
  $('#dockJobTitle').textContent = j.title;
  $('#dockLog').innerHTML = '';
  if(jobLogSrc) jobLogSrc.close();
  jobLogSrc = new EventSource('/api/jobs/'+id+'/stream');
  jobLogSrc.onmessage = e=>{
    const d = JSON.parse(e.data);
    if(d.t==='eof'){ jobLogSrc.close(); return; }
    const s = document.createElement('span');
    s.className = d.t; s.textContent = d.d + '\n';
    const log = $('#dockLog');
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 40;
    log.appendChild(s);
    while(log.childNodes.length > 1500) log.removeChild(log.firstChild);
    if(stick) log.scrollTop = log.scrollHeight;
  };
  openDock();
}
function openDock(){ $('#dock').classList.remove('min'); }
function stepDock(dir){
  const d = $('#dock');
  const states = ['min', 'normal', 'max'];
  const cur = d.classList.contains('min') ? 0 : (d.classList.contains('max') ? 2 : 1);
  const next = states[(cur + dir + states.length) % states.length];
  d.classList.remove('min', 'max');
  if(next !== 'normal') d.classList.add(next);
}
function cycleDock(e){
  if(e && e.target.closest('button')) return;
  stepDock(1);
}
async function cancelCurrent(){ if(currentJob) try{ await api('/api/jobs/'+currentJob+'/cancel',{method:'POST'}); }catch(e){fail(e);} }
async function retryCurrent(){ if(currentJob) try{ const j = await api('/api/jobs/'+currentJob+'/retry',{method:'POST'}); selectJob(j.job); }catch(e){fail(e);} }
async function cancelAll(){ try{ const j = await api('/api/jobs/cancel-all',{method:'POST'}); toast(`Cancelled ${j.cancelled}`); }catch(e){fail(e);} }
async function clearJobs(){ try{ await api('/api/jobs/clear',{method:'POST'});
  Array.from(jobs.keys()).forEach(k=>{ if(!['queued','running'].includes(jobs.get(k).status)) jobs.delete(k); });
  renderDock(); }catch(e){fail(e);} }
function openJobCmd(){
  const j = jobs.get(currentJob); if(!j) return;
  modal('Command', (j.all_cmds||[j.cmd]).map((c,i)=>
    `<span class="readout-stage">stage ${i+1}</span><div class="readout">${esc(c)}
      <button class="copy-btn" data-act="copyEl">Copy</button></div>`).join(''));
}
function renderQueue(){
  const list = Array.from(jobs.values()).sort((a,b)=>b.created-a.created);
  $('#queueStat').textContent = `${list.filter(j=>j.status==='running').length} running · ${list.length} total`;
  $('#queueList').innerHTML = list.length
    ? `<div class="panel"><div class="panel-body" style="padding:0">${list.map(j=>jobCard(j,true)).join('')}</div></div>`
    : `<div class="empty"><b>No jobs yet</b>Start a download or an ffmpeg operation.</div>`;
}
async function loadJobHistory(){
  try{ const j = await api('/api/jobhistory');
    $('#jobHistory').innerHTML = `<div class="tbl-wrap"><table>
      <thead><tr><th>When</th><th>Kind</th><th>Title</th><th>Status</th><th></th></tr></thead><tbody>
      ${j.jobs.map(r=>`<tr><td class="mono">${new Date(r.created*1000).toLocaleString()}</td>
        <td>${esc(r.kind)}</td><td>${esc(r.title)}</td><td>${esc(r.status)}</td>
        <td><a class="btn sm" href="/api/jobs/${r.id}/log" target="_blank">Log</a></td></tr>`).join('')}
      </tbody></table></div>`;
  }catch(e){ fail(e); }
}
