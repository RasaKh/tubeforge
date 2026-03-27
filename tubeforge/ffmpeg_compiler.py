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

