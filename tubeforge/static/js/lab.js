/* ══════════════════════════════════════════════════════════════════════
   MEDIA LAB
   ══════════════════════════════════════════════════════════════════════ */
function renderOpPicker(){
  const q = ($('#opSearch').value||'').toLowerCase();
  const groups = {};
  BOOT.ff_ops.forEach(o=>{
    if(q && !(o.label.toLowerCase().includes(q) || o.id.includes(q) ||
              (o.help||'').toLowerCase().includes(q))) return;
    (groups[o.group] = groups[o.group] || []).push(o);
  });
  $('#opPicker').innerHTML = Object.keys(groups).map(g=>`
    <div class="lbl" style="margin-top:8px">${esc(g)}</div>
    <div class="chips">${groups[g].map(o=>
      `<button class="chip ${lab.op===o.id?'on':''}" title="${esc(o.help||'')}"
        data-act="pickOp" data-o="${esc(o.id)}">${esc(o.label)}</button>`).join('')}</div>`).join('');
}

function opMeta(){ return BOOT.ff_ops.find(o=>o.id===lab.op) || {}; }

/* ── Output naming ─────────────────────────────────────────────────────
   The suggested output follows the source file: same folder, same stem with a
   suffix, and the source's own extension whenever the operation produces the
   same kind of file. Operations that inherently change type (a GIF, a PNG
   frame, an audio extraction) keep their declared format instead. */
const OUT_TAGS = {
  transcode:'converted', trim:'clip', cut_out:'cut', remux:'remuxed', speed:'speed',
  reverse:'reversed', loop_clip:'looped', stabilize:'stabilised', loudnorm2:'normalised',
  extract_audio:'audio', extract_video:'video', extract_subs:'subs', strip:'stripped',
  metadata:'tagged', map_streams:'remapped', watermark:'watermarked', pip:'pip',
  stack:'stacked', concat:'joined', mux:'muxed', add_audio:'new audio', add_subs:'subbed',
  screenshot:'frame', thumbnails:'contact sheet', waveform:'waveform',
  spectrogram:'spectrogram', visualizer:'visualiser', audio_convert:'audio',
};

function suggestedOutput(sourcePath, opId){
  const op = BOOT.ff_ops.find(o=>o.id===opId) || {};
  if(op.out === false) return '';                       // writes a folder, not a file
  if(!sourcePath) return lab.output || '';
  const slash = sourcePath.lastIndexOf('/');
  const dir  = slash >= 0 ? sourcePath.slice(0, slash+1) : '';
  const base = slash >= 0 ? sourcePath.slice(slash+1) : sourcePath;
  const dot  = base.lastIndexOf('.');
  const stem = dot > 0 ? base.slice(0, dot) : base;
  const srcExt = dot > 0 ? base.slice(dot+1).toLowerCase() : '';
  const preserving = (BOOT.container_preserving||[]).includes(opId);
  const ext = (preserving && srcExt) ? srcExt : (op.out_hint || srcExt || 'mkv');
  const tag = OUT_TAGS[op.id] || (op.id || 'out').replace(/_/g, ' ');
  return `${dir}${stem} [${tag}].${ext}`;
}

function sendToLab(path, opId){
  lab.inputs[0] = path;
  lab.output_mode = 'auto';
  if(opId && opId !== lab.op){ lab.params = {}; lab.enc = {}; }
  if(opId) lab.op = opId;
  lab.output = suggestedOutput(path, lab.op);
  $('#labOut').value = lab.output;
  show('lab'); renderLab();
}

function pickOp(id){
  lab.op = id; lab.params = {}; lab.enc = {}; lab.output_mode = 'auto';
  labAudioOnly = ['audio_convert','extract_audio'].includes(id);
  const m = opMeta();
  const need = m.inputs === 0 ? Math.max(2, lab.inputs.length) : m.inputs;
  while(lab.inputs.length < need) lab.inputs.push('');
  if(m.inputs > 0) lab.inputs = lab.inputs.slice(0, Math.max(m.inputs, 1));
  // Re-derive rather than string-swapping the extension, so switching from
  // "GIF" back to "Trim" returns to the source container instead of keeping .gif.
  if(lab.inputs[0]){
    lab.output = suggestedOutput(lab.inputs[0], id);
    $('#labOut').value = lab.output;
  } else if(m.out_hint && lab.output){
    lab.output = lab.output.replace(/\.[^.]+$/, '.'+m.out_hint);
    $('#labOut').value = lab.output;
  }
  renderLab();
}

let labProbe = { streams: [], duration: null, chapters: [] };

function updateLabPanelVisibility(){
  const m = opMeta();
  const showEnc = (m.enc && !(lab.op === 'concat' && (lab.params.mode || 'demuxer') === 'demuxer')) ||
                  (lab.op === 'add_subs' && lab.params.mode === 'burn');
  const showFilt = m.filters || (lab.op === 'add_subs' && lab.params.mode === 'burn');
  $('#labEncPanel').style.display = showEnc ? '' : 'none';
  $('#labFilterPanel').style.display = showFilt ? '' : 'none';
  $('#labSeekPanel').style.display = ['transcode','trim','audio_convert','extract_audio','video_to_images'].includes(lab.op) ? '' : 'none';
  if(lab.op === 'trim') $('#labSeekPanel').classList.remove('collapsed');
}

function renderLab(){
  const m = opMeta();
  renderOpPicker();
  $('#opInputHint').textContent = m.inputs === 0 ? 'as many as you like'
    : (m.inputs === 1 ? 'one file' : m.inputs + ' files');
  renderLabInputs();
  renderLabFields();
  updateLabPanelVisibility();
  const folder = ['video_to_images','extract_attachments','split_time','split_size','split_chapters'].includes(lab.op);
  $('#labOutLabel').textContent = folder ? 'Output folder' : 'Output file';
  $('#labFieldsPanel').style.display = (m.fields && m.fields.length) ? '' : 'none';
  if(m.help) $('#labFields').insertAdjacentHTML('afterbegin', `<div class="note info">${esc(m.help)}</div>`);
  renderEncoder(); renderContainerChips(); renderLabFilterPreview();
  $('#batchOpNote').textContent = 'Operation: ' + (m.label||'none');
  syncLab();
}

on('labDropIn', d=>{ lab.inputs.splice(+d.i,1); renderLab(); });
on('labAddIn',  ()=>{ lab.inputs.push(''); renderLab(); });

function browseLabInput(i){
  const m = opMeta();
  const multi = m.inputs === 0;
  browsePath({
    mode: multi ? 'files' : 'file',
    initial: lab.inputs[i] || '',
    title: multi ? 'Select input files' : 'Select input file',
    onPick: (p, paths) => {
      if(multi && paths && paths.length > 1){
        lab.inputs.splice(i, 1, ...paths);
        renderLabInputs();
      } else {
        lab.inputs[i] = p;
        const inp = $(`[data-labin="${i}"]`);
        if(inp) inp.value = p;
      }
      syncLab();
    }
  });
}

function browseLabOut(){
  const folder = ['video_to_images','extract_attachments','split_time','split_size','split_chapters'].includes(lab.op);
  browsePath({
    mode: folder ? 'dir' : 'save',
    initial: $('#labOut').value,
    title: folder ? 'Select output folder' : 'Save output as',
    onPick: p => {
      lab.output_mode = 'manual';
      lab.output = p;
      $('#labOut').value = p;
      syncLab();
    }
  });
}

function browseBatchFiles(){
  browsePath({
    mode: 'files',
    title: 'Select files for Batch',
    onPick: (_, paths) => {
      batchFiles = Array.from(new Set(batchFiles.concat(paths || [])));
      renderBatch();
    }
  });
}

function renderLabInputs(){
  const m = opMeta();
  const variable = m.inputs === 0;
  $('#labInputs').innerHTML = lab.inputs.map((v,i)=>`
    <div class="inline" style="margin-bottom:7px">
      <span class="lbl" style="width:52px;margin:0">${variable?'#'+(i+1):(i===0?'main':'extra')}</span>
      <input type="text" value="${esc(v)}" placeholder="path to a file"
        data-labin="${i}" oninput="lab.inputs[+this.dataset.labin]=this.value;syncLab()">
      <button class="btn sm" type="button" onclick="browseLabInput(${i})">Browse…</button>
      ${variable||i>=(m.inputs||1)?`<button class="btn sm bad icon" data-act="labDropIn" data-i="${i}">×</button>`:''}
    </div>`).join('') +
    (variable ? `<div class="btns"><button class="btn sm" data-act="labAddIn">+ Add input</button>
      <button class="btn sm alt" type="button" onclick="browseLabInput(lab.inputs.length)">+ Browse files…</button></div>` : '');
}

function fieldVisible(f, store, fields){
  if(!f.when) return true;
  return Object.entries(f.when).every(([k, allowed]) => {
    const defField = (fields || []).find(x => x.id === k);
    const cur = store[k] !== undefined ? store[k] : (defField ? defField.default : '');
    return Array.isArray(allowed) ? allowed.includes(cur) : cur === allowed;
  });
}

function fieldControl(f, store, onchange){
  const v = store[f.id] !== undefined ? store[f.id] : f.default;
  const setter = `${onchange}('${f.id}', this.${f.type==='bool'?'checked':'value'})`;
  if(f.type === 'bool')
    return checkWithHint(`<label class="check ${v?'on':''}">
      <input type="checkbox" ${v?'checked':''} onchange="${setter}">
      <span>${esc(f.label)}</span></label>`, f.label, f.help);
  let inp;
  if(onchange === 'setLabParam' && f.id === 'index' && ['extract_audio','extract_video','extract_subs'].includes(lab.op) && labProbe.streams.length){
    const want = {extract_audio:'audio', extract_video:'video', extract_subs:'subtitle'}[lab.op];
    const matching = labProbe.streams.filter(s => s.type === want);
    if(matching.length){
      inp = `<select onchange="${setter}">${matching.map((s, idx) => {
        const desc = [s.codec, s.language, s.channels ? `${s.channels}ch` : '', s.width ? `${s.width}x${s.height}` : '', s.bitrate_h].filter(Boolean).join(' · ');
        return `<option value="${idx}" ${String(idx)===String(v)?'selected':''}>${idx} — ${esc(desc || want)}</option>`;
      }).join('')}</select>`;
      return `<div class="field"><label>${esc(f.label)}</label>${inp}${f.help?`<p class="help">${esc(f.help)}</p>`:''}</div>`;
    }
  }
  if(f.type === 'select')
    inp = `<select onchange="${setter}">${(f.choices||[]).map(c=>
      `<option value="${esc(c)}" ${String(c)===String(v)?'selected':''}>${esc(c===''?'— not set —':c)}</option>`).join('')}</select>`;
  else if(f.type === 'textarea')
    inp = `<textarea rows="3" placeholder="${esc(f.placeholder||'')}" oninput="${setter}">${esc(v||'')}</textarea>`;
  else
    inp = `<input type="${f.type==='number'?'number':'text'}" value="${esc(v==null?'':v)}"
      ${f.step?`step="${f.step}"`:''} ${f.min!=null?`min="${f.min}"`:''} ${f.max!=null?`max="${f.max}"`:''}
      placeholder="${esc(f.placeholder||'')}" oninput="${setter}">`;
  return `<div class="field"><label>${esc(f.label)}</label>${inp}${f.help?`<p class="help">${esc(f.help)}</p>`:''}</div>`;
}

function renderLabFields(){
  const m = opMeta();
  const fields = (m.fields || []).filter(f => fieldVisible(f, lab.params, m.fields));
  const bools = fields.filter(f=>f.type==='bool'), rest = fields.filter(f=>f.type!=='bool');
  $('#labFields').innerHTML =
    (rest.length?`<div class="cols-3">${rest.map(f=>fieldControl(f, lab.params, 'setLabParam')).join('')}</div>`:'') +
    (bools.length?`<div class="checks" style="margin-top:8px">${bools.map(f=>fieldControl(f, lab.params, 'setLabParam')).join('')}</div>`:'');
}
function setLabParam(id, val){
  lab.params[id] = val;
  if(lab.op === 'add_audio' && id === 'mode' && val === 'mix' && (lab.params.acodec || 'copy') === 'copy'){
    lab.params.acodec = 'aac';
  }
  if(id === 'mode' || id === 'position'){
    renderLabFields();
    updateLabPanelVisibility();
  }
  syncLab();
}
const AUDIO_ONLY_KEYS = ['arc_mode','abitrate','aq','avbr','acompression','aprofile',
  'avbr_mode','aapplication','aframe_duration','asample_fmt','acutoff','aextra','ar','ac','achannel_layout'];

function onHwChange(val){
  if(val === 'cuda' && (!lab.enc.vcodec || lab.enc.vcodec === 'libx264')) lab.enc.vcodec = 'h264_nvenc';
  else if(val === 'vaapi' && (!lab.enc.vcodec || lab.enc.vcodec === 'libx264')) lab.enc.vcodec = 'h264_vaapi';
  else if(val === 'qsv' && (!lab.enc.vcodec || lab.enc.vcodec === 'libx264')) lab.enc.vcodec = 'h264_qsv';
  renderEncoder(); syncLab();
}

function setEnc(id, val){
  // Quality scales are codec-specific, so carrying them across a codec change
  // would silently apply an MP3 "2" as an AAC VBR figure.
  if(id === 'acodec' && val !== lab.enc.acodec)
    AUDIO_ONLY_KEYS.forEach(k=>{ delete lab.enc[k]; });
  if(id === 'vcodec' && val !== lab.enc.vcodec)
    ['rc_mode','crf','preset','tune','profile','level','pix_fmt','x_params','twopass','vbitrate','maxrate','bufsize'].forEach(k=>delete lab.enc[k]);
  if(id === 'ac') delete lab.enc.achannel_layout;
  if(id === 'achannel_layout') delete lab.enc.ac;
  lab.enc[id] = val;
  if(id === 'vcodec'){
    if(val.endsWith('_nvenc') && !$('#ffHw').value) $('#ffHw').value = 'cuda';
    else if(val.endsWith('_vaapi') && !$('#ffHw').value) $('#ffHw').value = 'vaapi';
    else if(val.endsWith('_qsv') && !$('#ffHw').value) $('#ffHw').value = 'qsv';
  }
  if(id === 'twopass' && val === true){
    lab.enc.rc_mode = 'bitrate';
    delete lab.enc.crf;
    if(!lab.enc.vbitrate){
      lab.enc.vbitrate = '4M';
      toast('Switched to bitrate mode (4M) for two-pass encoding');
    }
  }
  if(id === 'rc_mode' && val !== 'bitrate'){
    lab.enc.twopass = false;
  }
  if(lab.op === 'trim' && !$('#seekAcc').checked && (id === 'vcodec' || id === 'acodec') && val && val !== 'copy'){
    $('#seekAcc').checked = true;
  }
  renderEncoder(); syncLab();
}

function _enc(id, table){ return (table||[]).find(e=>e.id===id) || {}; }

/* The audio panel is built from the encoder's own declaration, because the
   quality scales genuinely differ: LAME counts 0-9 downward, native AAC uses a
   fractional VBR figure, libfdk takes 1-5, FLAC has a compression level and
   nothing else. Showing one generic "quality" box for all of them is wrong. */
function audioPanel(spec, opt){
  const e = lab.enc;
  const modes = spec.arc || [];
  const mode = modes.includes(e.arc_mode) ? e.arc_mode : (modes[0] || '');
  const label = { bitrate:'Target bitrate', quality:'Quality (VBR)',
                  vbr:'VBR level', compression:'Compression' };

  const modeChips = modes.length > 1 ? `
    <div class="field"><label>Rate control</label>
      <div class="chips">${modes.map(md=>
        `<button class="chip ${md===mode?'on':''}" data-act="encArc" data-m="${md}">${
          esc(label[md]||md)}</button>`).join('')}</div></div>` : '';

  let control = '';
  if(mode === 'bitrate'){
    const list = spec.bitrates || ['128k','192k','256k','320k'];
    const cur = e.abitrate || spec.abr_default || '';
    control = `
      <div class="field"><label>Bitrate</label>
        <input type="text" value="${esc(cur)}" placeholder="${esc(spec.abr_default||'192k')}"
          oninput="setEnc('abitrate',this.value)">
        <div class="chips" style="margin-top:6px">${list.map(bx=>
          `<button class="chip mono ${bx===cur?'on':''}" data-act="encAbr" data-v="${bx}">${bx}</button>`).join('')}</div>
        <p class="help">Sets the target bitrate. Actual variation depends on the encoder and its VBR mode.</p></div>`;
  } else if(mode === 'quality'){
    const r = spec.q_range || [0,9], step = spec.q_step || 1;
    const cur = e.aq != null && e.aq !== '' ? e.aq : (spec.q_default != null ? spec.q_default : r[0]);
    control = `
      <div class="field"><label>Quality &nbsp;<span class="mono">${esc(cur)}</span></label>
        <input type="range" min="${r[0]}" max="${r[1]}" step="${step}" value="${esc(cur)}"
          oninput="setEnc('aq',this.value)">
        <div class="inline" style="margin-top:4px">
          <span class="help" style="margin:0">${r[0]}</span>
          <input type="number" value="${esc(cur)}" min="${r[0]}" max="${r[1]}" step="${step}"
            style="max-width:88px" oninput="setEnc('aq',this.value)">
          <span class="help" style="margin:0">${r[1]}</span></div>
        ${spec.q_hint?`<p class="help">${esc(spec.q_hint)}</p>`:''}</div>`;
  } else if(mode === 'vbr'){
    const r = spec.vbr_range || [1,5];
    const cur = e.avbr != null && e.avbr !== '' ? e.avbr : (spec.vbr_default || 4);
    control = `
      <div class="field"><label>VBR level &nbsp;<span class="mono">${esc(cur)}</span></label>
        <input type="range" min="${r[0]}" max="${r[1]}" step="1" value="${esc(cur)}"
          oninput="setEnc('avbr',this.value)">
        ${spec.vbr_hint?`<p class="help">${esc(spec.vbr_hint)}</p>`:''}</div>`;
  } else if(mode === 'compression'){
    const r = spec.compression_range || [0,12];
    const cur = e.acompression != null && e.acompression !== ''
      ? e.acompression : (spec.compression_default != null ? spec.compression_default : r[1]);
    control = `
      <div class="field"><label>${esc(spec.compression_label||'Compression')} &nbsp;<span class="mono">${esc(cur)}</span></label>
        <input type="range" min="${r[0]}" max="${r[1]}" step="1" value="${esc(cur)}"
          oninput="setEnc('acompression',this.value)">
        ${spec.compression_hint?`<p class="help">${esc(spec.compression_hint)}</p>`:''}</div>`;
  } else {
    control = `<div class="field"><p class="help">This codec is lossless and has no quality
      setting. Resampling, channel changes and filters can still change the audio.</p></div>`;
  }

  // Encoding effort is offered alongside rate control where it is independent of it.
  const effort = (spec.compression_range && mode !== 'compression') ? `
    <div class="field"><label>${esc(spec.compression_label||'Encoding effort')} &nbsp;<span class="mono">${
      esc(e.acompression ?? (spec.compression_default ?? ''))}</span></label>
      <input type="range" min="${spec.compression_range[0]}" max="${spec.compression_range[1]}" step="1"
        value="${esc(e.acompression ?? (spec.compression_default ?? spec.compression_range[1]))}"
        oninput="setEnc('acompression',this.value)">
      <p class="help">Controls encoder effort. The speed, size and quality tradeoff depends on the codec.</p></div>` : '';

  const extras = [];
  if(spec.profiles) extras.push(`<div class="field"><label>Profile</label>
    <select onchange="setEnc('aprofile',this.value)">${opt(spec.profiles, e.aprofile)}</select>
    <p class="help">HE variants are for low bitrates and are not universally supported.</p></div>`);
  if(spec.vbr_modes) extras.push(`<div class="field"><label>VBR mode</label>
    <select onchange="setEnc('avbr_mode',this.value)">${opt([''].concat(spec.vbr_modes), e.avbr_mode)}</select></div>`);
  if(spec.applications) extras.push(`<div class="field"><label>Tuned for</label>
    <select onchange="setEnc('aapplication',this.value)">${opt(spec.applications, e.aapplication)}</select>
    <p class="help">"voip" favours speech intelligibility, "lowdelay" cuts latency.</p></div>`);
  if(spec.frame_durations) extras.push(`<div class="field"><label>Frame duration (ms)</label>
