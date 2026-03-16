import collections
import json
import os
import shutil
import subprocess
import threading

from .config import CONFIG, resolve_path

# ═══════════════════════════════════════════════════════════════════════════
#  BINARY DISCOVERY / DEPENDENCY CHECK
# ═══════════════════════════════════════════════════════════════════════════

def which(name):
    return shutil.which(name)


def probe_version(binary, args=("--version",)):
    path = which(binary)
    if not path:
        return {"found": False, "path": None, "version": None}
    try:
        out = subprocess.run([path] + list(args), capture_output=True, text=True, timeout=12)
        text = (out.stdout or out.stderr or "").strip().splitlines()
        version = text[0].strip() if text else ""
    except Exception as exc:
        version = "error: %s" % exc
    return {"found": True, "path": path, "version": version}


def dependency_report():
    return {
        "yt-dlp": probe_version(CONFIG["ytdlp_bin"]),
        "ffmpeg": probe_version(CONFIG["ffmpeg_bin"]),
        "ffprobe": probe_version(CONFIG["ffprobe_bin"]),
        "aria2c": probe_version("aria2c"),
        "AtomicParsley": probe_version("AtomicParsley"),
        "rtmpdump": probe_version("rtmpdump"),
        "phantomjs": probe_version("phantomjs"),
    }


ALLOWED_BINARIES = {"yt-dlp", "ffmpeg", "ffprobe", "aria2c", "AtomicParsley", "youtube-dl", "yt-dlp_linux"}


# ═══════════════════════════════════════════════════════════════════════════
#  MEDIA PROBING
# ═══════════════════════════════════════════════════════════════════════════

_probe_cache = {}
_probe_lock = threading.Lock()


def ffprobe_json(path, use_cache=True):
    """Full ffprobe dump: format, streams, chapters."""
    real = resolve_path(path, must_exist=True)
    key = (real, os.path.getmtime(real))
    with _probe_lock:
        if use_cache and key in _probe_cache:
            _probe_cache.move_to_end(key)
            return _probe_cache[key]
    cmd = [CONFIG["ffprobe_bin"], "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", "-show_chapters", real]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "ffprobe failed")
    data = json.loads(out.stdout or "{}")
    with _probe_lock:
        _probe_cache[key] = data
        _probe_cache.move_to_end(key)
        while len(_probe_cache) > 200:
            _probe_cache.popitem(last=False)
    return data


def media_duration(path):
    try:
        info = ffprobe_json(path)
        return float(info.get("format", {}).get("duration") or 0) or None
    except Exception:
        return None


def summarize_probe(data):
    """Condense an ffprobe dump into something the UI can render as a table."""
    fmt = data.get("format", {}) or {}
    streams = []
    for s in data.get("streams", []) or []:
        tags = s.get("tags", {}) or {}
        disp = s.get("disposition", {}) or {}
        entry = {
            "index": s.get("index"),
            "type": s.get("codec_type"),
            "codec": s.get("codec_name"),
            "codec_long": s.get("codec_long_name"),
            "profile": s.get("profile"),
            "language": tags.get("language"),
            "title": tags.get("title"),
            "bitrate": s.get("bit_rate"),
            "default": bool(disp.get("default")),
            "forced": bool(disp.get("forced")),
        }
        if s.get("codec_type") == "video":
            entry.update({
                "width": s.get("width"), "height": s.get("height"),
                "fps": s.get("r_frame_rate"), "avg_fps": s.get("avg_frame_rate"),
                "pix_fmt": s.get("pix_fmt"), "level": s.get("level"),
                "nb_frames": s.get("nb_frames"),
                "sar": s.get("sample_aspect_ratio"), "dar": s.get("display_aspect_ratio"),
                "color_space": s.get("color_space"), "color_primaries": s.get("color_primaries"),
                "color_transfer": s.get("color_transfer"),
            })
        elif s.get("codec_type") == "audio":
            entry.update({
                "sample_rate": s.get("sample_rate"), "channels": s.get("channels"),
                "channel_layout": s.get("channel_layout"), "sample_fmt": s.get("sample_fmt"),
            })
        streams.append(entry)
    chapters = []
    for c in data.get("chapters", []) or []:
        chapters.append({
            "id": c.get("id"),
            "start": float(c.get("start_time") or 0),
            "end": float(c.get("end_time") or 0),
            "title": (c.get("tags") or {}).get("title", ""),
        })
    return {
        "filename": fmt.get("filename"),
        "format_name": fmt.get("format_name"),
        "format_long": fmt.get("format_long_name"),
        "duration": float(fmt.get("duration") or 0) or None,
        "size": int(fmt.get("size") or 0) or None,
        "bitrate": fmt.get("bit_rate"),
        "nb_streams": fmt.get("nb_streams"),
        "tags": fmt.get("tags", {}),
        "streams": streams,
        "chapters": chapters,
    }


