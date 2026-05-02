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
        ['rc_mode','crf','preset','tune','profile','level','pix_fmt','x_params'].forEach(k => delete lab.enc[k]);
        lab.enc.vcodec = def.vcodec;
      }
      if(ext === 'webm' && !['libopus','opus','libvorbis','copy'].includes(lab.enc.acodec)){
        AUDIO_ONLY_KEYS.forEach(k => delete lab.enc[k]);
        lab.enc.acodec = def.acodec;
      }
      if(['mp4','m4v','mov'].includes(ext) && ['libvpx','libvorbis'].includes(lab.enc.vcodec)){
        lab.enc.vcodec = def.vcodec;
      }
      if(['mp4','m4v','mov'].includes(ext) && ['libvorbis','pcm_s16le'].includes(lab.enc.acodec)){
        AUDIO_ONLY_KEYS.forEach(k => delete lab.enc[k]);
        lab.enc.acodec = def.acodec;
      }
    }
  }
  lab.output = base + '.' + ext;
  $('#labOut').value = lab.output;
  renderLab();
}

function labSpec(){
  return {
    op: lab.op, inputs: lab.inputs.filter(x=>x.trim()), output: $('#labOut').value,
    params: lab.params, enc: lab.enc, output_mode:lab.output_mode || 'auto',
    vfilters: chains.video, afilters: chains.audio,
    seek: { ss:$('#seekSS').value, to:$('#seekTo').value, t:$('#seekT').value, accurate:$('#seekAcc').checked },
    hwaccel: $('#ffHw').value, loglevel: $('#ffLog').value,
    extra_pre: $('#ffPre').value, overwrite: $('#ffOverwrite').checked ? '1' : ''
  };
}

const syncLab = debounce(async (force)=>{
  lab.output = $('#labOut').value;
  saveLocal();
  let spec = labSpec();
  const revision = ++labRevision;
  const fingerprint = JSON.stringify(spec);
  if(!spec.inputs.length && lab.op !== 'freeform'){
    $('#labCmd').innerHTML = '<div class="readout"><span class="muted">Choose an input file to build the command.</span></div>';
    $('#labNotes').innerHTML = ''; return;
  }
  try{
    const settings = await api('/api/ffmpeg/settings', {method:'POST', body:JSON.stringify(spec)});
    if(revision!==labRevision || fingerprint!==JSON.stringify(labSpec())) return;
    lab.enc=settings.enc; lab.params=settings.params; lab.output=settings.output;
    labAudioOnly=settings.audio_only;
    labContainerOptions=settings.containers || [];
    labProbe = { streams: settings.streams || [], duration: settings.duration || null, chapters: settings.chapters || [] };
    labAudioCaps={...settings.audio_caps,codec:lab.enc.acodec};
    labVideoCaps={...settings.video_caps,codec:lab.enc.vcodec};
    $('#labOut').value=lab.output;
    $('#labOutputHint').textContent=(lab.output_mode==='manual'?'Custom name; extension checked against streams.':'Automatic name and compatible container.')+' Existing files are kept unless overwrite is enabled.';
    if(!document.activeElement?.closest('#labFields') && ['extract_audio','extract_video','extract_subs'].includes(lab.op)) renderLabFields();
    if(!document.activeElement?.closest('#encForm')) renderEncoder();
    renderContainerChips(); saveLocal();
    spec=labSpec();
    const normalizedFingerprint=JSON.stringify(spec);
    const j = await api('/api/ffmpeg/preview', {method:'POST', body:JSON.stringify(spec)});
    if(revision!==labRevision || normalizedFingerprint!==JSON.stringify(labSpec())) return;
    j.notes=[...(settings.notes||[]),...(j.notes||[])];
    $('#labCmd').innerHTML = j.stages.map(s=>{
      const id = 'rc'+Math.random().toString(36).slice(2,8);
      return `${j.stages.length>1?`<span class="readout-stage">${esc(s.label)}</span>`:''}
        <div class="readout" id="${id}"></div>`;
    }).join('');
    j.stages.forEach((s,i)=>paintCmd($$('#labCmd .readout')[i], s.cmd));
    const m = opMeta();
    const filterWarn = (!m.filters && (chains.video.length + chains.audio.length) > 0)
      ? `<div class="note info">Note: You have active filters in Filter Studio, which are not used by '${esc(m.label || lab.op)}'. Switch to Transcode or clear the filter chain.</div>`
      : '';
    $('#labNotes').innerHTML =
      filterWarn +
      (j.warnings||[]).map(w=>`
        <div class="note ${w.level==='block'?'':'info'}">
          <b>${esc(w.text)}</b>
          ${w.why?`<div style="margin-top:3px;opacity:.85">${esc(w.why)}</div>`:''}
          ${w.fix?`<div style="margin-top:3px">${esc(w.fix)}</div>`:''}
          ${w.apply?`<button class="btn sm alt" style="margin-top:7px"
            data-act="labFix" data-i="${(j.warnings||[]).indexOf(w)}">${esc(w.apply_label||'Fix this')}</button>`:''}
        </div>`).join('') +
      (j.notes||[]).map(n=>`<div class="note">${esc(n)}</div>`).join('');
    labWarnings = j.warnings || [];
  }catch(e){
    if(revision!==labRevision) return;
    $('#labCmd').innerHTML = `<div class="readout" style="border-left-color:var(--fault)">${esc(e.message)}</div>`;
    $('#labNotes').innerHTML = '';
  }
}, 260);

let labWarnings = [];
on('labFix', d=>{
  const w = labWarnings[+d.i];
  if(!w || !w.apply) return;
  Object.entries(w.apply).forEach(([k,v])=>{ lab.enc[k] = v; });
  renderEncoder(); syncLab();
  toast('Applied', w.apply_label||'');
});

async function runLab(extra){
  const spec = labSpec();
  if(extra && extra.ignore) spec.ignore_warnings = true;
  try{
    const r = await fetch('/api/ffmpeg/run', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(spec)});
    const j = await r.json();
    if(r.status === 409 && j.blocked){ showLabBlocker(j.warnings); return; }
    if(!r.ok || j.ok === false) throw new Error(j.error || 'Request failed');
    toast('Job queued', opMeta().label||''); openDock(); selectJob(j.job);
  }catch(e){ fail(e); }
}

function showLabBlocker(warnings){
  const w = (warnings||[]).find(x=>x.level==='block') || {};
  labWarnings = warnings || [];
  modal('This will not work as configured', `
    <div class="note"><b>${esc(w.text||'')}</b>
      ${w.why?`<div style="margin-top:6px;opacity:.85">${esc(w.why)}</div>`:''}
      ${w.fix?`<div style="margin-top:6px">${esc(w.fix)}</div>`:''}</div>`,
    `${w.apply?`<button class="btn go" data-act="labFixClose" data-i="${(warnings||[]).indexOf(w)}">${
      esc(w.apply_label||'Fix this')}</button>`:''}
     <button class="btn" data-act="labRunAnyway">Run anyway</button>`);
}
on('labFixClose', d=>{ ACTIONS.labFix(d); closeModal(); });
on('labRunAnyway', ()=>{ closeModal(); runLab({ignore:true}); });

/* ══════════════════════════════════════════════════════════════════════
   FILTER STUDIO
   ══════════════════════════════════════════════════════════════════════ */
function openFilterPicker(kind){
  const cats = {};
  BOOT.filters.filter(f=>f.kind===kind).forEach(f=>(cats[f.cat]=cats[f.cat]||[]).push(f));
  const html = Object.keys(cats).map(c=>`
    <div class="lbl" style="margin-top:10px">${esc(c)}</div>
    <div class="chips">${cats[c].map(f=>
      `<button class="chip" title="${esc(f.help||'')}" data-act="filtAdd" data-kind="${esc(kind)}" data-fid="${esc(f.id)}">${esc(f.label)}</button>`
    ).join('')}</div>`).join('');
  modal(kind==='video'?'Add a video filter':'Add an audio filter', html);
}

function addFilter(kind, id){
  const spec = BOOT.filters.find(f=>f.id===id);
  const params = {}; (spec.params||[]).forEach(p=>params[p.id]=p.default);
  chains[kind].push({ id, params, enabled:true, uid:Math.random().toString(36).slice(2,9) });
  if(kind === 'video' && lab.enc.vcodec === 'copy'){
    delete lab.enc.vcodec;
    toast('Filter added — switched video codec from Copy to Auto');
  }
  if(kind === 'audio' && lab.enc.acodec === 'copy'){
    delete lab.enc.acodec;
    toast('Filter added — switched audio codec from Copy to Auto');
  }
  closeModal(); renderChains(); toast('Filter added', spec.label);
}

function renderChains(){
  ['video','audio'].forEach(kind=>{
    const host = $(kind==='video'?'#vChain':'#aChain');
    const list = chains[kind];
    $(kind==='video'?'#vChainCount':'#aChainCount').textContent =
      `${list.length} filter${list.length===1?'':'s'}`;
    if(!list.length){
      host.innerHTML = `<div class="empty"><b>Chain is empty</b>Filters apply top to bottom, in order.</div>`;
      return;
    }
    host.innerHTML = list.map((f,i)=>{
      const spec = BOOT.filters.find(x=>x.id===f.id) || {label:f.id, params:[]};
      return `<div class="stepcard">
        <div class="stepcard-head">
          <span class="stepnum">${i+1}</span>
          <b style="font-size:.8rem">${esc(spec.label)}</b>
          <span class="mono muted" style="font-size:.68rem">${esc(f.id)}</span>
          <div class="spacer"></div>
          <label class="check" style="padding:0">
            <input type="checkbox" ${f.enabled!==false?'checked':''}
              data-change="filtToggle" data-kind="${kind}" data-i="${i}"><span>on</span></label>
          <button class="btn sm icon" ${i===0?'disabled':''} data-act="filtMove" data-kind="${kind}" data-i="${i}" data-d="-1">↑</button>
          <button class="btn sm icon" ${i===list.length-1?'disabled':''} data-act="filtMove" data-kind="${kind}" data-i="${i}" data-d="1">↓</button>
          <button class="btn sm bad icon" data-act="filtDrop" data-kind="${kind}" data-i="${i}">×</button>
        </div>
        <div class="stepcard-body">
          ${spec.help?`<p class="help" style="margin:0 0 8px">${esc(spec.help)}</p>`:''}
          ${(spec.params||[]).length?`<div class="cols-3">${spec.params.map(p=>
            fieldControlFilter(p, kind, i)).join('')}</div>`:'<p class="help">No parameters.</p>'}
        </div></div>`;
    }).join('');
  });
  updateGraphs(); renderLabFilterPreview(); saveLocal();
  $$('.filtCount').forEach(el=>{ el.textContent = chains.video.length + chains.audio.length; });
}

on('filtToggle', (d,el)=>{ chains[d.kind][+d.i].enabled = el.checked; renderChains(); syncLab(); });
on('filtMove',   d=>moveFilter(d.kind, +d.i, +d.d));
on('filtDrop',   d=>{ chains[d.kind].splice(+d.i,1); renderChains(); });
on('filtAdd',    d=>addFilter(d.kind, d.fid));
on('filtPicker', d=>openFilterPicker(d.kind));

function fieldControlFilter(p, kind, i){
  const v = chains[kind][i].params[p.id] ?? p.default ?? '';
  const set = `setFilterParam(this.dataset.kind, +this.dataset.i, this.dataset.pid, this.value)`;
  let inp;
  const ref = `data-kind="${kind}" data-i="${i}" data-pid="${esc(p.id)}"`;
  if(p.type==='select')
    inp = `<select ${ref} onchange="${set}">${(p.choices||[]).map(c=>
      `<option value="${esc(c)}" ${String(c)===String(v)?'selected':''}>${esc(c===''?'—':c)}</option>`).join('')}</select>`;
  else if(['file','fontfile','filename'].includes(p.id))
    inp = `<div class="inline"><input type="text" value="${esc(v)}" ${ref}
      placeholder="${esc(p.placeholder||'')}" oninput="${set}">
      <button class="btn sm" type="button" onclick="browsePath({mode:'file',initial:chains['${kind}'][${i}].params['${p.id}']||'',title:'Select ${esc(p.label)}',onPick:val=>{chains['${kind}'][${i}].params['${p.id}']=val;renderChains();}})">Browse…</button></div>`;
  else
    inp = `<input type="${p.type==='number'?'number':'text'}" value="${esc(v)}" ${ref}
      ${p.step?`step="${p.step}"`:''} placeholder="${esc(p.placeholder||'')}" oninput="${set}">`;
  return `<div class="field"><label>${esc(p.label)}</label>${inp}${p.help?`<p class="help">${esc(p.help)}</p>`:''}</div>`;
}
function setFilterParam(kind,i,pid,val){ chains[kind][i].params[pid]=val; updateGraphs(); renderLabFilterPreview(); saveLocal(); }
function moveFilter(kind,i,d){
  const a = chains[kind]; const j = i+d;
  if(j<0||j>=a.length) return;
  [a[i],a[j]] = [a[j],a[i]]; renderChains();
}
function clearFilters(){ chains={video:[],audio:[]}; renderChains(); syncLab(); }

function localGraph(kind){
  const escapeValue = value => {
    let v = String(value);
    for(const chars of ["\\:'", "\\'[],;"])
      v = Array.from(v).map(c => chars.includes(c) ? '\\' + c : c).join('');
    return v;
  };
  return chains[kind].filter(f => f.enabled !== false).map(f => {
    const spec = BOOT.filters.find(x => x.id === f.id);
    if(!spec) return '';
    const positional = [], named = [];
    let allowPos = true;
    (spec.params || []).forEach(p => {
      let value = f.params[p.id] ?? p.default ?? '';
      value = String(value).trim();
      if(value === ''){
        if(p.pos) allowPos = false;
        return;
      }
      const val = escapeValue(value);
      if(p.pos && allowPos && !named.length){
        positional.push(val);
      } else {
        allowPos = false;
        const key = (spec.id === 'aresample' && p.id === 'rate') ? 'sample_rate' : p.arg;
        named.push(`${key}=${val}`);
      }
    });
    if(spec.id === 'drawtext') named.push('expansion=none');
    const parts = positional.concat(named);
    return spec.id + (parts.length ? '=' + parts.join(':') : '');
  }).filter(Boolean).join(',');
}
function updateFilterPreview(){
  const box = $('#filterPrevBox');
  if(!box) return;
  const p = (lab.inputs && lab.inputs[0]) ? lab.inputs[0].trim() : '';
  if(!p){
    box.innerHTML = '<span class="muted">Set an input file in Media lab to preview filters on a frame.</span>';
    return;
  }
  const t = $('#filterPrevTime') ? $('#filterPrevTime').value : '5';
  const vf = encodeURIComponent(JSON.stringify(chains.video || []));
  box.innerHTML = `<img class="player" style="max-height:260px;object-fit:contain" src="/api/thumb?path=${encodeURIComponent(p)}&t=${encodeURIComponent(t)}&vf=${vf}&_=${Date.now()}" onerror="this.replaceWith(document.createTextNode('Preview unavailable for this input/filter.'))">`;
}

function updateGraphs(){
  const v = localGraph('video'), a = localGraph('audio');
  $('#vGraph').innerHTML = (v?esc(v):'<span class="muted">empty</span>') +
    '<button class="copy-btn" data-act="copyEl">Copy</button>';
  updateFilterPreview();
  $('#aGraph').innerHTML = (a?esc(a):'<span class="muted">empty</span>') +
    '<button class="copy-btn" data-act="copyEl">Copy</button>';
}
function renderLabFilterPreview(){
  const v = localGraph('video'), a = localGraph('audio');
  const n = chains.video.length + chains.audio.length;
  $('#labFiltSummary').textContent = n ? `${n} active` : 'none';
  $('#labFiltPreview').innerHTML =
    (v?`<span class="readout-stage">-vf</span><div class="readout">${esc(v)}</div>`:'') +
    (a?`<span class="readout-stage" style="margin-top:8px">-af</span><div class="readout">${esc(a)}</div>`:'') ||
    '<p class="help">No filters in the chain.</p>';
  syncLab();
}

/* ══════════════════════════════════════════════════════════════════════
   PIPELINE
   ══════════════════════════════════════════════════════════════════════ */
function addPipeStep(){
  pipeSteps.push({ op:'transcode', params:{}, enc:{}, extra_inputs:[],
                   vfilters:[], afilters:[], uid:Math.random().toString(36).slice(2,9) });
  renderPipeline();
}
function sendLabToPipeline(){
  const configured=labSpec();
  pipeSteps.push({ op:lab.op, seek:configured.seek, hwaccel:configured.hwaccel,
                   extra_pre:configured.extra_pre, overwrite:configured.overwrite,
                   params:JSON.parse(JSON.stringify(lab.params)),
                   enc:JSON.parse(JSON.stringify(lab.enc)), extra_inputs:lab.inputs.slice(1),
                   vfilters:JSON.parse(JSON.stringify(chains.video)),
                   afilters:JSON.parse(JSON.stringify(chains.audio)),
                   uid:Math.random().toString(36).slice(2,9) });
  if(!$('#pipeIn').value && lab.inputs[0]) $('#pipeIn').value = lab.inputs[0];
  toast('Added to pipeline', opMeta().label);
  show('pipeline');
}
on('pipeMove', d=>movePipe(+d.i, +d.d));
on('pipeDrop', d=>{ pipeSteps.splice(+d.i,1); renderPipeline(); });

function renderPipeline(){
  const host = $('#pipeSteps');
  if(!pipeSteps.length){
    host.innerHTML = `<div class="empty"><b>No steps yet</b>Add one, or configure something in the Media lab and send it here.</div>`;
    syncPipeline(); return;
  }
  host.innerHTML = pipeSteps.map((s,i)=>{
    const m = BOOT.ff_ops.find(o=>o.id===s.op)||{};
    const fields = m.fields||[];
    return `<div class="stepcard">
      <div class="stepcard-head"><span class="stepnum">${i+1}</span>
        <select style="width:auto;min-width:190px" data-i="${i}"
          onchange="pipeSteps[+this.dataset.i].op=this.value;pipeSteps[+this.dataset.i].params={};renderPipeline()">
          ${BOOT.ff_ops.filter(o=>o.out!==false).map(o=>
            `<option value="${o.id}" ${o.id===s.op?'selected':''}>${esc(o.label)}</option>`).join('')}
        </select>
        <div class="spacer"></div>
        <button class="btn sm icon" ${i===0?'disabled':''} data-act="pipeMove" data-i="${i}" data-d="-1">↑</button>
        <button class="btn sm icon" ${i===pipeSteps.length-1?'disabled':''} data-act="pipeMove" data-i="${i}" data-d="1">↓</button>
        <button class="btn sm bad icon" data-act="pipeDrop" data-i="${i}">×</button></div>
      <div class="stepcard-body">
        ${m.help?`<p class="help" style="margin:0 0 8px">${esc(m.help)}</p>`:''}
        ${(()=>{
          const bools = fields.filter(f=>f.type==='bool'), rest = fields.filter(f=>f.type!=='bool');
          return (rest.length?`<div class="cols-3">${rest.map(f=>fieldControl(f, s.params, `setPipeParam_${i}`)).join('')}</div>`:'') +
                 (bools.length?`<div class="row" style="margin-top:6px">${bools.map(f=>fieldControl(f, s.params, `setPipeParam_${i}`)).join('')}</div>`:'');
        })()}
        ${m.inputs>1?`<div class="field"><label>Extra input</label>
          <div class="inline"><input type="text" value="${esc((s.extra_inputs||[])[0]||'')}"
            data-i="${i}" oninput="pipeSteps[+this.dataset.i].extra_inputs=[this.value];syncPipeline()" placeholder="second file">
            <button class="btn sm" type="button" onclick="browsePath({mode:'file',initial:(pipeSteps[${i}].extra_inputs||[])[0]||'',title:'Select extra input',onPick:p=>{pipeSteps[${i}].extra_inputs=[p];renderPipeline();}})">Browse…</button></div></div>`:''}
        ${m.enc?`<div class="cols-3">
          <div class="field"><label>Video codec</label><select data-i="${i}" onchange="pipeSteps[+this.dataset.i].enc.vcodec=this.value;syncPipeline()">
            <option value="">— auto —</option>${BOOT.video_encoders.map(e=>
              `<option value="${e.id}" ${e.id===(s.enc.vcodec||'')?'selected':''}>${esc(e.label)}</option>`).join('')}</select></div>
          <div class="field"><label>Audio codec</label><select data-i="${i}" onchange="pipeSteps[+this.dataset.i].enc.acodec=this.value;syncPipeline()">
            <option value="">— auto —</option>${BOOT.audio_encoders.filter(e=>!e.hidden).map(e=>
              `<option value="${e.id}" ${e.id===(s.enc.acodec||'')?'selected':''}>${esc(e.label)}</option>`).join('')}</select></div>
          <div class="field"><label>Quality</label><input type="number" value="${esc(s.enc.crf||'')}"
            data-i="${i}" oninput="pipeSteps[+this.dataset.i].enc.crf=this.value;syncPipeline()"></div>
        </div>`:''}
      </div></div>`;
  }).join('');
  pipeSteps.forEach((s,i)=>{ window['setPipeParam_'+i] = (id,val)=>{ s.params[id]=val; syncPipeline(); }; });
  syncPipeline();
}
function movePipe(i,d){ const j=i+d; if(j<0||j>=pipeSteps.length) return;
  [pipeSteps[i],pipeSteps[j]]=[pipeSteps[j],pipeSteps[i]]; renderPipeline(); }

function pipeSpec(){
  return { input:$('#pipeIn').value, output:$('#pipeOut').value,
           steps: pipeSteps.map(s=>({ op:s.op, params:s.params, enc:s.enc,
             extra_inputs:s.extra_inputs||[], vfilters:s.vfilters||[], afilters:s.afilters||[],
             seek:s.seek||{}, hwaccel:s.hwaccel||'', extra_pre:s.extra_pre||'', overwrite:s.overwrite||'' })) };
}
const syncPipeline = debounce(async ()=>{
  saveLocal();
  if(!$('#pipeIn').value || !pipeSteps.length){
    $('#pipeCmd').innerHTML = '<div class="readout"><span class="muted">Set a source and add at least one step.</span></div>';
    return;
  }
  try{
    const j = await api('/api/pipeline/preview', {method:'POST', body:JSON.stringify(pipeSpec())});
    $('#pipeCmd').innerHTML = j.stages.map(s=>
      `<span class="readout-stage">${esc(s.label)}</span><div class="readout">${esc(s.cmd)}</div>`).join('') +
      (j.notes||[]).map(n=>`<div class="note">${esc(n)}</div>`).join('');
  }catch(e){ $('#pipeCmd').innerHTML = `<div class="readout" style="border-left-color:var(--fault)">${esc(e.message)}</div>`; }
}, 300);

async function runPipeline(){
  try{ const j = await api('/api/pipeline/run', {method:'POST', body:JSON.stringify(pipeSpec())});
    toast('Pipeline queued', `${pipeSteps.length} steps`); openDock(); selectJob(j.job);
  }catch(e){ fail(e); }
}
async function savePipeline(){
  const name = prompt('Name this pipeline'); if(!name) return;
  try{ await api('/api/pipelines',{method:'POST',body:JSON.stringify({name,data:pipeSpec()})});
    toast('Pipeline saved', name); }catch(e){ fail(e); }
}
async function loadPipelineDialog(){
  try{
    const j = await api('/api/pipelines');
    if(!j.pipelines.length) return toast('Nothing saved yet','Save a pipeline first.');
    pipeIndex = {};
    j.pipelines.forEach(p=>{ pipeIndex[p.id] = p; });
    modal('Load pipeline', j.pipelines.map(p=>`
      <div class="listrow"><span class="fname">${esc(p.name)}</span>
      <span class="facts">
        <button class="btn sm" data-act="pipeLoad" data-id="${p.id}">Load</button>
        <button class="btn sm bad" data-act="pipeDel" data-id="${p.id}">Delete</button>
      </span></div>`).join(''));
  }catch(e){ fail(e); }
}
let pipeIndex = {};
on('pipeLoad', d=>{ const p = pipeIndex[d.id]; if(p) applyPipeline(p.data); });
on('pipeDel',  d=>delPipeline(d.id));

function applyPipeline(d){
  $('#pipeIn').value = d.input||''; $('#pipeOut').value = d.output||'';
  pipeSteps = (d.steps||[]).map(s=>Object.assign({uid:Math.random().toString(36).slice(2,9)}, s));
  closeModal(); renderPipeline(); toast('Pipeline loaded');
}
async function delPipeline(id){ await api('/api/pipelines?id='+id,{method:'DELETE'}); closeModal(); toast('Deleted'); }

/* ══════════════════════════════════════════════════════════════════════
   BATCH
   ══════════════════════════════════════════════════════════════════════ */
on('batchDrop', d=>{ batchFiles.splice(+d.i,1); renderBatch(); });

function renderBatch(){
  $('#batchCount').textContent = `${batchFiles.length} selected`;
  $('#batchOpNote').textContent = 'Operation: ' + (opMeta().label || 'none');
  $('#batchList').innerHTML = batchFiles.length
    ? batchFiles.map((f,i)=>`<div class="listrow">
        <span class="fname" title="${esc(f)}">${esc(f.split('/').pop())}</span>
        <span class="fmeta">${esc(f.replace(/\/[^/]*$/,''))}</span>
        <span class="facts"><button class="btn sm bad icon" data-act="batchDrop" data-i="${i}">×</button></span></div>`).join('')
    : `<div class="empty"><b>No files yet</b>Select some in the Library and send them here.</div>`;
}
function addPastedBatch(){
  const lines = $('#batchPaste').value.split('\n').map(s=>s.trim()).filter(Boolean);
  batchFiles = Array.from(new Set(batchFiles.concat(lines)));
  $('#batchPaste').value=''; renderBatch();
}
async function runBatch(){
  if(!batchFiles.length) return toast('No files selected','Add files before queueing.','bad');
  const spec = { files:batchFiles, op_spec:labSpec(),
                 out_pattern:$('#batchPattern').value, out_dir:$('#batchDir').value };
  try{
    const j = await api('/api/batch/run',{method:'POST',body:JSON.stringify(spec)});
    toast(`Queued ${j.jobs.length} jobs`, j.errors.length?`${j.errors.length} skipped`:'');
    if(j.errors.length) console.warn(j.errors);
    openDock();
  }catch(e){ fail(e); }
}

