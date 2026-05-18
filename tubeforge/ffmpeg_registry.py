import os

from .config import resolve_path

# ═══════════════════════════════════════════════════════════════════════════
#  FFMPEG FILTER REGISTRY
#  Data-driven: the Filter Studio renders a form per filter from `params`,
#  and the compiler turns the values back into a filtergraph string.
#  param: id, label, type(text|number|select|bool), arg (ffmpeg key),
#         pos (positional), default, choices, help, esc (escape special chars)
# ═══════════════════════════════════════════════════════════════════════════

def P(pid, label, ptype="text", arg=None, pos=False, default="", choices=None,
      help="", esc=False, step=None, min=None, max=None, placeholder="", when=None):
    d = dict(id=pid, label=label, type=ptype, arg=arg or pid, pos=pos,
             default=default, help=help, esc=esc, placeholder=placeholder)
    if choices:
        d["choices"] = choices
    if when:
        d["when"] = when
    for k, v in (("step", step), ("min", min), ("max", max)):
        if v is not None:
            d[k] = v
    return d


FFMPEG_FILTERS = [
    # ── Geometry ───────────────────────────────────────────────────────────
    dict(id="scale", kind="video", cat="Geometry", label="Scale / resize",
         help="Resize the picture. Use -2 on one axis to preserve aspect ratio.",
         params=[P("w", "Width", pos=True, default="-2", placeholder="1920 or -2"),
                 P("h", "Height", pos=True, default="720", placeholder="1080"),
                 P("flags", "Scaler", "select", default="",
                   choices=["", "bilinear", "bicubic", "lanczos", "spline", "neighbor", "area"],
                   help="lanczos is sharpest for downscaling.")]),
    dict(id="crop", kind="video", cat="Geometry", label="Crop",
         help="Cut a rectangle out of the frame.",
         params=[P("w", "Width", pos=True, default="iw", placeholder="iw or 1280"),
                 P("h", "Height", pos=True, default="ih"),
                 P("x", "X offset", pos=True, default="(iw-ow)/2"),
                 P("y", "Y offset", pos=True, default="(ih-oh)/2")]),
    dict(id="pad", kind="video", cat="Geometry", label="Pad / letterbox",
         params=[P("w", "Width", pos=True, default="iw"), P("h", "Height", pos=True, default="ih"),
                 P("x", "X", pos=True, default="(ow-iw)/2"), P("y", "Y", pos=True, default="(oh-ih)/2"),
                 P("color", "Colour", default="black")]),
    dict(id="transpose", kind="video", cat="Geometry", label="Rotate 90°",
         params=[P("dir", "Direction", "select", pos=True, default="1",
                   choices=["0", "1", "2", "3"],
                   help="0=90°CCW+flip 1=90°CW 2=90°CCW 3=90°CW+flip")]),
    dict(id="rotate", kind="video", cat="Geometry", label="Rotate arbitrary",
         params=[P("angle", "Angle (radians or expr)", pos=True, default="PI/6"),
                 P("fillcolor", "Fill colour", default="black")]),
    dict(id="hflip", kind="video", cat="Geometry", label="Flip horizontally", params=[]),
    dict(id="vflip", kind="video", cat="Geometry", label="Flip vertically", params=[]),
    dict(id="setsar", kind="video", cat="Geometry", label="Set pixel aspect",
         params=[P("sar", "SAR", pos=True, default="1")]),
    dict(id="zoompan", kind="video", cat="Geometry", label="Ken Burns zoom",
         params=[P("z", "Zoom expr", default="min(zoom+0.0015,1.5)"),
                 P("d", "Duration (frames)", "number", default="125"),
                 P("s", "Output size", default="1920x1080")]),

    # ── Timing ─────────────────────────────────────────────────────────────
    dict(id="fps", kind="video", cat="Timing", label="Change frame rate",
         params=[P("fps", "FPS", pos=True, default="30", placeholder="24 / 30 / 60")]),
    dict(id="setpts", kind="video", cat="Timing", label="Video speed (setpts)",
         help="0.5*PTS = 2x faster, 2.0*PTS = half speed. Pair with atempo for audio.",
         params=[P("expr", "PTS expression", pos=True, default="0.5*PTS")]),
    dict(id="minterpolate", kind="video", cat="Timing", label="Motion interpolation",
         help="Smooth slow motion / frame rate up-conversion. Very slow.",
         params=[P("fps", "Target FPS", "number", default="60"),
                 P("mi_mode", "Mode", "select", default="mci", choices=["dup", "blend", "mci"]),
                 P("mc_mode", "MC mode", "select", default="aobmc", choices=["obmc", "aobmc"]),
                 P("vsbmc", "Variable block", "select", default="1", choices=["0", "1"])]),
    dict(id="framestep", kind="video", cat="Timing", label="Keep every Nth frame",
         params=[P("step", "N", "number", pos=True, default="2")]),
    dict(id="reverse", kind="video", cat="Timing", label="Reverse video",
         help="Buffers the whole clip in RAM. Use on short segments.", params=[]),
    dict(id="loop", kind="video", cat="Timing", label="Loop frames",
         params=[P("loop", "Loop count", "number", default="-1"),
                 P("size", "Frames to buffer", "number", default="250"),
                 P("start", "Start frame", "number", default="0")]),
    dict(id="tmix", kind="video", cat="Timing", label="Temporal blend",
         params=[P("frames", "Frames", "number", default="3")]),

    # ── Colour ─────────────────────────────────────────────────────────────
    dict(id="eq", kind="video", cat="Colour", label="Brightness / contrast / saturation",
         params=[P("brightness", "Brightness", "number", default="0", step="0.01", min=-1, max=1),
                 P("contrast", "Contrast", "number", default="1", step="0.01", min=-2, max=2),
                 P("saturation", "Saturation", "number", default="1", step="0.01", min=0, max=3),
                 P("gamma", "Gamma", "number", default="1", step="0.01", min=0.1, max=10)]),
    dict(id="hue", kind="video", cat="Colour", label="Hue / saturation shift",
         params=[P("h", "Hue degrees", "number", default="0"),
                 P("s", "Saturation", "number", default="1", step="0.01")]),
    dict(id="colorbalance", kind="video", cat="Colour", label="Colour balance",
         params=[P("rs", "Red shadows", "number", default="0", step="0.01"),
                 P("gs", "Green shadows", "number", default="0", step="0.01"),
                 P("bs", "Blue shadows", "number", default="0", step="0.01"),
                 P("rm", "Red midtones", "number", default="0", step="0.01"),
                 P("gm", "Green midtones", "number", default="0", step="0.01"),
                 P("bm", "Blue midtones", "number", default="0", step="0.01"),
                 P("rh", "Red highlights", "number", default="0", step="0.01"),
                 P("gh", "Green highlights", "number", default="0", step="0.01"),
                 P("bh", "Blue highlights", "number", default="0", step="0.01")]),
    dict(id="curves", kind="video", cat="Colour", label="Curves preset",
         params=[P("preset", "Preset", "select", default="vintage",
                   choices=["none", "color_negative", "cross_process", "darker", "increase_contrast",
                            "lighter", "linear_contrast", "medium_contrast", "negative",
                            "strong_contrast", "vintage"])]),
    dict(id="lut3d", kind="video", cat="Colour", label="Apply 3D LUT",
         params=[P("file", "LUT file (.cube)", esc=True, placeholder="/path/to/look.cube")]),
    dict(id="negate", kind="video", cat="Colour", label="Invert colours", params=[]),
    dict(id="format", kind="video", cat="Colour", label="Force pixel format",
         params=[P("pix_fmts", "Pixel format", "select", pos=True, default="yuv420p",
                   choices=["yuv420p", "yuv422p", "yuv444p", "yuv420p10le", "yuv422p10le",
                            "yuv444p10le", "rgb24", "gbrp", "nv12", "p010le"])]),
    dict(id="colorspace", kind="video", cat="Colour", label="Colourspace convert",
         params=[P("all", "Target", "select", default="bt709",
                   choices=["bt709", "bt601-6-625", "bt601-6-525", "bt2020"])]),
    dict(id="vignette", kind="video", cat="Colour", label="Vignette",
         params=[P("angle", "Angle", default="PI/5")]),
    dict(id="chromakey", kind="video", cat="Colour", label="Chroma key (green screen)",
         params=[P("color", "Key colour", default="green"),
                 P("similarity", "Similarity", "number", default="0.3", step="0.01"),
                 P("blend", "Blend", "number", default="0.0", step="0.01")]),

    # ── Restoration ────────────────────────────────────────────────────────
    dict(id="unsharp", kind="video", cat="Restore", label="Sharpen / blur (unsharp)",
         params=[P("luma_msize_x", "Luma X", "number", default="5"),
                 P("luma_msize_y", "Luma Y", "number", default="5"),
                 P("luma_amount", "Amount", "number", default="1.0", step="0.1",
                   help="Negative values blur.")]),
    dict(id="gblur", kind="video", cat="Restore", label="Gaussian blur",
         params=[P("sigma", "Sigma", "number", default="3", step="0.1")]),
    dict(id="boxblur", kind="video", cat="Restore", label="Box blur",
         params=[P("luma_radius", "Radius", default="2"), P("luma_power", "Power", "number", default="1")]),
    dict(id="hqdn3d", kind="video", cat="Restore", label="Denoise (hqdn3d)",
         params=[P("luma_spatial", "Luma spatial", "number", pos=True, default="4", step="0.1"),
                 P("chroma_spatial", "Chroma spatial", "number", pos=True, default="3", step="0.1"),
                 P("luma_tmp", "Luma temporal", "number", pos=True, default="6", step="0.1"),
                 P("chroma_tmp", "Chroma temporal", "number", pos=True, default="4.5", step="0.1")]),
    dict(id="nlmeans", kind="video", cat="Restore", label="Denoise (nlmeans, slow)",
         params=[P("s", "Strength", "number", default="1.0", step="0.1")]),
    dict(id="deband", kind="video", cat="Restore", label="Debanding",
         params=[P("range", "Range", "number", default="16"),
                 P("direction", "Direction", default="6.28")]),
    dict(id="yadif", kind="video", cat="Restore", label="Deinterlace (yadif)",
         params=[P("mode", "Mode", "select", pos=True, default="0",
                   choices=["0", "1", "2", "3"], help="1 doubles the frame rate.")]),
    dict(id="bwdif", kind="video", cat="Restore", label="Deinterlace (bwdif)",
         params=[P("mode", "Mode", "select", pos=True, default="0", choices=["0", "1"])]),
    dict(id="deshake", kind="video", cat="Restore", label="Quick stabilise (deshake)", params=[]),
    dict(id="delogo", kind="video", cat="Restore", label="Remove logo",
         params=[P("x", "X", "number", default="0"), P("y", "Y", "number", default="0"),
                 P("w", "Width", "number", default="100"), P("h", "Height", "number", default="50")]),
    dict(id="edgedetect", kind="video", cat="Restore", label="Edge detect",
         params=[P("low", "Low", "number", default="0.1", step="0.01"),
                 P("high", "High", "number", default="0.4", step="0.01")]),

    # ── Overlay / text ─────────────────────────────────────────────────────
    dict(id="drawtext", kind="video", cat="Overlay", label="Draw text",
         help="Burn text into the picture. Supports expressions for position and time.",
         params=[P("text", "Text", esc=True, default="Hello"),
                 P("fontfile", "Font file", esc=True, placeholder="/usr/share/fonts/.../DejaVuSans.ttf"),
                 P("fontsize", "Size", "number", default="36"),
                 P("fontcolor", "Colour", default="white"),
                 P("x", "X", default="(w-text_w)/2"), P("y", "Y", default="h-th-40"),
                 P("box", "Background box", "select", default="1", choices=["0", "1"]),
                 P("boxcolor", "Box colour", default="black@0.5"),
                 P("boxborderw", "Box padding", "number", default="10"),
                 P("enable", "Enable expression", esc=True, placeholder="between(t,5,10)")]),
    dict(id="drawbox", kind="video", cat="Overlay", label="Draw box",
         params=[P("x", "X", "number", default="0"), P("y", "Y", "number", default="0"),
                 P("w", "Width", "number", default="200"), P("h", "Height", "number", default="100"),
                 P("color", "Colour", default="red@0.6"), P("t", "Thickness", default="fill")]),
    dict(id="subtitles", kind="video", cat="Overlay", label="Burn in subtitles",
         params=[P("filename", "Subtitle file", esc=True, placeholder="subs.srt"),
                 P("force_style", "Style override", esc=True,
                   placeholder="FontName=DejaVu Sans,FontSize=24,OutlineColour=&H80000000")]),
    dict(id="fade", kind="video", cat="Overlay", label="Fade in/out",
         params=[P("t", "Type", "select", default="in", choices=["in", "out"]),
                 P("st", "Start (s)", "number", default="0", step="0.1"),
                 P("d", "Duration (s)", "number", default="1", step="0.1"),
                 P("color", "Colour", default="black")]),
    dict(id="tile", kind="video", cat="Overlay", label="Tile frames (contact sheet)",
         params=[P("layout", "Layout", pos=True, default="4x4"),
                 P("margin", "Margin", "number", default="4"),
                 P("padding", "Padding", "number", default="4")]),

    # ── Audio ──────────────────────────────────────────────────────────────
    dict(id="volume", kind="audio", cat="Level", label="Volume",
         params=[P("volume", "Gain", pos=True, default="1.0", placeholder="1.5 or 6dB")]),
    dict(id="loudnorm", kind="audio", cat="Level", label="EBU R128 loudness normalise",
         help="Broadcast-standard normalisation. Use the dedicated two-pass operation for best results.",
         params=[P("I", "Integrated LUFS", "number", default="-16", step="0.5"),
                 P("TP", "True peak dB", "number", default="-1.5", step="0.1"),
                 P("LRA", "Loudness range", "number", default="11", step="0.5")]),
    dict(id="dynaudnorm", kind="audio", cat="Level", label="Dynamic normalise",
         params=[P("f", "Frame length ms", "number", default="500"),
                 P("g", "Gauss window", "number", default="31"),
                 P("p", "Peak target", "number", default="0.95", step="0.01")]),
    dict(id="acompressor", kind="audio", cat="Level", label="Compressor",
         params=[P("threshold", "Threshold", "number", default="0.125", step="0.001"),
                 P("ratio", "Ratio", "number", default="4"),
                 P("attack", "Attack ms", "number", default="20"),
                 P("release", "Release ms", "number", default="250"),
                 P("makeup", "Makeup gain", "number", default="1", step="0.1")]),
    dict(id="alimiter", kind="audio", cat="Level", label="Limiter",
         params=[P("limit", "Limit", "number", default="0.9", step="0.01"),
                 P("attack", "Attack ms", "number", default="5"),
                 P("release", "Release ms", "number", default="50")]),
    dict(id="agate", kind="audio", cat="Level", label="Noise gate",
         params=[P("threshold", "Threshold", "number", default="0.06", step="0.001"),
                 P("ratio", "Ratio", "number", default="2")]),
    dict(id="compand", kind="audio", cat="Level", label="Compand (custom curve)",
         params=[P("attacks", "Attacks", default="0.3"), P("decays", "Decays", default="0.8"),
                 P("points", "Points", esc=True, default="-70/-70|-24/-12|0/-6")]),
    dict(id="highpass", kind="audio", cat="EQ", label="High-pass filter",
         params=[P("f", "Cutoff Hz", "number", default="80"), P("p", "Poles", "number", default="2")]),
    dict(id="lowpass", kind="audio", cat="EQ", label="Low-pass filter",
         params=[P("f", "Cutoff Hz", "number", default="12000"), P("p", "Poles", "number", default="2")]),
    dict(id="bandpass", kind="audio", cat="EQ", label="Band-pass filter",
         params=[P("f", "Centre Hz", "number", default="1000"), P("width_type", "Width type", "select",
                 default="h", choices=["h", "q", "o", "s"]), P("w", "Width", "number", default="500")]),
    dict(id="equalizer", kind="audio", cat="EQ", label="Parametric EQ band",
         params=[P("f", "Frequency Hz", "number", default="1000"),
                 P("width_type", "Width type", "select", default="q", choices=["h", "q", "o", "s"]),
                 P("w", "Width/Q", "number", default="1", step="0.1"),
                 P("g", "Gain dB", "number", default="0", step="0.5")]),
    dict(id="bass", kind="audio", cat="EQ", label="Bass shelf",
         params=[P("g", "Gain dB", "number", default="5", step="0.5"),
                 P("f", "Frequency", "number", default="100")]),
    dict(id="treble", kind="audio", cat="EQ", label="Treble shelf",
         params=[P("g", "Gain dB", "number", default="5", step="0.5"),
                 P("f", "Frequency", "number", default="3000")]),
    dict(id="afftdn", kind="audio", cat="Restore", label="FFT denoise",
         params=[P("nr", "Reduction dB", "number", default="12"),
                 P("nf", "Noise floor dB", "number", default="-50")]),
    dict(id="anlmdn", kind="audio", cat="Restore", label="Non-local means denoise",
         params=[P("s", "Strength", "number", default="0.00001", step="0.00001")]),
    dict(id="silenceremove", kind="audio", cat="Restore", label="Strip silence",
         params=[P("start_periods", "Start periods", "number", default="1"),
                 P("start_threshold", "Start threshold", default="-50dB"),
                 P("stop_periods", "Stop periods", "number", default="-1"),
                 P("stop_threshold", "Stop threshold", default="-50dB"),
                 P("stop_duration", "Stop duration", default="1")]),
    dict(id="atempo", kind="audio", cat="Timing", label="Tempo (keeps pitch)",
         help="Valid range 0.5–2.0. Chain two of them for more extreme changes.",
         params=[P("tempo", "Tempo", "number", pos=True, default="1.25", step="0.05")]),
    dict(id="asetrate", kind="audio", cat="Timing", label="Pitch via sample rate",
         params=[P("r", "New rate", "number", pos=True, default="48000")]),
    dict(id="rubberband", kind="audio", cat="Timing", label="Rubberband pitch/tempo",
         params=[P("tempo", "Tempo", "number", default="1", step="0.01"),
                 P("pitch", "Pitch", "number", default="1", step="0.01")]),
    dict(id="afade", kind="audio", cat="Timing", label="Audio fade",
         params=[P("t", "Type", "select", default="in", choices=["in", "out"]),
                 P("st", "Start (s)", "number", default="0", step="0.1"),
                 P("d", "Duration (s)", "number", default="2", step="0.1"),
                 P("curve", "Curve", "select", default="tri",
                   choices=["tri", "qsin", "hsin", "esin", "log", "ipar", "qua", "cub", "squ", "cbr"])]),
    dict(id="adelay", kind="audio", cat="Timing", label="Delay channels",
         params=[P("delays", "Delays (ms)", pos=True, default="500|500"),
                 P("all", "Apply to all", "select", default="1", choices=["0", "1"])]),
    dict(id="areverse", kind="audio", cat="Timing", label="Reverse audio", params=[]),
    dict(id="apad", kind="audio", cat="Timing", label="Pad with silence",
         params=[P("pad_dur", "Duration (s)", "number", default="2", step="0.1")]),
    dict(id="aresample", kind="audio", cat="Format", label="Resample",
         params=[P("rate", "Sample rate", "select", pos=True, default="48000",
                   choices=["8000", "16000", "22050", "32000", "44100", "48000", "96000", "192000"])]),
    dict(id="pan", kind="audio", cat="Format", label="Channel mixer (pan)",
         params=[P("args", "Pan spec", pos=True, esc=True, default="stereo|c0=c0|c1=c1")]),
    dict(id="channelmap", kind="audio", cat="Format", label="Channel map",
         params=[P("map", "Map", esc=True, default="0|1"),
                 P("channel_layout", "Layout", default="stereo")]),
    dict(id="stereotools", kind="audio", cat="Format", label="Stereo tools",
         params=[P("mlev", "Mid level", "number", default="1", step="0.05"),
                 P("slev", "Side level", "number", default="1", step="0.05"),
                 P("balance_in", "Balance", "number", default="0", step="0.05")]),
    dict(id="extrastereo", kind="audio", cat="Format", label="Stereo widener",
         params=[P("m", "Amount", "number", default="2.5", step="0.1")]),
    dict(id="crystalizer", kind="audio", cat="Format", label="Crystalizer (exciter)",
         params=[P("i", "Intensity", "number", default="2", step="0.1")]),
    dict(id="aecho", kind="audio", cat="Space", label="Echo",
         params=[P("in_gain", "In gain", "number", pos=True, default="0.8", step="0.05"),
                 P("out_gain", "Out gain", "number", pos=True, default="0.9", step="0.05"),
                 P("delays", "Delays ms", pos=True, default="1000"),
                 P("decays", "Decays", pos=True, default="0.5")]),
    dict(id="aphaser", kind="audio", cat="Space", label="Phaser",
         params=[P("in_gain", "In gain", "number", default="0.4", step="0.05"),
                 P("speed", "Speed", "number", default="0.5", step="0.05")]),
    dict(id="chorus", kind="audio", cat="Space", label="Chorus",
         params=[P("in_gain", "In gain", "number", pos=True, default="0.5", step="0.05"),
                 P("out_gain", "Out gain", "number", pos=True, default="0.9", step="0.05"),
                 P("delays", "Delays", pos=True, default="50|60"),
                 P("decays", "Decays", pos=True, default="0.4|0.32"),
                 P("speeds", "Speeds", pos=True, default="0.25|0.4"),
                 P("depths", "Depths", pos=True, default="2|1.3")]),
]

FILTER_INDEX = {f["id"]: f for f in FFMPEG_FILTERS}


def _esc_filter_value(v):
    """Escape a value destined for the inside of a filtergraph."""
    v = str(v)
    # AVOption parsing, then filtergraph parsing. argv avoids shell escaping,
    # but both FFmpeg parser layers are still present.
    for chars in ("\\:'", "\\'[],;"):
        v = "".join("\\" + c if c in chars else c for c in v)
    return v


def _validate_filter_file(spec_id, param_id, raw):
    """Resolve and sandbox filter file paths before escaping into filtergraph."""
    if spec_id == "drawtext" and param_id == "fontfile":
        real = os.path.realpath(os.path.expanduser(raw))
        if (real == "/usr/share/fonts" or real.startswith("/usr/share/fonts" + os.sep)) and os.path.isfile(real):
            return real
        return resolve_path(raw, must_exist=True)
    if (spec_id == "lut3d" and param_id == "file") or (spec_id == "subtitles" and param_id == "filename"):
        return resolve_path(raw, must_exist=True)
    return raw


def compile_filter(entry):
    """entry = {id: 'scale', params: {...}, enabled: bool} -> 'scale=-2:720'"""
    spec = FILTER_INDEX.get(entry.get("id"))
    if not spec:
        return None
    vals = entry.get("params") or {}
    positional, named = [], []
    allow_pos = True
    for p in spec["params"]:
        raw = vals.get(p["id"], p.get("default", ""))
        if raw is None:
            raw = ""
        raw = str(raw).strip()
        if raw == "":
            if p.get("pos"):
                allow_pos = False
            continue
        if str(raw) == str(p.get("default", "")) and not p.get("pos") and entry.get("lean"):
            continue
        raw = _validate_filter_file(spec["id"], p["id"], raw)
        val = _esc_filter_value(raw)
        if p.get("pos") and allow_pos and not named:
            positional.append(val)
        else:
            allow_pos = False
            arg = "sample_rate" if spec["id"] == "aresample" and p["id"] == "rate" else p["arg"]
            named.append("%s=%s" % (arg, val))
    if spec["id"] == "drawtext":
        named.append("expansion=none")
    parts = positional + named
    return spec["id"] + ("=" + ":".join(parts) if parts else "")


def compile_filterchain(entries, kind=None):
    out = []
    for e in entries or []:
        if e.get("enabled") is False:
            continue
        spec = FILTER_INDEX.get(e.get("id"))
        if not spec:
            continue
        if kind and spec["kind"] != kind:
            continue
        s = compile_filter(e)
        if s:
            out.append(s)
    return ",".join(out)


# ═══════════════════════════════════════════════════════════════════════════
#  ENCODER MATRIX
# ═══════════════════════════════════════════════════════════════════════════

# Encoders whose two-pass mode is a real average-bitrate pass. Hardware
# encoders either lack it or spell it differently, so the option is refused
# rather than silently producing a single-pass encode.
TWOPASS_FAMILIES = {"x264", "x265", "vpx", "mpeg"}

VIDEO_ENCODERS = [
    dict(id="copy", label="Copy (no re-encode)", family="copy"),
    dict(id="libx264", label="H.264 (libx264)", family="x264", rc=["crf", "bitrate", "twopass"],
         presets=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow",
                  "slower", "veryslow", "placebo"],
         tunes=["", "film", "animation", "grain", "stillimage", "fastdecode", "zerolatency"],
         profiles=["", "baseline", "main", "high", "high10", "high422", "high444"],
         crf_range=[0, 51], crf_default=21),
    dict(id="libx265", label="H.265 / HEVC (libx265)", family="x265", rc=["crf", "bitrate", "twopass"],
         presets=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow",
                  "slower", "veryslow", "placebo"],
         tunes=["", "psnr", "ssim", "grain", "zerolatency", "fastdecode", "animation"],
         profiles=["", "main", "main10", "main12", "main444-8"],
         crf_range=[0, 51], crf_default=26),
    dict(id="libsvtav1", label="AV1 (SVT-AV1)", family="av1", rc=["crf", "bitrate"],
         presets=[str(i) for i in range(0, 14)], profiles=["", "main", "high"],
         crf_range=[0, 63], crf_default=32),
    dict(id="libaom-av1", label="AV1 (libaom, slow)", family="av1", rc=["crf", "bitrate"],
         crf_range=[0, 63], crf_default=32),
    dict(id="librav1e", label="AV1 (rav1e)", family="av1", rc=["qp", "bitrate"],
         crf_range=[0, 255], crf_default=100),
    dict(id="libvpx-vp9", label="VP9 (libvpx-vp9)", family="vpx", rc=["crf", "bitrate", "twopass"],
         crf_range=[0, 63], crf_default=31),
    dict(id="libvpx", label="VP8 (libvpx)", family="vpx", rc=["crf", "bitrate"],
         crf_range=[4, 63], crf_default=10),
    dict(id="mpeg4", label="MPEG-4 Part 2", family="mpeg", rc=["bitrate", "qscale"]),
    dict(id="libxvid", label="Xvid", family="mpeg", rc=["bitrate", "qscale"]),
    dict(id="prores_ks", label="ProRes (prores_ks)", family="prores", rc=["qscale"],
         profiles=["0", "1", "2", "3", "4", "5"]),
    dict(id="dnxhd", label="DNxHD/DNxHR", family="dnx", rc=["bitrate"],
         profiles=["", "dnxhr_lb", "dnxhr_sq", "dnxhr_hq", "dnxhr_hqx", "dnxhr_444"]),
    dict(id="ffv1", label="FFV1 (lossless)", family="lossless", rc=[]),
    dict(id="libx264rgb", label="H.264 RGB (lossless-ish)", family="x264", rc=["crf"]),
    dict(id="h264_nvenc", label="H.264 NVENC (NVIDIA)", family="nvenc", rc=["cq", "bitrate"],
         presets=["p1", "p2", "p3", "p4", "p5", "p6", "p7"],
         tunes=["", "hq", "ll", "ull", "lossless"], hw=True),
    dict(id="hevc_nvenc", label="HEVC NVENC (NVIDIA)", family="nvenc", rc=["cq", "bitrate"],
         presets=["p1", "p2", "p3", "p4", "p5", "p6", "p7"], hw=True),
    dict(id="av1_nvenc", label="AV1 NVENC (NVIDIA 40xx)", family="nvenc", rc=["cq", "bitrate"], hw=True),
    dict(id="h264_vaapi", label="H.264 VAAPI (Intel/AMD)", family="vaapi", rc=["qp", "bitrate"], hw=True),
    dict(id="hevc_vaapi", label="HEVC VAAPI", family="vaapi", rc=["qp", "bitrate"], hw=True),
    dict(id="av1_vaapi", label="AV1 VAAPI", family="vaapi", rc=["qp", "bitrate"], hw=True),
    dict(id="h264_qsv", label="H.264 QuickSync", family="qsv", rc=["qscale", "bitrate"], hw=True),
    dict(id="hevc_qsv", label="HEVC QuickSync", family="qsv", rc=["qscale", "bitrate"], hw=True),
    dict(id="h264_amf", label="H.264 AMF (AMD)", family="amf", rc=["bitrate"], hw=True),
    dict(id="gif", label="GIF", family="image", rc=[]),
    dict(id="libwebp", label="WebP", family="image", rc=["qscale"]),
    dict(id="png", label="PNG sequence", family="image", rc=[]),
    dict(id="mjpeg", label="MJPEG", family="image", rc=["qscale"]),
]

# Each audio encoder declares how quality is actually expressed for it. A single
# generic -q:a is wrong for most of them: LAME wants 0-9, native AAC wants a
# fractional VBR scale, libfdk wants -vbr 1-5, Opus and FLAC use a compression
# level, and PCM has no rate control at all. `arc` lists the modes the UI offers.
#   bitrate     -> -b:a
#   quality     -> -q:a  (scale and direction differ per codec, hence q_hint)
#   vbr         -> -vbr  (libfdk only)
#   compression -> -compression_level
#   lossless    -> nothing to set
AUDIO_ENCODERS = [
    dict(id="copy", label="Copy (no re-encode)", family="copy", arc=[]),

    dict(id="aac", label="AAC (native)", family="aac",
         arc=["bitrate", "quality"], abr_default="192k",
         q_range=[0.1, 2.0], q_step=0.1, q_default=1.4,
         q_hint="Higher values use more bits and generally improve quality. Quality depends on the material.",
         bitrates=["64k", "96k", "128k", "160k", "192k", "224k", "256k", "320k"],
         profiles=["", "aac_low"],
         sample_fmts=["", "fltp"]),

    dict(id="libfdk_aac", label="AAC (libfdk, if built in)", family="aac",
         arc=["bitrate", "vbr"], abr_default="192k",
         vbr_range=[1, 5], vbr_default=4,
         vbr_hint="1 is roughly 32 kbps per channel, 5 is roughly 96. 4 is a good default.",
         bitrates=["64k", "96k", "128k", "160k", "192k", "256k", "320k"],
         profiles=["", "aac_low", "aac_he", "aac_he_v2", "aac_ld", "aac_eld"]),

    dict(id="libmp3lame", label="MP3 (LAME)", family="mp3",
         arc=["bitrate", "quality"], abr_default="192k",
         q_range=[0, 9], q_step=1, q_default=2,
         q_hint="0 is the best quality (about 245 kbps), 9 the worst. V2 (q=2) is the usual choice.",
         bitrates=["96k", "128k", "160k", "192k", "224k", "256k", "320k"],
         compression_range=[0, 9], compression_label="Encoding effort",
         joint_stereo=True),

    dict(id="libopus", label="Opus", family="opus",
         arc=["bitrate"], abr_default="128k",
         bitrates=["32k", "48k", "64k", "96k", "128k", "160k", "192k", "256k", "510k"],
         compression_range=[0, 10], compression_default=10,
         compression_label="Encoding effort",
         vbr_modes=["on", "constrained", "off"],
         applications=["", "audio", "voip", "lowdelay"],
         frame_durations=["", "2.5", "5", "10", "20", "40", "60"]),

    dict(id="opus", label="Opus (native, experimental)", family="opus",
         arc=["bitrate"], abr_default="128k",
         bitrates=["64k", "96k", "128k", "160k", "192k", "256k"]),

    dict(id="libvorbis", label="Vorbis", family="vorbis",
         arc=["bitrate", "quality"], abr_default="192k",
         q_range=[-1, 10], q_step=1, q_default=5,
         q_hint="-1 is the smallest, 10 the largest. 5 is about 160 kbps.",
         bitrates=["96k", "128k", "160k", "192k", "256k", "320k"]),

    dict(id="flac", label="FLAC (lossless)", family="flac",
         arc=["compression"],
         compression_range=[0, 12], compression_default=5,
         compression_label="Compression level",
         compression_hint="Higher is a smaller file and a slower encode. The audio is identical either way.",
         sample_fmts=["", "s16", "s32"]),

    dict(id="alac", label="ALAC (Apple lossless)", family="lossless", arc=[],
         sample_fmts=["", "s16p", "s32p"]),

    dict(id="pcm_s16le", label="PCM 16-bit WAV", family="pcm", arc=[]),
    dict(id="pcm_s24le", label="PCM 24-bit WAV", family="pcm", arc=[]),
    dict(id="pcm_s32le", label="PCM 32-bit WAV", family="pcm", arc=[]),
    dict(id="pcm_f32le", label="PCM 32-bit float", family="pcm", arc=[]),

    dict(id="ac3", label="AC-3", family="ac3", arc=["bitrate"], abr_default="448k",
         bitrates=["192k", "224k", "256k", "384k", "448k", "640k"]),
    dict(id="eac3", label="E-AC-3", family="ac3", arc=["bitrate"], abr_default="384k",
         bitrates=["128k", "192k", "256k", "384k", "640k", "1024k"]),
    dict(id="truehd", label="TrueHD (lossless)", family="lossless", arc=[]),

    dict(id="libmp3lame_vbr", label="MP3 (LAME, VBR preset)", family="mp3", hidden=True, arc=[]),
]


for _encoder in AUDIO_ENCODERS:
    if _encoder["id"] == "libopus":
        _encoder["sample_rates"] = ["8000", "12000", "16000", "24000", "48000"]
    elif _encoder["id"] == "opus":
        _encoder["sample_rates"] = ["48000"]

CHANNEL_LAYOUTS = ["", "mono", "stereo", "2.1", "quad", "5.0", "5.1", "6.1", "7.1"]
SAMPLE_RATES = ["", "8000", "11025", "12000", "16000", "22050", "24000", "32000", "44100", "48000", "64000", "88200", "96000", "192000"]

CONTAINERS = ["mp4", "mkv", "mov", "webm", "avi", "flv", "ts", "m4a", "mp3", "flac",
              "wav", "aiff", "opus", "ogg", "aac", "ac3", "eac3", "thd", "m4v", "gif", "webp", "png", "jpg", "srt", "ass", "vtt", "3gp", "wmv", "mxf"]

SUBTITLE_CODECS = ["copy", "mov_text", "srt", "ass", "webvtt", "dvdsub"]

HWACCELS = ["", "auto", "cuda", "vaapi", "qsv", "vdpau", "videotoolbox", "dxva2", "d3d11va", "opencl"]


# ═══════════════════════════════════════════════════════════════════════════
#  FFMPEG OPERATION REGISTRY
#  Each operation declares its own extra fields; the UI renders them and the
#  compiler below turns everything into one or more ffmpeg invocations
#  ("stages", which is how two-pass encodes and palette-based GIFs work).
# ═══════════════════════════════════════════════════════════════════════════

FF_OPS = [
    # ── Inspect ────────────────────────────────────────────────────────────
    dict(id="probe", label="Inspect / probe", group="Inspect", inputs=1, enc=False, filters=False,
         out=False, help="Full ffprobe dump: streams, chapters, tags, bitrates."),
    dict(id="silencedetect", label="Detect silence", group="Inspect", inputs=1, enc=False, filters=False,
         out=False, help="Report silent ranges — useful before auto-trimming.",
         fields=[P("noise", "Noise floor", default="-40dB"),
                 P("d", "Minimum duration (s)", "number", default="1", step="0.1")]),
    dict(id="blackdetect", label="Detect black frames", group="Inspect", inputs=1, enc=False,
         filters=False, out=False,
         fields=[P("d", "Min duration (s)", "number", default="2", step="0.1"),
                 P("pic_th", "Black threshold", "number", default="0.98", step="0.01")]),
    dict(id="scenedetect", label="Detect scene changes", group="Inspect", inputs=1, enc=False,
         filters=False, out=False,
         fields=[P("threshold", "Sensitivity 0-1", "number", default="0.3", step="0.05")]),

    # ── Convert ────────────────────────────────────────────────────────────
    dict(id="transcode", label="Transcode / re-encode", group="Convert", inputs=1, enc=True,
         filters=True, out_hint="mp4",
         help="The general-purpose encoder. Full codec, rate-control and filter control."),
    dict(id="remux", label="Remux container", group="Convert", inputs=1, enc=False, filters=False,
         out_hint="mkv", help="Change the container without touching the streams. Instant and lossless."),
    dict(id="audio_convert", label="Convert audio file", group="Convert", inputs=1, enc=True,
         filters=True, out_hint="mp3", help="Audio-only encode with the audio filter chain applied."),
    dict(id="images_to_video", label="Images → video", group="Convert", inputs=1, enc=True,
         filters=True, out_hint="mp4",
         help="Input should be a printf pattern such as frame_%04d.png or a glob.",
         fields=[P("framerate", "Input frame rate", "number", default="25"),
                 P("pattern_type", "Pattern type", "select", default="sequence",
                   choices=["sequence", "glob"])]),
    dict(id="video_to_images", label="Video → image sequence", group="Convert", inputs=1, enc=False,
         filters=True, out_hint="png",
         fields=[P("fps", "Frames per second to keep", default="1",
                   help="Use a fraction like 1/10 for one frame every ten seconds."),
                 P("quality", "JPEG quality (2 best – 31)", "number", default="2"),
                 P("pattern", "Filename pattern", default="frame_%05d.png")]),

    # ── Streams ────────────────────────────────────────────────────────────
    dict(id="extract_audio", label="Extract audio track", group="Streams", inputs=1, enc=True,
         filters=True, out_hint="m4a",
         fields=[P("index", "Audio stream index", "number", default="0")]),
    dict(id="extract_video", label="Extract video track", group="Streams", inputs=1, enc=False,
         filters=False, out_hint="mp4",
         fields=[P("index", "Video stream index", "number", default="0")]),
    dict(id="extract_subs", label="Extract subtitle track", group="Streams", inputs=1, enc=False,
         filters=False, out_hint="srt",
         fields=[P("index", "Subtitle stream index", "number", default="0")]),
    dict(id="extract_all_subs", label="Extract every subtitle track", group="Streams", inputs=1,
         enc=False, filters=False, out=False,
         fields=[P("fmt", "Format", "select", default="srt", choices=["srt", "ass", "vtt"])]),
    dict(id="extract_attachments", label="Extract attachments (fonts)", group="Streams", inputs=1,
         enc=False, filters=False, out=False),
    dict(id="strip", label="Remove streams", group="Streams", inputs=1, enc=False, filters=False,
         out_hint="mkv",
         fields=[P("audio", "Remove audio", "bool", default=""),
                 P("video", "Remove video", "bool", default=""),
                 P("subs", "Remove subtitles", "bool", default="1"),
                 P("data", "Remove data streams", "bool", default=""),
                 P("chapters", "Remove chapters", "bool", default=""),
                 P("metadata", "Strip metadata", "bool", default="")]),
    dict(id="add_audio", label="Add / replace audio", group="Streams", inputs=2, enc=False,
         filters=False, out_hint="mkv",
         fields=[P("mode", "Mode", "select", default="replace",
                   choices=["replace", "add", "mix"],
                   help="replace = swap the track, add = keep both, mix = blend into one"),
                 P("acodec", "Audio codec", "select", default="copy",
                   choices=["copy", "aac", "libmp3lame", "libopus", "flac"],
                   when={"mode": ["replace", "mix"]}),
                 P("shortest", "End at shortest input", "bool", default="1"),
                 P("delay", "Offset second input (s)", "number", default="0", step="0.1")]),
    dict(id="add_subs", label="Add subtitles", group="Streams", inputs=2, enc=False, filters=False,
         out_hint="mkv",
         fields=[P("mode", "Mode", "select", default="soft", choices=["soft", "burn"],
                   help="soft = selectable track, burn = permanently drawn into the picture"),
                 P("lang", "Language tag", default="eng", when={"mode": "soft"}),
                 P("title", "Track title", default="", when={"mode": "soft"}),
                 P("default", "Mark as default", "bool", default="", when={"mode": "soft"}),
                 P("scodec", "Subtitle codec", "select", default="auto",
                   choices=["auto", "mov_text", "srt", "ass", "webvtt", "copy"],
                   when={"mode": "soft"}),
                 P("style", "Burn-in style override", esc=True,
                   placeholder="FontName=DejaVu Sans,FontSize=24,MarginV=40",
                   when={"mode": "burn"})]),
    dict(id="mux", label="Mux multiple inputs", group="Streams", inputs=0, enc=False, filters=False,
         out_hint="mkv", help="Combine any number of files, mapping all streams from each.",
         fields=[P("maps", "Custom map expressions (one per line)", "textarea",
                   placeholder="0:v:0\n1:a:0\n2:s:0",
                   help="Leave empty to map every stream from every input.")]),
    dict(id="map_streams", label="Stream mapping editor", group="Streams", inputs=1, enc=True,
         filters=False, out_hint="mkv",
         fields=[P("maps", "Map expressions (one per line)", "textarea", placeholder="0:v:0\n0:a:1"),
                 P("disposition", "Disposition edits", "textarea",
                   placeholder="a:0 default\ns:0 forced")]),
    dict(id="metadata", label="Edit metadata & tags", group="Streams", inputs=1, enc=False,
         filters=False, out_hint="mkv",
         fields=[P("global_tags", "Global tags (key=value per line)", "textarea",
                   placeholder="title=My Video\nartist=Someone\ncomment=..."),
                 P("stream_tags", "Per-stream tags", "textarea",
                   placeholder="s:a:0 language=tur\ns:a:0 title=Turkish dub"),
                 P("strip_first", "Clear existing metadata first", "bool", default="")]),

    # ── Edit ───────────────────────────────────────────────────────────────
    dict(id="trim", label="Trim / cut a segment", group="Edit", inputs=1, enc=True, filters=True,
         out_hint="mp4",
         help="Fast mode seeks to keyframes and copies streams; accurate mode re-encodes."),
    dict(id="cut_out", label="Cut a segment OUT", group="Edit", inputs=1, enc=True, filters=False,
         out_hint="mp4", help="Removes the given range and joins what is left.",
         fields=[P("start", "Remove from", default="00:01:00"),
                 P("end", "Remove to", default="00:02:00")]),
    dict(id="split_time", label="Split into equal chunks", group="Edit", inputs=1, enc=False,
         filters=False, out=False,
         fields=[P("seconds", "Chunk length (s)", "number", default="600"),
                 P("pattern", "Name pattern", default="part_%03d",
                   help="Leave the extension off and the source container is kept."),
                 P("reset", "Reset timestamps", "bool", default="1")]),
    dict(id="split_size", label="Split by approximate file size", group="Edit", inputs=1, enc=False, filters=False,
         out=False,
         fields=[P("size", "Max size per part", default="1900M"),
                 P("pattern", "Name pattern", default="part_%03d",
                   help="Leave the extension off and the source container is kept.")]),
    dict(id="split_chapters", label="Split at chapter marks", group="Edit", inputs=1, enc=False,
         filters=False, out=False,
         fields=[P("pattern", "Name pattern", default="%02d - %s",
                   help="%02d becomes the chapter number, %s the chapter title. "
                        "Leave the extension off and the source container is kept.")]),
    dict(id="concat", label="Join files", group="Edit", inputs=0, enc=True, filters=False,
         out_hint="mp4",
         fields=[P("mode", "Method", "select", default="demuxer", choices=["demuxer", "filter"],
                   help="demuxer = stream copy, needs matching streams. filter = re-encodes and scales/pads clips to the first video's dimensions."),
                 P("audio", "Include audio", "bool", default="1", when={"mode": "filter"})]),
    dict(id="speed", label="Change playback speed", group="Edit", inputs=1, enc=True, filters=False,
         out_hint="mp4",
         fields=[P("factor", "Speed factor", "number", default="2", step="0.05",
                   help="2 = twice as fast, 0.5 = half speed. Audio is corrected automatically."),
                 P("keep_audio", "Keep audio", "bool", default="1"),
                 P("interpolate", "Interpolate frames (smooth slow-mo)", "bool", default="")]),
    dict(id="reverse", label="Reverse", group="Edit", inputs=1, enc=True, filters=False, out_hint="mp4",
         fields=[P("audio", "Reverse audio too", "bool", default="1")]),
    dict(id="loop_clip", label="Loop / repeat (stream copy)", group="Edit", inputs=1, enc=False, filters=False,
         out_hint="mp4",
         fields=[P("count", "Times to repeat", "number", default="3")]),
    dict(id="stabilize", label="Stabilise (two-pass vidstab)", group="Edit", inputs=1, enc=True,
         filters=False, out_hint="mp4",
         fields=[P("shakiness", "Shakiness 1-10", "number", default="5"),
                 P("accuracy", "Accuracy 1-15", "number", default="15"),
                 P("smoothing", "Smoothing frames", "number", default="30"),
                 P("zoom", "Zoom %", "number", default="0")]),
    dict(id="loudnorm2", label="Loudness normalise (two-pass)", group="Edit", inputs=1, enc=True,
         filters=False, out_hint="mp4",
         help="Measures the file, then encodes with exact correction values. Broadcast grade.",
         fields=[P("I", "Target LUFS", "number", default="-16", step="0.5"),
                 P("TP", "True peak dB", "number", default="-1.5", step="0.1"),
                 P("LRA", "Loudness range", "number", default="11", step="0.5")]),

    # ── Compose ────────────────────────────────────────────────────────────
    dict(id="watermark", label="Overlay image watermark", group="Compose", inputs=2, enc=True,
         filters=False, out_hint="mp4",
         fields=[P("position", "Position", "select", default="bottom-right",
                   choices=["top-left", "top-right", "bottom-left", "bottom-right", "center", "custom"]),
                 P("margin", "Margin px", "number", default="20",
                   when={"position": ["top-left", "top-right", "bottom-left", "bottom-right"]}),
                 P("x", "Custom X", default="", placeholder="only for custom position",
                   when={"position": "custom"}),
                 P("y", "Custom Y", default="", when={"position": "custom"}),
                 P("opacity", "Opacity 0-1", "number", default="1", step="0.05"),
                 P("scale", "Scale watermark width (px, blank = original)", default="")]),
    dict(id="pip", label="Picture-in-picture", group="Compose", inputs=2, enc=True, filters=False,
         out_hint="mp4",
         fields=[P("position", "Corner", "select", default="bottom-right",
                   choices=["top-left", "top-right", "bottom-left", "bottom-right"]),
                 P("width", "Inset width px", "number", default="480"),
                 P("margin", "Margin px", "number", default="24"),
                 P("audio", "Audio from", "select", default="0", choices=["0", "1", "mix", "none"])]),
    dict(id="stack", label="Side by side / stacked", group="Compose", inputs=2, enc=True, filters=False,
         out_hint="mp4",
         fields=[P("dir", "Direction", "select", default="h", choices=["h", "v"]),
                 P("normalize", "Match heights first", "bool", default="1"),
                 P("audio", "Audio from", "select", default="0", choices=["0", "1", "mix", "none"])]),
    dict(id="add_cover", label="Attach cover art", group="Compose", inputs=2, enc=False, filters=False,
         out_hint="m4a", help="Embed an image as album art in an audio file."),

    # ── Export ─────────────────────────────────────────────────────────────
    dict(id="gif", label="Export animated GIF", group="Export", inputs=1, enc=False, filters=True,
         out_hint="gif", help="Two-stage palette generation for much better colour than a naive encode.",
         fields=[P("start", "Start time", default="0"),
                 P("duration", "Duration (s)", "number", default="5", step="0.1"),
                 P("fps", "Frame rate", "number", default="15"),
                 P("width", "Width px (-1 keeps aspect)", "number", default="600"),
                 P("dither", "Dither", "select", default="sierra2_4a",
                   choices=["none", "bayer", "floyd_steinberg", "sierra2", "sierra2_4a"]),
                 P("colors", "Palette colours", "number", default="256"),
                 P("loop", "Loop (0 = forever)", "number", default="0")]),
    dict(id="webp", label="Export animated WebP", group="Export", inputs=1, enc=False, filters=True,
         out_hint="webp",
         fields=[P("start", "Start time", default="0"),
                 P("duration", "Duration (s)", "number", default="5", step="0.1"),
                 P("fps", "Frame rate", "number", default="20"),
                 P("width", "Width px", "number", default="600"),
                 P("quality", "Quality 0-100", "number", default="75"),
                 P("lossless", "Lossless", "bool", default="")]),
    dict(id="screenshot", label="Grab a single frame", group="Export", inputs=1, enc=False,
         filters=True, out_hint="png",
         fields=[P("time", "Timestamp", default="00:00:05"),
                 P("width", "Width px (-1 keeps aspect)", "number", default="-1")]),
    dict(id="thumbnails", label="Thumbnail sheet", group="Export", inputs=1, enc=False, filters=False,
         out_hint="jpg",
         fields=[P("interval", "Seconds between grabs", "number", default="30"),
                 P("cols", "Columns", "number", default="5"),
                 P("rows", "Rows", "number", default="5"),
                 P("width", "Tile width px", "number", default="320"),
                 P("margin", "Margin px", "number", default="6")]),
    dict(id="waveform", label="Waveform image", group="Export", inputs=1, enc=False, filters=False,
         out_hint="png",
         fields=[P("size", "Image size", default="1920x480"),
                 P("colors", "Colour", default="#ff6b35"),
                 P("mode", "Mode", "select", default="line", choices=["point", "line", "p2p", "cline"])]),
    dict(id="spectrogram", label="Spectrogram image", group="Export", inputs=1, enc=False, filters=False,
         out_hint="png",
         fields=[P("size", "Image size", default="1920x1080"),
                 P("mode", "Mode", "select", default="combined", choices=["combined", "separate"]),
                 P("scale", "Scale", "select", default="log", choices=["lin", "log", "sqrt", "cbrt"]),
                 P("color", "Palette", "select", default="intensity",
                   choices=["channel", "intensity", "rainbow", "moreland", "nebulae", "fire",
                            "fiery", "fruit", "cool", "magma", "green", "viridis", "plasma"])]),
    dict(id="visualizer", label="Audio → visualiser video", group="Export", inputs=1, enc=True,
         filters=False, out_hint="mp4",
         fields=[P("style", "Style", "select", default="showwaves",
                   choices=["showwaves", "showspectrum", "showfreqs", "showcqt", "avectorscope"]),
                 P("size", "Video size", default="1280x720"),
                 P("color", "Colour", default="#ff6b35"),
                 P("bg", "Background image (optional)", esc=True, placeholder="cover.jpg")]),

    # ── Raw ────────────────────────────────────────────────────────────────
    dict(id="custom", label="Raw ffmpeg command", group="Raw", inputs=1, enc=False, filters=False,
         out_hint="mp4",
         help="Full manual control. Input and output are inserted around your arguments.",
         fields=[P("pre", "Arguments before -i", "textarea", placeholder="-hwaccel cuda"),
                 P("post", "Arguments after -i", "textarea",
                   placeholder="-c:v libx264 -crf 18 -c:a copy")]),
    dict(id="freeform", label="Entirely free-form", group="Raw", inputs=0, enc=False, filters=False,
         out=False, help="Type a whole ffmpeg command line. Nothing is added or reordered.",
         fields=[P("line", "Command line (without the leading 'ffmpeg')", "textarea",
                   placeholder="-i input.mp4 -vf scale=1280:-2 out.mp4")]),
]

# Operations whose output is the same kind of file as the input. For these the
# sensible default extension is the source's own, not the registry's generic
# hint — trimming an .mkv should offer .mkv, not silently propose .mp4.
CONTAINER_PRESERVING = {
    "trim", "cut_out", "remux", "strip", "map_streams", "metadata", "speed",
    "reverse", "loop_clip", "stabilize", "loudnorm2", "concat", "mux",
    "add_audio", "add_subs", "watermark", "pip", "stack", "transcode",
    "split_time", "split_size", "split_chapters",
}

FF_OPS_INDEX = {o["id"]: o for o in FF_OPS}


