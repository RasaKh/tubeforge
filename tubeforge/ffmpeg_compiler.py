import json
import math
import os
import re
import shlex
import subprocess
import threading
import uuid

from .config import CONFIG, PathError, TMP_DIR, dl_dir, parse_time_to_seconds, resolve_path
from .probe import ffprobe_json, media_duration, summarize_probe
from .ffmpeg_registry import (
    AUDIO_ENCODERS,
    CONTAINERS,
    CONTAINER_PRESERVING,
    FF_OPS_INDEX,
    TWOPASS_FAMILIES,
    VIDEO_ENCODERS,
    _esc_filter_value,
    compile_filterchain,
)

# ═══════════════════════════════════════════════════════════════════════════
#  COMPILER HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _safe_ffmpeg_extra(raw, field_name="extra"):
    """Parse extra FFmpeg flags while blocking input/output/protocol escapes unless allow_raw_ffmpeg is enabled."""
    tokens = shlex.split(str(raw))
    if CONFIG.get("allow_raw_ffmpeg"):
        return tokens
    blocked_flags = {"-i", "-f", "-filter_complex_script", "-/filter_complex", "-passlogfile"}
    expect_flag_val = False
    for tok in tokens:
        low = tok.lower()
        if tok in blocked_flags or low.startswith(("concat:", "lavfi", "subfile:")):
            raise ValueError("Dangerous FFmpeg token %r in %s is disabled (set allow_raw_ffmpeg in config.json to allow)." % (tok, field_name))
        if tok.startswith("-"):
            expect_flag_val = True
            continue
        if not expect_flag_val:
            raise ValueError("Unexpected bare path/output token %r in %s is disabled (set allow_raw_ffmpeg in config.json to allow)." % (tok, field_name))
        expect_flag_val = False
    return tokens


def _b(v):
    return str(v).strip().lower() in ("1", "true", "on", "yes")


def _n(v, default=None):
    try:
        n = float(v)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _enc_index(eid, table):
    for e in table:
        if e["id"] == eid:
            return e
    return None


def with_defaults(enc, **defaults):
    """A bare `enc or {...}` only applies the fallback when the panel is completely
    empty, so setting one unrelated field (an audio bitrate, say) used to drop
    the default video codec. Merge instead."""
    out = dict(defaults)
    for k, v in (enc or {}).items():
        if v not in (None, ""):
            out[k] = v
    return out


def encoder_args(enc, want_video=True, want_audio=True, container=None):
    """Turn the encoder panel values into ffmpeg output arguments."""
    enc = normalize_encoder(enc, [])
    out = []
    vcodec = (enc.get("vcodec") or "").strip()
    acodec = (enc.get("acodec") or "").strip()

    if want_video and vcodec:
        out += ["-c:v", vcodec]
        spec = _enc_index(vcodec, VIDEO_ENCODERS) or {}
        fam = spec.get("family")
        if vcodec != "copy":
            mode = (enc.get("rc_mode") or "crf").strip()
            # Two-pass targets an average bitrate; a quality setting alongside it
            # is contradictory and ffmpeg's behaviour then depends on the encoder.
            if _b(enc.get("twopass")) and enc.get("vbitrate"):
                mode = "__bitrate__"
            if mode == "crf" and enc.get("crf") not in (None, ""):
                out += ["-crf", str(enc["crf"])]
            elif mode == "cq" and enc.get("crf") not in (None, ""):
                out += ["-cq", str(enc["crf"])]
            elif mode == "qp" and enc.get("crf") not in (None, ""):
                out += ["-qp", str(enc["crf"])]
            elif mode == "qscale" and enc.get("crf") not in (None, ""):
                out += ["-q:v", str(enc["crf"])]
            if enc.get("vbitrate"):
                out += ["-b:v", str(enc["vbitrate"])]
            if enc.get("maxrate"):
                out += ["-maxrate", str(enc["maxrate"])]
            if enc.get("bufsize"):
                out += ["-bufsize", str(enc["bufsize"])]
            if enc.get("preset") and fam != "vaapi":
                out += ["-preset", str(enc["preset"])]
            if enc.get("tune"):
                out += ["-tune", str(enc["tune"])]
            if enc.get("profile"):
                out += ["-profile:v", str(enc["profile"])]
            if enc.get("level"):
                out += ["-level", str(enc["level"])]
            if enc.get("pix_fmt"):
                out += ["-pix_fmt", str(enc["pix_fmt"])]
            if enc.get("gop"):
                out += ["-g", str(enc["gop"])]
            if enc.get("bframes") not in (None, ""):
                out += ["-bf", str(enc["bframes"])]
            if enc.get("x_params"):
                key = {"x264": "-x264-params", "x265": "-x265-params"}.get(fam)
                if key:
                    out += [key, str(enc["x_params"])]
    elif want_video is False:
        out += ["-vn"]

    if want_audio and acodec:
        out += ["-c:a", acodec]
        if acodec != "copy":
            aspec = _enc_index(acodec, AUDIO_ENCODERS) or {}
            modes = aspec.get("arc") or []
            mode = (enc.get("arc_mode") or "").strip()
            if mode not in modes:
                mode = modes[0] if modes else ""

            if mode == "bitrate":
                out += ["-b:a", str(enc.get("abitrate") or aspec.get("abr_default") or "192k")]
            elif mode == "quality" and enc.get("aq") not in (None, ""):
                out += ["-q:a", str(enc["aq"])]
            elif mode == "vbr" and enc.get("avbr") not in (None, ""):
                out += ["-vbr", str(enc["avbr"])]
            elif mode == "compression" and enc.get("acompression") not in (None, ""):
                out += ["-compression_level", str(enc["acompression"])]
            elif enc.get("abitrate"):
                out += ["-b:a", str(enc["abitrate"])]

            # Encoding effort is separate from rate control on Opus and LAME:
            # it trades encode time for efficiency without changing the target.
            if mode != "compression" and enc.get("acompression") not in (None, "") \
                    and aspec.get("compression_range"):
                out += ["-compression_level", str(enc["acompression"])]

            if enc.get("aprofile"):
                out += ["-profile:a", str(enc["aprofile"])]
            if enc.get("avbr_mode") and aspec.get("vbr_modes"):
                out += ["-vbr", {"on": "on", "constrained": "constrained", "off": "off"}
                        .get(str(enc["avbr_mode"]), "on")]
            if enc.get("aapplication"):
                out += ["-application", str(enc["aapplication"])]
            if enc.get("aframe_duration"):
                out += ["-frame_duration", str(enc["aframe_duration"])]
            if enc.get("asample_fmt"):
                out += ["-sample_fmt", str(enc["asample_fmt"])]
            if enc.get("ar"):
                out += ["-ar", str(enc["ar"])]
            if enc.get("ac"):
                out += ["-ac", str(enc["ac"])]
            if enc.get("achannel_layout"):
                out += ["-channel_layout", str(enc["achannel_layout"])]
            if enc.get("acutoff"):
                out += ["-cutoff", str(enc["acutoff"])]
            if enc.get("aextra"):
                out += _safe_ffmpeg_extra(enc["aextra"], "aextra")
            if acodec in ("opus", "truehd"):
                out += ["-strict", "-2"]
    elif want_audio is False:
        out += ["-an"]

    if enc.get("scodec"):
        out += ["-c:s", str(enc["scodec"])]
    if enc.get("threads"):
        out += ["-threads", str(enc["threads"])]
    if _b(enc.get("faststart")) and (container or "").lower() in ("mp4", "m4a", "mov", "m4v"):
        out += ["-movflags", "+faststart"]
    if _b(enc.get("shortest")):
        out += ["-shortest"]
    if enc.get("extra_out"):
        out += _safe_ffmpeg_extra(enc["extra_out"], "extra_out")
    return out


def seek_args(seek, before_input=True):
    """Fast seeking goes before -i, accurate seeking after."""
    seek = seek or {}
    accurate = _b(seek.get("accurate"))
    ss, to, dur = seek.get("ss"), seek.get("to"), seek.get("t")
    out = []
    if before_input and not accurate:
        if ss:
            out += ["-ss", str(ss)]
    if (not before_input) and accurate:
        if ss:
            out += ["-ss", str(ss)]
    if not before_input:
        if dur:
            out += ["-t", str(dur)]
        elif to:
            end = parse_time_to_seconds(to)
            start = parse_time_to_seconds(ss) if ss not in (None, "") else 0
            if start is None or end is None or end <= start:
                raise ValueError("End time must be later than the start time.")
            out += ["-t", str(end - start)]
    return out


def base_cmd(spec):
    cmd = [CONFIG["ffmpeg_bin"], "-hide_banner", "-nostdin"]
    cmd += ["-loglevel", spec.get("loglevel") or "info"]
    cmd += ["-nostats", "-progress", "pipe:1"]
    if _b(spec.get("overwrite", "0")):
        cmd.append("-y")
    else:
        cmd.append("-n")
    if spec.get("hwaccel"):
        cmd += ["-hwaccel", spec["hwaccel"]]
    if spec.get("extra_pre"):
        cmd += _safe_ffmpeg_extra(spec["extra_pre"], "extra_pre")
    return cmd


def pattern_with_ext(pattern, source, fallback="mkv"):
    """Segment file names inherit the source container unless the user names one.
    Splitting an .mp4 should produce .mp4 parts, not a hardcoded default."""
    name = str(pattern or "").strip()
    stem, ext = os.path.splitext(name)
    if ext and len(ext) <= 6 and not ext[1:].isdigit():
        return name
    src_ext = os.path.splitext(str(source or ""))[1].lstrip(".").lower()
    return "%s.%s" % (name, src_ext or fallback)


def safe_output_pattern(outdir, pattern):
    """Filename patterns come from a text box, so a stray "../" or an absolute
    path would silently write outside the folder the user chose. Only a bare
    file name is accepted."""
    raw = str(pattern or "").strip()
    if not raw:
        raise PathError("Give a file name pattern.")
    name = os.path.basename(raw.replace("\\", "/"))
    if not name or name in (".", "..") or name.startswith("."):
        raise PathError("'%s' is not a usable file name." % raw)
    if raw != name:
        raise PathError(
            "The name pattern must not contain a path: use '%s' and set the "
            "output folder separately." % name)
    root = os.path.realpath(outdir)
    target = os.path.realpath(os.path.join(root, name))
    if target != root and not target.startswith(root + os.sep):
        raise PathError("That pattern would write outside %s" % root)
    return os.path.join(outdir, name)


def out_path(spec, default_name="output.mp4"):
    # Previewing a command should not touch the disk; only a real run creates
    # the destination folder. `_creating` is set by the run endpoint.
    o = (spec.get("output") or "").strip() or default_name
    return resolve_path(o, for_output=bool(spec.get("_creating")))


def _vf(spec, extra=None):
    chain = compile_filterchain(spec.get("vfilters"), "video")
    if extra:
        chain = ",".join([c for c in ([chain] if chain else []) + list(extra) if c])
    return chain


def _af(spec, extra=None):
    chain = compile_filterchain(spec.get("afilters"), "audio")
    if extra:
        chain = ",".join([c for c in ([chain] if chain else []) + list(extra) if c])
    return chain


def _stage(label, argv, **kw):
    d = {"label": label, "argv": argv}
    d.update(kw)
    return d


# Which containers can actually carry a given audio codec. When someone asks for
# MP3 in an .m4a the mux fails deep inside ffmpeg with an unhelpful message, so
# the compiler corrects the extension and says so instead.
AUDIO_CONTAINER_OK = {
    "libmp3lame": ["mp3", "mkv", "avi", "ts"],
    "mp3": ["mp3", "mkv", "avi", "ts"],
    "aac": ["m4a", "aac", "mp4", "mkv", "ts", "mov"],
    "libfdk_aac": ["m4a", "aac", "mp4", "mkv", "ts", "mov"],
    "alac": ["m4a", "mp4", "mkv", "mov"],
    "libopus": ["opus", "ogg", "mkv", "webm", "mp4"],
    "opus": ["opus", "ogg", "mkv", "webm", "mp4"],
    "libvorbis": ["ogg", "mkv", "webm"],
    "flac": ["flac", "mkv", "ogg"],
    "pcm_s16le": ["wav", "aiff", "mkv"],
    "pcm_s24le": ["wav", "aiff", "mkv"],
    "pcm_s32le": ["wav", "aiff", "mkv"],
    "pcm_f32le": ["wav", "aiff", "mkv"],
    "ac3": ["ac3", "mkv", "mp4", "ts"],
    "eac3": ["eac3", "mkv", "mp4", "ts"],
    "truehd": ["thd", "mkv"],
}

# Conservative, portable muxing choices. Raw command mode remains available
# for unusual combinations. Codec names from ffprobe are mapped separately
# from encoder names; changing a suffix never implies transcoding.
VIDEO_CONTAINER_OK = {
    "h264": ["mp4", "mkv", "mov", "ts", "m4v", "avi", "flv"],
    "hevc": ["mp4", "mkv", "mov", "ts", "m4v"],
    "av1": ["mkv", "mp4", "webm"], "vp9": ["webm", "mkv", "mp4"],
    "vp8": ["webm", "mkv"], "mpeg4": ["mp4", "avi", "mkv", "mov"],
    "prores": ["mov", "mkv"], "dnxhd": ["mov", "mxf"],
    "ffv1": ["mkv", "avi"], "mjpeg": ["avi", "mov", "mkv"],
}
VIDEO_CODEC_NAMES = {
    "libx264": "h264", "libx264rgb": "h264", "libx265": "hevc",
    "libsvtav1": "av1", "libaom-av1": "av1", "librav1e": "av1",
    "libvpx-vp9": "vp9", "libvpx": "vp8", "libxvid": "mpeg4", "prores_ks": "prores",
}
AUDIO_CODEC_NAMES = {"mp3": "libmp3lame", "vorbis": "libvorbis", "opus": "libopus"}
AUDIO_EXT_ENCODER = {"mp3": "libmp3lame", "m4a": "aac", "aac": "aac", "flac": "flac",
                     "wav": "pcm_s16le", "aiff": "pcm_s16le", "opus": "libopus",
                     "ogg": "libvorbis", "ac3": "ac3", "eac3": "eac3", "thd": "truehd"}
DIRECTORY_OPS = {"video_to_images", "extract_attachments", "split_time", "split_size", "split_chapters"}
AUDIO_OPS = {"audio_convert", "extract_audio"}
SEEK_OPS = {"transcode", "trim", "audio_convert", "extract_audio", "video_to_images"}
VIDEO_FILTER_OPS = {"cut_out", "speed", "reverse", "stabilize", "watermark", "pip", "stack", "visualizer", "images_to_video"}
AUDIO_FILTER_OPS = {"cut_out", "speed", "loudnorm2"}
OUTPUT_TAGS = {"transcode": "converted", "trim": "clip", "audio_convert": "audio",
               "extract_audio": "audio", "extract_video": "video", "extract_subs": "subs",
               "metadata": "tagged", "screenshot": "frame", "thumbnails": "contact sheet"}
LAYOUT_CHANNELS = {"mono": 1, "stereo": 2, "2.1": 3, "quad": 4, "5.0": 5, "5.1": 6, "6.1": 7, "7.1": 8}
_encoder_caps_cache = {}
_encoder_caps_lock = threading.Lock()


def encoder_capabilities(codec):
    """Discover sample constraints from the actual installed FFmpeg build."""
    if not codec or codec == "copy":
        return {}
    key = (CONFIG["ffmpeg_bin"], codec)
    with _encoder_caps_lock:
        if key in _encoder_caps_cache:
            return _encoder_caps_cache[key]
    caps = {}
    try:
        p = subprocess.run([key[0], "-hide_banner", "-h", "encoder=" + codec],
                           capture_output=True, text=True, timeout=8)
        output = p.stdout + p.stderr
        caps["available"] = bool(re.search(r"^Encoder " + re.escape(codec) + r"\s", output, re.M))
        for field, phrase in (("sample_rates", "sample rates"), ("sample_fmts", "sample formats"),
                              ("channel_layouts", "channel layouts"), ("pixel_formats", "pixel formats")):
            match = re.search(r"Supported " + phrase + r": ([^\n]+)", output)
            if match:
                caps[field] = match.group(1).split()
    except (OSError, subprocess.TimeoutExpired):
        pass  # Offline command previews can still use the declared constraints.
    if codec in ("libopus", "opus"):
        caps.setdefault("sample_rates", ["8000", "12000", "16000", "24000", "48000"] if codec == "libopus" else ["48000"])
    with _encoder_caps_lock:
        _encoder_caps_cache[key] = caps
    return caps


def normalize_encoder(enc, notes):
    enc = {k: v for k, v in (enc or {}).items() if v not in (None, "")}
    if enc.get("acodec") == "libmp3lame_vbr":
        enc.update(acodec="libmp3lame", arc_mode="quality")
    for kind, table in (("v", VIDEO_ENCODERS), ("a", AUDIO_ENCODERS)):
        codec = enc.get(kind + "codec")
        if not codec or codec == "copy":
            continue
        declaration = _enc_index(codec, table)
        if declaration is None:
            raise ValueError("Unknown encoder: %s. Use Raw for custom encoders." % codec)
        caps = encoder_capabilities(codec)
        if caps.get("available") is False:
            raise ValueError("%s is not available in the configured FFmpeg build." % codec)
        if kind == "v":
            modes = [x for x in declaration.get("rc", []) if x != "twopass"]
            if modes:
                if enc.get("rc_mode") not in modes:
                    enc["rc_mode"] = modes[0]
                if "crf_default" in declaration and enc["rc_mode"] != "bitrate":
                    enc.setdefault("crf", declaration["crf_default"])
                if enc["rc_mode"] == "bitrate" and not enc.get("vbitrate"):
                    raise ValueError("Set a target video bitrate for bitrate mode.")
            elif enc.get("crf") is not None:
                enc.pop("crf", None)
            if enc.get("crf") is not None and declaration.get("crf_range"):
                q = _n(enc["crf"])
                lo, hi = declaration["crf_range"]
                if q is None or not lo <= q <= hi:
                    raise ValueError("%s quality must be between %s and %s." % (codec, lo, hi))
            for field, choices in (("preset", declaration.get("presets")), ("tune", declaration.get("tunes")),
                                   ("profile", declaration.get("profiles")), ("pix_fmt", caps.get("pixel_formats"))):
                if enc.get(field) and choices and str(enc[field]) not in choices:
                    raise ValueError("%s does not support %s=%s." % (codec, field, enc[field]))
        else:
            modes = declaration.get("arc") or []
            if modes:
                if enc.get("arc_mode") not in modes:
                    enc["arc_mode"] = modes[0]
                mode = enc["arc_mode"]
                field, default = {"bitrate": ("abitrate", "abr_default"), "quality": ("aq", "q_default"),
                                  "vbr": ("avbr", "vbr_default"), "compression": ("acompression", "compression_default")}[mode]
                if default in declaration:
                    enc.setdefault(field, declaration[default])
            if "compression_default" in declaration:
                enc.setdefault("acompression", declaration["compression_default"])
            if codec in ("libopus", "opus"):
                enc.setdefault("ar", "48000")
            rates = caps.get("sample_rates") or []
            if enc.get("ar") and rates and str(enc["ar"]) not in rates:
                wanted = _n(enc["ar"])
                if wanted is None or wanted <= 0:
                    raise ValueError("Sample rate must be a positive number.")
                rate = "48000" if codec in ("libopus", "opus") else min(rates, key=lambda x: abs(float(x) - wanted))
                notes.append("%s cannot encode at %s Hz; resampling to %s Hz." % (codec, enc["ar"], rate))
                enc["ar"] = rate
            for field, choices in (("asample_fmt", caps.get("sample_fmts")), ("aprofile", declaration.get("profiles")),
                                   ("aapplication", declaration.get("applications")), ("aframe_duration", declaration.get("frame_durations"))):
                if enc.get(field) and choices and str(enc[field]) not in choices:
                    raise ValueError("%s does not support %s=%s." % (codec, field, enc[field]))
            for field, bounds in (("aq", declaration.get("q_range")), ("avbr", declaration.get("vbr_range")),
                                  ("acompression", declaration.get("compression_range"))):
                if enc.get(field) is not None and bounds:
                    value = _n(enc[field])
                    if value is None or not bounds[0] <= value <= bounds[1]:
                        raise ValueError("%s must be between %s and %s." % (field, *bounds))
            if enc.get("achannel_layout"):
                count = LAYOUT_CHANNELS.get(enc["achannel_layout"])
                if count and enc.get("ac") and str(count) != str(enc["ac"]):
                    raise ValueError("Channel count and channel layout disagree.")
                supported = caps.get("channel_layouts")
                if supported and enc["achannel_layout"] not in supported:
                    raise ValueError("This encoder does not support that channel layout.")
            if codec in ("libmp3lame", "opus") and int(enc.get("ac") or LAYOUT_CHANNELS.get(enc.get("achannel_layout"), 2)) > 2:
                raise ValueError("%s supports mono/stereo; choose a channel downmix explicitly." % codec)
    for field in ("vbitrate", "abitrate", "maxrate", "bufsize"):
        if enc.get(field) and not re.fullmatch(r"\d+(?:\.\d+)?[kKmMgG]?", str(enc[field])):
            raise ValueError("%s must be a bitrate such as 128k or 5M." % field)
    return enc


def normalize_media_spec(original):
    """One settings/output policy shared by preview, jobs, batch and pipelines."""
    spec = dict(original)
    op = spec.get("op") or "transcode"
    meta = FF_OPS_INDEX.get(op, {})
    notes, choices = [], None
    params = {p["id"]: p.get("default", "") for p in meta.get("fields", [])}
    params.update(spec.get("params") or {})
    spec["params"] = params
    enc = dict(spec.get("enc") or {})
    inputs = spec.get("inputs") or []
    if not isinstance(inputs, list):
        raise ValueError("Inputs must be a list of file paths.")
    source = inputs[0] if inputs else ""
    info = {}
    if source and op not in ("freeform", "images_to_video"):
        path = resolve_path(source, must_exist=not spec.get("allow_missing_inputs"))
        if path and os.path.isfile(path):
            info = ffprobe_json(path)
    streams = info.get("streams") or []
    videos = [s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    audio_only = op in AUDIO_OPS or (bool(streams) and not videos and op in {"transcode", "trim", "loudnorm2"})
    src_ext = os.path.splitext(source)[1].lstrip(".").lower()
    output = str(spec.get("output") or "").strip()
    ext = os.path.splitext(output)[1].lstrip(".").lower()
    if not ext:
        ext = src_ext if op in CONTAINER_PRESERVING else meta.get("out_hint", "mp4")
    video_filters = bool(_vf(spec)) or op in VIDEO_FILTER_OPS or (op == "concat" and params.get("mode") == "filter") or (op == "add_subs" and params.get("mode") == "burn")
    audio_filters = bool(_af(spec)) or op in AUDIO_FILTER_OPS or (op == "reverse" and _b(params.get("audio"))) or (op == "concat" and params.get("mode") == "filter") or (op in ("pip", "stack") and params.get("audio") == "mix")
    if op == "trim" and _b((spec.get("seek") or {}).get("accurate")):
        video_filters = not audio_only
        audio_filters = audio_only
    if op not in ("custom", "freeform"):
        if not meta.get("enc") and not (op == "add_subs" and params.get("mode") == "burn"):
            enc = {}
        if audio_only:
            enc.pop("vcodec", None)
            enc.pop("twopass", None)
            default_audio = "copy" if op == "extract_audio" else AUDIO_EXT_ENCODER.get(ext, "aac")
            enc = with_defaults(enc, acodec=default_audio)
        elif meta.get("enc"):
            enc = with_defaults(enc, vcodec="libvpx-vp9" if ext == "webm" else "libx264",
                                acodec="libopus" if ext == "webm" else "aac")
        if op == "map_streams":
            enc = with_defaults(spec.get("enc"), vcodec="copy", acodec="copy", scodec="copy")
        if op == "trim" and not video_filters and not audio_filters:
            enc = {"vcodec": "copy", "acodec": "copy"}
        if op == "loop_clip":
            enc = {"vcodec": "copy", "acodec": "copy"}
        for kind, needed, default in (("v", video_filters, "libvpx-vp9" if ext == "webm" else "libx264"),
                                      ("a", audio_filters, AUDIO_EXT_ENCODER.get(ext, "aac") if audio_only else ("libopus" if ext == "webm" else "aac"))):
            if needed and enc.get(kind + "codec") == "copy":
                raise ValueError("This operation filters %s; stream copy is not possible. Select an encoder." % ("video" if kind == "v" else "audio"))
            if needed:
                enc = with_defaults(enc, **{kind + "codec": default})
        if op == "loudnorm2" and not audio_only:
            enc["vcodec"] = "copy"
        enc = normalize_encoder(enc, notes)
    if _b(enc.get("twopass")):
        family = (_enc_index(enc.get("vcodec"), VIDEO_ENCODERS) or {}).get("family")
        if op != "transcode" or family not in TWOPASS_FAMILIES or not enc.get("vbitrate"):
            raise ValueError("Two-pass is available for software Transcode with a target video bitrate.")
        if len(inputs) > 1 or spec.get("maps"):
            raise ValueError("Two-pass currently accepts one input and automatic stream selection.")
    for key in ("ss", "to", "t"):
        value = (spec.get("seek") or {}).get(key)
        if op in SEEK_OPS and value not in (None, "") and parse_time_to_seconds(value) is None:
            raise ValueError("Invalid %s time: %s" % (key, value))
    if op in DIRECTORY_OPS:
        if not output:
            stem = os.path.splitext(os.path.basename(source))[0] or "output"
            output = os.path.join(os.path.dirname(source), "%s [%s]" % (stem, op.replace("_", " ")))
    elif meta.get("out") is not False and op not in ("custom", "freeform"):
        choices = None
        if op in ("gif", "webp"):
            choices = [op]
        elif op in ("screenshot", "thumbnails", "waveform", "spectrogram"):
            choices = ["png", "jpg", "webp"]
        elif op == "extract_subs":
            choices = ["srt", "ass", "vtt"]
        elif audio_only:
            codec = enc.get("acodec")
            if codec == "copy" and audios:
                index = int(params.get("index") or 0)
                if index < 0 or index >= len(audios):
                    raise ValueError("Audio track index is outside this file's audio tracks.")
                codec = AUDIO_CODEC_NAMES.get(audios[index].get("codec_name"), audios[index].get("codec_name"))
            choices = AUDIO_CONTAINER_OK.get(codec)
        else:
            codec = enc.get("vcodec")
            copy_mode = op in {"remux", "extract_video", "strip", "metadata", "mux", "loop_clip", "add_audio"} or (op == "trim" and not video_filters and not audio_filters) or (op == "concat" and params.get("mode") != "filter") or (op == "add_subs" and params.get("mode") != "burn")
            if copy_mode or codec == "copy":
                codec = videos[0].get("codec_name") if videos else None
            codec = VIDEO_CODEC_NAMES.get(codec, codec)
            if codec and codec.endswith(("_nvenc", "_qsv", "_vaapi", "_amf")):
                codec = codec.split("_")[0]
            choices = VIDEO_CONTAINER_OK.get(codec)
            ac = enc.get("acodec")
            if copy_mode or ac == "copy":
                ac = audios[0].get("codec_name") if audios else None
            ac = AUDIO_CODEC_NAMES.get(ac, ac)
            audio_choices = AUDIO_CONTAINER_OK.get(ac)
            # Stream-removal operations must not constrain the removed type.
            if choices and audio_choices and op != "extract_video" and not (op == "strip" and _b(params.get("audio"))):
                choices = [c for c in choices if c in audio_choices]
            if op == "add_subs" and params.get("mode") != "burn" and choices:
                choices = [c for c in choices if c in ("mkv", "mp4", "mov", "m4v")]
            if copy_mode and choices and op in {"remux", "strip", "metadata", "loop_clip", "concat", "mux"}:
                for stream in streams:
                    kind, code = stream.get("codec_type"), stream.get("codec_name")
                    if op == "strip" and _b(params.get({"subtitle": "subs"}.get(kind, kind))):
                        continue
                    compatible = None
                    if kind == "audio":
                        compatible = AUDIO_CONTAINER_OK.get(AUDIO_CODEC_NAMES.get(code, code))
                    elif kind == "video" and not (stream.get("disposition") or {}).get("attached_pic"):
                        compatible = VIDEO_CONTAINER_OK.get(code)
                    elif kind == "subtitle":
                        compatible = ["mp4", "mov", "m4v"] if code == "mov_text" else (["mkv", "webm"] if code == "webvtt" else ["mkv"])
                    elif kind == "attachment":
                        compatible = ["mkv"]
                    if compatible:
                        choices = [c for c in choices if c in compatible]
                if not choices:
                    raise ValueError("These copied streams have no common supported container. Remove or convert incompatible tracks first.")
        if choices:
            out_mode = spec.get("output_mode", "manual" if output else "auto")
            if out_mode == "auto" and (audio_only or ext not in choices):
                ext = choices[0]
            elif ext not in choices:
                old_ext = ext
                ext = choices[0]
                if out_mode == "manual":
                    notes.append(".%s is incompatible with these streams; using .%s." % (old_ext or "(none)", ext))
        if not output or spec.get("output_mode") == "auto":
            stem = os.path.splitext(os.path.basename(source))[0] or "output"
            tag = OUTPUT_TAGS.get(op, op.replace("_", " "))
            output = os.path.join(os.path.dirname(source), "%s [%s].%s" % (stem, tag, ext))
        else:
            output = os.path.splitext(output)[0] + "." + ext
        target = resolve_path(output)
        if any(target == resolve_path(i) for i in inputs if i):
            raise ValueError("Output must differ from every input file.")
    if op == "transcode" and not spec.get("maps") and (len(audios) > 1 or len(videos) > 1):
        notes.append("Automatic stream selection keeps primary tracks. Use the mapping editor to select additional tracks.")
    spec.update(enc=enc, output=output, _audio_only=audio_only, _containers=choices or [])
    return spec, notes


def fix_audio_container(path, codec, notes):
    """Swap the output extension when the chosen codec cannot live in it."""
    if not codec or codec == "copy":
        return path
    allowed = AUDIO_CONTAINER_OK.get(codec)
    if not allowed:
        return path
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in allowed:
        return path
    fixed = os.path.splitext(path)[0] + "." + allowed[0]
    notes.append("%s cannot be stored in a .%s file, so the output is now .%s. "
                 "Pick a different codec if you wanted that container."
                 % (codec, ext or "(none)", allowed[0]))
    return fixed


POSITIONS = {
    "top-left": ("{m}", "{m}"),
    "top-right": ("W-w-{m}", "{m}"),
    "bottom-left": ("{m}", "H-h-{m}"),
    "bottom-right": ("W-w-{m}", "H-h-{m}"),
    "center": ("(W-w)/2", "(H-h)/2"),
}

