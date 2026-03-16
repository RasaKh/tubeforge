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


