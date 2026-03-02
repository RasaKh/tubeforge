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


