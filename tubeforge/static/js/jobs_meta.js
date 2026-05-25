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

/* ══════════════════════════════════════════════════════════════════════
   HISTORY / PRESETS / SETTINGS
   ══════════════════════════════════════════════════════════════════════ */
async function loadHistory(){
  try{ const j = await api('/api/history'); historyRows = j.history; renderHistory(); }catch(e){ fail(e); }
}
on('histFetch',   d=>{ $('#dlUrls').value = histView[+d.i].url; show('fetch'); syncFetch(); });
on('histFormats', d=>{ $('#fmtUrl').value = histView[+d.i].url; show('formats'); loadFormats(); });

let histView = [];
function renderHistory(){
  const q = ($('#histSearch').value||'').toLowerCase();
  const rows = historyRows.filter(r=>!q || (r.url+' '+(r.title||'')).toLowerCase().includes(q));
  histView = rows;
  $('#histList').innerHTML = rows.length ? `<div class="panel"><div class="panel-body" style="padding:0">
    ${rows.map((r,ri)=>`<div class="listrow">
      <span class="fname" title="${esc(r.url)}">${esc(r.title||r.url)}</span>
      <span class="fmeta">${esc(r.uploader||'')}</span>
      <span class="fmeta">${new Date(r.ts*1000).toLocaleDateString()}</span>
      <span class="facts">
        <button class="btn sm" data-act="histFetch" data-i="${ri}">Fetch</button>
        <button class="btn sm alt" data-act="histFormats" data-i="${ri}">Formats</button>
        <button class="btn sm bad icon" data-act="histDel" data-id="${r.id}">×</button>
      </span></div>`).join('')}</div></div>`
    : `<div class="empty"><b>Nothing yet</b>Links you fetch or probe are remembered here.</div>`;
}
on('histDel', async d=>{ await api('/api/history?id='+d.id, {method:'DELETE'}); loadHistory(); });
async function clearHistory(){ if(!confirm('Clear the whole URL history?')) return;
  await api('/api/history',{method:'DELETE'}); loadHistory(); }

async function savePreset(kind){
  const name = prompt('Name this preset'); if(!name) return;
  let data;
  if(kind==='ytdlp') data = {opts:ytOpts};
  else if(kind==='filters') data = chains;
  else data = {op:lab.op, params:lab.params, enc:lab.enc, hwaccel:$('#ffHw').value, vfilters:chains.video, afilters:chains.audio};
  try{ await api('/api/presets',{method:'POST',body:JSON.stringify({kind,name,data})});
    toast('Preset saved', name); }catch(e){ fail(e); }
}
async function loadPresets(){
  try{
    const j = await api('/api/presets');
    const byKind = {};
    presetIndex = {};
    j.presets.forEach(p=>{ (byKind[p.kind]=byKind[p.kind]||[]).push(p); presetIndex[p.id]=p; });
    const titles = {ytdlp:'Download presets', ffmpeg:'Operation presets', filters:'Filter chains'};
    $('#presetList').innerHTML = Object.keys(byKind).length ? Object.keys(byKind).map(k=>`
      <div class="panel"><div class="panel-head"><h3>${esc(titles[k]||k)}</h3></div>
      <div class="panel-body" style="padding:0">${byKind[k].map(p=>`
        <div class="listrow"><span class="fname">${esc(p.name)}</span>
          <span class="fmeta">${new Date(p.created*1000).toLocaleDateString()}</span>
          <span class="facts">
            <button class="btn sm" data-act="presetApply" data-id="${p.id}">Apply</button>
            <button class="btn sm bad" data-act="presetDel" data-id="${p.id}">Delete</button></span>
        </div>`).join('')}</div></div>`).join('')
      : `<div class="empty"><b>No presets yet</b>Configure something, then press Save preset.</div>`;
  }catch(e){ fail(e); }
}
let presetIndex = {};
on('presetApply', d=>{ const p = presetIndex[d.id]; if(p) applyPreset(p.kind, p.data); });
on('presetDel',   d=>delPreset(d.id));

function applyPreset(kind, d){
  if(kind==='ytdlp'){ ytOpts = d.opts||{};
    show('fetch'); renderYtOptions(); renderActiveStrip(); syncFetch(); }
  else if(kind==='filters'){ chains = {video:d.video||[], audio:d.audio||[]}; show('filters'); renderChains(); }
  else { lab.op=d.op; lab.params=d.params||{}; lab.enc=d.enc||{};
    if(d.hwaccel !== undefined) $('#ffHw').value = d.hwaccel;
    if(d.vfilters || d.afilters) chains = {video:d.vfilters||[], audio:d.afilters||[]};
    lab.output_mode = 'auto';
    lab.output = lab.inputs[0] ? suggestedOutput(lab.inputs[0], lab.op) : '';
    $('#labOut').value = lab.output; show('lab'); renderLab(); }
  toast('Preset applied');
}
async function delPreset(id){ await api('/api/presets?id='+id,{method:'DELETE'}); loadPresets(); }

async function showDeps(){
  try{
    const j = await api('/api/deps');
    modal('Tools', `<dl class="kv">${Object.entries(j.deps).map(([k,v])=>
      `<dt>${esc(k)}</dt><dd>${v.found
        ? esc(v.version||'').slice(0,120)+`<br><span class="muted">${esc(v.path)}</span>`
        : '<span style="color:var(--fault)">not found on PATH</span>'}</dd>`).join('')}</dl>`,
      `<button class="btn alt" onclick="updateYtdlp()">Update yt-dlp</button>`);
  }catch(e){ fail(e); }
}
async function updateYtdlp(){
  try{ const j = await api('/api/ytdlp/update',{method:'POST'});
    closeModal(); openDock(); selectJob(j.job); }catch(e){ fail(e); }
}
async function loadDisk(){
  try{
    const j = await api('/api/disk');
    if(!j.ok) return;
    $('#diskInfo').innerHTML = `<dt>Free</dt><dd>${esc(j.free_h)}</dd>
      <dt>This folder</dt><dd>${esc(j.folder_h)}</dd>
      <dt>Disk total</dt><dd>${fmtBytes(j.total)}</dd>`;
  }catch(e){}
}
function fillSettings(){
  const c = BOOT.config;
  $('#cfgDir').value = c.download_dir; $('#cfgRoots').value = (c.extra_roots||[]).join('\n');
  $('#cfgSandbox').checked = c.sandbox_paths; $('#cfgYtdlp').value = c.ytdlp_bin;
  $('#cfgFfmpeg').value = c.ffmpeg_bin; $('#cfgFfprobe').value = c.ffprobe_bin;
  $('#cfgConcurrent').value = c.max_concurrent_jobs; $('#cfgTemplate').value = c.default_output_template;
  $('#cfgHistory').value = c.keep_job_history; $('#cfgConfirm').checked = c.confirm_destructive;
  $('#cfgNotify').checked = c.notify_on_finish;
  setText('#confPath', BOOT.paths.conf_dir + '/config.json');
  setText('#pathChip', c.download_dir);
  const accents = ['#ff6b35','#35d6b0','#5aa9f8','#f5a623','#be8cff','#ff4d5e','#d0d4da'];
  setHTML('#accentChips', accents.map(a=>
    `<button class="chip" style="border-color:${a};color:${a}" data-act="setAccent" data-a="${esc(a)}">${a}</button>`).join(''));
}
function setAccent(a){
  document.documentElement.style.setProperty('--tally', a);
  try{ localStorage.setItem('tf_accent', a); }catch(e){}
}
async function saveSettings(){
  const cfg = {
    download_dir:$('#cfgDir').value.trim(),
    extra_roots:$('#cfgRoots').value.split('\n').map(s=>s.trim()).filter(Boolean),
    sandbox_paths:$('#cfgSandbox').checked, ytdlp_bin:$('#cfgYtdlp').value.trim(),
    ffmpeg_bin:$('#cfgFfmpeg').value.trim(), ffprobe_bin:$('#cfgFfprobe').value.trim(),
    max_concurrent_jobs:Number($('#cfgConcurrent').value)||2,
    default_output_template:$('#cfgTemplate').value,
    keep_job_history:Number($('#cfgHistory').value)||500,
    confirm_destructive:$('#cfgConfirm').checked, notify_on_finish:$('#cfgNotify').checked
  };
  try{ const j = await api('/api/config',{method:'POST',body:JSON.stringify({config:cfg})});
    BOOT.config = j.config; fillSettings(); toast('Settings saved'); loadDisk();
  }catch(e){ fail(e); }
}

/* ══════════════════════════════════════════════════════════════════════
   REFERENCE
   ══════════════════════════════════════════════════════════════════════ */
const RECIPES = [
  ['yt-dlp · everyday', [
    ['Best quality, merged','yt-dlp -f "bestvideo*+bestaudio/best" --merge-output-format mkv URL'],
    ['1080p MP4 that plays anywhere','yt-dlp -S "res:1080,vcodec:h264,acodec:aac" --merge-output-format mp4 URL'],
    ['MP3 at best quality','yt-dlp -x --audio-format mp3 --audio-quality 0 --embed-thumbnail --embed-metadata URL'],
    ['Everything embedded','yt-dlp --embed-subs --embed-thumbnail --embed-metadata --embed-chapters URL'],
    ['Subtitles only (SRT)','yt-dlp --skip-download --write-subs --write-auto-subs --sub-langs "en.*" --convert-subs srt URL'],
    ['Whole channel, newest first','yt-dlp -I 1:20 --download-archive seen.txt "https://www.youtube.com/@handle/videos"'],
  ]],
  ['yt-dlp · precision', [
    ['Just one section','yt-dlp --download-sections "*00:01:30-00:04:00" --force-keyframes-at-cuts URL'],
    ['Skip sponsors entirely','yt-dlp --sponsorblock-remove sponsor,selfpromo,interaction URL'],
    ['Split into chapter files','yt-dlp --split-chapters -o "chapter:%(title)s/%(section_number)02d %(section_title)s.%(ext)s" URL'],
    ['Live stream from start','yt-dlp --live-from-start --wait-for-video 15 URL'],
    ['Resume & retry reliably','yt-dlp -c -R infinite --fragment-retries infinite --concurrent-fragments 4 URL'],
    ['Use browser cookies','yt-dlp --cookies-from-browser firefox URL'],
    ['Throttle and be polite','yt-dlp -r 2M --sleep-interval 5 --max-sleep-interval 15 URL'],
    ['Only videos over ten minutes','yt-dlp --match-filters "duration > 600" URL'],
  ]],
  ['ffmpeg · encode', [
    ['Solid H.264 default','ffmpeg -i in.mkv -c:v libx264 -crf 20 -preset slow -c:a aac -b:a 192k out.mp4'],
    ['Small HEVC','ffmpeg -i in.mkv -c:v libx265 -crf 26 -preset medium -tag:v hvc1 -c:a copy out.mp4'],
    ['AV1, patient','ffmpeg -i in.mkv -c:v libsvtav1 -crf 32 -preset 6 -c:a libopus -b:a 128k out.mkv'],
    ['NVIDIA hardware encode','ffmpeg -hwaccel cuda -i in.mkv -c:v hevc_nvenc -preset p6 -cq 26 -c:a copy out.mp4'],
    ['VA-API hardware encode (Linux)','ffmpeg -vaapi_device /dev/dri/renderD128 -i in.mkv -vf "format=nv12,hwupload" -c:v h264_vaapi -qp 22 -c:a copy out.mp4'],
    ['Two-pass target bitrate','ffmpeg -y -i in.mp4 -c:v libx264 -b:v 1800k -pass 1 -an -f null /dev/null && ffmpeg -i in.mp4 -c:v libx264 -b:v 1800k -pass 2 -c:a aac -b:a 128k out.mp4'],
    ['Web-ready MP4','ffmpeg -i in.mov -c:v libx264 -crf 22 -pix_fmt yuv420p -movflags +faststart out.mp4'],
  ]],
  ['ffmpeg · cut & join', [
    ['Instant cut, no re-encode','ffmpeg -ss 00:01:00 -i in.mp4 -t 30 -c copy out.mp4'],
    ['Frame-accurate cut','ffmpeg -i in.mp4 -ss 00:01:00 -to 00:01:30 -c:v libx264 -crf 18 out.mp4'],
    ['Join identical files','ffmpeg -f concat -safe 0 -i list.txt -c copy out.mp4'],
    ['Loop a clip 3 times','ffmpeg -stream_loop 2 -i in.mp4 -c copy out.mp4'],
    ['Reverse clip + audio','ffmpeg -i in.mp4 -vf reverse -af areverse out.mp4'],
    ['Split every ten minutes','ffmpeg -i in.mp4 -c copy -f segment -segment_time 600 -reset_timestamps 1 part_%03d.mp4'],
    ['Images to 30fps video','ffmpeg -framerate 30 -i frame_%04d.png -c:v libx264 -pix_fmt yuv420p out.mp4'],
  ]],
  ['ffmpeg · streams', [
    ['Strip subtitles','ffmpeg -i in.mkv -map 0 -c copy -sn out.mkv'],
    ['Keep only the second audio track','ffmpeg -i in.mkv -map 0:v -map 0:a:1 -c copy out.mkv'],
    ['Replace audio track','ffmpeg -i vid.mp4 -i new_audio.m4a -map 0:v:0 -map 1:a:0 -c copy -shortest out.mp4'],
    ['Fix audio sync (+250ms)','ffmpeg -i in.mp4 -itsoffset 0.25 -i in.mp4 -map 0:v -map 1:a -c copy out.mp4'],
    ['Extract a subtitle track','ffmpeg -i in.mkv -map 0:s:0 subs.srt'],
    ['Soft-add subtitles to MP4','ffmpeg -i in.mp4 -i subs.srt -c copy -c:s mov_text -metadata:s:s:0 language=eng out.mp4'],
    ['Burn subtitles in','ffmpeg -i in.mp4 -vf "subtitles=subs.srt:force_style=\'FontSize=24\'" -c:a copy out.mp4'],
    ['Tag an audio track','ffmpeg -i in.mkv -map 0 -c copy -metadata:s:a:0 language=tur out.mkv'],
  ]],
  ['ffmpeg · audio', [
    ['Broadcast loudness','ffmpeg -i in.wav -af loudnorm=I=-16:TP=-1.5:LRA=11 out.wav'],
    ['Strip video, keep audio','ffmpeg -i in.mp4 -vn -c:a copy out.m4a'],
    ['Speed up, keep pitch','ffmpeg -i in.mp3 -af atempo=1.25 out.mp3'],
    ['Denoise a voice recording','ffmpeg -i in.wav -af "highpass=f=80,afftdn=nr=12,acompressor" out.wav'],
    ['Mix two tracks','ffmpeg -i a.wav -i b.wav -filter_complex amix=inputs=2:duration=longest out.wav'],
    ['Detect silence intervals','ffmpeg -i in.mp3 -af silencedetect=noise=-35dB:d=1.0 -f null -'],
    ['Waveform PNG image','ffmpeg -i in.mp3 -filter_complex "showwavespic=s=1200x240:colors=#ff6b35" -frames:v 1 wave.png'],
  ]],
  ['ffmpeg · picture', [
    ['Resize keeping aspect','ffmpeg -i in.mp4 -vf "scale=-2:720:flags=lanczos" -c:a copy out.mp4'],
    ['Crop to square','ffmpeg -i in.mp4 -vf "crop=ih:ih" out.mp4'],
    ['Rotate 90° clockwise','ffmpeg -i in.mp4 -vf transpose=1 -c:a copy out.mp4'],
    ['Deinterlace','ffmpeg -i in.mkv -vf bwdif -c:a copy out.mkv'],
    ['High-quality GIF (1-pass)','ffmpeg -ss 5 -t 4 -i in.mp4 -vf "fps=15,scale=520:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" out.gif'],
    ['Animated WebP','ffmpeg -ss 5 -t 4 -i in.mp4 -vf "fps=15,scale=640:-1:flags=lanczos" -loop 0 -c:v libwebp -q:v 75 out.webp'],
    ['Picture-in-picture','ffmpeg -i main.mp4 -i cam.mp4 -filter_complex "[1:v]scale=360:-1[pip];[0:v][pip]overlay=W-w-20:H-h-20" -c:a copy out.mp4'],
    ['Side-by-side stack','ffmpeg -i left.mp4 -i right.mp4 -filter_complex hstack=inputs=2 out.mp4'],
    ['Contact sheet','ffmpeg -i in.mp4 -vf "fps=1/30,scale=320:-1,tile=5x5" sheet.jpg'],
  ]],
  ['ffmpeg · web & timecode', [
    ['Remux MKV to MP4 fast','ffmpeg -i in.mkv -c copy -movflags +faststart out.mp4'],
    ['HLS stream segments','ffmpeg -i in.mp4 -c copy -hls_time 6 -hls_playlist_type vod out.m3u8'],
    ['Burn timecode overlay','ffmpeg -i in.mp4 -vf "drawtext=text=\'%{pts\\:hms}\':x=16:y=16:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.6" -c:a copy out.mp4'],
    ['Stabilize shaky footage','ffmpeg -i in.mp4 -vf vidstabdetect=shakiness=5:accuracy=15 -f null - && ffmpeg -i in.mp4 -vf vidstabtransform=smoothing=30,unsharp=5:5:0.8:3:3:0.4 -c:a copy out.mp4'],
  ]],
  ['ffprobe', [
    ['Everything as JSON','ffprobe -v quiet -print_format json -show_format -show_streams in.mkv'],
    ['Just the duration','ffprobe -v error -show_entries format=duration -of csv=p=0 in.mkv'],
    ['Stream summary','ffprobe -v error -show_entries stream=index,codec_type,codec_name -of csv in.mkv'],
    ['Resolution & bitrate','ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate,bit_rate -of default=noprint_wrappers=1 in.mp4'],
    ['Chapter list as JSON','ffprobe -v quiet -print_format json -show_chapters in.mkv'],
    ['Keyframe timestamps','ffprobe -v error -select_streams v:0 -skip_frame nokey -show_entries frame=pkt_pts_time -of csv=p=0 in.mp4'],
    ['Count frames exactly','ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of csv=p=0 in.mp4'],
  ]],
];
async function loadSnippets(){
  try{
    const j = await api('/api/snippets');
    const q = ($('#refSearch').value||'').toLowerCase();
    const rows = (j.snippets||[]).filter(s => !q || (s.name+' '+s.command+' '+(s.notes||'')).toLowerCase().includes(q));
    $('#snippetPanel').innerHTML = `<div class="panel"><div class="panel-head"><h3>Saved Snippets</h3>
      <div class="spacer"></div><button class="btn sm alt" onclick="saveSnippetPrompt()">+ Save snippet</button></div>
      <div class="panel-body">${rows.length ? rows.map(s=>`<div class="listrow">
        <span class="fname" title="${esc(s.command)}"><b>${esc(s.name)}</b> · ${esc(s.command)}</span>
        <span class="facts">
          <button class="btn sm" onclick="copyText(${JSON.stringify(s.command)})">Copy</button>
          <button class="btn sm bad icon" onclick="delSnippet(${s.id})">×</button>
        </span></div>`).join('') : '<span class="muted">No saved snippets yet.</span>'}</div></div>`;
  }catch(e){}
}
async function saveSnippetPrompt(){
  const name = prompt('Snippet name'); if(!name) return;
  const command = prompt('Command'); if(!command) return;
  await api('/api/snippets',{method:'POST',body:JSON.stringify({name, command})});
  toast('Snippet saved'); loadSnippets();
}
async function delSnippet(id){
  await api('/api/snippets?id='+id,{method:'DELETE'});
  loadSnippets();
}
function applyRecipe(cmd){
  if(cmd.startsWith('yt-dlp ')){
    if(cmd.includes(' -x')) ytOpts.extract_audio = true;
    if(cmd.includes('--embed-subs')) ytOpts.embed_subs = true;
    if(cmd.includes('--embed-thumbnail')) ytOpts.embed_thumbnail = true;
    if(cmd.includes('--embed-metadata')) ytOpts.embed_metadata = true;
    if(cmd.includes('--embed-chapters')) ytOpts.embed_chapters = true;
    if(cmd.includes('--split-chapters')) ytOpts.split_chapters = true;
    const mFmt = cmd.match(/--merge-output-format\s+(\S+)/); if(mFmt) ytOpts.merge_output_format = mFmt[1];
    const mAud = cmd.match(/--audio-format\s+(\S+)/); if(mAud) ytOpts.audio_format = mAud[1];
    show('fetch'); renderYtOptions(); renderActiveStrip(); syncFetch();
    toast('Applied recipe options to Fetch');
  } else if(cmd.startsWith('ffmpeg ')){
    lab.op = 'transcode';
    const mVc = cmd.match(/-c:v\s+(\S+)/); if(mVc) lab.enc.vcodec = mVc[1];
    const mAc = cmd.match(/-c:a\s+(\S+)/); if(mAc) lab.enc.acodec = mAc[1];
    const mCrf = cmd.match(/-crf\s+(\d+)/); if(mCrf) lab.enc.crf = mCrf[1];
    const mPre = cmd.match(/-preset\s+(\S+)/); if(mPre) lab.enc.preset = mPre[1];
    show('lab'); renderLab();
    toast('Applied recipe options to Media Lab');
  } else {
    copyText(cmd);
  }
}

function renderReference(){
  loadSnippets();
  const q = ($('#refSearch').value||'').toLowerCase();
  $('#refGrid').innerHTML = `<div class="cols-3">` + RECIPES.map(([title, items])=>{
    const hit = items.filter(([n,c])=>!q || n.toLowerCase().includes(q) || c.toLowerCase().includes(q));
    if(!hit.length) return '';
    return `<div class="panel"><div class="panel-head"><h3>${esc(title)}</h3></div>
      <div class="panel-body">${hit.map(([n,c])=>`
        <div style="margin-bottom:9px">
          <div class="inline" style="justify-content:space-between;margin-bottom:3px">
            <span class="lbl" style="margin:0;text-transform:none;letter-spacing:0;font-family:var(--sans);font-size:.73rem;color:var(--ink-dim)">${esc(n)}</span>
            ${(c.startsWith('yt-dlp ') || c.startsWith('ffmpeg ')) ? `<button class="btn sm" onclick="applyRecipe(${JSON.stringify(c)})">Apply to UI</button>` : ''}
          </div>
          <div class="readout" style="font-size:.68rem;cursor:pointer" data-act="copyEl">${esc(c)}</div>
        </div>`).join('')}</div></div>`;
  }).join('') + `</div>`;
}

/* ══════════════════════════════════════════════════════════════════════
   COMMAND PALETTE
   ══════════════════════════════════════════════════════════════════════ */
let palItems = [], palIdx = 0;
function buildPalette(){
  palItems = [];
  const seenViews = new Set();
  $$('.nav').forEach(n => {
    const v = n.dataset.view;
    if(!v || seenViews.has(v)) return;
    seenViews.add(v);
    const clone = n.cloneNode(true);
    $$('.ic, .count, .tool', clone).forEach(el => el.remove());
    const label = clone.textContent.trim();
    palItems.push({label: 'Go to ' + label, where: 'view', run: () => show(v)});
  });
  BOOT.ff_ops.forEach(o=>palItems.push({label:o.label, where:'operation',
    run:()=>{ pickOp(o.id); show('lab'); }}));
  BOOT.filters.forEach(f=>palItems.push({label:'Add filter · '+f.label, where:f.kind,
    run:()=>{ addFilter(f.kind, f.id); show('filters'); }}));
  BOOT.ytdlp_options.filter(o=>!o.hidden).forEach(o=>palItems.push({label:'Option · '+o.label, where:'yt-dlp',
    run:()=>{ show('fetch'); optGroup = o.group; $('#optSearch').value = '';
      $('#showAdv').checked = $('#showAdv').checked || !!o.adv; renderYtOptions();
      setTimeout(()=>{ const e = $('#yt_'+o.id); if(e){ e.focus(); e.scrollIntoView({block:'center'}); } },60); }}));
  [['Start download',()=>runFetch()],['Cancel every running job',cancelAll],
   ['Clear finished jobs',clearJobs],['Check tool versions',showDeps],
   ['Update yt-dlp',updateYtdlp],['Switch theme',toggleTheme],
   ['Clear the filter chain',clearFilters],['Reset download options',resetYtOptions],
   ['Scroll to top',()=>jumpTo('top')],
   ['Scroll to bottom',()=>jumpTo('bottom')]]
    .forEach(([label,run])=>palItems.push({label, where:'action', run}));
}
function openPalette(){
  $('#palScrim').hidden = false; $('#palInput').value = ''; palIdx = 0;
  renderPalette(); $('#palInput').focus();
}
function closePalette(){ $('#palScrim').hidden = true; }
function palMatches(){
  const q = $('#palInput').value.toLowerCase().trim();
  const hits = palItems.filter(i=>!q || i.label.toLowerCase().includes(q));
  return hits.slice(0, 60);
}
function renderPalette(){
  const hits = palMatches();
  if(palIdx >= hits.length) palIdx = Math.max(0, hits.length-1);
  $('#palList').innerHTML = hits.map((i,n)=>
    `<div class="pal-item ${n===palIdx?'on':''}" data-act="palRun" data-i="${n}">
      <span>${esc(i.label)}</span><span class="where">${esc(i.where)}</span></div>`).join('')
    || `<div class="empty">Nothing matches that.</div>`;
}
function runPal(n){ const h = palMatches(); if(h[n]){ closePalette(); h[n].run(); focusWork(); } }
$('#palInput').addEventListener('input', ()=>{ palIdx=0; renderPalette(); });
$('#palInput').addEventListener('keydown', e=>{
  const h = palMatches();
  if(e.key==='ArrowDown'){ palIdx=Math.min(palIdx+1,h.length-1); renderPalette(); e.preventDefault(); }
  if(e.key==='ArrowUp'){ palIdx=Math.max(palIdx-1,0); renderPalette(); e.preventDefault(); }
  if(e.key==='Enter'){ runPal(palIdx); }
  if(e.key==='Escape'){ closePalette(); }
});

function inTextField(el){
  return !!(el && el.closest && el.closest('input, textarea, select, [contenteditable]'));
}

document.addEventListener('keydown', e=>{
  if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'){ e.preventDefault(); openPalette(); }
  else if(e.key==='Escape'){ closeModal(); closePalette(); }
  else if((e.ctrlKey||e.metaKey) && e.key==='Enter'){
    e.preventDefault();
    if($('#view-fetch').classList.contains('on')) runFetch();
    else if($('#view-lab').classList.contains('on')) runLab();
    else if($('#view-pipeline').classList.contains('on')) runPipeline();
  }
  else if(e.key==='`' && (e.ctrlKey||e.metaKey)){ e.preventDefault(); cycleDock(); }
  else if((e.ctrlKey||e.metaKey) && (e.key==='ArrowUp' || e.key==='ArrowDown')){
    e.preventDefault(); jumpTo(e.key === 'ArrowUp' ? 'top' : 'bottom');
  }
  else if((e.key==='Home' || e.key==='End') && !inTextField(e.target)){
    e.preventDefault(); jumpTo(e.key === 'Home' ? 'top' : 'bottom');
  }
});

/* ══════════════════════════════════════════════════════════════════════
   PERSISTENCE OF UI STATE
   ══════════════════════════════════════════════════════════════════════ */
function saveLocal(){
  try{
    localStorage.setItem('tf_state', JSON.stringify({
      ytOpts, chains, lab:{op:lab.op,params:lab.params,enc:lab.enc,output:lab.output,inputs:lab.inputs,output_mode:lab.output_mode},
      urls:$('#dlUrls')?$('#dlUrls').value:'',
      dlSplit:$('#dlSplit')?$('#dlSplit').checked:false,
      seek:{ss:$('#seekSS')?.value||'', to:$('#seekTo')?.value||'', t:$('#seekT')?.value||'', accurate:!!$('#seekAcc')?.checked},
      ff:{hw:$('#ffHw')?.value||'', log:$('#ffLog')?.value||'info', pre:$('#ffPre')?.value||'', overwrite:!!$('#ffOverwrite')?.checked},
      pipe:{in:$('#pipeIn')?.value||'', out:$('#pipeOut')?.value||''},
      batch:{pattern:$('#batchPattern')?.value||'', dir:$('#batchDir')?.value||''},
      pipeSteps, batchFiles
    }));
  }catch(e){}
}
function restoreLocal(){
  try{
    const s = JSON.parse(localStorage.getItem('tf_state')||'{}');
    if(s.ytOpts) ytOpts = s.ytOpts;
    if(s.chains) chains = s.chains;
    if(s.lab) lab = Object.assign(lab, {output_mode:s.lab.output?'manual':'auto'}, s.lab);
    if(s.pipeSteps) pipeSteps = s.pipeSteps;
    if(s.batchFiles) batchFiles = s.batchFiles;
    if(s.urls && $('#dlUrls')) $('#dlUrls').value = s.urls;
    if(s.dlSplit != null && $('#dlSplit')) $('#dlSplit').checked = !!s.dlSplit;
    if(s.seek){
      if($('#seekSS')) $('#seekSS').value = s.seek.ss || '';
      if($('#seekTo')) $('#seekTo').value = s.seek.to || '';
      if($('#seekT')) $('#seekT').value = s.seek.t || '';
      if($('#seekAcc')) $('#seekAcc').checked = !!s.seek.accurate;
    }
    if(s.ff){
      if($('#ffHw')) $('#ffHw').value = s.ff.hw || '';
      if($('#ffLog')) $('#ffLog').value = s.ff.log || 'info';
      if($('#ffPre')) $('#ffPre').value = s.ff.pre || '';
      if($('#ffOverwrite')) $('#ffOverwrite').checked = !!s.ff.overwrite;
    }
    if(s.pipe){
      if($('#pipeIn')) $('#pipeIn').value = s.pipe.in || '';
      if($('#pipeOut')) $('#pipeOut').value = s.pipe.out || '';
    }
    if(s.batch){
      if($('#batchPattern') && s.batch.pattern) $('#batchPattern').value = s.batch.pattern;
      if($('#batchDir')) $('#batchDir').value = s.batch.dir || '';
    }
    const th = localStorage.getItem('tf_theme'); if(th) document.documentElement.dataset.theme = th;
    const ac = localStorage.getItem('tf_accent'); if(ac) setAccent(ac);
    const fs = localStorage.getItem('tf_fs'); if(fs){ $('#cfgFont').value = fs; applyFontScale(fs); }
    else applyFontScale(100);
  }catch(e){}
}

/* ══════════════════════════════════════════════════════════════════════
   BOOT
   ══════════════════════════════════════════════════════════════════════ */
async function boot(){
  BOOT = await api('/api/bootstrap');
  restoreLocal();

  renderFormatChips();
  $('#tplChips').innerHTML = BOOT.output_presets.map((p,i)=>
    `<button class="chip mono" title="${esc(p.value)}" data-act="tplPreset" data-i="${i}">${esc(p.label)}</button>`).join('');
  $('#tokenChips').innerHTML = BOOT.output_tokens.map(t=>
    `<button class="chip mono" title="${esc(t.desc)}" data-act="insToken" data-t="${esc(t.token)}">%(${esc(t.token)})s</button>`).join('');
  $('#ffHw').innerHTML = BOOT.hwaccels.map(h=>
    `<option value="${h}">${h===''?'— none —':h}</option>`).join('');

  $('#labOut').value = lab.output || '';
  $('#pathChip').onclick = ()=>{ libState.dir=''; show('library'); };

  renderKindChips(); renderYtOptions(); renderActiveStrip(); renderTplSummary();
  renderLab(); renderChains();
  renderPipeline(); renderBatch(); renderReference(); fillSettings(); buildPalette();
  connectJobs(); loadDisk(); syncFetch();

  $('#dlUrls').addEventListener('input', syncFetch);
  $('#railToggle').onclick = ()=>$('#rail').classList.toggle('open');
  if(window.innerWidth < 900) $('#railToggle').style.display = '';

  watchScroll(); wireJumpRail(); focusWork();
  $('#work').classList.add('snap');
  const h = location.hash.replace('#',''); if(h) show(h);
  window.addEventListener('beforeunload', saveLocal);
}

function insertToken(tok){
  const cur = ytOpts.output || BOOT.config.default_output_template || '';
  setOpt('output', cur.replace(/(\.%\(ext\)s)?$/, '') + `%(${tok})s` +
    (cur.includes('%(ext)s') ? '.%(ext)s' : ''));
  renderYtOptions();
}

boot().catch(e=>{
  console.error('boot failed', e);
  document.body.innerHTML = `<div style="padding:36px;font-family:ui-monospace,monospace;
      color:#ff8b96;line-height:1.6;max-width:70ch">
    <b style="font-size:1.1rem;color:#dfe3e8">TubeForge could not start</b>
    <p style="margin-top:10px">${esc(e.message)}</p>
    <p style="margin-top:10px;color:#98a1ad">The server is running — this is a problem in the page
      itself. The browser console has the full trace. Try a hard refresh
      (Ctrl+Shift+R) in case an old script is cached.</p>
    <pre style="margin-top:14px;color:#6d7682;font-size:.8rem;white-space:pre-wrap">${
      esc((e.stack||'').split('\n').slice(0,6).join('\n'))}</pre></div>`;
});
