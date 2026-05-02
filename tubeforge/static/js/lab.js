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
    <select onchange="setEnc('aframe_duration',this.value)">${opt(spec.frame_durations, e.aframe_duration)}</select></div>`);
  if(spec.sample_fmts) extras.push(`<div class="field"><label>Sample format</label>
    <select onchange="setEnc('asample_fmt',this.value)">${opt(spec.sample_fmts, e.asample_fmt)}</select></div>`);

  return `
    <div class="sep"></div>
    <div class="lbl" style="margin-bottom:8px">Audio · ${esc(spec.label||'')}</div>
    ${modeChips}
    <div class="cols-3">${control}${effort}</div>
    <div class="cols-3">
      <div class="field"><label>Sample rate</label>
        <select onchange="setEnc('ar',this.value)">${opt([''].concat((labAudioCaps.codec===e.acodec && labAudioCaps.sample_rates) || spec.sample_rates || BOOT.sample_rates.filter(Boolean)), e.ar, 'Auto')}</select>
        ${['libopus','opus'].includes(e.acodec)?'<p class="help">Opus input rates: 8, 12, 16, 24 or 48 kHz (native: 48 kHz). Playback/probe commonly reports 48 kHz.</p>':''}</div>
      <div class="field"><label>Channels</label>
        <select onchange="setEnc('ac',this.value)">${opt([''].concat(['libmp3lame','opus'].includes(e.acodec)?['1','2']:['1','2','3','4','5','6','7','8']), e.ac)}</select></div>
      <div class="field"><label>Channel layout</label>
        <select onchange="setEnc('achannel_layout',this.value)">${opt([''].concat((labAudioCaps.codec===e.acodec && labAudioCaps.channel_layouts) || (['libmp3lame','opus'].includes(e.acodec)?['mono','stereo']:BOOT.channel_layouts.filter(Boolean))), e.achannel_layout)}</select></div>
      ${extras.join('')}
      <div class="field"><label>Low-pass cutoff (Hz)</label>
        <input type="number" value="${esc(e.acutoff||'')}" placeholder="e.g. 20000"
          oninput="setEnc('acutoff',this.value)">
        <p class="help">Discards everything above this. Leave blank to let the encoder decide.</p></div>
      <div class="field"><label>Extra audio arguments</label>
        <input type="text" value="${esc(e.aextra||'')}" placeholder="-aac_coder twoloop"
          oninput="setEnc('aextra',this.value)"></div>
    </div>`;
}

on('encArc', d=>{ lab.enc.arc_mode = d.m; renderEncoder(); syncLab(); });
on('encAbr', d=>{ lab.enc.abitrate = d.v; renderEncoder(); syncLab(); });

function renderEncoder(){
  const v = lab.enc.vcodec || '';
  const a = lab.enc.acodec || '';
  const vs = BOOT.video_encoders.find(e=>e.id===v);
  const rcModes = (vs && vs.rc) ? vs.rc : [];
  const opt = (arr, sel, blank='— not set —') => (arr||[]).map(c=>
    `<option value="${esc(c)}" ${String(c)===String(sel)?'selected':''}>${esc(c===''?blank:c)}</option>`).join('');
  $('#encForm').innerHTML = `
    <div class="cols-3">
      <div class="field" ${labAudioOnly?'style="display:none"':''}><label>Video codec</label><select onchange="setEnc('vcodec',this.value)">
        <option value="">— leave to ffmpeg —</option>
        ${BOOT.video_encoders.map(e=>`<option value="${e.id}" ${e.id===v?'selected':''}>${esc(e.label)}</option>`).join('')}
      </select></div>
      <div class="field"><label>Audio codec</label><select onchange="setEnc('acodec',this.value)">
        <option value="">— leave to ffmpeg —</option>
        ${BOOT.audio_encoders.filter(e=>!e.hidden).map(e=>`<option value="${e.id}" ${e.id===a?'selected':''}>${esc(e.label)}</option>`).join('')}
      </select></div>
      <div class="field" ${labAudioOnly?'style="display:none"':''}><label>Subtitle codec</label><select onchange="setEnc('scodec',this.value)">
        ${opt([''].concat(BOOT.subtitle_codecs), lab.enc.scodec)}</select></div>
    </div>
    ${(vs && v!=='copy' && !labAudioOnly) ? `
    <div class="sep"></div>
    ${labProbe.duration ? `<div class="inline" style="margin-bottom:8px;flex-wrap:wrap;gap:6px">
      <span class="lbl" style="margin:0">Fit to:</span>
      ${[8, 10, 25, 50, 100].map(mb => `<button class="chip" onclick="fitTargetSize(${mb})">${mb} MB</button>`).join('')}
    </div>` : ''}
    <div class="cols-3">
      ${rcModes.length?`<div class="field"><label>Rate control</label><select onchange="setEnc('rc_mode',this.value)">
        ${opt(rcModes.filter(x=>x!=='twopass'), lab.enc.rc_mode||rcModes[0],'')}</select></div>`:''}
      <div class="field" ${!rcModes.length || lab.enc.rc_mode==='bitrate'?'style="display:none"':''}><label>Quality ${vs.crf_range?`(${vs.crf_range[0]}–${vs.crf_range[1]}, lower is better)`:''}</label>
        <input type="number" value="${esc(lab.enc.crf ?? (vs.crf_default ?? ''))}" oninput="setEnc('crf',this.value)"></div>
      <div class="field"><label>Target bitrate</label>
        <input type="text" value="${esc(lab.enc.vbitrate||'')}" placeholder="5M" oninput="setEnc('vbitrate',this.value)"></div>
      ${vs.presets?`<div class="field"><label>Speed preset</label><select onchange="setEnc('preset',this.value)">
        ${opt([''].concat(vs.presets), lab.enc.preset)}</select></div>`:''}
      ${vs.tunes?`<div class="field"><label>Tune</label><select onchange="setEnc('tune',this.value)">
        ${opt(vs.tunes, lab.enc.tune)}</select></div>`:''}
      ${vs.profiles?`<div class="field"><label>Profile</label><select onchange="setEnc('profile',this.value)">
        ${opt(vs.profiles, lab.enc.profile)}</select></div>`:''}
      <div class="field"><label>Pixel format</label><select onchange="setEnc('pix_fmt',this.value)">
        ${opt(['','yuv420p','yuv422p','yuv444p','yuv420p10le','yuv422p10le','nv12','p010le'], lab.enc.pix_fmt)}</select></div>
      <div class="field"><label>Max rate</label><input type="text" value="${esc(lab.enc.maxrate||'')}" placeholder="8M" oninput="setEnc('maxrate',this.value)"></div>
      <div class="field"><label>Buffer size</label><input type="text" value="${esc(lab.enc.bufsize||'')}" placeholder="16M" oninput="setEnc('bufsize',this.value)"></div>
      <div class="field"><label>Keyframe interval</label><input type="number" value="${esc(lab.enc.gop||'')}" placeholder="250" oninput="setEnc('gop',this.value)"></div>
      <div class="field"><label>B-frames</label><input type="number" value="${esc(lab.enc.bframes||'')}" oninput="setEnc('bframes',this.value)"></div>
      <div class="field"><label>Threads</label><input type="number" value="${esc(lab.enc.threads||'')}" placeholder="0 = auto" oninput="setEnc('threads',this.value)"></div>
      ${(vs.family==='x264'||vs.family==='x265')?`<div class="field"><label>${vs.family} params</label>
        <input type="text" value="${esc(lab.enc.x_params||'')}" placeholder="aq-mode=3:psy-rd=1.0" oninput="setEnc('x_params',this.value)"></div>`:''}
    </div>` : ''}
    ${(a && a!=='copy') ? audioPanel(_enc(a, BOOT.audio_encoders), opt) : ''}
    <div class="sep"></div>
    <div class="checks">
      ${lab.op==='transcode' && !labAudioOnly && vs && ['x264','x265','vpx','mpeg'].includes(vs.family) ? checkWithHint(`<label class="check ${lab.enc.twopass?'on':''}"><input type="checkbox" ${lab.enc.twopass?'checked':''} onchange="setEnc('twopass',this.checked)">
        <span>Two-pass encode</span></label>`, 'Two-pass encode', 'Encodes once to measure the material, then again to spend the bits where they matter. Needs a target bitrate, and only software encoders support it. Takes about twice as long.') : ''}
      ${checkWithHint(`<label class="check ${lab.enc.faststart?'on':''}"><input type="checkbox" ${lab.enc.faststart?'checked':''} onchange="setEnc('faststart',this.checked)">
        <span>Web-optimise MP4</span></label>`, 'Web-optimise MP4', 'Moves the index to the front of the file so playback can start before the download finishes. Only applies to the MP4 family.')}
      <label class="check ${lab.enc.shortest?'on':''}"><input type="checkbox" ${lab.enc.shortest?'checked':''} onchange="setEnc('shortest',this.checked)">
        <span>Stop at the shortest input</span></label>
    </div>
    <div class="field" style="margin-top:9px"><label>Extra output arguments</label>
      <input type="text" value="${esc(lab.enc.extra_out||'')}" placeholder="-map_metadata 0 -tag:v hvc1" oninput="setEnc('extra_out',this.value)"></div>`;
  const aspec = _enc(a, BOOT.audio_encoders);
  const amode = (aspec.arc||[]).includes(lab.enc.arc_mode) ? lab.enc.arc_mode : (aspec.arc||[])[0];
  const abit = amode === 'bitrate' ? (lab.enc.abitrate || aspec.abr_default || '')
             : amode === 'quality' ? ('q' + (lab.enc.aq ?? aspec.q_default ?? ''))
             : amode === 'vbr' ? ('vbr' + (lab.enc.avbr ?? aspec.vbr_default ?? ''))
             : amode === 'compression' ? ('c' + (lab.enc.acompression ?? aspec.compression_default ?? ''))
             : '';
  const bits = [v||'auto', a||'auto', lab.enc.crf!=null&&v&&v!=='copy'?('q'+lab.enc.crf):'',
                lab.enc.preset||'', abit];
  $('#encSummary').textContent = bits.filter(Boolean).join(' · ');
}

function renderContainerChips(){
  const cur = (lab.output.match(/\.([^.]+)$/)||[])[1];
  $('#containerChips').innerHTML = (labContainerOptions.length?labContainerOptions:BOOT.containers).map(c=>
    `<button class="chip mono ${c===cur?'on':''}" data-act="setContainer" data-c="${esc(c)}">.${c}</button>`).join('');
}
const CONTAINER_DEFAULT_CODECS = {
  webm: { vcodec: 'libvpx-vp9', acodec: 'libopus' },
  mp4:  { vcodec: 'libx264',    acodec: 'aac' },
  m4v:  { vcodec: 'libx264',    acodec: 'aac' },
  mov:  { vcodec: 'libx264',    acodec: 'aac' },
  mkv:  { vcodec: 'libx264',    acodec: 'aac' },
  avi:  { vcodec: 'mpeg4',      acodec: 'libmp3lame' },
  flv:  { vcodec: 'libx264',    acodec: 'aac' },
  ts:   { vcodec: 'libx264',    acodec: 'aac' },
  mxf:  { vcodec: 'dnxhd',      acodec: 'pcm_s16le' },
  gif:  { op: 'gif' },
  webp: { op: 'webp' },
  png:  { op: 'screenshot' },
  jpg:  { op: 'screenshot' },
};
const AUDIO_CONTAINER_CODECS = {
  mp3:'libmp3lame', m4a:'aac', aac:'aac', opus:'libopus', ogg:'libvorbis',
  flac:'flac', wav:'pcm_s16le', aiff:'pcm_s16le', ac3:'ac3', eac3:'eac3', thd:'truehd'
};

function fitTargetSize(targetMB){
  const clipDur = Math.max(1, Number(labProbe.duration) || 60);
  const audioKbps = parseInt(lab.enc.abitrate, 10) || 128;
  const vKbps = Math.max(100, Math.floor((targetMB * 8192 * 0.95) / clipDur - audioKbps));
  lab.enc.vbitrate = vKbps + 'k';
  lab.enc.rc_mode = 'bitrate';
  delete lab.enc.crf;
  const vs = BOOT.video_encoders.find(e => e.id === lab.enc.vcodec);
  if(lab.op === 'transcode' && vs && ['x264','x265','vpx','mpeg'].includes(vs.family)){
    lab.enc.twopass = true;
  }
  renderEncoder(); syncLab();
  toast(`Target ${targetMB} MB`, `Video bitrate set to ${lab.enc.vbitrate}`);
}

function setContainer(ext){
  const base = (lab.output || 'output').replace(/\.[^.]+$/, '');
  lab.output_mode = 'manual';

  if(AUDIO_CONTAINER_CODECS[ext]){
    if(!['audio_convert', 'extract_audio'].includes(lab.op) && lab.op === 'transcode'){
      lab.op = 'audio_convert';
      labAudioOnly = true;
    }
    if(['audio_convert', 'extract_audio'].includes(lab.op) || labAudioOnly){
      AUDIO_ONLY_KEYS.forEach(k => delete lab.enc[k]);
      lab.enc.acodec = AUDIO_CONTAINER_CODECS[ext];
    }
  } else if(CONTAINER_DEFAULT_CODECS[ext]){
    const def = CONTAINER_DEFAULT_CODECS[ext];
    if(def.op && lab.op === 'transcode'){
      pickOp(def.op);
      return;
    }
    if(opMeta().enc && !labAudioOnly){
      if(ext === 'webm' && !['libvpx-vp9','libvpx','libsvtav1','libaom-av1','librav1e','av1_nvenc','av1_vaapi','copy'].includes(lab.enc.vcodec)){
