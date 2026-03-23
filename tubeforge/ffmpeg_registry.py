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
        if spec["id"] == "pan":
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
