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
