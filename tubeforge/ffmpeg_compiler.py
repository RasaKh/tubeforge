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


# ═══════════════════════════════════════════════════════════════════════════
#  THE COMPILER
# ═══════════════════════════════════════════════════════════════════════════

def stream_kinds(path):
    """Which stream types a file contains. Filtergraphs that reference [0:a] on
    a silent video fail with an opaque ffmpeg error, so operations check first."""
    try:
        info = summarize_probe(ffprobe_json(path))
    except Exception:
        return {"video": True, "audio": True, "unknown": True}
    kinds = set(s["type"] for s in info["streams"])
    if not any(s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
               for s in ffprobe_json(path).get("streams", [])):
        kinds.discard("video")
    return {"video": "video" in kinds, "audio": "audio" in kinds, "unknown": False}


def preflight_ffmpeg(spec):
    """Combinations ffmpeg rejects at runtime, caught before anything starts.
    Each one names what will break and how to fix it."""
    warnings = []
    enc = spec.get("enc") or {}
    op = spec.get("op") or ""
    meta = FF_OPS_INDEX.get(op, {})

    vf = compile_filterchain(spec.get("vfilters"), "video")
    af = compile_filterchain(spec.get("afilters"), "audio")

    if meta.get("filters"):
        if vf and (enc.get("vcodec") or "") == "copy":
            warnings.append({
                "level": "block",
                "text": "Video filters cannot run while copying the video stream.",
                "why": "Copying passes the encoded stream through untouched, so there is "
                       "nothing for a filter to modify. ffmpeg refuses the combination.",
                "fix": "Pick a real video encoder such as H.264, or clear the video filter chain.",
                "apply": {"vcodec": "libx264"},
                "apply_label": "Switch to H.264",
            })
        if af and (enc.get("acodec") or "") == "copy":
            warnings.append({
                "level": "block",
                "text": "Audio filters cannot run while copying the audio stream.",
                "why": "The audio is passed through as-is, so a filter has nothing to act on.",
                "fix": "Pick a real audio encoder such as AAC, or clear the audio filter chain.",
                "apply": {"acodec": "aac"},
                "apply_label": "Switch to AAC",
            })

    if _b(enc.get("twopass")):
        if not enc.get("vbitrate"):
            warnings.append({
                "level": "block",
                "text": "Two-pass encoding needs a target bitrate.",
                "why": "The point of the second pass is to hit an average bitrate exactly. "
                       "Without one there is nothing to aim at.",
                "fix": "Set a target bitrate, or turn two-pass off and use quality instead.",
                "apply": {"twopass": ""},
                "apply_label": "Turn off two-pass",
            })
        else:
            spec_enc = _enc_index(enc.get("vcodec") or "", VIDEO_ENCODERS) or {}
            if spec_enc and spec_enc.get("family") not in TWOPASS_FAMILIES:
                warnings.append({
                    "level": "warn",
                    "text": "%s does not support two-pass encoding." % spec_enc.get("label", "This encoder"),
                    "why": "Hardware encoders manage their own rate control; the pass flags are ignored.",
                    "fix": "Use a software encoder such as H.264 or H.265 for two-pass, or "
                           "turn it off and set a bitrate directly.",
                })
            if enc.get("crf") not in (None, ""):
                warnings.append({
                    "level": "warn",
                    "text": "The quality setting is ignored during a two-pass encode.",
                    "why": "Two-pass aims at the target bitrate instead.",
                    "fix": "Nothing to do — the bitrate is what will be used.",
                })

    if op == "trim" and (spec.get("vfilters") or spec.get("afilters")) \
            and not _b((spec.get("seek") or {}).get("accurate")):
        warnings.append({
            "level": "warn",
            "text": "Filters force a re-encode, so the fast cut is not being used.",
            "why": "Copying and filtering cannot be combined.",
            "fix": "This is fine — just expect it to take as long as an encode.",
        })

    return warnings


def build_ffmpeg(spec):
    """Returns {'stages': [{'label','argv'}], 'notes': [...], 'outputs': [...]}"""
    spec, normalization_notes = normalize_media_spec(spec)
    op = spec.get("op") or "transcode"
    meta = FF_OPS_INDEX.get(op)
    if not meta:
        raise ValueError("Unknown operation: %s" % op)

    # Pipeline steps after the first read a file that does not exist yet at
    # compile time, so existence checking is skipped for them.
    _must = (op not in ("images_to_video", "freeform")) and not spec.get("allow_missing_inputs")
    inputs = [resolve_path(i, must_exist=_must)
              for i in (spec.get("inputs") or []) if str(i).strip()]
    params = spec.get("params") or {}
    enc = spec.get("enc") or {}
    notes, stages, outputs, cleanup = list(normalization_notes), [], [], []

    ffprobe = CONFIG["ffprobe_bin"]

    def need(n=1):
        if len(inputs) < n:
            raise ValueError("This operation needs %d input file(s)." % n)

    # ── Inspect ────────────────────────────────────────────────────────────
    if op == "probe":
        need(1)
        return {"stages": [_stage("ffprobe", [ffprobe, "-v", "quiet", "-print_format", "json",
                                              "-show_format", "-show_streams", "-show_chapters",
                                              inputs[0]])],
                "notes": ["Structured output is also rendered in the Inspector tab."],
                "outputs": []}

    if op in ("silencedetect", "blackdetect", "scenedetect"):
        need(1)
        if op == "silencedetect":
            f = "silencedetect=noise=%s:d=%s" % (params.get("noise", "-40dB"), params.get("d", "1"))
            av = ["-af", f]
        elif op == "blackdetect":
            f = "blackdetect=d=%s:pic_th=%s" % (params.get("d", "2"), params.get("pic_th", "0.98"))
            av = ["-vf", f]
        else:
            f = "select='gt(scene,%s)',showinfo" % params.get("threshold", "0.3")
            av = ["-vf", f]
        cmd = [CONFIG["ffmpeg_bin"], "-hide_banner", "-i", inputs[0]] + av + ["-f", "null", "-"]
        return {"stages": [_stage(meta["label"], cmd)],
                "notes": ["Results appear in the log output below."], "outputs": []}

    # ── Free-form ──────────────────────────────────────────────────────────
    if op == "freeform":
        if not CONFIG.get("allow_raw_ffmpeg"):
            raise ValueError("Free-form FFmpeg mode is disabled unless allow_raw_ffmpeg is enabled in config.json.")
        line = (params.get("line") or "").strip()
        if not line:
            raise ValueError("Nothing to run.")
        return {"stages": [_stage("custom", [CONFIG["ffmpeg_bin"], "-hide_banner"] + shlex.split(line))],
                "notes": ["Run verbatim — no arguments were added."], "outputs": []}

    if op == "custom":
        if not CONFIG.get("allow_raw_ffmpeg"):
            raise ValueError("Custom FFmpeg mode is disabled unless allow_raw_ffmpeg is enabled in config.json.")
        need(1)
        cmd = base_cmd(spec)
        if params.get("pre"):
            cmd += shlex.split(str(params["pre"]))
        cmd += ["-i", inputs[0]]
        for extra in inputs[1:]:
            cmd += ["-i", extra]
        if params.get("post"):
            cmd += shlex.split(str(params["post"]))
        o = out_path(spec, "custom_output.mp4")
        cmd.append(o)
        return {"stages": [_stage("custom", cmd)], "notes": [], "outputs": [o]}

    # ── Everything else starts from the common skeleton ────────────────────
    cmd = base_cmd(spec)
    seek = spec.get("seek") or {}

    # ---- Convert / transcode -------------------------------------------
    if op in ("transcode", "trim", "audio_convert"):
        need(1)
        if op == "trim":
            fast = not _b(seek.get("accurate"))
            cmd += seek_args(seek, True)
            cmd += ["-i", inputs[0]]
            cmd += seek_args(seek, False)
            o = out_path(spec, "trimmed.mp4")
            if fast and not _vf(spec) and not _af(spec):
                cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
                notes.append("Fast copy mode: cuts land on the nearest keyframe. "
                             "Tick 'accurate' to re-encode for frame-exact cuts.")
            else:
                vf, af = _vf(spec), _af(spec)
                if vf:
                    cmd += ["-vf", vf]
                if af:
                    cmd += ["-af", af]
                cmd += encoder_args(enc, want_video=False if spec.get("_audio_only") else True,
                                    container=os.path.splitext(o)[1][1:])
            cmd.append(o)
            outputs.append(o)
            stages.append(_stage("trim", cmd))
        elif op == "audio_convert":
            cmd += seek_args(seek, True) + ["-i", inputs[0]] + seek_args(seek, False)
            af = _af(spec)
            if af:
                cmd += ["-af", af]
            o = fix_audio_container(out_path(spec, "converted.mp3"), enc.get("acodec"), notes)
            cmd += ["-vn"] + encoder_args(enc, want_video=None,
                                          container=os.path.splitext(o)[1][1:])
            cmd.append(o)
            outputs.append(o)
            stages.append(_stage("audio encode", cmd))
        else:
            o = out_path(spec, "transcoded.mp4")
            ext = os.path.splitext(o)[1][1:]
            twopass = _b(enc.get("twopass"))
            vf, af = _vf(spec), _af(spec)
            if twopass and enc.get("vbitrate"):
                passlog = os.path.join(TMP_DIR, "ff2pass_%s" % uuid.uuid4().hex[:8])
                cleanup.extend([passlog, passlog + ".cutree", passlog + "-0.log", passlog + "-0.log.mbtree"])
                for p in (1, 2):
                    c = base_cmd(spec) + seek_args(seek, True) + ["-i", inputs[0]] + seek_args(seek, False)
                    pass_enc = dict(enc)
                    x265 = enc.get("vcodec") == "libx265"
                    if x265:
                        pass_enc["x_params"] = ":".join(filter(None, [enc.get("x_params"), "pass=%d:stats=%s" % (p, passlog)]))
                    if vf:
                        c += ["-vf", vf]
                    if p == 1:
                        c += encoder_args(pass_enc, want_audio=False, container=ext)
                        if not x265:
                            c += ["-pass", "1", "-passlogfile", passlog]
                        c += ["-f", "null", os.devnull]
                    else:
                        if af:
                            c += ["-af", af]
                        c += encoder_args(pass_enc, container=ext)
                        if not x265:
                            c += ["-pass", "2", "-passlogfile", passlog]
                        c += [o]
                    stages.append(_stage("pass %d" % p, c))
                notes.append("Two-pass encoding targets the average bitrate precisely.")
                outputs.append(o)
            else:
                cmd += seek_args(seek, True) + ["-i", inputs[0]]
                for extra in inputs[1:]:
                    cmd += ["-i", extra]
                cmd += seek_args(seek, False)
                if vf:
                    cmd += ["-vf", vf]
                if af:
                    cmd += ["-af", af]
                for m in (spec.get("maps") or []):
                    if str(m).strip():
                        cmd += ["-map", str(m).strip()]
                cmd += encoder_args(enc, want_video=False if spec.get("_audio_only") else True, container=ext)
                cmd.append(o)
                outputs.append(o)
                stages.append(_stage("encode", cmd))

    elif op == "remux":
        need(1)
        o = out_path(spec, "remuxed.mkv")
        cmd += ["-i", inputs[0], "-map", "0", "-c", "copy"]
        if os.path.splitext(o)[1].lower() in (".mp4", ".m4v", ".mov"):
            cmd += ["-movflags", "+faststart"]
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("remux", cmd))
        notes.append("Streams are copied byte-for-byte; only the container changes.")

    elif op == "images_to_video":
        need(1)
        o = out_path(spec, "from_images.mp4")
        if params.get("pattern_type") == "glob":
            cmd += ["-framerate", str(params.get("framerate", 25)), "-pattern_type", "glob",
                    "-i", inputs[0]]
        else:
            cmd += ["-framerate", str(params.get("framerate", 25)), "-i", inputs[0]]
        vf = _vf(spec, ["format=yuv420p"])
        cmd += ["-vf", vf]
        cmd += encoder_args(enc, want_audio=False, container=os.path.splitext(o)[1][1:])
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("assemble", cmd))

    elif op == "video_to_images":
        need(1)
        outdir = (spec.get("output") or "").strip() or "frames"
        outdir = resolve_path(outdir, for_output=bool(spec.get("_creating")))
        if spec.get("_creating"):
            os.makedirs(outdir, exist_ok=True)
        pattern = safe_output_pattern(outdir, params.get("pattern") or "frame_%05d.png")
        vf = _vf(spec, ["fps=%s" % (params.get("fps") or "1")])
        cmd += seek_args(seek, True) + ["-i", inputs[0]] + seek_args(seek, False)
        cmd += ["-vf", vf, "-vsync", "vfr"]
        if pattern.lower().endswith((".jpg", ".jpeg")):
            cmd += ["-q:v", str(params.get("quality", 2))]
        cmd.append(pattern)
        outputs.append(outdir)
        stages.append(_stage("extract frames", cmd))

    # ---- Streams --------------------------------------------------------
    elif op == "extract_audio":
        need(1)
        idx = str(params.get("index", "0") or "0")
        if not stream_kinds(inputs[0])["audio"]:
            raise ValueError("This file has no audio track to extract.")
        o = fix_audio_container(out_path(spec, "audio.m4a"), enc.get("acodec"), notes)
        cmd += seek_args(seek, True) + ["-i", inputs[0]] + seek_args(seek, False)
        cmd += ["-map", "0:a:%s" % idx, "-vn"]
        af = _af(spec)
        if af:
            cmd += ["-af", af]
        cmd += encoder_args(enc, want_video=None, container=os.path.splitext(o)[1][1:])
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("extract audio", cmd))

    elif op == "extract_video":
        need(1)
        o = out_path(spec, "video_only.mp4")
        cmd += ["-i", inputs[0], "-map", "0:v:%s" % (params.get("index", "0") or "0"),
                "-an", "-sn", "-c", "copy", o]
        outputs.append(o)
        stages.append(_stage("extract video", cmd))

    elif op == "extract_subs":
        need(1)
        o = out_path(spec, "subtitles.srt")
        cmd += ["-i", inputs[0], "-map", "0:s:%s" % (params.get("index", "0") or "0"), o]
        outputs.append(o)
        stages.append(_stage("extract subtitles", cmd))

    elif op == "extract_all_subs":
        need(1)
        info = summarize_probe(ffprobe_json(inputs[0]))
        subs = [s for s in info["streams"] if s["type"] == "subtitle"]
        if not subs:
            raise ValueError("This file has no subtitle streams.")
        fmt = params.get("fmt") or "srt"
        base = os.path.splitext(inputs[0])[0]
        c = base_cmd(spec) + ["-i", inputs[0]]
        for n, s in enumerate(subs):
            lang = re.sub(r"[^A-Za-z0-9_-]", "_", s.get("language") or "und")[:32]
            o = resolve_path("%s.track%d.%s.%s" % (base, n, lang, fmt), for_output=bool(spec.get("_creating")))
            c += ["-map", "0:s:%d" % n, o]
            outputs.append(o)
        stages.append(_stage("extract all subtitles", c))
        notes.append("Extracted %d subtitle track(s)." % len(subs))

    elif op == "extract_attachments":
        need(1)
        outdir = resolve_path((spec.get("output") or "attachments"),
                             for_output=bool(spec.get("_creating")))
        if spec.get("_creating"):
            os.makedirs(outdir, exist_ok=True)
        attachments = [s for s in ffprobe_json(inputs[0]).get("streams", []) if s.get("codec_type") == "attachment"]
        if not attachments:
            raise ValueError("This file has no attachments.")
        c = [CONFIG["ffmpeg_bin"], "-hide_banner", "-nostdin", "-y" if _b(spec.get("overwrite", "1")) else "-n"]
        for n, stream in enumerate(attachments):
            original = (stream.get("tags") or {}).get("filename", "attachment.bin")
            name = re.sub(r"[^\w. -]", "_", os.path.basename(original.replace("\\", "/"))).lstrip(".") or "attachment.bin"
            target = safe_output_pattern(outdir, "%03d_%s" % (n, name))
            c += ["-dump_attachment:t:%d" % n, target]
        c += ["-i", inputs[0], "-f", "null", "-"]
        stages.append(_stage("dump attachments", c, cwd=outdir))
        outputs.append(outdir)
        notes.append("Attachments (usually fonts) are written into %s" % outdir)

    elif op == "strip":
        need(1)
        o = out_path(spec, "stripped.mkv")
        cmd += ["-i", inputs[0], "-map", "0", "-c", "copy"]
        if _b(params.get("audio")):
            cmd.append("-an")
        if _b(params.get("video")):
            cmd.append("-vn")
        if _b(params.get("subs")):
            cmd.append("-sn")
        if _b(params.get("data")):
            cmd.append("-dn")
        if _b(params.get("chapters")):
            cmd += ["-map_chapters", "-1"]
        if _b(params.get("metadata")):
            cmd += ["-map_metadata", "-1"]
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("strip streams", cmd))

    elif op == "add_audio":
        need(2)
        o = out_path(spec, "with_audio.mkv")
        mode = params.get("mode") or "replace"
        delay = _n(params.get("delay"), 0) or 0
        cmd += ["-i", inputs[0]]
        if delay:
            cmd += ["-itsoffset", str(delay)]
        cmd += ["-i", inputs[1]]
        if mode == "replace":
            cmd += ["-map", "0:v", "-map", "1:a", "-c:v", "copy"]
            cmd += ["-c:a", params.get("acodec") or "copy"]
        elif mode == "add":
            cmd += ["-map", "0", "-map", "1:a", "-c", "copy"]
        else:  # mix
            cmd += ["-filter_complex", "[0:a][1:a]amix=inputs=2:duration=longest[aout]"]
            cmd += ["-map", "0:v", "-map", "[aout]", "-c:v", "copy",
                    "-c:a", (params.get("acodec") if params.get("acodec") != "copy" else "aac") or "aac"]
        if _b(params.get("shortest")):
            cmd.append("-shortest")
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("mux audio", cmd))

    elif op == "add_subs":
        need(2)
        o = out_path(spec, "with_subs.mkv")
        if (params.get("mode") or "soft") == "burn":
            style = params.get("style") or ""
            sub_arg = "subtitles=%s" % _esc_filter_value(inputs[1])
            if style:
                sub_arg += ":force_style='%s'" % style.replace("'", "")
            vf = _vf(spec, [sub_arg])
            cmd += ["-i", inputs[0], "-vf", vf]
            cmd += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="copy"),
                                container=os.path.splitext(o)[1][1:])
            cmd.append(o)
            notes.append("Burn-in re-encodes the video; subtitles become permanent.")
        else:
            existing_subs = sum(s.get("codec_type") == "subtitle" for s in ffprobe_json(inputs[0]).get("streams", [])) if os.path.exists(inputs[0]) else 0
            scodec = params.get("scodec") or "auto"
            if scodec == "auto":
                scodec = "mov_text" if os.path.splitext(o)[1].lower() in (".mp4", ".m4v", ".mov") else "srt"
            cmd += ["-i", inputs[0], "-i", inputs[1], "-map", "0", "-map", "1:s:0",
                    "-c", "copy", "-c:s", scodec,
                    "-metadata:s:s:%d" % existing_subs, "language=%s" % (params.get("lang") or "eng")]
            if params.get("title"):
                cmd += ["-metadata:s:s:%d" % existing_subs, "title=%s" % params["title"]]
            if _b(params.get("default")):
                cmd += ["-disposition:s:%d" % existing_subs, "default"]
            cmd.append(o)
        outputs.append(o)
        stages.append(_stage("add subtitles", cmd))

    elif op == "mux":
        if len(inputs) < 2:
            raise ValueError("Add at least two input files.")
        o = out_path(spec, "muxed.mkv")
        for i in inputs:
            cmd += ["-i", i]
        maps = [m.strip() for m in str(params.get("maps") or "").splitlines() if m.strip()]
        if maps:
            for m in maps:
                cmd += ["-map", m]
        else:
            for n in range(len(inputs)):
                cmd += ["-map", str(n)]
        cmd += ["-c", "copy", o]
        outputs.append(o)
        stages.append(_stage("mux", cmd))

    elif op == "map_streams":
        need(1)
        o = out_path(spec, "remapped.mkv")
        cmd += ["-i", inputs[0]]
        for m in [x.strip() for x in str(params.get("maps") or "").splitlines() if x.strip()]:
            cmd += ["-map", m]
        cmd += encoder_args(with_defaults(enc, vcodec="copy", acodec="copy"),
                            container=os.path.splitext(o)[1][1:]) or ["-c", "copy"]
        for line in [x.strip() for x in str(params.get("disposition") or "").splitlines() if x.strip()]:
            bits = line.split(None, 1)
            if len(bits) == 2:
                cmd += ["-disposition:%s" % bits[0], bits[1]]
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("remap", cmd))

    elif op == "metadata":
        need(1)
        o = out_path(spec, "tagged.mkv")
        cmd += ["-i", inputs[0], "-map", "0", "-c", "copy"]
        if _b(params.get("strip_first")):
            cmd += ["-map_metadata", "-1"]
        for line in [x.strip() for x in str(params.get("global_tags") or "").splitlines() if x.strip()]:
            cmd += ["-metadata", line]
        for line in [x.strip() for x in str(params.get("stream_tags") or "").splitlines() if x.strip()]:
            bits = line.split(None, 1)
            if len(bits) == 2:
                cmd += ["-metadata:%s" % bits[0], bits[1]]
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("write metadata", cmd))

    # ---- Edit -----------------------------------------------------------
    elif op == "cut_out":
        need(1)
        o = out_path(spec, "cut.mp4")
        a = parse_time_to_seconds(params.get("start")) or 0
        b = parse_time_to_seconds(params.get("end")) or 0
        if b <= a:
            raise ValueError("The end of the removed range must come after its start.")
        has = stream_kinds(inputs[0])
        if not has["video"]:
            raise ValueError("This file has no video track to cut.")
        if has["audio"]:
            fc = ("[0:v]trim=end=%s,setpts=PTS-STARTPTS[v0];"
                  "[0:v]trim=start=%s,setpts=PTS-STARTPTS[v1];"
                  "[0:a]atrim=end=%s,asetpts=PTS-STARTPTS[a0];"
                  "[0:a]atrim=start=%s,asetpts=PTS-STARTPTS[a1];"
                  "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]") % (a, b, a, b)
            maps = ["-map", "[v]", "-map", "[a]"]
        else:
            fc = ("[0:v]trim=end=%s,setpts=PTS-STARTPTS[v0];"
                  "[0:v]trim=start=%s,setpts=PTS-STARTPTS[v1];"
                  "[v0][v1]concat=n=2:v=1:a=0[v]") % (a, b)
            maps = ["-map", "[v]"]
            notes.append("This file has no audio, so only the picture was joined.")
        cmd += ["-i", inputs[0], "-filter_complex", fc] + maps
        cmd += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="aac"),
                            container=os.path.splitext(o)[1][1:])
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("cut segment out", cmd))
        notes.append("Re-encoding is unavoidable when joining across a removed range.")

    elif op in ("split_time", "split_size"):
        need(1)
        outdir = resolve_path((spec.get("output") or "split_output"),
                             for_output=bool(spec.get("_creating")))
        if spec.get("_creating"):
            os.makedirs(outdir, exist_ok=True)
        pattern = safe_output_pattern(
            outdir, pattern_with_ext(params.get("pattern") or "part_%03d", inputs[0]))
        cmd += ["-i", inputs[0], "-map", "0", "-c", "copy", "-f", "segment"]
        if op == "split_time":
            cmd += ["-segment_time", str(params.get("seconds") or 600)]
        else:
            raw_size = str(params.get("size") or "1900M")
            match = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmMgG]?)(i?)[bB]?", raw_size)
            if not match:
                raise ValueError("Size must be bytes or a value such as 100M / 100MiB.")
            target_bytes = float(match[1]) * ((1024 if match[3] else 1000) ** ("kmg".find(match[2].lower()) + 1) if match[2] else 1)
            info = ffprobe_json(inputs[0]).get("format", {})
            duration, size = _n(info.get("duration")), _n(info.get("size"))
            if not duration or not size or target_bytes <= 0:
                raise ValueError("Size splitting needs a finite file duration and positive target size.")
            seconds = max(0.001, duration * target_bytes / size)
            cmd += ["-segment_time", "%.6f" % seconds]
            notes.append("Approximate size: %.3f seconds per part, estimated from average bitrate. Variable bitrate and keyframes can exceed the target; this is not a hard size cap." % seconds)
        if _b(params.get("reset", "1")):
            cmd += ["-reset_timestamps", "1"]
        cmd.append(pattern)
        outputs.append(outdir)
        stages.append(_stage("split", cmd))

    elif op == "split_chapters":
        need(1)
        info = summarize_probe(ffprobe_json(inputs[0]))
        chapters = info["chapters"]
        if not chapters:
            raise ValueError("This file has no chapter markers.")
        outdir = resolve_path((spec.get("output") or "chapters"),
                             for_output=bool(spec.get("_creating")))
        if spec.get("_creating"):
            os.makedirs(outdir, exist_ok=True)
        pat = pattern_with_ext(params.get("pattern") or "%02d - %s", inputs[0])
        for n, ch in enumerate(chapters, 1):
            title = re.sub(r'[/\\:*?"<>|]', "_", ch["title"] or ("chapter%02d" % n))
            try:
                name = pat % (n, title)
            except TypeError:
                name = pattern_with_ext("%02d - %s" % (n, title), inputs[0])
            o = safe_output_pattern(outdir, name)
            c = base_cmd(spec) + ["-ss", str(ch["start"]), "-i", inputs[0],
                                  "-t", "%.3f" % max(0.001, ch["end"] - ch["start"]),
                                  "-map", "0", "-c", "copy", o]
            stages.append(_stage("chapter %d" % n, c))
            outputs.append(o)
        notes.append("Split into %d chapter files." % len(chapters))

    elif op == "concat":
        if len(inputs) < 2:
            raise ValueError("Add at least two files to join.")
        o = out_path(spec, "joined.mp4")
        if (params.get("mode") or "demuxer") == "demuxer":
            lst = os.path.join(TMP_DIR, "concat_%s.txt" % uuid.uuid4().hex[:8])
            if any("\n" in f or "\r" in f for f in inputs):
                raise ValueError("Concat filenames cannot contain line breaks.")
            contents = "".join("file '%s'\n" % f.replace("'", "'\\''") for f in inputs)
            cleanup.append(lst)
            cmd += ["-f", "concat", "-safe", "0", "-i", lst, "-map", "0", "-c", "copy", o]
            notes.append("Demuxer mode requires identical codecs and parameters. "
                         "If the result is broken, switch to filter mode.")
        else:
            with_audio = _b(params.get("audio", "1"))
            if with_audio and not all(stream_kinds(f)["audio"] for f in inputs):
                raise ValueError("A clip has no audio. Add a silent track or explicitly disable audio for this join.")
            for f in inputs:
                cmd += ["-i", f]
            n = len(inputs)
            first_video = next(
                (s for s in ffprobe_json(inputs[0]).get("streams", [])
                 if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")),
                None,
            )
            if first_video is None:
                raise ValueError("Filter concat requires video streams in the inputs (or use demuxer mode for audio-only files).")
            width, height = first_video["width"], first_video["height"]
            prefix = []
            for i in range(n):
                prefix.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS[v%d]" % (i, width, height, width, height, i))
                if with_audio:
                    prefix.append("[%d:a]asetpts=PTS-STARTPTS[a%d]" % (i, i))
            if with_audio:
                streams = "".join("[v%d][a%d]" % (i, i) for i in range(n))
                fc = ";".join(prefix + ["%sconcat=n=%d:v=1:a=1[v][a]" % (streams, n)])
                cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]"]
            else:
                streams = "".join("[v%d]" % i for i in range(n))
                fc = ";".join(prefix + ["%sconcat=n=%d:v=1:a=0[v]" % (streams, n)])
                cmd += ["-filter_complex", fc, "-map", "[v]"]
            cmd += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="aac"),
                                container=os.path.splitext(o)[1][1:])
            cmd.append(o)
        outputs.append(o)
        stages.append(_stage("join", cmd, prepare_files={lst: contents}) if (params.get("mode") or "demuxer") == "demuxer" else _stage("join", cmd))

    elif op == "speed":
        need(1)
        o = out_path(spec, "speed.mp4")
        factor = _n(params.get("factor", 2))
        # A zero or negative factor is meaningless, and negatives never climb
        # back into atempo's valid range — the correction loop would not end.
        if factor is None or factor <= 0:
            raise ValueError("Speed factor must be greater than zero. "
                             "Use 2 for twice as fast, 0.5 for half speed.")
        if factor < 0.01 or factor > 100:
            raise ValueError("Speed factor must be between 0.01 and 100.")
        has = stream_kinds(inputs[0])
        keep_audio = _b(params.get("keep_audio", "1")) and has["audio"]
        if _b(params.get("keep_audio", "1")) and not has["audio"]:
            notes.append("This file has no audio track, so only the video speed was changed.")
        if not has["video"]:
            raise ValueError("This file has no video track. Use 'Convert audio file' "
                             "with a tempo filter to change audio speed.")
        vparts = ["setpts=%.6f*PTS" % (1.0 / factor)]
        if _b(params.get("interpolate")) and factor < 1:
            vparts.append("minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc")
        # atempo only accepts 0.5-2.0, so chain until we reach the target
        aparts, remaining = [], factor
        while remaining > 2.0:
            aparts.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            aparts.append("atempo=0.5")
            remaining /= 0.5
        aparts.append("atempo=%.6f" % remaining)
        cmd += ["-i", inputs[0], "-filter_complex"]
        if keep_audio:
            cmd.append("[0:v]%s[v];[0:a]%s[a]" % (",".join(vparts), ",".join(aparts)))
            cmd += ["-map", "[v]", "-map", "[a]"]
        else:
            cmd.append("[0:v]%s[v]" % ",".join(vparts))
            cmd += ["-map", "[v]", "-an"]
        cmd += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="aac"),
                            want_audio=keep_audio, container=os.path.splitext(o)[1][1:])
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("speed change", cmd))

    elif op == "reverse":
        need(1)
        o = out_path(spec, "reversed.mp4")
        has = stream_kinds(inputs[0])
        cmd += ["-i", inputs[0]]
        if not has["video"] and has["audio"]:
            cmd += ["-af", _af(spec, ["areverse"]), "-vn"]
            cmd += encoder_args(with_defaults(enc, acodec="aac"),
                                want_video=False, container=os.path.splitext(o)[1][1:])
        else:
            if _b(params.get("audio", "1")) and has["audio"]:
                cmd += ["-vf", _vf(spec, ["reverse"]), "-af", _af(spec, ["areverse"])]
            else:
                cmd += ["-vf", _vf(spec, ["reverse"]), "-an"]
                if _b(params.get("audio", "1")) and not has["audio"]:
                    notes.append("This file has no audio track to reverse.")
            cmd += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="aac"),
                                container=os.path.splitext(o)[1][1:])
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("reverse", cmd))
        notes.append("Reversing buffers the whole clip in memory — keep it short.")

    elif op == "loop_clip":
        need(1)
        o = out_path(spec, "looped.mp4")
        count = int(_n(params.get("count"), 3) or 3)
        cmd += ["-stream_loop", str(max(0, count - 1)), "-i", inputs[0], "-map", "0", "-c", "copy", o]
        outputs.append(o)
        stages.append(_stage("loop", cmd))

    elif op == "stabilize":
        need(1)
        o = out_path(spec, "stabilized.mp4")
        trf = os.path.join(TMP_DIR, "vidstab_%s.trf" % uuid.uuid4().hex[:8])
        cleanup.append(trf)
        c1 = base_cmd(spec) + ["-i", inputs[0], "-vf",
                               "vidstabdetect=shakiness=%s:accuracy=%s:result=%s" % (
                                   params.get("shakiness", 5), params.get("accuracy", 15), trf),
                               "-f", "null", os.devnull]
        vf = _vf(spec, ["vidstabtransform=input=%s:smoothing=%s:zoom=%s" % (
            trf, params.get("smoothing", 30), params.get("zoom", 0)), "unsharp=5:5:0.8:3:3:0.4"])
        c2 = base_cmd(spec) + ["-i", inputs[0], "-vf", vf]
        c2 += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="copy"),
                           container=os.path.splitext(o)[1][1:])
        c2.append(o)
        stages += [_stage("analyse motion", c1), _stage("apply stabilisation", c2)]
        outputs.append(o)
        notes.append("Requires an ffmpeg build with libvidstab.")

    elif op == "loudnorm2":
        need(1)
        if not stream_kinds(inputs[0])["audio"]:
            raise ValueError("This file has no audio track to normalise.")
        o = out_path(spec, "normalized.mp4")
        ln = "loudnorm=I=%s:TP=%s:LRA=%s" % (params.get("I", -16), params.get("TP", -1.5),
                                             params.get("LRA", 11))
        af_prefix = _af(spec)
        c1_chain = ",".join(filter(None, [af_prefix, ln + ":print_format=json"]))
        c1 = [CONFIG["ffmpeg_bin"], "-hide_banner", "-i", inputs[0],
              "-af", c1_chain, "-f", "null", "-"]
        stages.append(_stage("measure loudness", c1, capture="loudnorm"))
        c2_chain = ",".join(filter(None, [af_prefix, "__LOUDNORM__"]))
        c2 = base_cmd(spec) + ["-i", inputs[0], "-af", c2_chain]
        if not spec.get("_audio_only"):
            c2 += ["-c:v", "copy"]
        c2 += encoder_args(enc,
                           want_video=None, container=os.path.splitext(o)[1][1:])
        c2.append(o)
        stages.append(_stage("apply correction", c2, needs="loudnorm", loudnorm_base=ln))
        outputs.append(o)
        notes.append("Pass one measures, pass two applies exact correction values.")

    # ---- Compose --------------------------------------------------------
    elif op == "watermark":
        need(2)
        o = out_path(spec, "watermarked.mp4")
        m = str(params.get("margin", 20) or 20)
        pos = params.get("position") or "bottom-right"
        if pos == "custom":
            x, y = params.get("x") or "10", params.get("y") or "10"
        else:
            xt, yt = POSITIONS.get(pos, POSITIONS["bottom-right"])
            x, y = xt.replace("{m}", m), yt.replace("{m}", m)
        pre = []
        if params.get("scale"):
            pre.append("[1:v]scale=%s:-1[wm0]" % params["scale"])
            src = "[wm0]"
        else:
            src = "[1:v]"
        op_ = _n(params.get("opacity", 1))
        if op_ is None or not 0 <= op_ <= 1:
            raise ValueError("Opacity must be between 0 and 1.")
        if op_ < 1:
            pre.append("%sformat=rgba,colorchannelmixer=aa=%.3f[wm]" % (src, op_))
            src = "[wm]"
        fc = ";".join(pre + ["[0:v]%soverlay=%s:%s[v]" % (src, x, y)])
        cmd += ["-i", inputs[0], "-i", inputs[1], "-filter_complex", fc,
                "-map", "[v]", "-map", "0:a?"]
        cmd += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="copy"),
                            container=os.path.splitext(o)[1][1:])
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("overlay watermark", cmd))

    elif op == "pip":
        need(2)
        o = out_path(spec, "pip.mp4")
        m = str(params.get("margin", 24) or 24)
        xt, yt = POSITIONS.get(params.get("position") or "bottom-right", POSITIONS["bottom-right"])
        fc = "[1:v]scale=%s:-1[pip];[0:v][pip]overlay=%s:%s[v]" % (
            params.get("width", 480), xt.replace("{m}", m), yt.replace("{m}", m))
        amode = params.get("audio") or "0"
        if amode == "mix" and not all(stream_kinds(f)["audio"] for f in inputs[:2]):
            amode = "0" if stream_kinds(inputs[0])["audio"] else ("1" if stream_kinds(inputs[1])["audio"] else "none")
            notes.append("Mixing skipped; using the available audio track." if amode != "none" else "Neither input contains audio.")
        if amode == "mix":
            fc += ";[0:a][1:a]amix=inputs=2[a]"
        cmd += ["-i", inputs[0], "-i", inputs[1], "-filter_complex", fc, "-map", "[v]"]
        if amode == "mix":
            cmd += ["-map", "[a]"]
        elif amode in ("0", "1"):
            cmd += ["-map", "%s:a?" % amode]
        else:
            cmd += ["-an"]
        cmd += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="aac"),
                            container=os.path.splitext(o)[1][1:])
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("picture in picture", cmd))

    elif op == "stack":
        need(2)
        o = out_path(spec, "stacked.mp4")
        direction = "hstack" if (params.get("dir") or "h") == "h" else "vstack"
        if _b(params.get("normalize", "1")):
            if direction == "hstack":
                fc = "[0:v]scale=-2:720[l];[1:v]scale=-2:720[r];[l][r]hstack=inputs=2[v]"
            else:
                fc = "[0:v]scale=1280:-2[l];[1:v]scale=1280:-2[r];[l][r]vstack=inputs=2[v]"
        else:
            fc = "[0:v][1:v]%s=inputs=2[v]" % direction
        amode = params.get("audio") or "0"
        if amode == "mix" and not all(stream_kinds(f)["audio"] for f in inputs[:2]):
            amode = "0" if stream_kinds(inputs[0])["audio"] else ("1" if stream_kinds(inputs[1])["audio"] else "none")
            notes.append("Mixing skipped; using the available audio track." if amode != "none" else "Neither input contains audio.")
        if amode == "mix":
            fc += ";[0:a][1:a]amix=inputs=2[a]"
        cmd += ["-i", inputs[0], "-i", inputs[1], "-filter_complex", fc, "-map", "[v]"]
        if amode == "mix":
            cmd += ["-map", "[a]"]
        elif amode in ("0", "1"):
            cmd += ["-map", "%s:a?" % amode]
        else:
            cmd += ["-an"]
        cmd += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="aac"),
                            container=os.path.splitext(o)[1][1:])
        cmd.append(o)
        outputs.append(o)
        stages.append(_stage("stack", cmd))

    elif op == "add_cover":
        need(2)
        o = out_path(spec, "with_cover.m4a")
        cmd += ["-i", inputs[0], "-i", inputs[1], "-map", "0:a", "-map", "1:v",
                "-c", "copy", "-disposition:v:0", "attached_pic", o]
        outputs.append(o)
        stages.append(_stage("attach cover", cmd))

    # ---- Export ---------------------------------------------------------
    elif op in ("gif", "webp"):
        need(1)
        o = out_path(spec, "animation." + op)
        start = params.get("start") or "0"
        dur = params.get("duration") or "5"
        fps = params.get("fps") or (15 if op == "gif" else 20)
        width = params.get("width") or 600
        base_chain = "fps=%s,scale=%s:-1:flags=lanczos" % (fps, width)
        user_chain = compile_filterchain(spec.get("vfilters"), "video")
        if user_chain:
            base_chain = base_chain + "," + user_chain
        if op == "gif":
            palette = os.path.join(TMP_DIR, "palette_%s.png" % uuid.uuid4().hex[:8])
            cleanup.append(palette)
            c1 = base_cmd(spec) + ["-ss", str(start), "-t", str(dur), "-i", inputs[0],
                                   "-vf", "%s,palettegen=max_colors=%s:stats_mode=diff" % (
                                       base_chain, params.get("colors", 256)),
                                   palette]
            c2 = base_cmd(spec) + ["-ss", str(start), "-t", str(dur), "-i", inputs[0], "-i", palette,
                                   "-lavfi", "%s[x];[x][1:v]paletteuse=dither=%s" % (
                                       base_chain, params.get("dither", "sierra2_4a")),
                                   "-loop", str(params.get("loop", 0)), o]
            stages += [_stage("build palette", c1), _stage("encode gif", c2)]
            notes.append("A per-clip palette gives dramatically better colour than the default 216.")
        else:
            cmd += ["-ss", str(start), "-t", str(dur), "-i", inputs[0], "-vf", base_chain,
                    "-vcodec", "libwebp", "-lossless", "1" if _b(params.get("lossless")) else "0",
                    "-quality", str(params.get("quality", 75)), "-loop", "0", "-an", o]
            stages.append(_stage("encode webp", cmd))
        outputs.append(o)

    elif op == "screenshot":
        need(1)
        o = out_path(spec, "frame.png")
        vf = _vf(spec, ["scale=%s:-1" % params.get("width", -1)] if str(params.get("width", -1)) != "-1" else None)
        cmd += ["-ss", str(params.get("time") or "0"), "-i", inputs[0], "-frames:v", "1"]
        if vf:
            cmd += ["-vf", vf]
        cmd += ["-q:v", "2", o]
        outputs.append(o)
        stages.append(_stage("grab frame", cmd))

    elif op == "thumbnails":
        need(1)
        o = out_path(spec, "contact_sheet.jpg")
        cols = int(_n(params.get("cols"), 5) or 5)
        rows = int(_n(params.get("rows"), 5) or 5)
        interval = _n(params.get("interval"), 30) or 30
        vf = "fps=1/%s,scale=%s:-1,tile=%dx%d:margin=%s:padding=%s" % (
            interval, params.get("width", 320), cols, rows,
            params.get("margin", 6), params.get("margin", 6))
        cmd += ["-i", inputs[0], "-vf", vf, "-frames:v", "1", "-q:v", "3", o]
        outputs.append(o)
        stages.append(_stage("contact sheet", cmd))

    elif op == "waveform":
        need(1)
        o = out_path(spec, "waveform.png")
        color = (params.get("colors") or "#ff6b35").lstrip("#")
        cmd += ["-i", inputs[0], "-filter_complex",
                "showwavespic=s=%s:colors=0x%s:split_channels=0:draw=%s" % (
                    params.get("size", "1920x480"), color,
                    "full" if params.get("mode") == "line" else "scale"),
                "-frames:v", "1", o]
        outputs.append(o)
        stages.append(_stage("waveform", cmd))

    elif op == "spectrogram":
        need(1)
        o = out_path(spec, "spectrogram.png")
        cmd += ["-i", inputs[0], "-lavfi",
                "showspectrumpic=s=%s:mode=%s:scale=%s:color=%s" % (
                    params.get("size", "1920x1080"), params.get("mode", "combined"),
                    params.get("scale", "log"), params.get("color", "intensity")),
                "-frames:v", "1", o]
        outputs.append(o)
        stages.append(_stage("spectrogram", cmd))

    elif op == "visualizer":
        need(1)
        if not stream_kinds(inputs[0])["audio"]:
            raise ValueError("This file has no audio track to visualise.")
        o = out_path(spec, "visualizer.mp4")
        style = params.get("style") or "showwaves"
        size = params.get("size") or "1280x720"
        color = (params.get("color") or "#ff6b35").lstrip("#")
        if style == "showwaves":
            fc = "[0:a]showwaves=s=%s:mode=cline:colors=0x%s[v]" % (size, color)
        elif style == "showspectrum":
            fc = "[0:a]showspectrum=s=%s:mode=combined:color=intensity:slide=scroll[v]" % size
        elif style == "showfreqs":
            fc = "[0:a]showfreqs=s=%s:mode=bar:colors=0x%s[v]" % (size, color)
        elif style == "showcqt":
            fc = "[0:a]showcqt=s=%s[v]" % size
        else:
            fc = "[0:a]avectorscope=s=%s:zoom=1.5[v]" % size
        cmd += ["-i", inputs[0]]
        if params.get("bg"):
            bg = resolve_path(params["bg"], must_exist=True)
            cmd += ["-loop", "1", "-i", bg]
            fc += ";[1:v]scale=%s[bg];[bg][v]overlay=0:0:format=auto[vout]" % size
            vlabel = "[vout]"
        else:
            vlabel = "[v]"
        cmd += ["-filter_complex", fc, "-map", vlabel, "-map", "0:a"]
        cmd += encoder_args(with_defaults(enc, vcodec="libx264", crf=20, acodec="aac"),
                            container=os.path.splitext(o)[1][1:])
        cmd += ["-shortest", o]
        outputs.append(o)
        stages.append(_stage("render visualiser", cmd))

    else:
        raise ValueError("Operation '%s' is declared but not implemented." % op)

    return {"stages": stages, "notes": notes, "outputs": outputs, "cleanup": cleanup,
            "effective": {"enc": enc, "params": params, "output": spec.get("output"),
                          "audio_only": spec.get("_audio_only", False)}}


