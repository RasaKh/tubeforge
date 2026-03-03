import hashlib
import json
import math
import os
import re
import tempfile
import threading

APP_NAME = "TubeForge"
APP_VERSION = "4.3"

# ═══════════════════════════════════════════════════════════════════════════
#  PATHS & CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

HOME = os.path.expanduser("~")
CONF_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "tubeforge")
LOG_DIR = os.path.join(CONF_DIR, "logs")
DB_PATH = os.path.join(CONF_DIR, "tubeforge.db")
CONF_PATH = os.path.join(CONF_DIR, "config.json")
TMP_DIR = os.path.join(tempfile.gettempdir(), "tubeforge")

for _d in (CONF_DIR, LOG_DIR, TMP_DIR):
    os.makedirs(_d, exist_ok=True)

DEFAULT_CONFIG = {
    "download_dir": os.path.join(HOME, "yt-dlp-downloads"),
    "extra_roots": [],            # additional browsable/allowed directories
    "max_concurrent_jobs": 2,
    "ytdlp_bin": "yt-dlp",
    "ffmpeg_bin": "ffmpeg",
    "ffprobe_bin": "ffprobe",
    "sandbox_paths": True,        # restrict file access to download_dir + extra_roots
    "keep_job_history": 500,
    "theme": "forge",
    "accent": "#ff6b35",
    "font_scale": 100,
    "confirm_destructive": True,
    "auto_open_queue": True,
    "default_output_template": "%(title)s [%(id)s].%(ext)s",
    "notify_on_finish": True,
    "auth_enabled": False,
    "auth_token_hash": "",
    "auth_cookie_secure": True,
    "allow_raw_ffmpeg": False,
}

_config_lock = threading.RLock()
SESSIONS = {}
SESSION_TTL = 8 * 60 * 60


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONF_PATH, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except Exception:
        pass
    token = os.environ.get("TUBEFORGE_AUTH_TOKEN", "")
    if token:
        cfg["auth_enabled"] = True
        cfg["auth_token_hash"] = hashlib.sha256(token.encode()).hexdigest()
    elif not cfg.get("auth_token_hash"):
        # Do not persist an enabled flag without its secret; otherwise a
        # restart could lock the local operator out with no way to log in.
        cfg["auth_enabled"] = False
    if os.environ.get("TUBEFORGE_ALLOW_RAW_FFMPEG", "").lower() in ("1", "true", "yes"):
        cfg["allow_raw_ffmpeg"] = True
    return cfg


def save_config(cfg):
    with _config_lock:
        tmp = CONF_PATH + ".tmp"
        persisted = dict(cfg)
        # Authentication is configured through TUBEFORGE_AUTH_TOKEN, never
        # written to disk or exposed through the API.
        persisted.pop("auth_token_hash", None)
        persisted["auth_enabled"] = bool(cfg.get("auth_token_hash")) and bool(cfg.get("auth_enabled"))
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(persisted, fh, indent=2)
        os.replace(tmp, CONF_PATH)


CONFIG = load_config()
os.makedirs(CONFIG["download_dir"], exist_ok=True)


def dl_dir():
    return CONFIG["download_dir"]


def allowed_roots():
    roots = [os.path.realpath(CONFIG["download_dir"])]
    for r in CONFIG.get("extra_roots") or []:
        if r:
            roots.append(os.path.realpath(os.path.expanduser(r)))
    roots.append(os.path.realpath(TMP_DIR))
    return roots


# ═══════════════════════════════════════════════════════════════════════════
#  PATH SAFETY
# ═══════════════════════════════════════════════════════════════════════════

class PathError(Exception):
    pass


def resolve_path(p, must_exist=False, for_output=False):
    """Expand a user-supplied path.  Relative paths resolve inside download_dir.
    When sandbox_paths is on, the result must live under an allowed root."""
    if p is None:
        return None
    p = str(p).strip()
    if not p:
        return None
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(dl_dir(), p)
    real = os.path.realpath(p)
    if CONFIG.get("sandbox_paths", True):
        ok = any(real == root or real.startswith(root + os.sep) for root in allowed_roots())
        if not ok:
            raise PathError(
                "Path is outside the allowed roots: %s\n"
                "Add its folder under Settings > Extra roots, or disable sandboxing." % real)
    if must_exist and not os.path.exists(real):
        raise PathError("File not found: %s" % real)
    if for_output:
        parent = os.path.dirname(real)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
    return real


def human_size(n):
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return "%.1f PB" % n


def human_time(seconds):
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "-"
    if seconds < 0:
        return "-"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


def parse_time_to_seconds(value):
    """Accepts 90, '90', '1:30', '00:01:30', '00:01:30.500'."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    if not re.fullmatch(r"\d+(?::\d{1,2}){0,2}(?:\.\d+)?", s):
        return None
    parts = s.split(":")
    try:
        parts = [float(x) for x in parts]
    except ValueError:
        return None
    if len(parts) > 1 and any(p >= 60 for p in parts[1:]):
        return None
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total if math.isfinite(total) else None




def update_config(new_cfg):
    with _config_lock:
        CONFIG.clear()
        CONFIG.update(new_cfg)
