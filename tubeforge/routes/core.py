import hashlib
import os
import shutil
import time
import uuid

from flask import Blueprint, jsonify, render_template, request

from ..config import (
    APP_NAME,
    APP_VERSION,
    CONFIG,
    CONF_DIR,
    CONF_PATH,
    DEFAULT_CONFIG,
    LOG_DIR,
    SESSIONS,
    SESSION_TTL,
    TMP_DIR,
    _config_lock,
    allowed_roots,
    dl_dir,
    human_size,
    save_config,
    update_config,
)
from ..ffmpeg_compiler import build_ffmpeg
from ..ffmpeg_registry import (
    AUDIO_ENCODERS,
    CHANNEL_LAYOUTS,
    CONTAINERS,
    CONTAINER_PRESERVING,
    FFMPEG_FILTERS,
    FF_OPS,
    HWACCELS,
    SAMPLE_RATES,
    SUBTITLE_CODECS,
    VIDEO_ENCODERS,
)
from ..jobs import JOBS
from ..probe import dependency_report
from ..ytdlp_compiler import (
    FORMAT_PRESETS,
    OUTPUT_TEMPLATE_PRESETS,
    OUTPUT_TOKENS,
    YTDLP_GROUPS,
    YTDLP_OPTIONS,
)
from . import auth_required, auth_token_valid, body, jerr, public_config

bp = Blueprint("core", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/healthz")
def healthz():
    return jsonify({"ok": True, "version": APP_VERSION,
                    "jobs_active": len(JOBS.active())})


@bp.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    if not auth_required():
        return jsonify({"ok": True, "auth_required": False})
    data = body()
    token = data.get("token") or ""
    if not auth_token_valid(token):
        return jerr("Invalid access token.", 401)
    session_id = uuid.uuid4().hex
    with _config_lock:
        SESSIONS[session_id] = time.time() + SESSION_TTL
        expired = [k for k, expires in SESSIONS.items() if expires < time.time()]
        for key in expired:
            SESSIONS.pop(key, None)
    response = jsonify({"ok": True, "expires_in": SESSION_TTL})
    cookie_secure_cfg = CONFIG.get("auth_cookie_secure", "auto")
    is_secure = (
        request.is_secure
        or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
        if cookie_secure_cfg == "auto"
        else bool(cookie_secure_cfg)
    )
    response.set_cookie(
        "tubeforge_session",
        session_id,
        httponly=True,
        secure=is_secure,
        samesite="Strict",
        max_age=SESSION_TTL,
        path="/",
    )
    return response


@bp.route("/api/bootstrap")
def api_bootstrap():
    return jsonify({
        "ok": True,
        "app": {"name": APP_NAME, "version": APP_VERSION},
        "config": public_config(CONFIG),
        "auth": {"enabled": auth_required()},
        "paths": {"download_dir": dl_dir(), "conf_dir": CONF_DIR, "tmp": TMP_DIR},
        "ytdlp_groups": [{"id": g[0], "label": g[1], "hint": g[2]} for g in YTDLP_GROUPS],
        "ytdlp_options": YTDLP_OPTIONS,
        "format_presets": [{"label": a, "value": b, "sets": c} for a, b, c in FORMAT_PRESETS],
        "output_tokens": [{"token": a, "desc": b} for a, b in OUTPUT_TOKENS],
        "output_presets": [{"label": a, "value": b} for a, b in OUTPUT_TEMPLATE_PRESETS],
        "ff_ops": FF_OPS,
        "container_preserving": sorted(CONTAINER_PRESERVING),
        "filters": FFMPEG_FILTERS,
        "video_encoders": VIDEO_ENCODERS,
        "audio_encoders": AUDIO_ENCODERS,
        "containers": CONTAINERS,
        "channel_layouts": CHANNEL_LAYOUTS,
        "sample_rates": SAMPLE_RATES,
        "subtitle_codecs": SUBTITLE_CODECS,
        "hwaccels": HWACCELS,
    })


@bp.route("/api/deps")
def api_deps():
    return jsonify({"ok": True, "deps": dependency_report()})


@bp.route("/api/config", methods=["GET", "POST"])
def api_config():
    global CONFIG
    if request.method == "GET":
        return jsonify({"ok": True, "config": public_config(CONFIG)})

    data = body()
    incoming = data.get("config") or data
    cfg = dict(CONFIG)
    for k, v in incoming.items():
        if k in DEFAULT_CONFIG and k not in ("auth_token_hash", "allow_raw_ffmpeg", "auth_cookie_secure"):
            cfg[k] = v
    if incoming.get("auth_enabled") and not cfg.get("auth_token_hash"):
        return jerr("Set TUBEFORGE_AUTH_TOKEN before enabling authentication.")
    try:
        cfg["max_concurrent_jobs"] = int(cfg["max_concurrent_jobs"])
        cfg["keep_job_history"] = int(cfg["keep_job_history"])
        if not 1 <= cfg["max_concurrent_jobs"] <= 32 or not 1 <= cfg["keep_job_history"] <= 10000:
            return jerr("Use 1–32 concurrent jobs and 1–10000 history entries.")
        cfg["download_dir"] = os.path.abspath(os.path.expanduser(cfg["download_dir"]))
        for key in ("ytdlp_bin", "ffmpeg_bin", "ffprobe_bin"):
            value = str(cfg.get(key) or "")
            if not value or os.path.basename(value) != value or not shutil.which(value):
                return jerr("Use a binary name from PATH for %s." % key)
        if not cfg.get("sandbox_paths", True):
            return jerr("Path sandboxing cannot be disabled through the web API.")
    except (TypeError, ValueError):
        return jerr("Invalid settings value.")
    try:
        os.makedirs(cfg["download_dir"], exist_ok=True)
    except Exception as exc:
        return jerr("Cannot use that download folder: %s" % exc)
    update_config(cfg)
    save_config(CONFIG)
    JOBS._ensure_workers()
    return jsonify({"ok": True, "config": public_config(CONFIG)})


_disk_cache = {"key": None, "ts": 0.0, "data": None}


@bp.route("/api/disk")
def api_disk():
    try:
        root = dl_dir()
        now = time.time()
        if _disk_cache["key"] == root and (now - _disk_cache["ts"]) < 15.0 and _disk_cache["data"]:
            return jsonify(_disk_cache["data"])
        usage = shutil.disk_usage(root)
        total = 0
        count = 0
        for dp, _, fs in os.walk(root):
            for f in fs:
                p = os.path.join(dp, f)
                if os.path.isfile(p):
                    total += os.path.getsize(p)
                    count += 1
                    if count >= 10000:
                        break
            if count >= 10000:
                break
        res = {"ok": True, "free": usage.free, "total": usage.total, "used": usage.used,
               "free_h": human_size(usage.free), "folder_bytes": total,
               "folder_h": human_size(total), "capped": count >= 10000}
        _disk_cache.update({"key": root, "ts": now, "data": res})
        return jsonify(res)
    except Exception:
        return jsonify({"ok": False})


